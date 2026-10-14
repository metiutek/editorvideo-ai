"""Audio 5.1, volume del master e misuratori del mixer."""

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import ffmpeg, render, review
from vedit.graph import CompileOptions, compile_project
from vedit.store import EditError, Store


def _tre_tracce(assets, layout="5.1") -> tuple[Store, dict]:
    """Musica davanti (V1), voce al centro (A), un rumore nel subwoofer (A)."""
    s = Store.create("m", "720p")
    s.set_settings(audio_layout=layout)
    m = s.import_media([assets["red"]])[0]
    s.add_clip(m.id, duration=2)
    voce = s.add_track("audio")
    s.add_clip(m.id, voce.id, start=0, duration=2)
    s.set_track(voce.id, surround="center")
    sub = s.add_track("audio")
    s.add_clip(m.id, sub.id, start=0, duration=2)
    s.set_track(sub.id, surround="surround")
    return s, {"voce": voce.id, "dietro": sub.id}


def test_validazione(assets):
    s, ids = _tre_tracce(assets)
    with pytest.raises(EditError, match="audio"):
        s.set_settings(audio_layout="7.1")
    with pytest.raises(EditError, match="routing"):
        s.set_track(ids["voce"], surround="soffitto")
    with pytest.raises(EditError, match="master"):
        s.set_master_volume(9)
    s.set_master_volume(0.5)
    assert s.project.master.volume == 0.5
    assert s.summary()["settings"]["audio_layout"] == "5.1"


def test_grafo_51(assets):
    s, _ = _tre_tracce(assets)
    g = compile_project(s.project, CompileOptions(video=False)).filtergraph
    assert "pan=5.1|FC=0.5*c0+0.5*c1" in g and "pan=5.1|BL=c0|BR=c1" in g
    assert "pan=5.1|FL=c0|FR=c1" in g
    # in stereo niente 5.1
    s.set_settings(audio_layout="stereo")
    assert "5.1" not in compile_project(s.project, CompileOptions(video=False)).filtergraph


def _rms_canali(path) -> list[float]:
    err = subprocess.run([ffmpeg.binary("ffmpeg"), "-v", "info", "-i", str(path), "-af",
                          "astats=measure_overall=none:measure_perchannel=RMS_level", "-f", "null",
                          "-"], capture_output=True, text=True).stderr
    return [float(r.split(":")[-1]) for r in err.splitlines() if "RMS level dB" in r]


@pytest.mark.slow
def test_ogni_traccia_al_suo_posto(tmp_path, assets):
    s, _ = _tre_tracce(assets)
    out = tmp_path / "o.wav"
    render.render(s.project, render.RenderOptions(output=str(out), video=False))
    fl, fr, fc, lfe, bl, br = _rms_canali(out)
    # musica davanti, voce al centro, terza traccia dietro, subwoofer muto
    assert min(fl, fr, fc, bl, br) > -40 and lfe < -80


@pytest.mark.slow
@pytest.mark.parametrize("nome, canali", [("o.mp4", 6), ("o.webm", 6), ("o.mp3", 2)])
def test_contenitori_51(tmp_path, assets, nome, canali):
    s, _ = _tre_tracce(assets)
    out = tmp_path / nome
    render.render(s.project, render.RenderOptions(output=str(out), quality="draft",
                                                  codec="vp9" if nome.endswith("webm") else "h264"))
    st = json.loads(subprocess.run([ffmpeg.binary("ffprobe"), "-v", "error", "-select_streams", "a",
                                    "-show_entries", "stream=channels", "-of", "json", str(out)],
                                   capture_output=True, text=True).stdout)["streams"]
    assert st[0]["channels"] == canali      # l'mp3 non ha il 5.1: ripiega in stereo


@pytest.mark.slow
def test_mp3_esce(tmp_path, assets):
    """L'AAC predefinito faceva fallire ogni .mp3: ora prende il suo codec."""
    s, _ = _tre_tracce(assets, layout="stereo")
    out = tmp_path / "o.mp3"
    render.render(s.project, render.RenderOptions(output=str(out)))
    assert out.stat().st_size > 1000


def test_livelli_per_traccia(assets):
    s = Store.create("l", "720p")
    m = s.import_media([assets["red"]])[0]
    s.add_clip(m.id, duration=3)
    a = s.add_track("audio")
    s.add_clip(m.id, a.id, start=1, duration=2)
    s.set_track(a.id, volume=0.25)          # -12 dB
    s.add_text("solo testo", duration=1)
    lv = review.livelli(s.project)
    assert set(lv["tracce"]) == {"V1", a.id}     # la traccia di testi non suona
    v1, an = lv["tracce"]["V1"], lv["tracce"][a.id]
    assert len(v1["rms"]) == 60 and lv["passo"] == 0.05
    # prima di 1 s la seconda traccia tace, poi suona 12 dB sotto la prima
    assert an["rms"][5] <= -89
    assert abs((v1["rms"][40] - an["rms"][40]) - 12.0) < 0.5
    assert lv["master"]["max_db"] > v1["max_db"] - 1


def test_api_mixer(tmp_path, assets):
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
        m = c.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]
        c.post("/api/op/add_clip", json={"media_id": m, "duration": 1})
        r = c.get("/api/mixer/levels?r=1")
        assert r.status_code == 200 and "V1" in r.json()["tracce"]
        r = c.post("/api/op/set_master_volume", json={"volume": 0.8})
        assert r.status_code == 200 and r.json()["project"]["master"]["volume"] == 0.8
