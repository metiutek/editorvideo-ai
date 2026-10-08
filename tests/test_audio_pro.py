"""Strumenti audio "da studio": sidechain, equalizzatore parametrico, de-esser.

Si misura il suono vero, non il filtergraph: un compressore che non comprime
o un'equalizzazione che non taglia renderizzano lo stesso senza errori.
"""

import subprocess

import numpy as np
import pytest

from vedit import effects as fx
from vedit import ffmpeg, render
from vedit.store import EditError, Store

SR = 48000


def _tono(path, freq, durata, inizio=0.0, fine=None, volume=0.5):
    """Sinusoide; fuori da [inizio, fine) silenzio."""
    fine = durata if fine is None else fine
    espr = f"{volume}*sin(2*PI*{freq}*t)*between(t,{inizio},{fine})"
    subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"aevalsrc='{espr}':s={SR}:d={durata}", "-ac", "2", str(path)], check=True)
    return str(path)


def _leggi(path):
    raw = subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-i", str(path),
                          "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _ampiezza(x, freq, a, b):
    """Ampiezza della componente a ``freq`` Hz fra i secondi a e b."""
    seg = x[int(a * SR):int(b * SR)]
    spettro = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    return float(spettro[np.argmin(abs(f - freq))])


# --------------------------------------------------------------------------
# sidechain
# --------------------------------------------------------------------------


def test_sidechain_validazione():
    s = Store.create("t", "720p")
    a2 = s.add_track("audio")
    with pytest.raises(EditError):
        s.set_sidechain(a2.id, a2.id)
    with pytest.raises(EditError):
        s.set_sidechain(a2.id, "A1", ratio=99)
    with pytest.raises(EditError):
        s.set_sidechain(a2.id, "A1", volume=3)
    t = s.set_sidechain(a2.id, "A1", threshold=-40)
    assert t.sidechain["source"] == "A1" and t.sidechain["threshold"] == -40
    assert s.summary()["tracks"][-1]["sidechain"]["ratio"] == 6.0
    assert s.set_sidechain(a2.id, None).sidechain is None
    s.undo()
    assert s.project.track_by_id(a2.id).sidechain is not None


def test_sidechain_nel_grafo():
    from vedit.graph import CompileOptions, compile_project

    s = Store.create("t", "720p")
    s.project.media.append(__import__("vedit.model", fromlist=["Media"]).Media(
        id="mv", path="voce.wav", kind="audio", duration=4, has_video=False, has_audio=True))
    s.project.media.append(__import__("vedit.model", fromlist=["Media"]).Media(
        id="mm", path="musica.wav", kind="audio", duration=4, has_video=False, has_audio=True))
    a2 = s.add_track("audio")
    s.add_clip("mv", "A1", 0)
    s.add_clip("mm", a2.id, 0)
    senza = compile_project(s.project, CompileOptions(video=False))
    assert "sidechaincompress" not in senza.filtergraph
    s.set_sidechain(a2.id, "A1")
    con = compile_project(s.project, CompileOptions(video=False))
    assert "sidechaincompress" in con.filtergraph and "asplit=2" in con.filtergraph


@pytest.mark.slow
def test_sidechain_abbassa_la_musica_quando_parla_la_voce(tmp_path):
    musica = _tono(tmp_path / "musica.wav", 220, 3.0)
    voce = _tono(tmp_path / "voce.wav", 1000, 3.0, inizio=1.0, fine=2.0)
    s = Store.create("t", "720p")
    mv, mm = s.import_media([voce, musica])
    a2 = s.add_track("audio")
    s.add_clip(mv.id, "A1", 0)
    s.add_clip(mm.id, a2.id, 0)

    def misura(nome):
        out = tmp_path / f"{nome}.wav"
        render.render(s.project, render.RenderOptions(output=str(out), video=False))
        x = _leggi(out)
        return _ampiezza(x, 220, 0.2, 0.9), _ampiezza(x, 220, 1.2, 1.9)

    prima, durante = misura("senza")
    assert durante > prima * 0.8      # senza sidechain la musica resta com'e'
    s.set_sidechain(a2.id, "A1", threshold=-40, ratio=12, attack=5, release=100)
    prima_sc, durante_sc = misura("con")
    assert durante_sc < prima_sc * 0.5, (prima_sc, durante_sc)
    assert prima_sc > prima * 0.8     # quando la voce tace la musica torna su


# --------------------------------------------------------------------------
# equalizzatore parametrico e de-esser
# --------------------------------------------------------------------------


def test_bande_validate():
    b = fx.bande_valide([{"type": "peak", "freq": 1000, "gain": 3, "q": 2}])
    assert b[0]["on"] is True
    for sbagliata in ({"type": "boh"}, {"freq": 5}, {"gain": 60}, {"q": 50}):
        with pytest.raises(ValueError):
            fx.bande_valide([sbagliata])
    with pytest.raises(ValueError):
        fx.bande_valide([{"type": "peak"}] * 11)
    with pytest.raises(ValueError):
        fx.validate_effect("eqparam", {"bands": [{"type": "peak", "freq": 1}]})


def test_bande_diventano_filtri():
    filtri = fx._a_eqparam({"bands": [
        {"type": "highpass", "freq": 80, "q": 0.7},
        {"type": "peak", "freq": 3000, "gain": -6, "q": 2},
        {"type": "peak", "freq": 500, "gain": 0, "q": 1},          # piatta: niente filtro
        {"type": "notch", "freq": 50, "q": 10, "on": False},       # spenta
        {"type": "highshelf", "freq": 8000, "gain": 4, "q": 0.7},
    ], "output": -2}, fx.Ctx())
    assert filtri == ["highpass=f=80:t=q:w=0.7", "equalizer=f=3000:t=q:w=2:g=-6",
                      "highshelf=f=8000:g=4:t=q:w=0.7", "volume=-2dB"]


@pytest.mark.slow
def test_eq_parametrico_taglia_davvero(tmp_path):
    """Una campana a -18 dB su 1 kHz abbassa il 1 kHz e lascia stare il 200 Hz."""
    misto = tmp_path / "misto.wav"
    subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"aevalsrc='0.3*sin(2*PI*200*t)+0.3*sin(2*PI*1000*t)':s={SR}:d=1.5",
                    "-ac", "2", str(misto)], check=True)
    s = Store.create("t", "720p")
    m = s.import_media([str(misto)])[0]
    c = s.add_clip(m.id, "A1", 0)

    def misura(nome):
        out = tmp_path / f"{nome}.wav"
        render.render(s.project, render.RenderOptions(output=str(out), video=False))
        x = _leggi(out)
        return _ampiezza(x, 200, 0.3, 1.2), _ampiezza(x, 1000, 0.3, 1.2)

    b200, b1k = misura("piatto")
    s.add_effect(c.id, "eqparam", {"bands": [{"type": "peak", "freq": 1000, "gain": -18, "q": 2}]})
    e200, e1k = misura("eq")
    assert e1k < b1k * 0.2, (b1k, e1k)
    assert e200 > b200 * 0.8, (b200, e200)


@pytest.mark.slow
def test_deesser_smorza_le_sibilanti(tmp_path):
    """Un fischio a 7 kHz (una "s") perde energia, un 300 Hz (la voce) no."""
    misto = tmp_path / "s.wav"
    subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"aevalsrc='0.3*sin(2*PI*300*t)+0.4*sin(2*PI*7000*t)':s={SR}:d=1.5",
                    "-ac", "2", str(misto)], check=True)
    s = Store.create("t", "720p")
    m = s.import_media([str(misto)])[0]
    c = s.add_clip(m.id, "A1", 0)

    def misura(nome):
        out = tmp_path / f"{nome}.wav"
        render.render(s.project, render.RenderOptions(output=str(out), video=False))
        x = _leggi(out)
        return _ampiezza(x, 300, 0.3, 1.2), _ampiezza(x, 7000, 0.3, 1.2)

    b300, b7k = misura("prima")
    s.add_effect(c.id, "deesser", {"amount": 0.9, "frequency": 5000})
    d300, d7k = misura("dopo")
    assert d7k < b7k * 0.8, (b7k, d7k)
    assert d300 > b300 * 0.7, (b300, d300)
