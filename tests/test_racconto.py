"""Video raccontati da una voce: tempi della voce, chat per progetto, modello e sforzo."""

import json
import wave

import pytest
from fastapi.testclient import TestClient

from vedit import allinea, analyze, chat, conversazioni, llm, stili, tts
from vedit import api as api_mod
from vedit import mcp_server as srv
from vedit.store import Store


# --------------------------------------------------------------------------
# tempi della voce
# --------------------------------------------------------------------------


def _parole(testo, passo=0.5):
    return [{"w": w, "t": i * passo, "e": i * passo + 0.4} for i, w in enumerate(testo.split())]


def test_frasi_trovate_in_ordine_e_con_i_numeri():
    ws = _parole("They plan $725 billion, up 77%. Microsoft adds twenty-five billion. "
                 "Then twenty-five billion again.")
    # il copione scrive i numeri in lettere, la trascrizione in cifre
    assert allinea.trova(ws, "seven hundred twenty-five billion")["t"] == 1.0
    assert allinea.trova(ws, "up seventy-seven percent")["t"] == 2.0
    # "twenty-five billion" sta anche dentro "seven hundred twenty-five billion":
    # e' il bug del "+$25B" comparso sette secondi prima. Conta da dove si cerca
    assert allinea.trova(ws, "twenty-five billion")["t"] == 1.0
    assert allinea.trova(ws, "twenty-five billion", 1.5)["t"] == 4.0
    assert allinea.trova(ws, "twenty-five billion", 4.5)["t"] == 5.5
    assert allinea.trova(ws, "nothing like this at all")["t"] is None
    assert allinea._norm("1,000") == ["one", "thousand"]


def _con_voce(tmp_path, assets, monkeypatch, speed=1.0):
    """Un progetto con la voce sulla traccia VO e una trascrizione finta."""
    s = Store.create("v", path=str(tmp_path / "p.json"))
    clips = s.add_voiceover([{"path": assets["music"], "start": 2.0,
                              "text": "AI is the biggest bet. Where does the money go?"}])
    c = clips[0]
    if speed != 1.0:
        s.set_speed(c.id, speed)
    parole = [("AI", 1.0), ("is", 1.3), ("the", 1.5), ("biggest", 1.7), ("bet.", 2.1),
              ("Where", 3.0), ("does", 3.3), ("the", 3.5), ("money", 3.7), ("go?", 4.0)]
    finta = {"segments": [{"start": 1.0, "end": 4.3, "text": "",
                           "words": [{"w": w, "t": t, "e": t + 0.25} for w, t in parole]}]}
    monkeypatch.setattr(analyze, "transcribe", lambda path, model="small", language=None: finta)
    return s, c


def test_tempi_in_timeline_non_in_sorgente(tmp_path, assets, monkeypatch):
    s, c = _con_voce(tmp_path, assets, monkeypatch, speed=2.0)
    out = allinea.tempi(s, ["biggest bet", "where does the money go"])
    a, b = out["phrases"]
    # clip a 2 s, velocita' 2: la parola a 1.7 s della sorgente cade a 2 + 1.7/2
    assert a["t"] == pytest.approx(2.85, abs=0.01)
    assert b["t"] == pytest.approx(3.5, abs=0.01)
    assert "missing" not in out
    frasi = allinea.tempi(s)["sentences"]
    assert frasi[0][2] == "AI is the biggest bet." and frasi[1][0] == pytest.approx(3.5, abs=0.01)


def test_senza_whisper_stima_dal_testo(tmp_path, assets, monkeypatch):
    s, c = _con_voce(tmp_path, assets, monkeypatch)

    def manca(*a, **k):
        raise analyze.AnalysisError("faster-whisper not installed: pip install faster-whisper")

    monkeypatch.setattr(analyze, "transcribe", manca)
    out = allinea.tempi(s, ["where does the money go"])
    assert "estimated" in out
    t = out["phrases"][0]["t"]
    assert c.start < t < c.end


def test_senza_traccia_voce_lo_dice(tmp_path):
    s = Store.create("v", path=str(tmp_path / "p.json"))
    with pytest.raises(allinea.AllineaError, match="voice track"):
        allinea.tempi(s)


@pytest.mark.anyio
async def test_strumento_mcp_e_chat(tmp_path, assets, monkeypatch):
    s, c = _con_voce(tmp_path, assets, monkeypatch)
    srv._stores[s.path] = s
    srv._current[0] = s.path
    try:
        res = await srv.mcp.call_tool("speech_times", {"phrases": ["the money"]})
        assert "5.5" in json.dumps(res, default=str)   # "the money": 3.5 s nella sorgente + 2
    finally:
        srv._stores.clear()
        srv._current[0] = None
    out = json.loads(chat.execute(s, "speech_times", {"phrases": ["biggest bet"]}))
    assert out["phrases"][0]["t"] == pytest.approx(3.7, abs=0.01)


def test_lo_stile_non_abbassa_la_voce(tmp_path, assets):
    """apply_style trattava la voce fuori campo come musica e la portava a -16 dB."""
    s = Store.create("v", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["red"]])[0]
    s.add_clip(m.id, "V1", 0, duration=5)
    lunga = s.import_media([assets["music"]])[0]
    vo = s.add_voiceover([{"path": assets["music"], "start": 0, "text": "voce"}])[0]
    musica = s.add_clip(lunga.id, s.add_track("audio").id, 0)
    out = stili.applica(s, "documentario")
    toccate = " ".join(out["applicato"]["musica"])
    assert musica.id in toccate and vo.id not in toccate


def test_metodo_nelle_istruzioni():
    for testo in (srv.ISTRUZIONI, chat.SYSTEM):
        assert "speech_times" in testo and "set_speed" in testo
    assert "speech_times" in llm.SISTEMA_CLAUDE_CODE


# --------------------------------------------------------------------------
# chat salvata per progetto
# --------------------------------------------------------------------------


class _Blocco:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_cronologia_pulita_per_il_disco(tmp_path):
    msgs = [
        {"role": "user", "content": [{"type": "image", "source": {"data": "x" * 1000}},
                                     {"type": "text", "text": "ciao"}]},
        {"role": "assistant", "content": [_Blocco(type="thinking", thinking="", signature="s"),
                                          _Blocco(type="text", text="ok"),
                                          _Blocco(type="tool_use", id="t1", name="undo", input={})]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                      "content": [{"type": "text", "text": "fatto"},
                                                  {"type": "image", "source": {}}]}]},
    ]
    out = conversazioni.pulisci(msgs)
    assert out[0]["content"][0] == {"type": "text", "text": "(immagine)"}
    assert [b["type"] for b in out[1]["content"]] == ["text", "tool_use"]
    assert out[2]["content"][0]["content"] == "fatto\n(immagine)"
    json.dumps(out)
    # troppi messaggi: si taglia da un messaggio dell'utente, mai da un risultato orfano
    lunghi = (msgs[1:] + msgs) * 50
    tagliati = conversazioni.pulisci(lunghi)
    assert len(tagliati) <= conversazioni.MAX_MESSAGGI
    assert tagliati[0]["role"] == "user" and tagliati[0]["content"][0]["type"] != "tool_result"


@pytest.fixture
def senza_modello(monkeypatch):
    monkeypatch.setattr(llm, "claude_exe", lambda: None)
    f = llm._file()
    f.unlink(missing_ok=True)
    yield
    f.unlink(missing_ok=True)


def test_ogni_progetto_ha_la_sua_chat(tmp_path, monkeypatch, senza_modello):
    visti = []

    def finto_run(store, stato, domanda, run_op, refs=None, mcp_url=None, fermo=None,
                  stile=None, precedente=""):
        visti.append(precedente)
        stato.setdefault("messaggi", []).append({"role": "user", "content": domanda})
        stato["sessione"] = "sess-1"
        yield {"type": "tool", "name": "add_color", "input": {"color": "red", "html": "x" * 5000}}
        yield {"type": "tool_done", "name": "add_color"}
        yield {"type": "text", "text": "Fatto: "}
        yield {"type": "text", "text": "rosso."}
        yield {"type": "done"}

    monkeypatch.setattr(chat, "run", finto_run)
    a, b = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    api_mod.S.store = None
    try:
        with TestClient(api_mod.app) as c:
            c.post("/api/project/create", json={"path": a, "preset": "720p"})
            c.post("/api/chat", json={"message": "metti un rosso"})
            vista = c.get("/api/chat/storia").json()["vista"]
            assert vista[0] == {"role": "user", "text": "metti un rosso", "refs": []}
            assert vista[1]["text"] == "Fatto: rosso."
            assert vista[1]["tools"] == [{"name": "add_color", "state": "ok",
                                          "input": {"color": "red"}}]
            assert (tmp_path / "a.chat.json").is_file()
            # un altro progetto parte vuoto...
            c.post("/api/project/create", json={"path": b, "preset": "720p"})
            assert c.get("/api/chat/storia").json()["vista"] == []
            # ...e riaprendo il primo la conversazione torna, con la sessione
            c.post("/api/project/open", json={"path": a})
            assert len(c.get("/api/chat/storia").json()["vista"]) == 2
            assert api_mod.S.chat["sessione"] == "sess-1"
            # il turno dopo riceve anche il testo della conversazione gia' fatta
            c.post("/api/chat", json={"message": "e adesso blu"})
            assert "metti un rosso" in visti[-1] and "Fatto: rosso." in visti[-1]
            # ricominciare la toglie anche dal disco
            c.post("/api/chat/reset")
            assert c.get("/api/chat/storia").json()["vista"] == []
            assert not (tmp_path / "a.chat.json").exists()
    finally:
        api_mod.S.store = None


def test_contesto_quando_la_cronologia_riparte(tmp_path, monkeypatch, senza_modello):
    """Altro modello, o sessione persa: il testo della chat entra nel primo turno."""
    visto = {}

    def motore(p, cfg, stato, contenuto, *a, **k):
        visto["testo"] = " ".join(x.get("text", "") for x in contenuto)
        yield {"type": "done"}

    monkeypatch.setattr(llm, "claude_exe", lambda: "claude")
    monkeypatch.setattr(llm, "run_claude_code", motore)
    llm.imposta("claude_code")
    s = Store.create("v", path=str(tmp_path / "p.json"))
    stato = {}
    list(chat.run(s, stato, "continua", lambda n, a: "", mcp_url="http://x/mcp/",
                  precedente="Utente: fai uno short"))
    assert "fai uno short" in visto["testo"]
    stato["sessione"] = "s"
    list(chat.run(s, stato, "ancora", lambda n, a: "", mcp_url="http://x/mcp/",
                  precedente="Utente: fai uno short"))
    assert "fai uno short" not in visto["testo"]


# --------------------------------------------------------------------------
# modello e sforzo in un clic
# --------------------------------------------------------------------------


def test_modello_e_sforzo_rapidi(monkeypatch, senza_modello):
    monkeypatch.setattr(llm, "claude_exe", lambda: "claude")
    llm.imposta("claude_code")
    st = llm.imposta_rapido("opus", "xhigh")
    assert st["model"] == "opus" and st["sforzo"] == "xhigh"
    assert "fable" in st["modelli"] and "max" in st["sforzi"]
    with pytest.raises(ValueError):
        llm.imposta_rapido(sforzo="tantissimo")
    # i modelli che non sono Claude non hanno lo sforzo
    llm.imposta("ollama", modello="qwen3")
    assert llm.stato()["sforzi"] == []


def test_claude_code_parte_con_modello_e_sforzo(monkeypatch, senza_modello):
    import subprocess

    visto = {}

    class Finto:
        def __init__(self, args, **kw):
            import io

            visto["args"] = args
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(json.dumps({"type": "result"}).encode() + b"\n")
            self.stderr = io.BytesIO()

        def poll(self):
            return 0

        def wait(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(llm, "claude_exe", lambda: "claude")
    monkeypatch.setattr(subprocess, "Popen", Finto)
    llm.imposta("claude_code")
    llm.imposta_rapido("sonnet", "high")
    p, cfg = llm.attivo()
    list(llm.run_claude_code(p, cfg, {}, [{"type": "text", "text": "x"}], "http://x/mcp/", None))
    args = visto["args"]
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--effort") + 1] == "high"


def test_api_rapida_non_cancella_la_chat(tmp_path, monkeypatch, senza_modello):
    monkeypatch.setattr(llm, "claude_exe", lambda: "claude")
    api_mod.S.store = None
    try:
        with TestClient(api_mod.app) as c:
            c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
            c.post("/api/llm", json={"provider": "claude_code"})
            api_mod.S.chat["sessione"] = "tienimi"
            r = c.post("/api/llm/rapido", json={"modello": "opus", "sforzo": "max"})
            assert r.status_code == 200 and r.json()["sforzo"] == "max"
            assert api_mod.S.chat["sessione"] == "tienimi"
            assert c.post("/api/llm/rapido", json={"sforzo": "boh"}).status_code == 400
    finally:
        api_mod.S.store = None


# --------------------------------------------------------------------------
# voce di Gemini
# --------------------------------------------------------------------------


def test_gemini_tts(monkeypatch, tmp_path):
    import base64

    viste = []
    pcm = b"\x00\x01" * 2400

    def post(url, headers, body, timeout=180):
        viste.append((url, headers, body))
        return json.dumps({"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000",
            "data": base64.b64encode(pcm).decode()}}]}}]}).encode()

    monkeypatch.setattr(tts, "_post", post)
    tts.imposta("gemini", chiave="AIza-prova", voce="Kore", predefinito=False)
    try:
        f = tts.genera("Hello there.", tmp_path, "gemini", istruzioni="Fast, punchy explainer")
        url, headers, body = viste[0]
        assert url.endswith(":generateContent") and "gemini" in url
        assert headers == {"x-goog-api-key": "AIza-prova"}
        testo = body["contents"][0]["parts"][0]["text"]
        assert testo.startswith("Fast, punchy explainer") and "Hello there." in testo
        voce = body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
        assert voce == {"voiceName": "Kore"}
        with wave.open(str(f)) as w:
            assert w.getframerate() == 24000 and w.getnframes() == 2400
    finally:
        tts.imposta("gemini", chiave="", predefinito=False)
