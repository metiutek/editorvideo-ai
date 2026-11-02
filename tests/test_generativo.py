"""Generare immagini e video (generativo.py): servizi finti in locale, niente rete vera.
Si controlla cosa parte verso il servizio, che il risultato diventi un media, che la
stessa richiesta non si ripaghi, e che senza il si' dell'utente non si generi."""

import base64
import http.server
import io
import json
import threading

import pytest
from PIL import Image

from test_mcp import call
from vedit import api as api_mod
from vedit import chat, domande, generativo
from vedit import mcp_server as srv
from vedit.store import EditError, Store


def _png(colore="orange") -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 36), colore).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def servizio():
    """OpenAI-like (/images/generations) e coda fal, sullo stesso server."""
    visti: list[tuple[str, str, dict | None, str | None]] = []
    stato = {"polls": 0, "esito": "COMPLETED"}

    class H(http.server.BaseHTTPRequestHandler):
        def _corpo(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n)) if n else None

        def _json(self, d, codice=200):
            b = json.dumps(d).encode()
            self.send_response(codice)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            corpo = self._corpo()
            visti.append(("POST", self.path, corpo, self.headers.get("Authorization")))
            host = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.path.endswith("/images/generations"):
                if corpo["prompt"] == "rifiuta":
                    return self._json({"error": {"message": "policy"}}, 400)
                if corpo["prompt"] == "da url":
                    return self._json({"data": [{"url": f"{host}/file/img.png"}]})
                return self._json({"data": [{"b64_json": base64.b64encode(_png()).decode()}]})
            # coda fal
            self._json({"request_id": "r1", "status_url": f"{host}/status/r1",
                        "response_url": f"{host}/result/r1"})

        def do_GET(self):
            visti.append(("GET", self.path, None, self.headers.get("Authorization")))
            host = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.path.startswith("/status"):
                stato["polls"] += 1
                s = "IN_QUEUE" if stato["polls"] < 2 else stato["esito"]
                return self._json({"status": s, "queue_position": 1, "error": "boom"})
            if self.path.startswith("/result"):
                ultimo = next(v for v in reversed(visti) if v[0] == "POST")[1]
                if "video" in ultimo:
                    return self._json({"video": {"url": f"{host}/file/clip.mp4"}})
                return self._json({"images": [{"url": f"{host}/file/img.png"}]})
            if self.path == "/file/img.png":
                b = _png("blue")
                ct = "image/png"
            else:
                b = _VIDEO.read_bytes()
                ct = "video/mp4"
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass

    srv_ = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv_.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv_.server_address[1]}", "visti": visti, "stato": stato}
    srv_.shutdown()


_VIDEO = None


@pytest.fixture(autouse=True)
def _video(assets):
    global _VIDEO
    from pathlib import Path
    _VIDEO = Path(assets["red"])
    yield


@pytest.fixture(autouse=True)
def _config_pulita():
    """La cache dei test e' una per sessione: la configurazione di un test non deve
    restare al successivo."""
    generativo._file().unlink(missing_ok=True)
    yield
    generativo._file().unlink(missing_ok=True)


def _config(url, **sopra):
    generativo.imposta("openai", "k-openai", indirizzo=url + "/v1", predefinito=True)
    generativo.imposta("fal", "k-fal", indirizzo=url, predefinito=False)


def test_senza_servizio_dice_cosa_fare(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    with pytest.raises(generativo.GenError, match="no service ready to make images.*gen-setup"):
        generativo.genera("image", "un gatto", tmp_path)
    with pytest.raises(generativo.GenError, match="cannot make videos; use fal"):
        generativo.genera("video", "un gatto", tmp_path, servizio="openai")
    with pytest.raises(generativo.GenError, match="unknown generation service"):
        generativo.imposta("midjourney")


def test_la_chiave_sta_nel_file_privato_e_non_esce_dallo_stato(tmp_path):
    generativo.imposta("fal", "segretissima")
    assert "segretissima" in generativo._file().read_text(encoding="utf-8")
    assert "segretissima" not in json.dumps(generativo.stato())
    fal = next(m for m in generativo.stato()["motori"] if m["id"] == "fal")
    assert fal["ha_chiave"] and fal["pronto"] == {"image": True, "video": True}


def test_immagine_openai_in_base64_e_cache(servizio, tmp_path):
    _config(servizio["url"])
    r = generativo.genera("image", "un gatto arancione", tmp_path, formato="9:16", seed=3)
    assert r["servizio"] == "openai" and r["cache"] is False and r["path"].endswith(".png")
    assert Image.open(r["path"]).size == (64, 36)
    metodo, percorso, corpo, auth = servizio["visti"][0]
    assert percorso == "/v1/images/generations" and auth == "Bearer k-openai"
    assert corpo["model"] == "gpt-image-1" and corpo["size"] == "1024x1536" and corpo["n"] == 1
    # la stessa richiesta non chiama di nuovo il servizio
    n = len(servizio["visti"])
    r2 = generativo.genera("image", "un gatto arancione", tmp_path, formato="9:16", seed=3)
    assert r2["cache"] is True and r2["path"] == r["path"] and len(servizio["visti"]) == n
    # un parametro diverso e' un'altra richiesta
    assert generativo.genera("image", "un gatto arancione", tmp_path, formato="16:9")["cache"] is False


def test_immagine_da_url_e_errori_del_servizio(servizio, tmp_path):
    _config(servizio["url"])
    r = generativo.genera("image", "da url", tmp_path)
    assert Image.open(r["path"]).size == (64, 36)
    with pytest.raises(generativo.GenError, match=r"service error \(400\): policy"):
        generativo.genera("image", "rifiuta", tmp_path)
    with pytest.raises(generativo.GenError, match="format 4:3 is not available"):
        generativo.genera("image", "x", tmp_path, formato="4:3", servizio="openai")


def test_video_fal_coda_attesa_e_scaricamento(servizio, tmp_path, monkeypatch):
    monkeypatch.setattr(generativo.time, "sleep", lambda s: None)
    _config(servizio["url"])
    avanza = []
    r = generativo.genera("video", "un drone sulla costa", tmp_path, durata=5, formato="9:16",
                          seed=7, opzioni={"negative_prompt": "blur"},
                          avanza=lambda f, n: avanza.append(n))
    assert r["servizio"] == "fal" and r["path"].endswith(".mp4") and r["cache"] is False
    post = next(v for v in servizio["visti"] if v[0] == "POST")
    assert post[1] == "/fal-ai/kling-video/v2.1/master/text-to-video" and post[3] == "Key k-fal"
    assert post[2] == {"prompt": "un drone sulla costa", "aspect_ratio": "9:16", "duration": "5",
                       "seed": 7, "negative_prompt": "blur"}
    assert servizio["stato"]["polls"] >= 2 and any("queue" in n for n in avanza)


def test_immagine_in_video_manda_il_file_come_data_uri(servizio, tmp_path, monkeypatch):
    monkeypatch.setattr(generativo.time, "sleep", lambda s: None)
    _config(servizio["url"])
    partenza = tmp_path / "start.png"
    partenza.write_bytes(_png())
    generativo.genera("video", "si muove", tmp_path, durata=5, immagine=str(partenza))
    post = next(v for v in servizio["visti"] if v[0] == "POST")
    assert post[1].endswith("/image-to-video")        # il modello cambia con la partenza
    assert post[2]["image_url"].startswith("data:image/png;base64,")
    with pytest.raises(generativo.GenError, match="image not found"):
        generativo.genera("video", "x", tmp_path, immagine=str(tmp_path / "manca.png"))


def test_fallimento_e_modello_scelto_dall_utente(servizio, tmp_path, monkeypatch):
    monkeypatch.setattr(generativo.time, "sleep", lambda s: None)
    _config(servizio["url"])
    servizio["stato"]["esito"] = "FAILED"
    with pytest.raises(generativo.GenError, match="could not make it: boom"):
        generativo.genera("image", "x", tmp_path, servizio="fal")
    servizio["visti"].clear()
    servizio["stato"].update(polls=0, esito="COMPLETED")
    generativo.imposta("fal", modello_immagini="fal-ai/mio-modello")
    generativo.genera("image", "x2", tmp_path, servizio="fal")
    assert servizio["visti"][0][1] == "/fal-ai/mio-modello"


def test_indirizzi_inutilizzabili_non_si_scaricano(tmp_path):
    with pytest.raises(generativo.GenError, match="unusable address"):
        generativo._scarica("file:///etc/passwd", tmp_path / "x")


# --------------------------------------------------------------------------
# dentro l'editor: conferma, MCP, chat, API
# --------------------------------------------------------------------------


def test_la_conferma_dice_cosa_e_quanto_costa():
    d = domande.conferma_genera("video", "un drone\nsulla costa " * 20, "fal.ai", "kling")
    assert "generate a video with fal.ai" in d[0]["domanda"]
    assert "credits" in d[0]["opzioni"][0]["descrizione"] and len(d[0]["opzioni"][0]["descrizione"]) < 260


@pytest.mark.anyio
async def test_mcp_senza_conferma_non_genera(servizio, tmp_path):
    _config(servizio["url"])
    await call("project_create", path=str(tmp_path / "p.json"), name="t", preset="720p")
    r = await call("generate_media", kind="image", prompt="un gatto")
    assert r["generato"] is False and "conferma" in r["motivo"]
    assert not servizio["visti"]                     # niente e' partito verso il servizio


@pytest.mark.anyio
async def test_mcp_con_conferma_importa_il_media(servizio, tmp_path):
    _config(servizio["url"])
    await call("project_create", path=str(tmp_path / "p.json"), name="t", preset="720p")
    r = await call("generate_media", kind="image", prompt="un gatto", confirmed=True)
    assert r["generato"] is True and r["kind"] == "image" and r["servizio"] == "openai"
    assert r["resolution"] == "64x36"
    info = await call("project_info", detail="full")
    assert r["id"] in json.dumps(info)
    assert (tmp_path / "p_gen").is_dir()
    # un video da quell'immagine: la partenza e' un media del progetto
    servizio["visti"].clear()
    v = await call("generate_media", kind="video", prompt="si muove", image=r["id"], duration=5,
                   confirmed=True)
    assert v["generato"] is True and v["kind"] == "video"
    assert servizio["visti"][0][2]["image_url"].startswith("data:image/png")
    with pytest.raises(Exception, match="starting frame must be an image"):
        await call("generate_media", kind="video", prompt="x", image=v["id"], confirmed=True)
    servizi = await call("generation_services")
    assert servizi["motore"] == "openai"             # il predefinito scelto da _config


@pytest.mark.anyio
async def test_mcp_senza_servizio_pronto_dice_come_impostarlo(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    await call("project_create", path=str(tmp_path / "p.json"), name="t", preset="720p")
    with pytest.raises(Exception, match="no service ready"):
        await call("generate_media", kind="image", prompt="x", confirmed=True)


def test_chat_genera_e_importa(servizio, tmp_path):
    _config(servizio["url"])
    s = Store.create("t", "720p", path=str(tmp_path / "c.json"))
    assert "generate_media" in {t["name"] for t in chat.build_tools()}
    out = json.loads(chat.execute(s, "generate_media", {"kind": "image", "prompt": "un gatto"}))
    assert out["generato"] is True and out["kind"] == "image"
    assert any(m.id == out["id"] for m in s.project.media)
    # il servizio finto ha ricevuto una richiesta sola e l'elenco dei servizi non porta segreti
    assert "k-openai" not in chat.execute(s, "generation_services", {})


def test_api_configura_e_la_chat_chiede_prima(servizio, tmp_path, monkeypatch):
    """Dal modello in chat: se l'utente dice no, niente parte verso il servizio."""
    from fastapi.testclient import TestClient

    api_mod.S.store = None
    risultati = []

    def finto_run(store, stato, domanda, run_op, **k):
        risultati.append(json.loads(run_op("generate_media", {"kind": "image", "prompt": domanda})))
        yield {"type": "text", "text": "ok"}
        yield {"type": "done"}

    monkeypatch.setattr(chat, "run", finto_run)
    risposte = iter([{"risposte": {"0": "No"}}, {"risposte": {"0": "Yes, generate"}}])
    domandate = []
    monkeypatch.setattr(api_mod, "chiedi", lambda d: (domandate.append(d), next(risposte))[1])
    try:
        with TestClient(api_mod.app) as c:
            r = c.post("/api/gen", json={"servizio": "openai", "chiave": "k-openai",
                                         "indirizzo": servizio["url"] + "/v1"})
            assert r.status_code == 200 and r.json()["motore"] == "openai"
            assert "k-openai" not in r.text
            assert c.post("/api/gen", json={"servizio": "boh"}).status_code == 400
            c.post("/api/project/create", json={"path": str(tmp_path / "a.json"), "preset": "720p"})

            c.post("/api/chat", json={"message": "un gatto"})
            assert risultati[0]["generato"] is False and not servizio["visti"]   # ha detto no
            c.post("/api/chat", json={"message": "un gatto"})
            assert risultati[1]["generato"] is True and risultati[1]["kind"] == "image"
            assert len(domandate) == 2 and "generate an image" in domandate[0][0]["domanda"]
            assert any(m.id == risultati[1]["id"] for m in api_mod.S.store.project.media)
    finally:
        api_mod.S.store = None


def test_i_servizi_sono_dichiarati_senza_dipendenze():
    """Solo libreria standard: niente da aggiungere a pyproject."""
    import ast
    import pathlib

    fonte = pathlib.Path(generativo.__file__).read_text(encoding="utf-8")
    esterni = {n.names[0].name.split(".")[0] for n in ast.walk(ast.parse(fonte))
               if isinstance(n, ast.Import)}
    assert esterni <= {"base64", "hashlib", "json", "mimetypes", "os", "time", "urllib"}
    assert srv.generativo is generativo and isinstance(EditError("x"), Exception)


@pytest.mark.anyio
async def test_un_errore_nel_lavoro_lungo_arriva_col_suo_messaggio(tmp_path):
    """Con il canale di progresso attivo l'errore non si incapsula in un ExceptionGroup:
    chi lo cattura (``except GenError``) lo vede, e l'agente legge il motivo vero."""
    generativo.imposta("openai", "k", indirizzo="http://127.0.0.1:9/v1")      # niente in ascolto
    await call("project_create", path=str(tmp_path / "p.json"), name="t", preset="720p")
    with pytest.raises(Exception, match="cannot reach the service"):
        await call("generate_media", kind="image", prompt="x", confirmed=True)
