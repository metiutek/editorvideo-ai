"""Plugin VST: si caricano, si elencano e cambiano davvero il suono nel render."""

import json
import subprocess

import numpy as np
import pytest

from vedit import effects as fx
from vedit import ffmpeg, plugins, render
from vedit.graph import CompileOptions, compile_project
from vedit.store import Store


def test_effetto_vst_validazione():
    assert fx.validate_effect("vst", {"file": "x.vst3", "values": {"gain": 3, "on": True}, "mix": 0.5})
    with pytest.raises(ValueError):
        fx.validate_effect("vst", {"values": [1, 2]})
    with pytest.raises(ValueError):
        fx.validate_effect("vst", {"values": {"x": {"annidato": 1}}})


def test_vst2_rifiutato_con_spiegazione(tmp_path):
    dll = tmp_path / "vecchio.dll"
    dll.write_bytes(b"0")
    with pytest.raises(plugins.PluginNonDisponibile, match="VST3"):
        plugins.risolvi(str(dll))


def test_grafo_usa_il_suono_lavorato():
    s = Store.create("t", "720p")
    from vedit.model import Media
    s.project.media.append(Media(id="m1", path="voce.wav", kind="audio", duration=10,
                                 has_video=False, has_audio=True))
    c = s.add_clip("m1", "A1", 0, in_=2, duration=3)
    comp = compile_project(s.project, CompileOptions(video=False, audio_files={c.id: ("lavorato.wav", 2.0)}))
    assert "lavorato.wav" in comp.inputs and "voce.wav" not in comp.inputs
    # in un segmento si salta solo la differenza dall'attacco originale
    comp = compile_project(s.project, CompileOptions(video=False, start=1, end=2,
                                                     audio_files={c.id: ("lavorato.wav", 2.0)}))
    i = comp.inputs.index("lavorato.wav")
    assert comp.inputs[i - 5:i - 3] == ["-ss", "1"]


def _primo_plugin():
    pytest.importorskip("pedalboard")
    for p in plugins.elenco():
        try:
            plugins.parametri(p["path"])
            return p["path"]
        except plugins.PluginNonDisponibile:
            continue
    pytest.skip("nessun plugin VST3 caricabile su questa macchina")


@pytest.mark.slow
def test_parametri_sono_json_validi():
    info = plugins.parametri(_primo_plugin())
    json.dumps(info, allow_nan=False)          # niente -inf: l'interfaccia non li legge
    assert info["parametri"]


@pytest.mark.slow
def test_plugin_cambia_il_suono(tmp_path):
    path = _primo_plugin()
    sorgente = tmp_path / "voce.wav"
    subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.4*sin(2*PI*220*t)':s=48000:d=1.5", "-ac", "2", str(sorgente)], check=True)
    s = Store.create("t", "720p")
    m = s.import_media([str(sorgente)])[0]
    c = s.add_clip(m.id, "A1", 0)

    def leggi(out):
        raw = subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-i", str(out), "-ac", "1",
                              "-f", "f32le", "-"], check=True, capture_output=True).stdout
        return np.frombuffer(raw, dtype=np.float32)

    asciutto = tmp_path / "a.wav"
    render.render(s.project, render.RenderOptions(output=str(asciutto), video=False))
    info = plugins.parametri(path)
    # un plugin a mix 1 con un preset diverso dal default deve lasciare un segno
    valori = {}
    preset = next((p for p in info["parametri"] if p["nome"] == "preset"), None)
    if preset and len(preset.get("scelte", [])) > 4:
        valori["preset"] = preset["scelte"][4]
    s.add_effect(c.id, "vst", {"file": path, "values": valori, "mix": 1.0})
    bagnato = tmp_path / "b.wav"
    render.render(s.project, render.RenderOptions(output=str(bagnato), video=False))
    a, b = leggi(asciutto), leggi(bagnato)
    n = min(len(a), len(b))
    assert np.sqrt(np.mean((a[:n] - b[:n]) ** 2)) > 0.01
