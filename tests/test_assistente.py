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


# --------------------------------------------------------------------------
# allegati
# --------------------------------------------------------------------------


def test_tipo_allegato():
    assert chat.tipo_allegato("a.PNG") == "image"
    assert chat.tipo_allegato("doc.pdf") == "pdf"
    assert chat.tipo_allegato("titolo.html") == "testo"
    assert chat.tipo_allegato("ripresa.mov") == "media"
    assert chat.tipo_allegato("x.zip") == "altro"


def test_allegati_arrivano_al_modello(tmp_path):
    from PIL import Image

    s = Store.create("t", "720p")
    img = tmp_path / "logo.png"
    Image.new("RGB", (8, 8), "red").save(img)
    html = tmp_path / "grafica.html"
    html.write_text("<h1>Ciao</h1>", encoding="utf-8")
    video = tmp_path / "ripresa.mp4"
    video.write_bytes(b"0")
    testo, immagini = chat.riferimenti(s, [
        {"kind": "file", "path": str(img), "name": "logo.png"},
        {"kind": "file", "path": str(html), "name": "grafica.html"},
        {"kind": "file", "path": str(video), "name": "ripresa.mp4"},
        {"kind": "file", "path": str(tmp_path / "sparito.png"), "name": "sparito.png"},
    ])
    assert immagini == [{"etichetta": "[1]", "path": str(img), "tipo": "image"}]
    assert "<h1>Ciao</h1>" in testo                     # il testo arriva per intero
    assert "importalo con import_media" in testo        # il video si puo' montare
    assert "[4] file allegato sparito.png (non trovato)" in testo
    blocco = llm.immagine(str(img))
    assert blocco["mime"] == "image/png" and blocco["b64"]


def test_api_allega_accanto_al_progetto(client, tmp_path):
    r = client.post("/api/chat/allega", files=[
        ("files", ("schizzo.png", b"\x89PNG-finto", "image/png")),
        ("files", ("schizzo.png", b"\x89PNG-altro", "image/png")),
    ])
    assert r.status_code == 200, r.text
    a, b = r.json()["allegati"]
    assert a["tipo"] == "image" and a["name"] == "schizzo.png"
    assert b["name"] == "schizzo_1.png"                 # non sovrascrive
    assert (tmp_path / "allegati" / "schizzo.png").read_bytes() == b"\x89PNG-finto"


# --------------------------------------------------------------------------
# link e cartelle
# --------------------------------------------------------------------------


@pytest.fixture
def sito(tmp_path):
    """Un piccolo sito locale: una pagina e un'immagine."""
    import http.server
    import threading
    from functools import partial

    from PIL import Image

    www = tmp_path / "www"
    www.mkdir()
    (www / "pagina.html").write_text(
        "<html><head><title>Guida al montaggio</title><style>p{}</style></head>"
        "<body><h1>Ritmo</h1><p>Taglia sul battere.</p><script>var x=1</script></body></html>",
        encoding="utf-8")
    Image.new("RGB", (4, 4), "blue").save(www / "foto.png")
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(http.server.SimpleHTTPRequestHandler, directory=str(www)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_link_a_una_pagina_diventa_testo(sito, tmp_path):
    from vedit import collegamenti

    r = collegamenti.risolvi_link(f"{sito}/pagina.html", tmp_path / "allegati")
    assert r["tipo"] == "pagina" and r["name"] == "Guida al montaggio"
    s = Store.create("t", "720p")
    testo, immagini = chat.riferimenti(s, [r])
    assert "Taglia sul battere." in testo and "var x" not in testo and "p{}" not in testo
    assert immagini == []


def test_link_a_un_immagine_si_scarica(sito, tmp_path):
    from vedit import collegamenti

    r = collegamenti.risolvi_link(f"{sito}/foto.png", tmp_path / "allegati")
    assert r["tipo"] == "image" and (tmp_path / "allegati" / "foto.png").is_file()
    _, immagini = chat.riferimenti(Store.create("t", "720p"), [r])
    assert immagini[0]["tipo"] == "image"


def test_link_non_valido():
    from vedit import collegamenti

    with pytest.raises(ValueError):
        collegamenti.risolvi_link("file:///C:/Windows/win.ini", __import__("pathlib").Path("."))


def test_cartella_elencata(tmp_path):
    (tmp_path / "girato").mkdir()
    (tmp_path / "girato" / "a.mp4").write_bytes(b"0" * 10)
    (tmp_path / "girato" / "note.txt").write_text("x", encoding="utf-8")
    (tmp_path / "girato" / ".nascosto").write_text("x", encoding="utf-8")
    testo, _ = chat.riferimenti(Store.create("t", "720p"),
                                [{"kind": "folder", "path": str(tmp_path / "girato")}])
    assert "2 file (1 video/audio" in testo
    assert "a.mp4  [media" in testo and ".nascosto" not in testo
    assert "import_media" in testo


def test_api_link(client, sito):
    r = client.post("/api/chat/link", json={"url": f"{sito}/pagina.html"})
    assert r.status_code == 200 and r.json()["tipo"] == "pagina"
    assert client.post("/api/chat/link", json={"url": "non un link"}).status_code == 400


# --------------------------------------------------------------------------
# ferma
# --------------------------------------------------------------------------


def test_ferma_a_meta_lascia_una_cronologia_valida(monkeypatch):
    """Fermato fra due strumenti: ogni chiamata ha la sua risposta e niente altro parte."""
    s = Store.create("t", "720p")
    fermato = {"si": False}
    risposta = [{"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "a", "function": {"name": "add_text", "arguments": '{"text": "uno"}'}},
        {"index": 1, "id": "b", "function": {"name": "add_text", "arguments": '{"text": "due"}'}},
    ]}, "finish_reason": "tool_calls"}]}]
    monkeypatch.setattr(llm, "_post_stream", lambda *a: iter(risposta))
    llm.imposta("openai", chiave="k", modello="gpt-5")

    def op(nome, args):
        out = chat.execute(s, nome, args)
        fermato["si"] = True      # l'utente preme "ferma" dopo il primo
        return out

    stato: dict = {}
    eventi = list(chat.run(s, stato, "due titoli", op, fermo=lambda: fermato["si"]))
    assert eventi[-1]["type"] == "stopped"
    testi = [c.text.text for c in s.project.tracks[0].clips if c.type == "text"]
    assert testi == ["uno"]
    risposte = [m for m in stato["messaggi"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in risposte] == ["a", "b"]
    assert "interrotto" in risposte[1]["content"]


def test_api_stop(client):
    assert client.post("/api/chat/stop").json() == {"ok": True}
    assert api_mod.S.fermo.is_set()
