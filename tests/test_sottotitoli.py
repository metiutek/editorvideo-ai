"""Sottotitoli esistenti: lettura, traccia di testi, uscita come traccia del file."""

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import captions, ffmpeg, render
from vedit import mcp_server as srv
from vedit.store import EditError, Store

SRT = ("1\r\n00:00:00,500 --> 00:00:02,000\r\nCiao <b>mondo</b>\r\n\r\n"
       "2\r\n00:00:02,500 --> 00:00:04,000\r\nseconda riga\r\ndue linee\r\n")
VTT = ("WEBVTT\n\nNOTE commento\n\n00:01.000 --> 00:02.000 align:start\nuno\n\n"
       "intro\n01:00:03.000 --> 01:00:04.250\n<v Anna>due</v>\n")
ASS = ("[Script Info]\nTitle: x\n\n[Events]\n"
       "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
       "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\k20}Ciao, a tutti\\Nfine\n")


def test_leggi_i_tre_formati():
    srt = captions.leggi(SRT, "srt")
    assert srt == [{"start": 0.5, "end": 2.0, "text": "Ciao mondo"},
                   {"start": 2.5, "end": 4.0, "text": "seconda riga\ndue linee"}]
    vtt = captions.leggi("﻿" + VTT, "vtt")
    assert [(r["start"], r["end"], r["text"]) for r in vtt] == [(1.0, 2.0, "uno"),
                                                                 (3603.0, 3604.25, "due")]
    # la virgola dentro il testo resta: e' l'ultimo campo
    assert captions.leggi(ASS, "ass") == [{"start": 1.0, "end": 2.5, "text": "Ciao, a tutti\nfine"}]
    with pytest.raises(ValueError, match="no readable subtitles"):
        captions.leggi("niente qui", "srt")


def test_import_diventa_traccia_di_testi(tmp_path):
    s = Store.create("s", "720p")
    passi = len(s._undo)
    r = s.import_subtitles(testo=SRT, fmt="srt", offset=1.0)
    t = s.track_or_die(r["track"])
    assert t.name == "subtitles" and r["righe"] == 2 and len(s._undo) == passi + 1
    assert [(c.start, c.duration, c.text.text) for c in t.clips] == \
        [(1.5, 1.5, "Ciao mondo"), (3.5, 1.5, "seconda riga\ndue linee")]
    assert all(c.text.box and c.transform.y > 0 for c in t.clips)   # in basso, su riquadro
    # e si rileggono uguali
    assert [r["text"] for r in captions.da_traccia(s.project, t.id)] == ["Ciao mondo",
                                                                        "seconda riga\ndue linee"]
    with pytest.raises(EditError, match="use .srt"):
        s.import_subtitles(testo="x", fmt="txt")


def test_da_traccia_taglia_sul_tratto():
    s = Store.create("s", "720p")
    t = s.import_subtitles(testo=SRT, fmt="srt")["track"]
    righe = captions.da_traccia(s.project, t, 1.0, 3.0)
    assert righe == [{"start": 0.0, "end": 1.0, "text": "Ciao mondo"},
                     {"start": 1.5, "end": 2.0, "text": "seconda riga\ndue linee"}]


def test_formato_senza_sottotitoli_rifiutato(tmp_path):
    s = Store.create("s", "720p")
    s.add_color("#202020", duration=2)
    t = s.import_subtitles(testo=SRT, fmt="srt")["track"]
    with pytest.raises(ValueError, match="cannot carry a subtitle stream"):
        render.render(s.project, render.RenderOptions(output=str(tmp_path / "x.mxf"),
                                                      subtitle_track=t))


def _flussi(path) -> list[tuple]:
    out = subprocess.run([ffmpeg.binary("ffprobe"), "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name:stream_tags=language", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return [(x["codec_type"], x["codec_name"], x.get("tags", {}).get("language"))
            for x in json.loads(out)["streams"]]


@pytest.mark.slow
@pytest.mark.parametrize("nome, codec, atteso", [
    ("o.mp4", "h264", "mov_text"), ("o.mkv", "h264", "subrip"), ("o.webm", "vp9", "webvtt"),
])
def test_traccia_di_sottotitoli_nel_file(tmp_path, assets, nome, codec, atteso):
    s = Store.create("s", "720p")
    m = s.import_media([assets["red"]])[0]
    s.add_clip(m.id, duration=4)
    t = s.import_subtitles(testo=SRT, fmt="srt")["track"]
    out = tmp_path / nome
    r = render.render(s.project, render.RenderOptions(output=str(out), codec=codec,
                                                      quality="draft", subtitle_track=t,
                                                      subtitle_lang="eng"))
    assert ("subtitle", atteso, "eng") in _flussi(out)
    assert any("sottotitoli" in w for w in r.warnings)
    # il webm con audio esce: l'AAC predefinito non ci sta, va in Opus
    assert any(f[0] == "audio" for f in _flussi(out))


@pytest.mark.slow
def test_soft_non_si_imprime(tmp_path, assets):
    """Con la traccia scelta come sottotitoli del file, nell'immagine non c'e'."""
    import numpy as np
    from PIL import Image

    s = Store.create("s", "720p")
    s.add_color("#000000", duration=3)
    t = s.import_subtitles(testo=SRT, fmt="srt", font_size=80)["track"]
    out = tmp_path / "o.mp4"
    render.render(s.project, render.RenderOptions(output=str(out), quality="draft",
                                                  subtitle_track=t))
    png = tmp_path / "f.png"
    subprocess.run([ffmpeg.binary("ffmpeg"), "-v", "error", "-y", "-ss", "1.0", "-i", str(out),
                    "-frames:v", "1", str(png)], check=True)
    assert np.asarray(Image.open(png).convert("L")).max() < 40
    testo = subprocess.run([ffmpeg.binary("ffmpeg"), "-v", "error", "-i", str(out), "-map", "0:s",
                            "-f", "srt", "-"], capture_output=True, text=True).stdout
    assert "Ciao mondo" in testo and "00:00:00,500" in testo


def test_api_import_ed_export(tmp_path):
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
        r = c.post("/api/op/import_subtitles", json={"testo": SRT, "fmt": "srt"})
        assert r.status_code == 200, r.text
        t = r.json()["result"]["track"]
        r = c.post("/api/subtitles/export", json={"track": t, "path": str(tmp_path / "o.vtt")})
        assert r.status_code == 200 and r.json()["righe"] == 2
        assert (tmp_path / "o.vtt").read_text(encoding="utf-8").startswith("WEBVTT")
        r = c.post("/api/render", json={"output": str(tmp_path / "o.gif"), "subtitle_track": t})
        assert r.status_code == 400


@pytest.mark.anyio
async def test_strumenti_mcp():
    nomi = {t.name for t in await srv.mcp.list_tools()}
    assert {"import_subtitles", "export_subtitles"} <= nomi
