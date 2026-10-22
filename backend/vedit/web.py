"""Il web per chi monta: cercare, leggere pagine, scaricare media da usare come clip.

Nessun sito fisso: il modello cerca in tutto il web (pagine, immagini, video,
notizie), legge qualunque pagina e scarica qualunque immagine, video o audio.
Per le pagine dei video (YouTube, Vimeo, social...) usa yt-dlp, se c'e'.

Motori di ricerca, in ``~/.vedit/web.json``:

- ``duckduckgo``: senza chiave, e' il default: DuckDuckGo per web, video e
  notizie, Bing per le immagini. Legge le stesse risposte dei siti, quindi puo'
  rompersi quando cambiano le pagine;
- ``brave``: Brave Search API, chiave gratuita, web/immagini/video/notizie;
- ``tavily``: pensato per gli agenti, web e immagini;
- ``searxng``: un'istanza SearXNG (propria o pubblica con il formato json).

Ogni file scaricato lascia una riga in ``FONTI.md`` nella cartella dei download
del progetto: da dove viene, per i crediti e per sapere cosa si puo' usare.

Sicurezza: niente indirizzi locali o di rete privata (si arriverebbe all'API
dell'editor stesso, o ad altro sulla rete di casa), anche dopo un redirect.
Il testo delle pagine e' materiale da leggere, non istruzioni.
"""

from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .collegamenti import _ext_da_tipo, _nome_da_url, _Testo

MOTORI = ("duckduckgo", "brave", "tavily", "searxng")
TIPI = ("web", "images", "videos", "news")
MAX_PAGINA = 3_000_000
MAX_SCARICO = 2_000_000_000
MAX_TESTO = 20_000
# Chi siamo, onestamente: Wikipedia e altri rifiutano un finto browser. Solo le
# pagine dei motori senza chiave vogliono l'intestazione di un browser vero.
_UA = "Mozilla/5.0 (vedit; +https://github.com/metiutek/editorvideo-ai)"
_UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
_MEDIA_CT = ("image/", "video/", "audio/")


class WebError(RuntimeError):
    """Ricerca o scaricamento non riusciti: il messaggio dice perche'."""


# --------------------------------------------------------------------------
# configurazione
# --------------------------------------------------------------------------


def _file() -> Path:
    return Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")) / "web.json"


def carica() -> dict:
    try:
        cfg = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("motore", "")
    cfg.setdefault("chiavi", {})
    cfg.setdefault("indirizzi", {})
    return cfg


def imposta(motore: str, chiave: str | None = None, indirizzo: str | None = None) -> dict:
    if motore not in MOTORI:
        raise WebError(f"unknown search engine {motore!r}; available: {', '.join(MOTORI)}")
    cfg = carica()
    if chiave is not None:
        if chiave.strip():
            cfg["chiavi"][motore] = chiave.strip()
        else:
            cfg["chiavi"].pop(motore, None)
    if indirizzo is not None:
        cfg["indirizzi"][motore] = indirizzo.strip().rstrip("/")
    cfg["motore"] = motore
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"~{f.name}")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, f)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return stato()


def _chiave(motore: str, cfg: dict) -> str:
    env = {"brave": "BRAVE_API_KEY", "tavily": "TAVILY_API_KEY"}.get(motore, "")
    return cfg["chiavi"].get(motore) or os.environ.get(env, "")


def motore_attivo(cfg: dict | None = None) -> str:
    """Il motore scelto; senza scelta il primo con la chiave, poi DuckDuckGo."""
    cfg = cfg or carica()
    if cfg["motore"]:
        return cfg["motore"]
    for m in ("brave", "tavily"):
        if _chiave(m, cfg):
            return m
    return "searxng" if cfg["indirizzi"].get("searxng") else "duckduckgo"


def stato() -> dict:
    cfg = carica()
    return {
        "motore": motore_attivo(cfg),
        "motori": [
            {"id": "duckduckgo", "nome": "No key (DuckDuckGo)", "pronto": True,
             "nota": "No key: DuckDuckGo for web, videos and news, Bing for images. "
                     "Reads the sites' own answers, so it may break when they change."},
            {"id": "brave", "nome": "Brave Search", "pronto": bool(_chiave("brave", cfg)),
             "chiave": bool(_chiave("brave", cfg)), "vuole_chiave": True,
             "nota": "Free API key from api-dashboard.search.brave.com. Web, images, videos, news."},
            {"id": "tavily", "nome": "Tavily", "pronto": bool(_chiave("tavily", cfg)),
             "chiave": bool(_chiave("tavily", cfg)), "vuole_chiave": True,
             "nota": "API key from tavily.com, made for agents. Web and images."},
            {"id": "searxng", "nome": "SearXNG", "pronto": bool(cfg["indirizzi"].get("searxng")),
             "indirizzo": cfg["indirizzi"].get("searxng", ""), "vuole_indirizzo": True,
             "nota": "Address of a SearXNG instance with the json format enabled."},
        ],
        "yt_dlp": bool(_yt_dlp()),
    }


# --------------------------------------------------------------------------
# rete, con la rete locale chiusa
# --------------------------------------------------------------------------


def _host_permesso(url: str) -> None:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise WebError(f"only http(s) addresses: {url}")
    if os.environ.get("VEDIT_WEB_LOCALE") == "1":
        return  # i test parlano con un server finto in locale
    try:
        indirizzi = {a[4][0] for a in socket.getaddrinfo(p.hostname, None)}
    except socket.gaierror as exc:
        raise WebError(f"cannot resolve {p.hostname}") from exc
    for a in indirizzi:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global:
            raise WebError(f"{p.hostname} is a local or private address: not allowed")


class _RedirectControllato(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _host_permesso(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_apri = urllib.request.build_opener(_RedirectControllato).open
_apri_certifi = None


def _con_certifi(req, timeout):
    """Secondo tentativo con i certificati di certifi.

    Su alcuni Windows l'archivio di sistema che legge Python ha una radice
    scaduta: curl e il browser passano, urllib no ("certificate has expired").
    """
    global _apri_certifi
    if _apri_certifi is None:
        import ssl

        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        _apri_certifi = urllib.request.build_opener(
            _RedirectControllato, urllib.request.HTTPSHandler(context=ctx)).open
    return _apri_certifi(req, timeout=timeout)


def _richiesta(url: str, dati: bytes | None = None, headers: dict | None = None,
               timeout: float = 30):
    import ssl

    _host_permesso(url)
    h = {"User-Agent": _UA, "Accept-Language": "en,it;q=0.8", **(headers or {})}
    req = urllib.request.Request(url, data=dati, headers=h)
    try:
        try:
            return _apri(req, timeout=timeout)
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise
            return _con_certifi(req, timeout)
    except urllib.error.HTTPError as exc:
        raise WebError(f"{urllib.parse.urlparse(url).netloc} answered {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise WebError(f"cannot reach {urllib.parse.urlparse(url).netloc}: {exc.reason}") from exc


def _testo(url: str, dati: bytes | None = None, headers: dict | None = None) -> str:
    with _richiesta(url, dati, headers) as r:
        grezzo = r.read(MAX_PAGINA)
        return grezzo.decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def _json(url: str, dati: bytes | None = None, headers: dict | None = None) -> dict:
    try:
        return json.loads(_testo(url, dati, headers))
    except ValueError as exc:
        raise WebError(f"unexpected answer from {urllib.parse.urlparse(url).netloc}") from exc


# --------------------------------------------------------------------------
# ricerca
# --------------------------------------------------------------------------


def _voce(titolo, url, media=None, anteprima=None, testo="", **extra) -> dict:
    out = {"title": " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(titolo or ""))).split())[:200],
           "url": url or ""}
    if media:
        out["media"] = media
    if anteprima:
        out["thumb"] = anteprima
    if testo:
        out["snippet"] = " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(testo))).split())[:400]
    out.update({k: v for k, v in extra.items() if v})
    return out


class _RisultatiDdg(HTMLParser):
    """I risultati di html.duckduckgo.com: link, titolo, estratto."""

    def __init__(self) -> None:
        super().__init__()
        self.voci: list[dict] = []
        self._dove = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classi = a.get("class") or ""
        if tag == "a" and "result__a" in classi:
            href = a.get("href") or ""
            q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            self.voci.append({"title": "", "url": q.get("uddg", [href])[0], "snippet": ""})
            self._dove = "title"
        elif tag in ("a", "div") and "result__snippet" in classi and self.voci:
            self._dove = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "div"):
            self._dove = ""

    def handle_data(self, data):
        if self._dove and self.voci:
            self.voci[-1][self._dove] += data


def _vqd(query: str) -> str:
    pagina = _testo("https://duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": query, "iax": "images", "ia": "images"}), headers={"User-Agent": _UA_BROWSER})
    m = re.search(r"vqd=[\"']?([\d-]+)", pagina)
    if not m:
        raise WebError("DuckDuckGo did not answer as expected: try again, or set another "
                       "search engine (Brave, Tavily, SearXNG)")
    return m.group(1)


def _bing_immagini(query: str, n: int) -> list[dict]:
    """Immagini da Bing: l'endpoint immagini di DuckDuckGo ora chiede una verifica
    anti-bot, e quella non si aggira."""
    pagina = _testo("https://www.bing.com/images/async?" + urllib.parse.urlencode(
        {"q": query, "first": 0, "count": max(n, 10), "mmasync": 1}),
        headers={"User-Agent": _UA_BROWSER})
    out = []
    for grezzo in re.findall(r'\bm="([^"]+)"', pagina):
        try:
            d = json.loads(html.unescape(grezzo))
        except ValueError:
            continue
        if d.get("murl"):
            out.append(_voce(d.get("t"), d.get("purl"), d["murl"], d.get("turl"),
                             source=urllib.parse.urlparse(d.get("purl") or "").netloc))
        if len(out) >= n:
            break
    return out


def _duckduckgo(query: str, tipo: str, n: int) -> list[dict]:
    if tipo == "web":
        pagina = _testo("https://html.duckduckgo.com/html/",
                        urllib.parse.urlencode({"q": query}).encode(),
                        {"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": _UA_BROWSER})
        p = _RisultatiDdg()
        p.feed(pagina)
        return [_voce(v["title"], v["url"], testo=v["snippet"]) for v in p.voci[:n]]
    if tipo == "images":
        return _bing_immagini(query, n)
    fine = {"images": "i.js", "videos": "v.js", "news": "news.js"}[tipo]
    d = _json(f"https://duckduckgo.com/{fine}?" + urllib.parse.urlencode(
        {"l": "wt-wt", "o": "json", "q": query, "vqd": _vqd(query), "p": "1"}),
        headers={"Referer": "https://duckduckgo.com/", "User-Agent": _UA_BROWSER})
    out = []
    for r in d.get("results", [])[:n]:
        if tipo == "images":
            out.append(_voce(r.get("title"), r.get("url"), r.get("image"), r.get("thumbnail"),
                             size=f"{r.get('width')}x{r.get('height')}" if r.get("width") else "",
                             source=r.get("source")))
        elif tipo == "videos":
            out.append(_voce(r.get("title"), r.get("content"), r.get("content"),
                             (r.get("images") or {}).get("medium"), r.get("description"),
                             duration=r.get("duration"), publisher=r.get("publisher")))
        else:
            out.append(_voce(r.get("title"), r.get("url"), None, r.get("image"),
                             r.get("excerpt"), source=r.get("source"),
                             date=time.strftime("%Y-%m-%d", time.gmtime(r["date"]))
                             if r.get("date") else ""))
    return out


def _brave(query: str, tipo: str, n: int, chiave: str) -> list[dict]:
    if not chiave:
        raise WebError("Brave Search needs an API key")
    tratto = {"web": "web", "images": "images", "videos": "videos", "news": "news"}[tipo]
    d = _json(f"https://api.search.brave.com/res/v1/{tratto}/search?" + urllib.parse.urlencode(
        {"q": query, "count": min(n, 20 if tipo != "images" else 100)}),
        headers={"X-Subscription-Token": chiave, "Accept": "application/json"})
    righe = (d.get("web") or {}).get("results", []) if tipo == "web" else d.get("results", [])
    out = []
    for r in righe[:n]:
        anteprima = (r.get("thumbnail") or {}).get("src")
        if tipo == "images":
            out.append(_voce(r.get("title"), r.get("url"), (r.get("properties") or {}).get("url"),
                             anteprima, source=r.get("source")))
        elif tipo == "videos":
            out.append(_voce(r.get("title"), r.get("url"), r.get("url"), anteprima,
                             r.get("description"),
                             duration=(r.get("video") or {}).get("duration")))
        else:
            out.append(_voce(r.get("title"), r.get("url"), None, anteprima, r.get("description"),
                             date=r.get("age")))
    return out


def _tavily(query: str, tipo: str, n: int, chiave: str) -> list[dict]:
    if not chiave:
        raise WebError("Tavily needs an API key")
    if tipo == "videos":
        raise WebError("Tavily does not search videos: use DuckDuckGo, Brave or SearXNG")
    d = _json("https://api.tavily.com/search", json.dumps({
        "api_key": chiave, "query": query, "max_results": min(n, 20),
        "include_images": tipo == "images", "topic": "news" if tipo == "news" else "general",
    }).encode(), {"Content-Type": "application/json"})
    if tipo == "images":
        return [_voce(query, u, u, u) for u in d.get("images", [])[:n]]
    return [_voce(r.get("title"), r.get("url"), testo=r.get("content"))
            for r in d.get("results", [])[:n]]


def _searxng(query: str, tipo: str, n: int, base: str) -> list[dict]:
    if not base:
        raise WebError("set the address of a SearXNG instance")
    cat = {"web": "general", "images": "images", "videos": "videos", "news": "news"}[tipo]
    d = _json(f"{base}/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "categories": cat}))
    out = []
    for r in d.get("results", [])[:n]:
        media = r.get("img_src") if tipo == "images" else (r.get("url") if tipo == "videos" else None)
        out.append(_voce(r.get("title"), r.get("url"), media,
                         r.get("thumbnail_src") or r.get("thumbnail"), r.get("content"),
                         size=r.get("resolution"), source=r.get("engine")))
    return out


def cerca(query: str, tipo: str = "web", n: int = 10, motore: str | None = None) -> dict:
    """Cerca sul web. Ogni risultato: title, url (la pagina), media (il file
    diretto di un'immagine o la pagina di un video), thumb, snippet."""
    query = " ".join((query or "").split())
    if not query:
        raise WebError("what should I search for?")
    if tipo not in TIPI:
        raise WebError(f"kind must be one of {', '.join(TIPI)}")
    n = max(1, min(int(n or 10), 50))
    cfg = carica()
    m = motore or motore_attivo(cfg)
    if m == "duckduckgo":
        voci = _duckduckgo(query, tipo, n)
    elif m == "brave":
        voci = _brave(query, tipo, n, _chiave("brave", cfg))
    elif m == "tavily":
        voci = _tavily(query, tipo, n, _chiave("tavily", cfg))
    elif m == "searxng":
        voci = _searxng(query, tipo, n, cfg["indirizzi"].get("searxng", ""))
    else:
        raise WebError(f"unknown search engine {m!r}")
    return {"motore": m, "tipo": tipo, "risultati": voci}


# --------------------------------------------------------------------------
# leggere una pagina
# --------------------------------------------------------------------------


class _Media(HTMLParser):
    """Immagini e video di una pagina: og:image/og:video, <img>, <video>, <source>."""

    def __init__(self, base: str) -> None:
        super().__init__()
        self.base = base
        self.immagini: list[str] = []
        self.video: list[str] = []

    def _aggiungi(self, lista: list[str], src: str | None) -> None:
        if not src or src.startswith("data:"):
            return
        u = urllib.parse.urljoin(self.base, html.unescape(src.strip()))
        if u.startswith(("http://", "https://")) and u not in lista:
            lista.append(u)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop in ("og:image", "og:image:url", "twitter:image"):
                self._aggiungi(self.immagini, a.get("content"))
            elif prop in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"):
                self._aggiungi(self.video, a.get("content"))
        elif tag == "img":
            src = a.get("src") or a.get("data-src")
            if not src and a.get("srcset"):
                # la variante piu' grande dell'srcset
                src = a["srcset"].split(",")[-1].strip().split(" ")[0]
            w = a.get("width") or ""
            if w.isdigit() and int(w) < 64:
                return  # icone, pixel di tracciamento
            self._aggiungi(self.immagini, src)
        elif tag in ("video", "source"):
            src = a.get("src")
            tipo = a.get("type") or ""
            if tag == "source" and tipo and not tipo.startswith("video/"):
                return
            self._aggiungi(self.video, src)
            if tag == "video":
                self._aggiungi(self.immagini, a.get("poster"))


def leggi(url: str, max_testo: int = MAX_TESTO) -> dict:
    """Testo di una pagina, piu' le immagini e i video che contiene."""
    with _richiesta(url.strip()) as r:
        finale = r.geturl()
        ct = (r.headers.get("Content-Type") or "").lower()
        if ct.startswith(_MEDIA_CT):
            return {"url": finale, "media": finale, "tipo": ct.split(";")[0],
                    "nota": "this address is a media file: web_download it"}
        grezzo = r.read(MAX_PAGINA)
        pagina = grezzo.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    if "html" not in ct and "<html" not in pagina[:3000].lower():
        return {"url": finale, "title": _nome_da_url(finale), "testo": pagina[:max_testo]}
    t = _Testo()
    t.feed(pagina)
    m = _Media(finale)
    m.feed(pagina)
    corpo = t.testo()
    out = {"url": finale, "title": html.unescape(t.titolo.strip()),
           "testo": corpo[:max_testo] + ("\n[... cut ...]" if len(corpo) > max_testo else ""),
           "immagini": m.immagini[:40], "video": m.video[:15]}
    if _yt_dlp():
        out["nota"] = "video pages (YouTube, Vimeo, social...) can be web_download-ed directly"
    return out


# --------------------------------------------------------------------------
# scaricare
# --------------------------------------------------------------------------


def _yt_dlp() -> list[str] | None:
    if exe := shutil.which("yt-dlp"):
        return [exe]
    try:
        import importlib.util
        if importlib.util.find_spec("yt_dlp") is not None:
            return [sys.executable, "-m", "yt_dlp"]
    except (ImportError, ValueError):
        pass
    return None


def cartella_progetto(percorso_progetto: str | None) -> Path:
    """Dove mettere i download: accanto al progetto, come le voci."""
    if percorso_progetto:
        p = Path(percorso_progetto)
        return p.parent / f"{p.stem}_web"
    return Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")) / "web"


def _libero(cartella: Path, nome: str) -> Path:
    dest = cartella / nome
    i = 1
    while dest.exists():
        dest = cartella / f"{Path(nome).stem}_{i}{Path(nome).suffix}"
        i += 1
    return dest


def _annota(cartella: Path, file: Path, url: str, pagina: str = "", titolo: str = "") -> None:
    """Una riga in FONTI.md: da dove viene ogni file, per i crediti e le licenze."""
    fonti = cartella / "FONTI.md"
    nuovo = not fonti.exists()
    with fonti.open("a", encoding="utf-8") as f:
        if nuovo:
            f.write("# Sources\n\nWhere every downloaded file comes from. Check the license "
                    "and credit the authors where it is required.\n\n")
        extra = f" — page: {pagina}" if pagina and pagina != url else ""
        nome = f" \"{titolo}\"" if titolo else ""
        f.write(f"- `{file.name}`{nome} — {url}{extra} ({time.strftime('%Y-%m-%d')})\n")


def _scarica_diretto(r, url: str, cartella: Path) -> Path:
    ct = (r.headers.get("Content-Type") or "").lower()
    p = urllib.parse.urlparse(r.geturl())
    nome = _nome_da_url(r.geturl(), "" if Path(p.path).suffix else _ext_da_tipo(ct))
    dest = _libero(cartella, nome)
    tmp = dest.with_name(f"~{dest.name}")
    letti = 0
    try:
        with tmp.open("wb") as fh:
            while chunk := r.read(1 << 20):
                letti += len(chunk)
                if letti > MAX_SCARICO:
                    raise WebError("file too large to download (over 2 GB)")
                fh.write(chunk)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def _scarica_ytdlp(url: str, cartella: Path, altezza: int) -> Path:
    cmd = _yt_dlp()
    if not cmd:
        raise WebError("this address is a web page, not a media file. Install yt-dlp "
                       "(pip install yt-dlp) to download from video pages, or web_read the "
                       "page and download one of its images or videos")
    modello = str(cartella / "%(title).80B [%(id)s].%(ext)s")
    from . import ffmpeg as ff
    args = cmd + ["--no-playlist", "--no-progress", "--restrict-filenames",
                  "-f", f"bv*[height<={altezza}]+ba/b[height<={altezza}]/b",
                  "--merge-output-format", "mp4", "-o", modello, "--print", "after_move:filepath"]
    try:
        args += ["--ffmpeg-location", str(Path(ff.binary("ffmpeg")).parent)]
    except Exception:
        pass
    r = subprocess.run(args + [url], capture_output=True, text=True, timeout=3600,
                       encoding="utf-8", errors="replace", creationflags=ff._NO_WINDOW)
    righe = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
    if r.returncode != 0 or not righe or not Path(righe[-1]).is_file():
        err = (r.stderr or "").strip().splitlines()
        motivo = err[-1] if err else str(r.returncode)
        # i siti video cambiano spesso: quasi sempre basta un yt-dlp piu' nuovo
        raise WebError(f"yt-dlp could not download it: {motivo}. If the site works in the "
                       f"browser, update yt-dlp: pip install -U yt-dlp")
    return Path(righe[-1])


def scarica(url: str, cartella: str | Path, altezza: int = 1080, titolo: str = "") -> dict:
    """Scarica un'immagine, un video o un audio; da una pagina video passa da yt-dlp."""
    url = (url or "").strip()
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    with _richiesta(url, timeout=60) as r:
        ct = (r.headers.get("Content-Type") or "").lower()
        if ct.startswith(_MEDIA_CT) or ct.startswith("application/octet-stream"):
            f = _scarica_diretto(r, url, cartella)
            _annota(cartella, f, r.geturl(), titolo=titolo)
            return {"path": str(f), "url": url}
    f = _scarica_ytdlp(url, cartella, altezza)
    _annota(cartella, f, url, titolo=titolo)
    return {"path": str(f), "url": url}


def scarica_molti(urls: list[str], cartella: str | Path, altezza: int = 1080,
                  progresso=None) -> tuple[list[dict], list[dict]]:
    """Scarica una lista: chi fallisce non ferma gli altri. Torna (riusciti, errori)."""
    ok, ko = [], []
    for i, u in enumerate(urls):
        try:
            ok.append(scarica(u, cartella, altezza))
        except (WebError, OSError, subprocess.SubprocessError) as exc:
            ko.append({"url": u, "errore": str(exc)})
        if progresso:
            progresso(i + 1, len(urls))
    return ok, ko
