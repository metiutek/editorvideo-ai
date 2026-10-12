"""Render a pezzi paralleli e distorsioni su mappa ridotta.

Il difetto da cui nascono: un progetto di due minuti con 370 tagli si
esportava in un'ora e tre quarti. Il grafo unico teneva aperte tutte le clip
per tutta la durata (costo quadratico nel numero di tagli) e warp e glitch
calcolavano geq su ogni pixel. Qui si verifica che il render a pezzi dia lo
stesso file del grafo unico e che le distorsioni veloci diano la stessa
immagine di geq.
"""

import subprocess

import numpy as np
import pytest

from vedit import effects as fx
from vedit import ffmpeg, probe, render
from vedit.graph import CompileOptions, compile_project, slice_project
from vedit.store import Store


def _montaggio(assets, n=24, durata=1.0, preset="720p") -> Store:
    s = Store.create("p", preset)
    red, blue, music = s.import_media([assets["red"], assets["blue"], assets["music"]])
    s.add_clips([{"media": (red if i % 2 else blue).id, "start": i * durata, "in": 0.0,
                  "duration": durata} for i in range(n)])
    a = s.add_track("audio")
    s.add_clip(music.id, track_id=a.id, start=0.0, duration=8.0)
    return s


def test_confini_sui_fotogrammi_e_sugli_stacchi(assets):
    s = _montaggio(assets, n=40, durata=0.9)
    fps = s.project.settings.fps
    c = render.confini_pezzi(s.project, 0.0, s.project.duration(), fps)
    assert c[0] == 0.0 and c[-1] == pytest.approx(s.project.duration(), abs=1 / fps)
    assert all(b > a for a, b in zip(c, c[1:]))
    assert all(abs(x * fps - round(x * fps)) < 1e-6 for x in c), "confini fuori fotogramma"
    stacchi = {round(cl.start * fps) for cl in s.project.tracks[0].clips}
    assert all(round(x * fps) in stacchi for x in c[1:-1]), "i confini cadono sugli stacchi"
    assert all(b - a <= render.PEZZO_MAX + 1e-6 for a, b in zip(c, c[1:]))


def test_nessun_confine_dentro_una_clip_con_memoria(assets):
    """La stabilizzazione conta i fotogrammi dall'inizio della clip: non si taglia li'."""
    s = Store.create("p", "720p")
    red = s.import_media([assets["red"]])[0]
    lunga = s.add_clip(red.id, start=0.0, duration=5.0)
    s.set_speed(lunga.id, 0.2)   # 25 s in timeline, una clip sola
    s.add_effect(lunga.id, "denoise", {})
    c = render.confini_pezzi(s.project, 0.0, s.project.duration(), s.project.settings.fps)
    assert c == [0.0, pytest.approx(s.project.duration(), abs=0.05)]


def test_corto_resta_un_grafo_solo(assets, tmp_path):
    s = _montaggio(assets, n=6)
    opts = render.RenderOptions(output=str(tmp_path / "o.mp4"))
    assert render._confini_se_conviene(s.project, opts) is None
    lungo = _montaggio(assets, n=30)
    assert render._confini_se_conviene(lungo.project, opts)
    assert render._confini_se_conviene(lungo.project, render.RenderOptions(
        output=str(tmp_path / "o.mp4"), jobs=1)) is None
    assert render._confini_se_conviene(lungo.project, render.RenderOptions(
        output=str(tmp_path / "o.gif"))) is None


def test_stima_memoria_cresce_con_clip_e_risoluzione(assets):
    s = _montaggio(assets, n=30)
    p = s.project
    poche = render.stima_memoria(p, 0.0, 2.0, 1920, 1080)
    tante = render.stima_memoria(p, 0.0, 8.0, 1920, 1080)
    assert tante > poche > render.MEMORIA_BASE
    assert render.stima_memoria(p, 0.0, 8.0, 640, 360) < tante
    assert render.memoria_libera() is None or render.memoria_libera() > 0


def test_master_nel_pezzo_vede_il_tempo_vero(assets):
    """Un keyframe sul master non deve ripartire da zero a ogni pezzo."""
    s = _montaggio(assets, n=30)
    s.add_effect(None, "hue", {"hue": {"kf": [{"t": 0, "v": 0}, {"t": 30, "v": 90}]}})
    pezzo = slice_project(s.project, 12.0, 18.0)
    assert pezzo._slice_start == 12.0
    g = compile_project(s.project, CompileOptions(start=12.0, end=18.0, audio=False)).filtergraph
    assert "setpts=PTS+12/TB" in g


def test_warp_e_glitch_usano_la_mappa_ridotta(monkeypatch):
    c = fx.Ctx(width=1920, height=1080)
    for mode in ("ripple", "swirl", "bulge"):
        assert "remap" in fx._f_warp({"mode": mode, "amount": 60}, c)[0]
    assert "displace" in fx._f_warp({"mode": "wave", "amount": 50}, c)[0]
    # un'onda oltre i 127 px non sta in un byte: va con remap, non si tronca
    assert "remap" in fx._f_warp({"mode": "wave", "amount": 300}, c)[0]
    assert "displace" in "".join(fx._f_glitch({"intensity": 0.5, "amount": 100}, c))
    assert "geq=r='r(X+" in "".join(fx._f_glitch({"intensity": 0.5, "amount": 300}, c))
    monkeypatch.setattr(fx, "_ha_filtri", lambda *n: False)
    assert fx._f_warp({"mode": "swirl", "amount": 60}, c)[0] == "format=gbrap"


def test_warp_mappa_proporzionata_e_spenta_a_zero():
    """Vortice e rigonfiamento su mappa 8x a 1080p; a keyframe, con amount 0 la mappa e' l'identita'."""
    c = fx.Ctx(width=1920, height=1080)
    assert "crop=w=iw/8" in fx._f_warp({"mode": "swirl", "amount": 60}, c)[0]
    assert "crop=w=iw/8" in fx._f_warp({"mode": "bulge", "amount": 60}, c)[0]
    # l'increspatura ha onde fitte: resta a 4
    assert "crop=w=iw/4" in fx._f_warp({"mode": "ripple", "amount": 60}, c)[0]
    # a 720p il fattore scende, la mappa resta grande uguale
    assert "crop=w=iw/5" in fx._f_warp({"mode": "swirl", "amount": 60}, fx.Ctx(width=1280, height=720))[0]
    smorza = {"kf": [{"t": 0, "v": 120}, {"t": 0.35, "v": 0}]}
    g = fx._f_warp({"mode": "swirl", "amount": smorza}, c)[0]
    assert "if(eq(" in g
    # amount fisso: nessun ramo in piu'
    assert "if(eq(" not in fx._f_warp({"mode": "swirl", "amount": 60}, c)[0]


def _fotogrammi(path, w, h):
    raw = subprocess.run([ffmpeg.binary("ffmpeg"), "-v", "error", "-i", str(path), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.int16)


@pytest.mark.slow
@pytest.mark.parametrize("effetto, params", [
    ("warp", {"mode": "wave", "amount": {"kf": [{"t": 0, "v": 20}, {"t": 1.5, "v": 60}]}}),
    ("warp", {"mode": "ripple", "amount": 40}),
    ("warp", {"mode": "swirl", "amount": 120}),
    ("warp", {"mode": "swirl", "amount": {"kf": [{"t": 0, "v": 120}, {"t": 0.4, "v": 0}]}}),
    ("warp", {"mode": "bulge", "amount": 40}),
    ("glitch", {"intensity": 0.6, "amount": 60, "rate": 20}),
])
def test_mappa_ridotta_come_geq(assets, tmp_path, monkeypatch, effetto, params):
    """Stessa immagine di geq, a meno del mezzo pixel che geq interpola."""
    risultati = []
    for veloce in (True, False):
        if not veloce:
            monkeypatch.setattr(fx, "_ha_filtri", lambda *n: False)
        s = Store.create("w", "720p")
        m = s.import_media([assets["blue"]])[0]
        c = s.add_clip(m.id, start=0.0, duration=2.0)
        s.add_effect(c.id, effetto, params)
        out = tmp_path / f"{veloce}.mkv"
        render.render(s.project, render.RenderOptions(output=str(out), quality="max", audio=False,
                                                      prefer_hw=False, width=640, height=360))
        risultati.append(_fotogrammi(out, 640, 360))
    veloce, lento = risultati
    assert veloce.shape == lento.shape
    d = np.abs(veloce - lento)
    assert d.mean() < 3.0, d.mean()


@pytest.mark.slow
def test_a_pezzi_uguale_al_grafo_unico(assets, tmp_path):
    """Stessi fotogrammi, stessa durata, audio intero: il taglio non si vede."""
    s = _montaggio(assets, n=26, durata=1.0, preset="720p")
    c = s.project.tracks[0].clips
    s.add_effect(c[5].id, "warp", {"mode": "ripple", "amount": 30})
    s.set_transform(c[9].id, scale={"kf": [{"t": 0, "v": 1.0}, {"t": 1.0, "v": 1.3}]})
    s.add_effect(None, "hue", {"hue": {"kf": [{"t": 0, "v": 0}, {"t": 26, "v": 90}]}})
    s.set_fades(c[12].id, fade_out=0.4)
    w, h = 640, 360
    piccolo = {"width": w, "height": h}

    uno = tmp_path / "uno.mp4"
    pezzi = tmp_path / "pezzi.mp4"
    render.render(s.project, render.RenderOptions(output=str(uno), quality="max", jobs=1,
                                                  prefer_hw=False, **piccolo))
    r = render.render(s.project, render.RenderOptions(output=str(pezzi), quality="max", jobs=3,
                                                      prefer_hw=False, **piccolo))
    assert any("pezzi" in x for x in r.warnings), r.warnings

    # memoria scarsa: i pezzi vanno in fila, uno alla volta, e il file e' lo stesso
    poca = tmp_path / "poca.mp4"
    import vedit.render as rmod
    vera = rmod.memoria_libera
    rmod.memoria_libera = lambda: 0
    try:
        r2 = render.render(s.project, render.RenderOptions(output=str(poca), quality="max",
                                                           jobs=3, prefer_hw=False, **piccolo))
    finally:
        rmod.memoria_libera = vera
    assert any("fino a 1 alla volta" in x for x in r2.warnings), r2.warnings

    a, b = probe.probe(str(uno)), probe.probe(str(pezzi))
    assert b.duration == pytest.approx(a.duration, abs=0.05)
    assert b.has_audio
    fa = _fotogrammi(uno, w, h)
    for f in (pezzi, poca):
        fb = _fotogrammi(f, w, h)
        assert len(fa) == len(fb), (f.name, len(fa), len(fb))
        diff = np.abs(fa - fb).mean(axis=(1, 2, 3))
        assert diff.max() < 4.0, f"{f.name}: fotogramma {int(diff.argmax())} diverso di {diff.max():.1f}"


def test_zoom_sotto_uno_senza_tela_gigante(assets):
    """Sotto 1 lo zoom va con scale per fotogramma, non con una tela 4x per zoompan."""
    s = Store.create("z", "1080p")
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, duration=2.0)
    s.set_transform(c.id, scale={"kf": [{"t": 0, "v": 0.1}, {"t": 1.0, "v": 1.0}]})
    g = compile_project(s.project, CompileOptions(audio=False)).filtergraph
    assert "eval=frame" in g and "zoompan" not in g and "pad=7680" not in g
    # con una rotazione resta zoompan: rotate vuole una misura fissa
    s.set_transform(c.id, rotation=10)
    assert "zoompan" in compile_project(s.project, CompileOptions(audio=False)).filtergraph


@pytest.mark.slow
def test_zoom_sotto_uno_si_vede_giusto(assets, tmp_path):
    s = Store.create("z", "720p")
    s.project.settings.background = "blue"
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, duration=2.0)
    s.set_transform(c.id, scale={"kf": [{"t": 0, "v": 0.2}, {"t": 1.0, "v": 1.0}]})
    out = tmp_path / "z.mkv"
    w, h = 640, 360
    render.render(s.project, render.RenderOptions(output=str(out), audio=False, prefer_hw=False,
                                                  width=w, height=h))
    f = _fotogrammi(out, w, h)
    primo, ultimo = f[0], f[-1]
    # all'inizio il rosso e' un quadratino al centro, il resto e' sfondo blu
    assert primo[h // 2, w // 2, 0] > 180 and primo[5, 5, 2] > 180 and primo[5, 5, 0] < 60
    rossi = (primo[..., 0] > 150) & (primo[..., 2] < 80)
    assert 0.02 < rossi.mean() < 0.08, rossi.mean()
    # alla fine riempie il quadro
    assert ((ultimo[..., 0] > 150) & (ultimo[..., 2] < 80)).mean() > 0.95


def test_browser_paralleli_rispettano_la_memoria(monkeypatch):
    from vedit import htmlclip

    monkeypatch.setattr(render, "memoria_libera", lambda: 0)
    assert htmlclip._browser_paralleli(10) == 1
    monkeypatch.setattr(render, "memoria_libera", lambda: 64 * 2**30)
    assert 1 <= htmlclip._browser_paralleli(10) <= 4
    assert htmlclip._browser_paralleli(2) <= 2


def test_scale2ref_porta_alla_misura_del_riferimento(tmp_path):
    """``rw`` esiste solo da ffmpeg 7.1, e prima ``main_w`` voleva dire l'opposto."""
    from vedit import ffmpeg
    out = tmp_path / "m.png"
    ffmpeg.run(ffmpeg.base_cmd() + [
        "-f", "lavfi", "-i", "color=s=10x10:d=0.1", "-f", "lavfi", "-i", "color=s=100x50:d=0.1",
        "-filter_complex", f"[0][1]scale2ref={ffmpeg.misura_scale2ref()}[a][b];[b]nullsink",
        "-map", "[a]", "-frames:v", "1", str(out)])
    r = ffmpeg.run([ffmpeg.binary("ffprobe"), "-v", "error", "-show_entries", "stream=width,height",
                    "-of", "csv=p=0", str(out)])
    assert r.stdout.strip() == "100,50"
