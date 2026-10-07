"""Assistente: scelta del modello, chiavi, riferimenti e server MCP dentro l'editor."""

import json

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import chat, llm
from vedit.store import Store


@pytest.fixture(autouse=True)
def _senza_chiavi(monkeypatch):
    """Le chiavi di chi lancia i test non devono cambiare l'esito."""
    for p in llm.PROVIDERS:
        if p.get("env"):
            monkeypatch.delenv(p["env"], raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    # Claude Code installato o no lo decide il test, non la macchina
    monkeypatch.setattr(llm, "claude_exe", lambda: None)
    f = llm._file()
    f.unlink(missing_ok=True)
    yield
    f.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# configurazione
# --------------------------------------------------------------------------


def test_senza_niente_lo_dice():
    st = llm.stato()
    assert st["ok"] is False
    assert st["motivo"]
    assert {p["id"] for p in st["providers"]} >= {"claude_code", "anthropic", "openai", "gemini",
                                                  "openrouter", "ollama", "custom"}


def test_la_chiave_si_salva_ma_non_si_mostra():
    llm.imposta("openai", chiave="sk-segretissima-1234567890", modello="gpt-5")
    st = llm.stato()
    assert st["ok"] and st["provider"] == "openai"
    voce = next(p for p in st["providers"] if p["id"] == "openai")
    assert "segretissima" not in json.dumps(st)
    assert voce["chiave"].startswith("sk-s") and voce["chiave"].endswith("7890")
    # resta su questa macchina, nel file di vedit, non nel progetto
    assert json.loads(llm._file().read_text(encoding="utf-8"))["chiavi"]["openai"].startswith("sk-")
    llm.imposta("openai", chiave="")
    assert llm.stato()["ok"] is False


def test_servizio_compatibile_con_indirizzo_proprio():
    llm.imposta("custom", chiave="k", modello="mio-modello", indirizzo="http://localhost:9999/v1/")
    voce = next(p for p in llm.stato()["providers"] if p["id"] == "custom")
    assert voce["indirizzo"] == "http://localhost:9999/v1" and voce["pronto"]


def test_modello_locale_senza_chiave():
    llm.imposta("ollama", modello="qwen3")
    assert llm.stato()["ok"]


def test_claude_code_pronto_se_installato(monkeypatch):
    assert llm.stato()["providers"][0]["pronto"] is False
    monkeypatch.setattr(llm, "claude_exe", lambda: "C:/finto/claude.exe")
    llm.imposta("claude_code")
    st = llm.stato()
    assert st["ok"] and st["provider"] == "claude_code"


def test_provider_sconosciuto():
    with pytest.raises(ValueError):
        llm.imposta("inventato")


def test_strumenti_nel_formato_openai():
    fn = llm.strumenti_openai(chat.build_tools())
    nomi = {f["function"]["name"] for f in fn}
    assert {"add_clip", "add_html", "set_transform"} <= nomi
    assert all(f["type"] == "function" and "properties" in f["function"]["parameters"] for f in fn)


# --------------------------------------------------------------------------
# riferimenti
# --------------------------------------------------------------------------


def test_riferimenti_in_parole(monkeypatch):
    monkeypatch.setattr(chat, "_fotogramma", lambda store, t, area=None: None)
    s = Store.create("t", "720p")
    c = s.add_color("red", duration=4)
    testo, immagini = chat.riferimenti(s, [
        {"kind": "time", "t": 1.5},
        {"kind": "range", "a": 3, "b": 1},
        {"kind": "clip", "id": c.id},
        {"kind": "area", "t": 2, "x": .25, "y": .5, "w": .5, "h": .25, "nota": "il logo"},
    ])
    assert "[1] l'istante 0:01.50" in testo
    assert "[2] il tratto da 0:01.00 a 0:03.00" in testo
    assert f"[3] clip {c.id}" in testo
    # l'area arriva in pixel di progetto e come spostamento dal centro, cioe'
    # pronta per set_transform
    assert "x=320 y=360 larghezza=640 altezza=180" in testo
    assert "centro dell'area = 0, 90" in testo and "il logo" in testo
    assert immagini == []


@pytest.mark.slow
def test_riferimento_area_porta_il_fotogramma_col_riquadro():
    from PIL import Image

    s = Store.create("t", "720p")
    s.add_color("#0000ff", duration=2)
    _, immagini = chat.riferimenti(s, [{"kind": "area", "t": 1, "x": .1, "y": .1, "w": .3, "h": .3}])
    assert len(immagini) == 1
    im = Image.open(immagini[0]["path"]).convert("RGB")
    w, h = im.size
    r, g, b = im.getpixel((int(.1 * w) - 1, int(.25 * h)))
    assert r > 200 and b < 120           # il bordo rosso del riquadro
    assert im.getpixel((w // 2 + 200, h // 2))[2] > 200   # fuori dal riquadro, il blu


# --------------------------------------------------------------------------
# motore compatibile OpenAI, con un finto servizio
# --------------------------------------------------------------------------


def test_giro_openai_con_strumenti(monkeypatch):
    s = Store.create("t", "720p")
    risposte = [
        [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {
            "name": "add_text", "arguments": '{"text": "Ci'}}]}}]},
         {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
             "arguments": 'ao", "duration": 2}'}}]}, "finish_reason": "tool_calls"}]}],
        [{"choices": [{"delta": {"content": "Fatto."}, "finish_reason": "stop"}]}],
    ]
    mandati = []

    def finto(url, chiave, body):
        mandati.append(body)
        yield from risposte.pop(0)

    monkeypatch.setattr(llm, "_post_stream", finto)
    llm.imposta("openai", chiave="k", modello="gpt-5")
    stato: dict = {}
    eventi = list(chat.run(s, stato, "metti un titolo", lambda n, a: chat.execute(s, n, a)))
    tipi = [e["type"] for e in eventi]
    assert tipi == ["tool", "tool_done", "text", "done"]
    assert any(c.type == "text" and c.text.text == "Ciao" for c in s.project.tracks[0].clips)
    # il secondo giro rimanda il risultato dello strumento
    assert mandati[1]["messages"][-1]["role"] == "tool"
    # cambiando modello la cronologia ricomincia: i formati non si mescolano
    llm.imposta("ollama", modello="x")
    monkeypatch.setattr(llm, "_post_stream", lambda *a: iter(
        [{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]))
    list(chat.run(s, stato, "ciao", lambda n, a: ""))
    assert stato["provider"] == "ollama" and len(stato["messaggi"]) == 2


# --------------------------------------------------------------------------
# API e server MCP ospitato
# --------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
        yield c
    api_mod.S.store = None


def test_api_imposta_il_modello(client):
    r = client.post("/api/llm", json={"provider": "gemini", "chiave": "AIza-chiave-di-prova-123",
                                      "modello": "gemini-2.5-pro"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["provider"] == "gemini"
    assert "chiave-di-prova" not in r.text
    assert client.post("/api/llm", json={"provider": "boh"}).status_code == 400


@pytest.mark.anyio
async def test_mcp_dentro_l_editor_lavora_sul_progetto_aperto(tmp_path):
    """Chi si collega a /mcp tocca lo stesso progetto del browser."""
    from vedit import mcp_server as srv

    api_mod.S.store = None
    try:
        with TestClient(api_mod.app) as c:
            c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
            assert api_mod.MCP_ATTIVO
            out = await srv.mcp.call_tool("add_color", {"color": "red", "duration": 2})
            assert out
            stato = c.get("/api/project").json()["project"]
            assert any(cl["type"] == "color" for t in stato["tracks"] for cl in t["clips"])
            # e la risposta HTTP del server MCP c'e' davvero
            r = c.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"}}},
                headers={"Accept": "application/json, text/event-stream"})
            assert r.status_code == 200 and "vedit" in r.text
    finally:
        api_mod.S.store = None
        srv._stores.clear()
        srv._current[0] = None
