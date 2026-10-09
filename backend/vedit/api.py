"""API REST/WebSocket per l'interfaccia web.

Le modifiche non hanno un endpoint ciascuno: passano tutte da ``/api/op/{nome}``
che chiama il metodo omonimo di ``Store``. Cosi' la UI e il server MCP usano
esattamente le stesse operazioni e non possono divergere.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import mimetypes
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from urllib.parse import quote

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat as chat_mod
from . import effects as fx
from . import domande, ffmpeg, htmlclip, hw, llm, presets, proxy, render, stili
from .model import TRANSITIONS, Effect
from .store import PRESETS, EditError, Store

def _frontend_dir() -> Path:
    """Dove sta l'interfaccia compilata.

    Installata da pip la UI viaggia dentro il pacchetto (``vedit/webui``);
    lavorando sulla repo sta in ``frontend/dist``, che e' anche quella che si
    ricompila con ``npm run build`` — quindi in sviluppo vince la seconda solo
    se la prima non c'e'.
    """
    dentro = Path(__file__).resolve().parent / "webui"
    if (dentro / "index.html").is_file():
        return dentro
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


FRONTEND = _frontend_dir()

# operazioni di editing esposte alla UI (nomi dei metodi di Store)
OPS = {
    "import_media", "set_media", "remove_media", "rename_folder",
    "add_track", "set_track", "set_sidechain", "remove_track", "move_track",
    "add_clip", "add_text", "add_color", "add_html", "set_html", "remove_clip", "move_clip", "move_layer", "trim_clip",
    "split_clip", "set_speed", "set_reverse", "set_transform", "set_audio",
    "set_fades", "set_clip", "set_text", "add_effect", "update_effect",
    "remove_effect", "move_effect", "append_sequence", "crossfade", "set_transition", "close_gaps",
    "set_loudnorm", "set_settings", "undo", "redo", "save",
}


class Session:
    """Progetto aperto + code di lavoro. Una sola sessione per processo."""

    def __init__(self) -> None:
        self.store: Store | None = None
        self.jobs: dict[str, dict] = {}
        self.listeners: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.lock = threading.RLock()
        # conversazione con l'assistente: contiene i blocchi tool_use/tool_result,
        # che i turni successivi devono rimandare intatti
        self.chat: dict = {}
        # "ferma" premuto nella chat: il turno in corso si interrompe al primo passo utile
        self.fermo = threading.Event()
        # domanda in attesa di risposta nel browser (ask_user, conferma export)
        self.domanda: dict | None = None
        # porta su cui ascolta l'interfaccia: serve a dire a Claude Code dov'e'
        # il server MCP dell'editor
        self.porta: int | None = None
        # Numero di modifiche al progetto viste da questo processo. Viaggia in
        # ogni risposta e in ogni evento "project": il browser applica solo lo
        # stato piu' nuovo che conosce, cosi' una risposta arrivata in ritardo
        # non riporta la timeline indietro di un passo.
        self.seq = 0
        self._rev_cache: tuple | None = None

    def need(self) -> Store:
        if self.store is None:
            raise HTTPException(400, "nessun progetto aperto")
        return self.store

    def publish(self, event: dict) -> None:
        """Notifica i client connessi (chiamabile anche da thread di lavoro)."""
        if event.get("type") == "project":
            self.seq += 1
            event = {**event, "seq": self.seq}
        if self.loop is None:
            return
        for q in list(self.listeners):
            self.loop.call_soon_threadsafe(q.put_nowait, event)

    def state_of_project(self) -> dict:
        """Progetto, percorso e revisione: quello che la UI applica a ogni cambio."""
        return {"project": self.store.summary("full") if self.store else None,
                "path": self.store.path if self.store else None,
                "revision": self.revision(), "seq": self.seq}

    def revision(self) -> str:
        """Impronta del progetto: invalida le cache di anteprima quando cambia.

        E' un hash del contenuto, cosi' due stati uguali (una modifica e il suo
        undo) ritrovano le stesse anteprime. Ma serializzare tutto il progetto
        a ogni fotogramma dello scrub costa: l'impronta si ricalcola solo
        quando ``Store.version`` dice che qualcosa e' cambiato.
        """
        store = self.store
        if store is None:
            return "0"
        # oggetti veri e non id(): un id si ricicla dopo la garbage collection
        c = self._rev_cache
        if c and c[0] is store and c[1] is store.project and c[2] == store.version:
            return c[3]
        project, version = store.project, store.version
        blob = json.dumps(project.to_dict(), sort_keys=True).encode()
        rev = hashlib.sha1(blob).hexdigest()[:16]
        self._rev_cache = (store, project, version, rev)
        return rev


# --------------------------------------------------------------------------
# progetti recenti
# --------------------------------------------------------------------------

RECENTI_MAX = 12


def _file_recenti() -> Path:
    return proxy.cache_dir() / "recenti.json"


def recenti() -> list[dict]:
    """Ultimi progetti aperti o creati, dal piu' recente; quelli spariti no."""
    try:
        voci = json.loads(_file_recenti().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for v in voci:
        p = Path(str(v.get("path", "")))
        if p.is_file():
            out.append({"path": str(p), "name": v.get("name") or p.stem,
                        "quando": v.get("quando", 0)})
    return out[:RECENTI_MAX]


def ricorda_recente(store: Store) -> None:
    """Segna il progetto fra i recenti: e' quello che la schermata iniziale propone."""
    if not store.path:
        return
    voci = [v for v in recenti() if v["path"] != store.path]
    voci.insert(0, {"path": store.path, "name": store.project.name, "quando": time.time()})
    try:
        _file_recenti().write_text(json.dumps(voci[:RECENTI_MAX], ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    except OSError:
        pass   # non poter ricordare non e' un motivo per non aprire


S = Session()
class _PonteMcp:
    """Il server MCP dell'editor, montato su /mcp dell'interfaccia.

    Chi si collega qui (Claude Code, Cursor, un altro agente) lavora sullo
    *stesso* Store del browser: un solo progetto in memoria, un solo
    scrittore, e ogni modifica compare subito in timeline. L'app MCP vera si
    crea a ogni avvio del server, perche' il suo gestore di sessioni si puo'
    avviare una volta sola.
    """

    def __init__(self) -> None:
        self.app = None

    async def __call__(self, scope, receive, send):
        if self.app is None:
            res = JSONResponse({"detail": "server MCP non attivo"}, status_code=503)
            await res(scope, receive, send)
            return
        await self.app(scope, receive, send)


_mcp = _PonteMcp()
MCP_ATTIVO = False


@asynccontextmanager
async def _vita(_app):
    """Avvia e ferma il server MCP insieme all'interfaccia."""
    global MCP_ATTIVO
    try:
        from mcp.server.transport_security import TransportSecuritySettings

        from . import mcp_server

        # i controlli su host e origine li fa gia' il middleware qui sotto
        sub = mcp_server.mcp.streamable_http_app(
            streamable_http_path="/", stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    except Exception:  # noqa: BLE001 - senza MCP l'interfaccia funziona lo stesso
        sub = None
    if sub is None:
        yield
        return
    async with sub.router.lifespan_context(sub):
        _mcp.app = sub
        MCP_ATTIVO = True
        try:
            yield
        finally:
            MCP_ATTIVO = False
            _mcp.app = None


app = FastAPI(title="vedit", lifespan=_vita)
app.mount("/mcp", _mcp)


def mcp_url() -> str | None:
    """Indirizzo del server MCP dell'editor, se l'interfaccia e' in ascolto."""
    if not MCP_ATTIVO or not S.porta:
        return None
    return f"http://127.0.0.1:{S.porta}/mcp/"

# Nomi con cui il server accetta di essere chiamato. Vuoto = nessun controllo
# (i test usano TestClient, che si presenta come "testserver"); serve() e
# serve_background() lo riempiono.
_host_consentiti: set[str] = set()
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _consenti_host(host: str) -> None:
    _host_consentiti.update(_LOOPBACK)
    if host not in ("0.0.0.0", "::", ""):
        _host_consentiti.add(host)
    else:
        # in ascolto su tutte le interfacce l'utente ha scelto la rete: il
        # controllo sul nome non avrebbe senso
        _host_consentiti.clear()


def _nome_host(valore: str) -> str:
    """'127.0.0.1:8760' -> '127.0.0.1'; '[::1]:8760' -> '[::1]'."""
    valore = valore.strip().lower()
    if valore.startswith("["):
        return valore.split("]")[0] + "]"
    return valore.rsplit(":", 1)[0] if valore.count(":") == 1 else valore


@app.middleware("http")
async def _solo_locale(request: Request, call_next):
    """Difesa da DNS rebinding e da richieste mandate da altri siti.

    L'API legge e scrive file ovunque sul disco (import, render, /api/file).
    Una pagina qualunque aperta nel browser puo' puntare a 127.0.0.1: con un
    dominio che si risolve in locale (rebinding) il nome nella richiesta non e'
    il nostro, e con un form multipart l'Origin e' quella dell'altro sito.
    Entrambe si rifiutano.
    """
    if not _da_qui(request.headers) and not _lettura_html(request):
        return JSONResponse({"detail": "richiesta non locale rifiutata"}, status_code=403)
    return await call_next(request)


def _lettura_html(request: Request) -> bool:
    """Le clip html girano in un iframe in sandbox, quindi con Origin "null".

    Font e moduli che caricano dalla loro cartella arrivano cosi': si lasciano
    passare solo in lettura e solo sotto /api/html/, che serve file della
    cartella della clip e nient'altro. Il controllo sul nome host resta.
    """
    if request.method != "GET" or not request.url.path.startswith("/api/html/"):
        return False
    if request.headers.get("origin") != "null":
        return False
    return not _host_consentiti or _nome_host(request.headers.get("host", "")) in _host_consentiti


def _da_qui(headers) -> bool:
    if not _host_consentiti:
        return True
    if _nome_host(headers.get("host", "")) not in _host_consentiti:
        return False
    origin = headers.get("origin")
    if origin is None:
        return True     # navigazione e GET dalla stessa pagina: niente Origin
    # "null" e' l'Origin delle pagine in sandbox: non e' la nostra interfaccia
    return _nome_host(origin.split("://", 1)[-1]) in _host_consentiti


# --------------------------------------------------------------------------
# progetto
# --------------------------------------------------------------------------


class CreateBody(BaseModel):
    path: str
    name: str = "untitled"
    preset: str = "1080p"


class OpenBody(BaseModel):
    path: str


@app.get("/api/state")
def state() -> dict:
    info = hw.detect()
    return {
        **S.state_of_project(),
        # cartella proposta dai dialoghi "nuovo progetto" ed "esporta": chi apre
        # l'editor per la prima volta non deve inventarsi un percorso
        "home": _cartella_video(),
        "recenti": recenti(),
        "effects": fx.describe(),
        "transitions": list(TRANSITIONS),
        "library": presets.describe(),
        "presets": list(PRESETS),
        "chat": chat_available(),
        "stili": stili.descrivi(),
        "system": {"ffmpeg": ffmpeg.version(), "encoders": info.encoders,
                   "hw": info.working},
    }


def _cartella_video() -> str:
    """Dove proporre i nuovi progetti: la cartella Video dell'utente se c'e'."""
    home = Path.home()
    for nome in ("Videos", "Video", "Movies", "Filmati"):
        if (home / nome).is_dir():
            return str(home / nome)
    return str(home)


@app.get("/api/project")
def project_state() -> dict:
    """Solo il progetto: e' quello che la UI richiede a ogni evento "project".

    Piu' leggero di /api/state, che porta anche cataloghi e rilevamento
    hardware, roba che non cambia mentre si monta.
    """
    return S.state_of_project()


@app.post("/api/project/create")
def project_create(body: CreateBody) -> dict:
    try:
        attach(Store.create(name=body.name, preset=body.preset, path=body.path))
    except (EditError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    S.chat.clear()
    ricorda_recente(S.store)
    S.publish({"type": "project"})
    return {**S.state_of_project(), "recenti": recenti()}


@app.post("/api/project/open")
def project_open(body: OpenBody) -> dict:
    try:
        attach(Store.open(body.path))
    except (EditError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    S.chat.clear()
    ricorda_recente(S.store)
    S.publish({"type": "project"})
    return {**S.state_of_project(), "recenti": recenti()}


@app.get("/api/recenti")
def lista_recenti() -> list[dict]:
    return recenti()


@app.post("/api/op/{name}")
def op(name: str, body: dict | None = None) -> dict:
    """Esegue un'operazione di editing e restituisce il progetto aggiornato."""
    if name not in OPS:
        raise HTTPException(404, f"operazione sconosciuta: {name}")
    store = S.need()
    args = dict(body or {})
    try:
        with S.lock:
            result = getattr(store, name)(**args)
    except TypeError as exc:
        raise HTTPException(400, f"argomenti non validi per {name}: {exc}") from exc
    except (EditError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc

    _avvisa(store)
    return {"result": _plain(result), **S.state_of_project()}


def _avvisa(store: Store) -> None:
    """Dice ai browser che il progetto e' cambiato, una volta sola.

    Con l'interfaccia agganciata al server MCP ci pensa gia' ``on_change`` a
    ogni modifica di Store: pubblicare anche qui mandava due eventi per ogni
    gesto, e il browser ricaricava lo stato due volte.
    """
    if store.on_change is None:
        S.publish({"type": "project"})


def _plain(value: Any) -> Any:
    """Rende serializzabile qualunque cosa tornino i metodi di Store."""
    from dataclasses import is_dataclass

    from .model import to_dict

    if is_dataclass(value):
        return to_dict(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------
# file system (dialogo di import)
# --------------------------------------------------------------------------


@app.get("/api/browse")
def browse(path: str | None = None) -> dict:
    from .model import AUDIO_EXTS, IMAGE_EXTS, VIDEO_EXTS

    # .json compreso: la stessa finestra serve per aprire i progetti
    known = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | {".json"}
    base = Path(path) if path else Path.home()
    if not base.exists():
        raise HTTPException(404, f"cartella inesistente: {base}")
    if base.is_file():
        base = base.parent

    dirs, files = [], []
    try:
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": str(entry)})
                elif entry.suffix.lower() in known:
                    files.append({"name": entry.name, "path": str(entry),
                                  "size": entry.stat().st_size})
            except OSError:
                continue
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc

    return {"path": str(base), "parent": str(base.parent) if base.parent != base else None,
            "dirs": dirs, "files": files}


@app.get("/api/media/{media_id}/waveform")
def waveform(media_id: str) -> dict:
    store = S.need()
    m = store.media_or_die(media_id)
    return {"peaks": proxy.waveform(m), "duration": m.duration}


@app.get("/api/media/{media_id}/strip")
def strip(media_id: str, height: int = 44) -> dict:
    """Striscia di fotogrammi usata come sfondo delle clip video in timeline."""
    store = S.need()
    m = store.media_or_die(media_id)
    info = proxy.filmstrip(m, height)
    if not info:
        return {}
    return {**info, "url": f"/api/file?path={quote(info['path'])}"}


@app.get("/api/media/{media_id}/stream")
def stream(media_id: str, request: Request):
    """Riproduce il file nel monitor sorgente: usa il proxy se disponibile."""
    store = S.need()
    m = store.media_or_die(media_id)
    src = m.proxy if (m.proxy and Path(m.proxy).exists()) else m.path
    p = Path(src)
    if not p.is_file():
        raise HTTPException(404, f"file non trovato: {src}")
    # FileResponse gestisce le richieste Range, indispensabili per il seek
    return FileResponse(p, media_type=mimetypes.guess_type(p.name)[0] or "video/mp4")


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), folder: str = Form("")) -> dict:
    """Riceve i file trascinati dal desktop.

    Il browser non passa il percorso di origine, quindi qui il file viene
    copiato accanto al progetto. Per file grandi conviene il pulsante di import,
    che li referenzia dove sono senza duplicarli.
    """
    store = S.need()
    if not store.path:
        raise HTTPException(400, "salva il progetto prima di trascinarci dentro dei file")
    dest_dir = Path(store.path).parent / "media"
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for f in files:
        name = Path(f.filename or "file").name
        target = dest_dir / name
        i = 1
        while target.exists():
            target = dest_dir / f"{Path(name).stem}_{i}{Path(name).suffix}"
            i += 1
        with target.open("wb") as out:
            while chunk := await f.read(1 << 20):
                out.write(chunk)
        saved.append(str(target))

    with S.lock:
        media = store.import_media(saved)
        if folder:
            for m in media:
                store.set_media(m.id, folder=folder)
    _avvisa(store)
    return {"importati": [m.id for m in media], **S.state_of_project()}


@app.get("/api/file")
def raw_file(path: str):
    p = Path(path)
    if not p.is_file():
        raise HTTPException(404, "file inesistente")
    return FileResponse(p, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream")


# --------------------------------------------------------------------------
# clip html: il documento per l'anteprima dal vivo
# --------------------------------------------------------------------------

# l'iframe e' in sandbox (origine opaca): i font e i moduli che carica sono
# richieste CORS e senza questo intestazione il browser le scarta
_CORS_HTML = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}


def _clip_html(clip_id: str):
    store = S.need()
    found = store.project.find_clip(clip_id)
    if not found or found[1].type != "html":
        raise HTTPException(404, f"clip html {clip_id!r} inesistente")
    return store, found[1]


@app.get("/api/html/{clip_id}")
def html_doc(clip_id: str) -> HTMLResponse:
    """Il documento della clip con l'orologio virtuale, pilotato dalla UI.

    E' lo stesso che Chromium fotografa al render (htmlclip.compose): quello
    che si vede nell'anteprima dal vivo e' quello che finisce nel file.
    """
    store, clip = _clip_html(clip_id)
    base = f"/api/html/{clip_id}/files/" if clip.html_base else None
    doc = htmlclip.compose(clip.html or "", store.project.settings.fps, base)
    return HTMLResponse(doc, headers=_CORS_HTML)


@app.get("/api/html/{clip_id}/files/{rel:path}")
def html_file(clip_id: str, rel: str):
    """File relativi della clip (immagini, font, script), solo dalla sua cartella."""
    _, clip = _clip_html(clip_id)
    if not clip.html_base:
        raise HTTPException(404, "la clip non ha una cartella base")
    root = Path(clip.html_base).resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "file inesistente")
    return FileResponse(target, headers=_CORS_HTML,
                        media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")


# --------------------------------------------------------------------------
# anteprima
# --------------------------------------------------------------------------


def _preview_dir() -> Path:
    return proxy.cache_dir("preview")


# Un lock per chiave di cache: due richieste sullo stesso segmento non lo
# renderizzano due volte, la seconda aspetta ed usa il file della prima.
_render_locks: dict[str, threading.Lock] = {}
_render_guard = threading.Lock()


def _key_lock(key: str) -> threading.Lock:
    with _render_guard:
        if len(_render_locks) > 256:
            # le chiavi contengono la revisione: quelle vecchie non servono piu'
            for k, lock in list(_render_locks.items()):
                if not lock.locked():
                    del _render_locks[k]
        return _render_locks.setdefault(key, threading.Lock())


def _ready(path: Path) -> bool:
    """Vero solo se il file e' completo: quelli in corso di scrittura non contano."""
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def _temp_beside(out: Path) -> Path:
    """Nome temporaneo con la stessa estensione: ffmpeg sceglie il formato da li'."""
    return out.with_name(f"~{uuid.uuid4().hex[:8]}_{out.name}")


# Fotogrammi al secondo dei segmenti di anteprima. Solo la codifica sta sulla
# GPU: filtri, sovrapposizioni e scalatura sono su CPU, e il loro costo e' per
# fotogramma prodotto. Su una timeline a 60 fps questo dimezza l'attesa.
PREVIEW_FPS = 30.0

# Quanti render di anteprima possono girare insieme. Non e' un limite di CPU:
# oltre qualche ffmpeg in parallelo si litiga la memoria e il disco, e ognuno
# diventa piu' lento di quanto si guadagni dal parallelismo.
_preview_slots = threading.Semaphore(3)


def _snapshot():
    """Copia del progetto su cui rendere, presa sotto lock.

    Il lock serve a non leggere il progetto mentre una modifica lo sta
    cambiando: quella lettura dura la compilazione del filtergraph, 7 ms.
    Tenerlo per tutta l'esecuzione di ffmpeg significava invece che un solo
    prefetch da dodici secondi bloccava *ogni* fotogramma dello scrub finche'
    non aveva finito. La copia costa quanto la compilazione e li disaccoppia.
    """
    with S.lock:
        return copy.deepcopy(S.need().project)


def _produce(out: Path, make) -> None:
    """Renderizza in un file temporaneo e lo sposta a destinazione solo a fine lavoro.

    Senza questo passaggio la cache espone il file mentre ffmpeg lo sta ancora
    scrivendo: il player riceve un mp4 senza atomo ``moov`` e la riproduzione
    non parte. ``os.replace`` e' atomico sullo stesso volume.
    """
    tmp = _temp_beside(out)
    try:
        with _preview_slots:
            make(tmp)
        os.replace(tmp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _aggiungi_prova(snap, effetti: list[Effect], clip_id: str | None) -> None:
    """Mette gli effetti sulla *copia*.

    Serve all'anteprima al passaggio del mouse: si vede come verrebbe senza che
    il progetto cambi, quindi niente voce di undo e niente da annullare se poi
    non lo si vuole.
    """
    if not clip_id:
        snap.master.effects.extend(effetti)
        return
    for track in snap.tracks:
        for c in track.clips:
            if c.id == clip_id:
                c.effects.extend(effetti)
                return
    raise HTTPException(404, f"clip sconosciuta: {clip_id}")


@app.get("/api/frame")
def frame(t: float = 0.0, width: int = 960,
          effect: str | None = None, preset: str | None = None, clip: str | None = None):
    """Fotogramma della timeline: e' l'anteprima usata durante lo scrub.

    Con ``effect`` (un effetto) o ``preset`` (un look della libreria, che e' una
    catena di effetti) il fotogramma esce come se fosse applicato, senza
    applicarlo davvero.
    """
    store = S.need()
    if store.project.duration() <= 0:
        raise HTTPException(400, "timeline vuota")
    if effect and effect not in fx.EFFECTS:
        raise HTTPException(400, f"effetto sconosciuto: {effect}")

    da_provare: list[Effect] = []
    if effect:
        da_provare.append(Effect(type=effect, params=fx.validate_effect(effect, {})))
    if preset:
        p = presets.find(preset)
        if not p:
            raise HTTPException(400, f"preset sconosciuto: {preset}")
        for e in p.get("effects", []):
            da_provare.append(Effect(type=e["type"],
                                     params=fx.validate_effect(e["type"], e.get("params") or {})))

    prova = f"_{effect or ''}_{preset or ''}_{clip or 'master'}" if da_provare else ""
    key = f"f_{S.revision()}_{t:.3f}_{width}{prova}"
    out = _preview_dir() / f"{key}.jpg"
    if not _ready(out):
        with _key_lock(key):
            if not _ready(out):
                snap = _snapshot()
                if da_provare:
                    _aggiungi_prova(snap, da_provare, clip)
                try:
                    _produce(out, lambda tmp: render.render_frame(
                        snap, t, str(tmp), width, use_proxy=True))
                except Exception as exc:
                    raise HTTPException(500, f"anteprima fallita: {exc}") from exc
    return FileResponse(out, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


def _segment(start: float, duration: float, height: int) -> tuple[Path, float, float]:
    """Percorso in cache del segmento; lo renderizza se manca."""
    store = S.need()
    total = store.project.duration()
    if total <= 0:
        raise HTTPException(400, "timeline vuota")
    start = max(0.0, min(start, max(0.0, total - 0.05)))
    duration = max(0.2, min(duration, total - start))

    # Il costo del segmento e' per fotogramma prodotto: su un progetto a 60 fps
    # renderizzarne meta' dimezza l'attesa prima che parta la riproduzione. E'
    # il compromesso normale di un monitor di lavorazione — il file finale esce
    # sempre agli fps del progetto. Sta nella chiave perche' descrive il
    # contenuto del file in cache.
    fps = min(float(store.project.settings.fps or PREVIEW_FPS), PREVIEW_FPS)

    key = f"p_{S.revision()}_{start:.3f}_{duration:.3f}_{height}_{fps:g}"
    out = _preview_dir() / f"{key}.mp4"
    if _ready(out):
        return out, start, duration

    w = int(store.project.settings.width * height / max(1, store.project.settings.height))
    w += w % 2
    snap = _snapshot()

    def make(tmp: Path) -> None:
        render.render(snap, render.RenderOptions(
            output=str(tmp), quality="draft", start=start, end=start + duration,
            width=w, height=height, fps=fps, use_proxy=True, audio_bitrate="128k",
        ))

    with _key_lock(key):
        # potrebbe averlo appena finito il prefetch mentre aspettavamo il lock
        if not _ready(out):
            try:
                _produce(out, make)
            except Exception as exc:
                raise HTTPException(500, f"anteprima fallita: {exc}") from exc
    return out, start, duration


@app.get("/api/preview")
def preview(start: float = 0.0, duration: float = 10.0, height: int = 540):
    """Segmento riprodotto dal player: renderizzato in bozza e messo in cache."""
    out, _, _ = _segment(start, duration, height)
    return FileResponse(out, media_type="video/mp4",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/preview/prefetch")
def preview_prefetch(start: float = 0.0, duration: float = 10.0, height: int = 540) -> dict:
    """Prepara un segmento in sottofondo, cosi' e' pronto quando servira'.

    Il player lo chiama per il pezzo successivo appena inizia a riprodurre:
    la riproduzione prosegue senza attesa al cambio di segmento.
    """
    S.need()
    total = S.store.project.duration()
    if start >= total - 0.05:
        return {"skip": True}

    def work() -> None:
        try:
            _segment(start, duration, height)
            S.publish({"type": "prefetch", "start": start, "state": "done"})
        except Exception:
            pass  # un prefetch fallito non e' un errore per l'utente

    threading.Thread(target=work, daemon=True, name="prefetch").start()
    return {"avviato": True, "start": start, "duration": duration}


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------


class RenderBody(BaseModel):
    output: str
    quality: str = "high"
    codec: str = "h264"
    bitrate: str | None = None
    start: float | None = None
    end: float | None = None
    # Formato di uscita diverso da quello del progetto: la stessa timeline esce
    # 16:9, quadrata o verticale senza doverla rifare. Le clip si adattano al
    # nuovo fotogramma secondo il proprio "fit" — cover riempie tagliando ai
    # lati, contain lascia le bande.
    width: int | None = None
    height: int | None = None


@app.post("/api/render")
def render_start(body: RenderBody) -> dict:
    S.need()
    job_id = uuid.uuid4().hex[:8]
    S.jobs[job_id] = {"id": job_id, "state": "running", "percent": 0.0,
                      "output": body.output, "started": time.time()}

    # Copia presa sotto lock, come per l'anteprima: un export dura minuti e le
    # modifiche di Store avvengono sugli stessi oggetti Clip che il thread sta
    # leggendo. Senza copia, continuare a montare mentre si esporta cambia il
    # file che sta uscendo — o fa fallire la compilazione a meta'.
    project = _snapshot()

    def work() -> None:
        def on_progress(p: dict) -> None:
            S.jobs[job_id].update(percent=p["percent"], seconds=p["seconds"],
                                  duration=p["duration"], elapsed=p["elapsed"])
            S.publish({"type": "render", "job": S.jobs[job_id]})

        try:
            opts = render.RenderOptions(
                output=body.output, quality=body.quality, codec=body.codec,
                bitrate=body.bitrate, start=body.start, end=body.end,
                width=body.width, height=body.height,
            )
            res = render.render(project, opts, on_progress=on_progress)
            S.jobs[job_id].update(state="done", percent=100.0, output=res.output,
                                  mb=round(res.size / 1e6, 2), encoder=res.encoder,
                                  seconds_total=res.seconds, warnings=res.warnings)
        except Exception as exc:
            S.jobs[job_id].update(state="error", error=str(exc))
        S.publish({"type": "render", "job": S.jobs[job_id]})

    threading.Thread(target=work, daemon=True, name=f"render-{job_id}").start()
    return S.jobs[job_id]


@app.get("/api/render/{job_id}")
def render_status(job_id: str) -> dict:
    job = S.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job inesistente")
    return job


@app.post("/api/proxies")
def build_proxies(height: int = 540) -> dict:
    store = S.need()

    def work() -> None:
        try:
            proxy.ensure(store.project, height)
            with S.lock:
                # i percorsi dei proxy entrano nel progetto senza passare da una
                # modifica di Store: la revisione va invalidata a mano, se no
                # le anteprime in cache restano quelle fatte sugli originali
                store.version += 1
                if store.path:
                    store.save()
            S.publish({"type": "proxies", "state": "done"})
            S.publish({"type": "project"})
        except Exception as exc:
            S.publish({"type": "proxies", "state": "error", "error": str(exc)})

    threading.Thread(target=work, daemon=True, name="proxies").start()
    return {"avviato": True}


@app.post("/api/loudness")
def loudness() -> dict:
    # Sulla copia, non sotto lock: la misura e' un passaggio intero di ffmpeg
    # sul mix, e tenere il lock per tutto quel tempo bloccava ogni modifica e
    # ogni anteprima finche' non aveva finito.
    try:
        measured = render.measure_loudness(_snapshot())
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"lufs": float(measured.get("input_i", 0)),
            "true_peak": float(measured.get("input_tp", 0)),
            "lra": float(measured.get("input_lra", 0)),
            "measured": measured}


# --------------------------------------------------------------------------
# libreria preset
# --------------------------------------------------------------------------


class PresetBody(BaseModel):
    preset_id: str
    clip_id: str | None = None


@app.post("/api/preset/apply")
def preset_apply(body: PresetBody) -> dict:
    """Applica un preset in un colpo solo: un'unica voce di undo, non una per effetto."""
    store = S.need()
    p = presets.find(body.preset_id)
    if p is None:
        raise HTTPException(404, f"preset sconosciuto: {body.preset_id}")
    try:
        with S.lock:
            store.add_effects(body.clip_id, p["effects"])
    except (EditError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    _avvisa(store)
    return {"applicato": p["name"], "effetti": len(p["effects"]), **S.state_of_project()}


# --------------------------------------------------------------------------
# assistente
# --------------------------------------------------------------------------


class ChatBody(BaseModel):
    message: str
    stile: str | None = None
    # punti del video di cui si parla: istanti, tratti, clip, aree dell'inquadratura
    refs: list[dict] = []


def chat_available() -> dict:
    """Modello attivo, se si puo' usare, e l'elenco di quelli configurabili."""
    try:
        return chat_mod.available()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "motivo": str(exc), "providers": []}


class LlmBody(BaseModel):
    provider: str
    chiave: str | None = None
    modello: str | None = None
    indirizzo: str | None = None
    attiva: bool = True


@app.get("/api/plugins")
def plugin_elenco() -> dict:
    from . import plugins

    return {"plugin": plugins.elenco()}


@app.get("/api/plugin/parametri")
def plugin_parametri(file: str) -> dict:
    from . import plugins

    try:
        return plugins.parametri(file)
    except plugins.PluginNonDisponibile as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/llm")
def llm_stato() -> dict:
    return {**chat_available(), "mcp": mcp_url()}


@app.post("/api/llm")
def llm_imposta(body: LlmBody) -> dict:
    """Sceglie il modello e salva la chiave, solo su questa macchina (~/.vedit)."""
    try:
        llm.imposta(body.provider, body.chiave, body.modello, body.indirizzo, body.attiva)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    S.chat.clear()
    return {**chat_available(), "mcp": mcp_url()}


class StileBody(BaseModel):
    nome: str
    guida: str
    breve: str = ""
    piano: str = "vlog"
    id: str | None = None


@app.get("/api/stili")
def stili_elenco() -> dict:
    return {"stili": stili.descrivi()}


@app.post("/api/stili")
def stili_salva(body: StileBody) -> dict:
    """Stile di montaggio scritto dall'utente: resta su questo computer (~/.vedit)."""
    try:
        nuovo = stili.salva(body.nome, body.guida, body.breve, body.piano, body.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"stile": nuovo["id"], "stili": stili.descrivi()}


@app.delete("/api/stili/{stile_id}")
def stili_elimina(stile_id: str) -> dict:
    try:
        stili.elimina(stile_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"stili": stili.descrivi()}


def _cartella_allegati() -> Path:
    import tempfile

    store = S.store
    dest = (Path(store.path).parent / "allegati") if store and store.path \
        else Path(tempfile.gettempdir()) / "vedit_allegati"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


class LinkBody(BaseModel):
    url: str


@app.post("/api/chat/link")
def chat_link(body: LinkBody) -> dict:
    """Legge (o scarica) un link e lo restituisce come riferimento per la chat."""
    from . import collegamenti

    try:
        return collegamenti.risolvi_link(body.url, _cartella_allegati())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - rete, certificati, 404 del sito
        raise HTTPException(400, f"non riesco a leggere il link: {exc}") from exc


@app.post("/api/chat/allega")
async def chat_allega(files: list[UploadFile] = File(...)) -> dict:
    """File allegati a un messaggio: immagini, PDF, testi, video, audio.

    Restano accanto al progetto (cartella ``allegati``) cosi' il modello, e
    l'utente, li ritrovano; senza progetto salvato vanno nella cartella
    temporanea.
    """
    dest = _cartella_allegati()
    out = []
    for f in files:
        name = Path(f.filename or "file").name
        target = dest / name
        i = 1
        while target.exists():
            target = dest / f"{Path(name).stem}_{i}{Path(name).suffix}"
            i += 1
        size = 0
        with target.open("wb") as fh:
            while chunk := await f.read(1 << 20):
                fh.write(chunk)
                size += len(chunk)
        out.append({"name": target.name, "path": str(target), "size": size,
                    "tipo": chat_mod.tipo_allegato(target)})
    return {"allegati": out}


def chiedi(lista, timeout: float = 1800.0) -> dict:
    """Mostra le domande nel browser e aspetta la risposta (o "ferma").

    Blocca chi chiama, quindi va usata da un thread: la chat gira gia' in uno,
    il server MCP ci passa con anyio.to_thread. Una domanda per volta: e' una
    persona sola a rispondere.
    """
    norm = domande.valida(lista)
    qid = uuid.uuid4().hex[:10]
    evento = threading.Event()
    if S.domanda is not None:
        return {"annullata": True, "motivo": "c'e' gia' una domanda in attesa di risposta"}
    S.domanda = {"id": qid, "domande": norm, "evento": evento, "risposte": None}
    S.publish({"type": "domande", "id": qid, "domande": norm})
    scadenza = time.time() + timeout
    try:
        while not evento.wait(0.25):
            if S.fermo.is_set():
                return {"annullata": True, "motivo": "l'utente ha fermato l'assistente"}
            if time.time() > scadenza:
                return {"annullata": True, "motivo": "nessuna risposta"}
        r = S.domanda["risposte"] or {}
        if r.get("__annulla__"):
            return {"annullata": True, "motivo": "l'utente ha chiuso le domande senza rispondere"}
        return {"risposte": r}
    finally:
        S.domanda = None
        S.publish({"type": "domande_chiuse", "id": qid})


@app.get("/api/domanda")
def domanda_aperta() -> dict:
    d = S.domanda
    return {"domanda": {"id": d["id"], "domande": d["domande"]} if d else None}


class RispostaBody(BaseModel):
    risposte: dict


@app.post("/api/domanda/{qid}")
def domanda_rispondi(qid: str, body: RispostaBody) -> dict:
    d = S.domanda
    if d is None or d["id"] != qid:
        raise HTTPException(404, "nessuna domanda in attesa con questo id")
    d["risposte"] = body.risposte
    d["evento"].set()
    return {"ok": True}


@app.post("/api/chat/stop")
def chat_stop() -> dict:
    """Interrompe il turno dell'assistente in corso (le modifiche gia' fatte restano)."""
    S.fermo.set()
    return {"ok": True}


@app.post("/api/chat/reset")
def chat_reset() -> dict:
    S.chat.clear()
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatBody) -> StreamingResponse:
    """Un turno con l'assistente, in streaming (SSE).

    Gli strumenti passano dagli stessi metodi di ``Store`` usati dalla UI, sotto
    lo stesso lock: una modifica dell'assistente e una tua non possono
    intrecciarsi a meta'.
    """
    store = S.need()

    def run_op(name: str, args: dict) -> str:
        if name == "ask_user":
            # fuori dal lock: si aspetta l'utente, non si tocca il progetto
            return json.dumps(chiedi(args.get("domande", args)), ensure_ascii=False)
        with S.lock:
            out = chat_mod.execute(store, name, args)
        _avvisa(store)
        return out

    def events():
        def send(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n"

        try:
            S.fermo.clear()
            for ev in chat_mod.run(store, S.chat, body.message, run_op,
                                   refs=body.refs, mcp_url=mcp_url(), fermo=S.fermo.is_set,
                                   stile=body.stile):
                yield send(ev)
        except chat_mod.ChatUnavailable as exc:
            yield send({"type": "error", "message": str(exc)})
        except Exception as exc:
            yield send({"type": "error", "message": str(exc)})
        # il progetto e' cambiato: la UI ricarica lo stato completo
        yield send({"type": "end", **S.state_of_project()})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------
# websocket
# --------------------------------------------------------------------------


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    # il middleware http non vede i websocket: stesso controllo qui
    if not _da_qui(sock.headers):
        await sock.close(code=1008)
        return
    await sock.accept()
    S.loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    S.listeners.add(queue)
    try:
        await sock.send_json({"type": "hello", "revision": S.revision(), "seq": S.seq})
        while True:
            event = await queue.get()
            await sock.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        S.listeners.discard(queue)


# --------------------------------------------------------------------------
# frontend
# --------------------------------------------------------------------------


@app.exception_handler(EditError)
def _edit_error(_request, exc: EditError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


class _Interfaccia(StaticFiles):
    """File della UI; la pagina d'ingresso non resta mai in cache.

    Gli script compilati hanno l'impronta nel nome e possono restare in cache
    per sempre, ma index.html no: il browser la teneva e dopo un aggiornamento
    continuava a caricare l'interfaccia vecchia — le correzioni sembravano non
    funzionare finche' non si forzava il ricaricamento.
    """

    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        if path in ("", ".", "index.html") or r.media_type == "text/html":
            r.headers["Cache-Control"] = "no-cache"
        return r


def mount_frontend() -> None:
    if FRONTEND.is_dir():
        app.mount("/", _Interfaccia(directory=str(FRONTEND), html=True), name="ui")
    else:
        @app.get("/")
        def _missing() -> dict:
            return {"errore": "interfaccia non compilata",
                    "come": "cd frontend && npm install && npm run build"}


def serve(host: str = "127.0.0.1", port: int = 8760, project: str | None = None,
          open_browser: bool = True) -> None:
    import uvicorn

    if project:
        attach(Store.open(project))
    _consenti_host(host)
    mount_frontend()

    S.porta = port
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.0, lambda: __import__("webbrowser").open(url)).start()
    print(f"vedit su {url}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


# --------------------------------------------------------------------------
# interfaccia avviata da dentro un altro processo (server MCP)
# --------------------------------------------------------------------------

_background: dict[str, Any] = {}


def attach(store: Store) -> None:
    """Fa lavorare l'interfaccia sullo *stesso* Store di chi la avvia.

    E' il punto che evita il conflitto descritto in AGENTS.md: se UI e agente
    aprissero due Store sullo stesso file, ognuno salverebbe la propria copia e
    l'ultimo vincerebbe. Condividendo l'oggetto c'e' un solo scrittore, e
    ``on_change`` fa aggiornare il browser quando a montare e' l'agente.
    """
    if S.store is not None and S.store is not store:
        S.store.on_change = None
    S.store = store
    store.on_change = lambda: S.publish({"type": "project"})


def _porta_libera(host: str, porta: int) -> int:
    import socket

    for tentativo in range(porta, porta + 20):
        with socket.socket() as s:
            if s.connect_ex((host, tentativo)) != 0:
                return tentativo
    raise RuntimeError(f"nessuna porta libera fra {porta} e {porta + 20}")


def serve_background(store: Store | None = None, host: str = "127.0.0.1", port: int = 8760,
                     open_browser: bool = True) -> dict:
    """Avvia l'interfaccia in un thread di questo processo e torna subito.

    Chiamarla di nuovo non riavvia niente: aggancia l'eventuale nuovo progetto
    al server gia' in piedi.
    """
    import uvicorn

    if store is not None:
        attach(store)

    if _background.get("url"):
        if open_browser:
            __import__("webbrowser").open(_background["url"])
        return {**_background, "avviato_ora": False,
                "progetto": S.store.path if S.store else None}

    _consenti_host(host)
    mount_frontend()
    port = _porta_libera(host, port)
    S.porta = port
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="vedit-ui")
    thread.start()

    scadenza = time.time() + 15
    while not server.started and thread.is_alive() and time.time() < scadenza:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("l'interfaccia non si e' avviata entro 15 secondi")

    _background.update({"url": f"http://{host}:{port}", "host": host, "port": port,
                        "server": server, "thread": thread})
    if open_browser:
        __import__("webbrowser").open(_background["url"])
    return {"url": _background["url"], "host": host, "port": port, "avviato_ora": True,
            "progetto": S.store.path if S.store else None,
            "interfaccia_compilata": FRONTEND.is_dir()}


def background_info() -> dict | None:
    if not _background.get("url"):
        return None
    return {"url": _background["url"], "port": _background["port"],
            "progetto": S.store.path if S.store else None}


def stop_background() -> bool:
    server = _background.get("server")
    if not server:
        return False
    server.should_exit = True
    thread = _background.get("thread")
    if thread:
        thread.join(timeout=10)
    _background.clear()
    _host_consentiti.clear()
    return True
