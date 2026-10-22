"""Pubblicare un video esportato sui social, dall'editor.

- **YouTube**: Data API v3, caricamento a riprese (resumable) con login OAuth
  dell'utente. Serve un "client OAuth per app desktop" creato dall'utente su
  Google Cloud (API YouTube Data v3 attiva): id e segreto si incollano una
  volta, poi il login si fa nel browser e resta un refresh token. Il video
  parte **privato** se non si sceglie altro: rendere pubblico e' un gesto
  dell'utente. Un 9:16 sotto i tre minuti YouTube lo tratta da Short.
- **TikTok**: Content Posting API, caricamento nella *casella* dell'utente: il
  video arriva come bozza nell'app TikTok e lo pubblica lui da li'. Vuole un
  access token con lo scope ``video.upload`` di un'app TikTok for Developers
  dell'utente (scade in 24 ore).

Instagram non c'e': l'API dei Reels vuole un account professionale collegato a
una pagina Facebook e un'app Meta approvata, non un login da editor.

Le credenziali stanno in ``~/.vedit/social.json``, solo su questa macchina.
Solo libreria standard: niente SDK di Google o TikTok.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

PIATTAFORME = ("youtube", "tiktok")
PRIVACY = ("private", "unlisted", "public")

_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_SCOPE = ("https://www.googleapis.com/auth/youtube.upload "
          "https://www.googleapis.com/auth/youtube.readonly")
_UPLOAD = ("https://www.googleapis.com/upload/youtube/v3/videos"
           "?uploadType=resumable&part=snippet,status")
_CANALI = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
_TIKTOK = "https://open.tiktokapis.com/v2/post/publish"

# pezzi del caricamento: YouTube vuole multipli di 256 KiB, TikTok fra 5 e 64 MB
_PEZZO_YT = 32 * 256 * 1024
_PEZZO_TT = 10 * 1024 * 1024


class SocialError(RuntimeError):
    """Account non collegato, credenziali scadute, servizio che rifiuta."""


# --------------------------------------------------------------------------
# configurazione (solo su questa macchina)
# --------------------------------------------------------------------------


def _file() -> Path:
    return Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")) / "social.json"


_lock = threading.Lock()


def carica() -> dict:
    try:
        cfg = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    for p in PIATTAFORME:
        cfg.setdefault(p, {})
    return cfg


def _salva(cfg: dict) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"~{f.name}")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def _aggiorna(piattaforma: str, **valori) -> None:
    with _lock:
        cfg = carica()
        for k, v in valori.items():
            if v is None:
                continue
            if v == "":
                cfg[piattaforma].pop(k, None)
            else:
                cfg[piattaforma][k] = v
        _salva(cfg)


def imposta(piattaforma: str, client_id: str | None = None, client_secret: str | None = None,
            token: str | None = None) -> dict:
    """Credenziali di un servizio; ``""`` cancella, ``None`` lascia com'e'."""
    _piattaforma(piattaforma)
    if piattaforma == "youtube":
        cambia = client_id is not None and client_id.strip() != carica()["youtube"].get("client_id")
        _aggiorna("youtube", client_id=client_id and client_id.strip() or client_id,
                  client_secret=client_secret and client_secret.strip() or client_secret)
        if cambia:
            # un altro client: il login fatto col vecchio non vale piu'
            _aggiorna("youtube", refresh_token="", canale="")
    else:
        _aggiorna("tiktok", access_token=token and token.strip() or token,
                  salvato=time.time() if token else None)
    return stato()


def scollega(piattaforma: str) -> dict:
    _piattaforma(piattaforma)
    if piattaforma == "youtube":
        _aggiorna("youtube", refresh_token="", canale="")
    else:
        _aggiorna("tiktok", access_token="", salvato="")
    return stato()


def _piattaforma(p: str) -> None:
    if p not in PIATTAFORME:
        raise SocialError(f"unknown platform {p!r}; available: {', '.join(PIATTAFORME)}")


def stato() -> dict:
    """Cosa e' collegato, senza mai restituire segreti."""
    cfg = carica()
    yt, tt = cfg["youtube"], cfg["tiktok"]
    eta = time.time() - float(tt.get("salvato") or 0)
    return {
        "youtube": {"client": bool(yt.get("client_id") and yt.get("client_secret")),
                    "collegato": bool(yt.get("refresh_token")), "canale": yt.get("canale", ""),
                    "nota": "Needs your own OAuth client (Google Cloud → APIs & Services → "
                            "Credentials → OAuth client ID → Desktop app, with YouTube Data API "
                            "v3 enabled). Paste its id and secret, then sign in."},
        "tiktok": {"collegato": bool(tt.get("access_token")),
                   "scaduto": bool(tt.get("access_token")) and eta > 24 * 3600,
                   "nota": "Paste an access token with the video.upload scope from your TikTok "
                           "for Developers app. The video lands in your TikTok inbox as a draft: "
                           "you post it from the app. Tokens last 24 hours."},
    }


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class _SenzaRedirect(urllib.request.HTTPRedirectHandler):
    """Il 308 di YouTube vuol dire "continua", non "vai altrove": niente redirect."""

    def redirect_request(self, *args, **kwargs):
        return None


_apri = urllib.request.build_opener(_SenzaRedirect).open


def _richiesta(url: str, metodo: str = "GET", dati: bytes | None = None,
               headers: dict | None = None, timeout: float = 120) -> tuple[int, dict, bytes]:
    """Una chiamata HTTP che restituisce anche i codici d'errore invece di sollevarli.

    Il 308 di YouTube ("continua a caricare") per urllib e' un errore: qui e'
    una risposta come le altre.
    """
    req = urllib.request.Request(url, data=dati, method=metodo, headers=headers or {})
    try:
        with _apri(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() or b""
    except urllib.error.URLError as exc:
        raise SocialError(f"cannot reach {urllib.parse.urlsplit(url).netloc}: {exc.reason}") from exc


def _json(corpo: bytes) -> dict:
    try:
        return json.loads(corpo.decode("utf-8") or "{}")
    except ValueError:
        return {}


def _errore(servizio: str, codice: int, corpo: bytes) -> SocialError:
    d = _json(corpo)
    err = d.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("code") or ""
    else:
        msg = d.get("error_description") or err or corpo.decode("utf-8", "replace")[:300]
    return SocialError(f"{servizio} answered {codice}: {msg}")


# --------------------------------------------------------------------------
# YouTube: login
# --------------------------------------------------------------------------


def avvia_login_youtube(apri_browser: bool = True, timeout: float = 300) -> dict:
    """Prepara il login OAuth e aspetta il ritorno in un thread.

    Restituisce subito l'indirizzo da aprire: l'utente accede nel browser,
    Google rimanda a ``http://127.0.0.1:<porta>`` e il thread scambia il codice
    con i token. ``stato()`` dice quando il collegamento e' fatto.
    """
    cfg = carica()["youtube"]
    if not (cfg.get("client_id") and cfg.get("client_secret")):
        raise SocialError("paste the OAuth client id and secret first")
    verificatore = secrets.token_urlsafe(64)
    sfida = base64.urlsafe_b64encode(
        hashlib.sha256(verificatore.encode()).digest()).rstrip(b"=").decode()
    stato_oauth = secrets.token_urlsafe(16)
    esito: dict = {}

    class Ritorno(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (nome imposto da http.server)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if q.get("state", [""])[0] != stato_oauth or not (q.get("code") or q.get("error")):
                self.send_response(404)
                self.end_headers()
                return
            esito["code"] = q.get("code", [""])[0]
            esito["error"] = q.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = ("vedit is connected to YouTube. You can close this tab." if esito["code"]
                   else f"Sign-in cancelled ({esito['error']}). You can close this tab.")
            self.wfile.write(f"<!doctype html><title>vedit</title><p style='font:16px "
                             f"system-ui;margin:3em'>{msg}</p>".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Ritorno)
    server.timeout = 1
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = _AUTH + "?" + urllib.parse.urlencode({
        "client_id": cfg["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": _SCOPE, "code_challenge": sfida, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent", "state": stato_oauth,
    })

    def attendi() -> None:
        fine = time.time() + timeout
        try:
            while time.time() < fine and not esito:
                server.handle_request()
        finally:
            server.server_close()
        if esito.get("code"):
            try:
                _scambia_codice(esito["code"], redirect, verificatore)
            except SocialError as exc:
                _aggiorna("youtube", ultimo_errore=str(exc))

    _aggiorna("youtube", ultimo_errore="")
    threading.Thread(target=attendi, daemon=True, name="youtube-login").start()
    if apri_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return {"url": url}


def _scambia_codice(codice: str, redirect: str, verificatore: str) -> None:
    cfg = carica()["youtube"]
    dati = urllib.parse.urlencode({
        "code": codice, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code",
        "code_verifier": verificatore}).encode()
    c, _, corpo = _richiesta(_TOKEN, "POST", dati,
                             {"Content-Type": "application/x-www-form-urlencoded"})
    if c != 200:
        raise _errore("Google", c, corpo)
    tok = _json(corpo)
    if not tok.get("refresh_token"):
        raise SocialError("Google gave no refresh token: remove vedit's access from your "
                          "Google account and sign in again")
    _aggiorna("youtube", refresh_token=tok["refresh_token"])
    canale = _nome_canale(tok.get("access_token", ""))
    _aggiorna("youtube", canale=canale)


def _nome_canale(access_token: str) -> str:
    c, _, corpo = _richiesta(_CANALI, headers={"Authorization": f"Bearer {access_token}"})
    if c != 200:
        return ""
    items = _json(corpo).get("items") or []
    return items[0]["snippet"]["title"] if items else ""


def _access_token_youtube() -> str:
    cfg = carica()["youtube"]
    if not cfg.get("refresh_token"):
        raise SocialError("YouTube is not connected: sign in from the Publish window")
    dati = urllib.parse.urlencode({
        "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
        "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"}).encode()
    c, _, corpo = _richiesta(_TOKEN, "POST", dati,
                             {"Content-Type": "application/x-www-form-urlencoded"})
    if c != 200:
        if _json(corpo).get("error") == "invalid_grant":
            _aggiorna("youtube", refresh_token="")
            raise SocialError("the YouTube sign-in expired or was revoked: sign in again")
        raise _errore("Google", c, corpo)
    return _json(corpo)["access_token"]


# --------------------------------------------------------------------------
# caricamento
# --------------------------------------------------------------------------


def _controlla_file(file: str) -> Path:
    f = Path(file)
    if not f.is_file() or f.stat().st_size == 0:
        raise SocialError(f"video not found: {file}. Export it first.")
    return f


def pubblica_youtube(file: str, titolo: str, descrizione: str = "", tag: list[str] | None = None,
                     privacy: str = "private", per_bambini: bool = False,
                     categoria: str = "22",
                     progresso: Callable[[float], None] | None = None) -> dict:
    """Carica su YouTube e restituisce id e indirizzo del video."""
    f = _controlla_file(file)
    if privacy not in PRIVACY:
        raise SocialError(f"privacy must be one of {', '.join(PRIVACY)}")
    titolo = " ".join((titolo or "").replace("<", "").replace(">", "").split())[:100]
    if not titolo:
        raise SocialError("the video needs a title")
    descrizione = (descrizione or "").replace("<", "").replace(">", "")[:5000]
    tag = [t.strip().lstrip("#") for t in (tag or []) if t.strip()][:30]
    token = _access_token_youtube()
    dimensione = f.stat().st_size
    meta = {"snippet": {"title": titolo, "description": descrizione, "tags": tag,
                        "categoryId": categoria},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": per_bambini}}
    c, h, corpo = _richiesta(_UPLOAD, "POST", json.dumps(meta).encode("utf-8"), {
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(dimensione), "X-Upload-Content-Type": "video/*"})
    if c != 200:
        raise _errore("YouTube", c, corpo)
    sessione = next((v for k, v in h.items() if k.lower() == "location"), None)
    if not sessione:
        raise SocialError("YouTube gave no upload address")
    inviati = 0
    with f.open("rb") as fh:
        while True:
            fh.seek(inviati)
            pezzo = fh.read(_PEZZO_YT)
            fine = inviati + len(pezzo) - 1
            for tentativo in range(4):
                c, h, corpo = _richiesta(sessione, "PUT", pezzo, {
                    "Authorization": f"Bearer {token}",
                    "Content-Range": f"bytes {inviati}-{fine}/{dimensione}"}, timeout=600)
                if c < 500:
                    break
                time.sleep(2 ** tentativo)
            if c in (200, 201):
                if progresso:
                    progresso(1.0)
                vid = _json(corpo).get("id", "")
                return {"piattaforma": "youtube", "id": vid, "url": f"https://youtu.be/{vid}",
                        "privacy": privacy}
            if c != 308:
                raise _errore("YouTube", c, corpo)
            # il server dice fin dove ha ricevuto davvero
            rng = next((v for k, v in h.items() if k.lower() == "range"), "")
            inviati = int(rng.rsplit("-", 1)[1]) + 1 if rng else 0
            if progresso:
                progresso(inviati / dimensione)


def pubblica_tiktok(file: str, progresso: Callable[[float], None] | None = None) -> dict:
    """Manda il video nella casella TikTok dell'utente, come bozza da pubblicare."""
    f = _controlla_file(file)
    token = carica()["tiktok"].get("access_token")
    if not token:
        raise SocialError("TikTok is not connected: paste an access token in the Publish window")
    dimensione = f.stat().st_size
    pezzo = dimensione if dimensione < 5 * 1024 * 1024 else _PEZZO_TT
    # l'ultimo pezzo assorbe il resto: TikTok conta i pezzi interi
    n = max(1, dimensione // pezzo)
    corpo = json.dumps({"source_info": {"source": "FILE_UPLOAD", "video_size": dimensione,
                                        "chunk_size": pezzo, "total_chunk_count": n}}).encode()
    h_json = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    c, _, risposta = _richiesta(f"{_TIKTOK}/inbox/video/init/", "POST", corpo, h_json)
    d = _json(risposta)
    if c != 200 or (d.get("error") or {}).get("code") not in (None, "ok"):
        raise _errore("TikTok", c, risposta)
    upload, publish_id = d["data"]["upload_url"], d["data"]["publish_id"]
    with f.open("rb") as fh:
        for i in range(n):
            inizio = i * pezzo
            dati = fh.read(pezzo if i < n - 1 else dimensione - inizio)
            c, _, risposta = _richiesta(upload, "PUT", dati, {
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes {inizio}-{inizio + len(dati) - 1}/{dimensione}"},
                timeout=600)
            if c not in (200, 201, 206):
                raise _errore("TikTok", c, risposta)
            if progresso:
                progresso((i + 1) / n)
    return {"piattaforma": "tiktok", "id": publish_id, "url": "",
            "nota": "sent to your TikTok inbox: open the TikTok app to finish and post it"}


def pubblica(piattaforma: str, file: str, titolo: str = "", descrizione: str = "",
             tag: list[str] | None = None, privacy: str = "private",
             progresso: Callable[[float], None] | None = None) -> dict:
    _piattaforma(piattaforma)
    if piattaforma == "youtube":
        return pubblica_youtube(file, titolo, descrizione, tag, privacy, progresso=progresso)
    return pubblica_tiktok(file, progresso)
