"""Voce dal testo: configurazione, servizi via API (finti), timeline."""

import shutil
from pathlib import Path

import pytest

from vedit import tts
from vedit import mcp_server as srv
from vedit.store import EditError, Store


@pytest.fixture
def finto(monkeypatch, assets):
    """Un motore che 'parla' copiando un audio vero: niente rete, niente sintesi."""
    chiamate = []

    def genera(m, cfg, testo, voce, velocita, istruzioni, out):
        chiamate.append({"testo": testo, "voce": voce, "velocita": velocita})
        shutil.copy(assets["music"], out)

    monkeypatch.setitem(tts._GENERATORI, "system", genera)
    monkeypatch.setattr(tts, "_pronto", lambda m, cfg: None)
    return chiamate


def test_openai_compatibile(monkeypatch, tmp_path):
    """La richiesta ha la forma di /audio/speech, verso l'indirizzo scelto."""
    viste = []

    def post(url, headers, body, timeout=180):
        viste.append((url, headers, body))
        return b"RIFF....WAVE"

    monkeypatch.setattr(tts, "_post", post)
    tts.imposta("openai", chiave="sk-prova", voce="nova", indirizzo="http://localhost:8880/v1/")
    f = tts.genera("ciao", tmp_path, velocita=1.2, istruzioni="calmo")
    url, headers, body = viste[0]
    assert url == "http://localhost:8880/v1/audio/speech"
    assert headers["Authorization"] == "Bearer sk-prova"
    assert body == {"model": "gpt-4o-mini-tts", "voice": "nova", "input": "ciao",
                    "response_format": "wav", "speed": 1.2, "instructions": "calmo"}
    assert f.read_bytes() == b"RIFF....WAVE"
    # stessa battuta, stessi parametri: niente seconda chiamata
    assert tts.genera("ciao", tmp_path, velocita=1.2, istruzioni="calmo") == f
    assert len(viste) == 1
    # la chiave non esce mai per intero
    st = tts.stato()
    assert st["motore"] == "openai"
    assert next(m for m in st["motori"] if m["id"] == "openai")["chiave"] == "…rova"
    tts.imposta("openai", chiave="", indirizzo="")


def test_elevenlabs(monkeypatch, tmp_path):
    viste = []
    monkeypatch.setattr(tts, "_post", lambda u, h, b, timeout=180: viste.append((u, h, b)) or b"ID3")
    tts.imposta("elevenlabs", chiave="xi", voce="abc", predefinito=False)
    f = tts.genera("hello", tmp_path, "elevenlabs")
    assert f.suffix == ".mp3"
    assert viste[0][0].startswith("https://api.elevenlabs.io/v1/text-to-speech/abc")
    assert viste[0][1] == {"xi-api-key": "xi"}
    tts.imposta("elevenlabs", chiave="", predefinito=False)


def test_errori_comprensibili(tmp_path):
    with pytest.raises(tts.TtsError, match="no text"):
        tts.genera("  ", tmp_path, "system")
    with pytest.raises(tts.TtsError, match="unknown voice engine"):
        tts.genera("x", tmp_path, "boh")
    with pytest.raises(tts.TtsError, match="ElevenLabs"):
        tts.genera("x", tmp_path, "elevenlabs")


def test_battute_in_timeline(finto, tmp_path):
    s = Store.create("v", path=str(tmp_path / "p.json"))
    voci = tts.battute([{"text": "prima", "start": 2.0}, {"text": "seconda", "speed": 1.5},
                        {"text": "prima", "start": 2.0}],
                       tts.cartella_progetto(s.path), "system")
    assert voci[0]["path"] == voci[2]["path"]
    assert finto[1]["velocita"] == 1.5 and len(finto) == 2   # la ripetuta e' in cache
    assert "p_voice" in voci[0]["path"]
    clips = s.add_voiceover(voci[:2])
    vo = s.project.find_clip(clips[0].id)[0]
    assert vo.kind == "audio" and vo.name == "VO"
    assert clips[0].start == 2.0
    assert clips[1].start == pytest.approx(clips[0].end)
    assert clips[0].name == "prima"
    # un solo undo per tutte le battute, traccia compresa
    s.undo()
    assert not any(t.name == "VO" for t in s.project.tracks)
    with pytest.raises(EditError):
        s.add_voiceover(voci[:1], track_id="V1")


@pytest.mark.anyio
async def test_strumento_mcp(finto, tmp_path):
    from test_mcp import call

    srv._stores.clear()
    await call("project_create", path=str(tmp_path / "m.json"))
    r = await call("generate_voice", lines=[{"text": "uno"}, {"text": "due"}], start=1.0,
                   engine="system")
    assert len(r["clips"]) == 2 and r["clips"][0]["start"] == 1.0
    assert r["track"]
    r = await call("generate_voice", text="tre", engine="system", apply=False)
    assert len(r["files"]) == 1 and Path(r["files"][0]).is_file()
