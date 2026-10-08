"""Link e cartelle come riferimenti per l'assistente.

Un link si risolve una volta sola, quando l'utente lo aggiunge: una pagina web
diventa il suo testo (salvato in un file, cosi' il turno successivo non la
riscarica), un'immagine resta un'immagine, un video o un audio diretti vengono
scaricati e si possono importare nel progetto. Una cartella diventa l'elenco
dei suoi file, con i media riconosciuti.
"""

from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

MAX_PAGINA = 3_000_000       # byte letti da una pagina web
MAX_SCARICO = 500_000_000    # byte scaricati per un media
MAX_VOCI = 150               # file elencati per una cartella

_UA = "Mozilla/5.0 (vedit; +https://github.com/metiutek/editorvideo-ai)"

_MEDIA_CT = ("image/", "video/", "audio/", "application/pdf")


class _Testo(HTMLParser):
    """Testo leggibile di una pagina: titolo e corpo, senza script e stili."""

    def __init__(self) -> None:
        super().__init__()
        self.titolo = ""
        self.parti: list[str] = []
        self._salta = 0
        self._nel_titolo = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "template"):
            self._salta += 1
        elif tag == "title":
            self._nel_titolo = True
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"):
            self.parti.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "template") and self._salta:
            self._salta -= 1
        elif tag == "title":
            self._nel_titolo = False

    def handle_data(self, data):
        if self._salta:
            return
        if self._nel_titolo:
            self.titolo += data
        else:
            self.parti.append(data)

    def testo(self) -> str:
        t = "".join(self.parti)
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n\n", t)
        return t.strip()


def _nome_da_url(url: str, ext: str = "") -> str:
    p = urllib.parse.urlparse(url)
    nome = Path(urllib.parse.unquote(p.path)).name or p.netloc or "link"
    nome = re.sub(r"[^\w.\-]+", "_", nome)[:80] or "link"
    if ext and not nome.lower().endswith(ext):
        nome += ext
    return nome


def _ext_da_tipo(ct: str) -> str:
    import mimetypes

    return mimetypes.guess_extension(ct.split(";")[0].strip()) or ""


def risolvi_link(url: str, cartella: Path) -> dict:
    """Scarica o legge il link e torna il riferimento pronto per la chat."""
    url = url.strip()
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("serve un indirizzo che inizi con http:// o https://")
    cartella.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30) as res:
        ct = (res.headers.get("Content-Type") or "").lower()
        if ct.startswith(_MEDIA_CT):
            nome = _nome_da_url(url, "" if Path(p.path).suffix else _ext_da_tipo(ct))
            dest = cartella / nome
            i = 1
            while dest.exists():
                dest = cartella / f"{Path(nome).stem}_{i}{Path(nome).suffix}"
                i += 1
            letti = 0
            with dest.open("wb") as fh:
                while chunk := res.read(1 << 20):
                    letti += len(chunk)
                    if letti > MAX_SCARICO:
                        fh.close()
                        dest.unlink(missing_ok=True)
                        raise ValueError("file troppo grande da scaricare (oltre 500 MB)")
                    fh.write(chunk)
            from .chat import tipo_allegato

            return {"kind": "link", "url": url, "name": dest.name, "path": str(dest),
                    "tipo": tipo_allegato(dest)}

        grezzo = res.read(MAX_PAGINA)
        charset = res.headers.get_content_charset() or "utf-8"
    testo = grezzo.decode(charset, errors="replace")
    if "html" in ct or "<html" in testo[:2000].lower():
        parser = _Testo()
        parser.feed(testo)
        titolo = html.unescape(parser.titolo.strip()) or p.netloc
        corpo = parser.testo()
    else:
        titolo, corpo = _nome_da_url(url), testo
    firma = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    dest = cartella / f"link_{firma}.txt"
    dest.write_text(f"{titolo}\n{url}\n\n{corpo}", encoding="utf-8")
    return {"kind": "link", "url": url, "name": titolo[:80], "path": str(dest), "tipo": "pagina"}


def elenco_cartella(path: str) -> str:
    """Contenuto di una cartella in poche righe: sottocartelle e file, media segnati."""
    from .chat import tipo_allegato

    base = Path(path)
    if not base.is_dir():
        return "(cartella non trovata)"
    righe, n, conti = [], 0, {"media": 0, "image": 0, "testo": 0, "pdf": 0, "altro": 0}
    for f in sorted(base.rglob("*"), key=lambda x: str(x).lower()):
        rel = f.relative_to(base)
        if any(part.startswith(".") for part in rel.parts) or len(rel.parts) > 3:
            continue
        if f.is_dir():
            continue
        tipo = tipo_allegato(f)
        conti[tipo] = conti.get(tipo, 0) + 1
        n += 1
        if len(righe) < MAX_VOCI:
            try:
                mb = f.stat().st_size / 1e6
            except OSError:
                mb = 0
            righe.append(f"  {rel.as_posix()}  [{tipo}, {mb:.1f} MB]")
    testa = (f"{n} file ({conti['media']} video/audio, {conti['image']} immagini, "
             f"{conti['testo']} testi, {conti['pdf']} PDF)")
    if n > MAX_VOCI:
        righe.append(f"  … e altri {n - MAX_VOCI}")
    return testa + "\n" + "\n".join(righe)
