"""Raccolte: tanti video sotto un tetto, con memoria e riferimenti comuni.

Una raccolta e' una cartella per qualunque gruppo di video che hanno qualcosa
in comune: un canale YouTube o TikTok, i video di famiglia, un cliente, una
serie, un corso, i viaggi. Dentro::

    <raccolta>/
      raccolta.json        nome e descrizione
      MEMORIA.md           memoria della raccolta, stesso formato di memoria.py
      riferimenti/         immagini che valgono per ogni video (logo, miniature,
                           palette, persone, grafiche) + note.json con una nota a testa
      documenti/           file di informazioni (brief, copioni, testi, dati, pdf): i
                           testi brevi entrano nel contesto, gli altri si leggono a richiesta
      skills/              skill che valgono solo per i video di questa raccolta
      <video>/<video>.json un progetto per video, con le sue cartelle accanto

Un progetto fa parte della raccolta se il suo file sta dentro la cartella: si
risale dalle cartelle che lo contengono fino a ``raccolta.json``. Niente indice
da tenere allineato: spostare un video dentro o fuori basta, e trasformare in
raccolta una cartella che ha gia' dei progetti li adotta tutti.

Il contesto della raccolta (descrizione, memoria, elenco dei riferimenti con le
note) arriva all'agente MCP all'apertura del progetto e all'assistente della
chat una volta per conversazione, insieme al foglio dei riferimenti come
immagine: e' il "di che cosa si tratta" che non si deve ripetere a ogni video.

``~/.vedit/raccolte.json`` ricorda solo quali cartelle sono raccolte, per
elencarle nella schermata iniziale; quelle sparite si saltano.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from . import memoria

FILE = "raccolta.json"
CARTELLA_RIF = "riferimenti"
CARTELLA_DOC = "documenti"
CARTELLA_SKILL = "skills"
# file di informazioni che si leggono come testo; i pdf si accettano per chi li sa
# leggere da se' (Claude Code), agli altri modelli arriva solo il nome
TESTI = {".md", ".txt", ".csv", ".tsv", ".json", ".srt", ".vtt", ".html", ".htm", ".xml",
         ".yaml", ".yml", ".rtf"}
DOCUMENTI = TESTI | {".pdf"}
MAX_DOCUMENTO = 20 * 1024 * 1024
# quanto testo dei documenti entra da solo nel contesto; il resto a richiesta
MAX_DOC_CONTESTO = 12000
MAX_LETTURA = 200_000
NOTE = "note.json"
IMMAGINI = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
# fin dove si risale per trovare la raccolta di un progetto: <raccolta>/<video>/<video>.json
# e' a due livelli, qualche sottocartella in piu' e' organizzazione dell'utente
RISALITA = 5
# quanto in profondita' cercare i progetti nella cartella, e quanti al massimo
PROFONDITA = 3
MAX_VIDEO = 500

_INTESTAZIONE = """\
# Memoria della raccolta

Cose che valgono per tutti i video di questa raccolta: di che cosa si tratta,
pubblico, tono, formato, grafica, nomi e persone ricorrenti, errori da non
ripetere. La scrivono l'assistente e l'agente (`remember` con
scope="collection"); si puo' modificare a mano.
"""

_lock = threading.Lock()


class RaccoltaError(ValueError):
    """Richiesta impossibile su una raccolta: il testo va a chi l'ha fatta."""


# --------------------------------------------------------------------------
# dove stanno
# --------------------------------------------------------------------------


def _registro() -> Path:
    return Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")) / "raccolte.json"


def cartella_video() -> Path:
    """Dove proporre raccolte e progetti nuovi: la cartella Video dell'utente se c'e'."""
    home = Path.home()
    for nome in ("Videos", "Video", "Movies", "Filmati"):
        if (home / nome).is_dir():
            return home / nome
    return home


def nome_file(nome: str) -> str:
    """Un nome leggibile che vale come nome di cartella su tutti i sistemi."""
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", (nome or "").strip()).strip(" .-")
    return n[:80] or "untitled"


def _letti() -> list[str]:
    try:
        voci = json.loads(_registro().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(v) for v in voci if isinstance(v, str)]


def _salva_registro(voci: list[str]) -> None:
    f = _registro()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"~{f.name}")
    tmp.write_text(json.dumps(voci, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def _registra(cartella: Path) -> None:
    with _lock:
        voci = [v for v in _letti() if Path(v) != cartella]
        _salva_registro([str(cartella), *voci])


def dimentica_raccolta(cartella: str) -> dict:
    """Toglie la raccolta dall'elenco. I file restano dove sono."""
    c = Path(cartella).resolve()
    with _lock:
        voci = _letti()
        tenute = [v for v in voci if Path(v).resolve() != c]
        _salva_registro(tenute)
    return {"tolta": len(voci) != len(tenute)}


def _e_raccolta(cartella: Path) -> bool:
    return (cartella / FILE).is_file()


def di_progetto(path: str | None) -> Path | None:
    """La cartella della raccolta di cui fa parte il progetto, o None."""
    if not path:
        return None
    d = Path(path).resolve().parent
    for _ in range(RISALITA):
        if _e_raccolta(d):
            return d
        if d.parent == d:
            break
        d = d.parent
    return None


def trova(rif: str | None, progetto: str | None = None) -> Path:
    """La raccolta indicata per cartella o per nome; senza, quella del progetto."""
    if not rif:
        if c := di_progetto(progetto):
            return c
        raise RaccoltaError("the open project is not in a collection: give collection= (name or "
                            "folder), or create one with collection_create")
    p = Path(rif).expanduser()
    if p.is_dir() and _e_raccolta(p):
        return p.resolve()
    if p.is_file() and p.name == FILE:
        return p.parent.resolve()
    note = elenco()
    cerca = rif.strip().lower()
    for c in note:
        if c["name"].lower() == cerca or Path(c["path"]).name.lower() == cerca:
            return Path(c["path"])
    nomi = ", ".join(c["name"] for c in note) or "none yet"
    raise RaccoltaError(f"unknown collection {rif!r}. Collections: {nomi}")


# --------------------------------------------------------------------------
# la raccolta
# --------------------------------------------------------------------------


def _dati(cartella: Path) -> dict:
    try:
        d = json.loads((cartella / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _scrivi_dati(cartella: Path, dati: dict) -> None:
    f = cartella / FILE
    tmp = f.with_name(f"~{f.name}")
    tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def crea(nome: str, cartella: str | None = None, descrizione: str = "") -> dict:
    """Crea una raccolta. Una cartella che esiste gia' diventa raccolta con i
    progetti che contiene; una che e' gia' una raccolta si riapre senza toccarla."""
    nome = " ".join((nome or "").split())
    if not nome:
        raise RaccoltaError("give the collection a name")
    c = (Path(cartella).expanduser() if cartella else cartella_video() / nome_file(nome)).resolve()
    if c.is_file():
        raise RaccoltaError(f"{c} is a file, not a folder")
    if (sopra := di_progetto(str(c / "x"))) and sopra != c:
        raise RaccoltaError(f"{c} is inside the collection {_dati(sopra).get('name') or sopra.name}: "
                            "collections do not nest")
    c.mkdir(parents=True, exist_ok=True)
    if not _e_raccolta(c):
        _scrivi_dati(c, {"name": nome, "description": (descrizione or "").strip(),
                         "created": time.strftime("%Y-%m-%d")})
    (c / CARTELLA_RIF).mkdir(exist_ok=True)
    _registra(c)
    return info(str(c))


def modifica(cartella: str, nome: str | None = None, descrizione: str | None = None) -> dict:
    c = trova(cartella)
    with _lock:
        d = _dati(c)
        if nome is not None:
            if not (nome := " ".join(nome.split())):
                raise RaccoltaError("the collection name cannot be empty")
            d["name"] = nome
        if descrizione is not None:
            if len(descrizione) > 4000:
                raise RaccoltaError("the description is at most 4000 characters: "
                                    "details go in the collection memory")
            d["description"] = descrizione.strip()
        _scrivi_dati(c, d)
    return info(str(c))


def _e_progetto(f: Path) -> dict | None:
    """Nome e durata se ``f`` e' un progetto vedit, altrimenti None."""
    if f.name in (FILE, NOTE) or f.name.endswith((".chat.json", ".piano.json")):
        return None
    # "~..." sono i temporanei dei salvataggi atomici (Store.save): uno rimasto
    # da un salvataggio interrotto ha lo stesso contenuto del progetto e
    # compariva nella raccolta come una sua copia
    if f.name.startswith("~"):
        return None
    try:
        if f.stat().st_size > 50_000_000:
            return None
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (isinstance(d, dict) and isinstance(d.get("tracks"), list) and "settings" in d):
        return None
    durata = 0.0
    for t in d["tracks"]:
        for cl in (t.get("clips") or []) if isinstance(t, dict) else []:
            try:
                durata = max(durata, float(cl.get("start", 0)) + float(cl.get("duration", 0)))
            except (TypeError, ValueError, AttributeError):
                pass
    s = d.get("settings") or {}
    return {"name": d.get("name") or f.stem, "duration": round(durata, 2),
            "resolution": f"{s.get('width')}x{s.get('height')}" if s.get("width") else None}


# le cartelle che vedit mette accanto a un progetto: dentro non ci sono progetti
# (le istantanee di .versioni lo sembrerebbero)
_ACCANTO = ("_gen", "_voice", "_covers", "_web", "_sottotitoli", ".versioni")


def video(cartella: str | Path) -> list[dict]:
    """I progetti dentro la raccolta, dal piu' recente."""
    c = Path(cartella)
    out = []
    for radice, dirs, files in os.walk(c):
        r = Path(radice)
        livello = len(r.relative_to(c).parts)
        # le cartelle che vedit crea accanto ai progetti non contengono progetti
        dirs[:] = [d for d in dirs if livello + 1 < PROFONDITA and not d.startswith(".")
                   and d != CARTELLA_RIF and not d.endswith(_ACCANTO)
                   and d not in ("media", "web", "proxy", "render", "allegati",
                                 CARTELLA_DOC, CARTELLA_SKILL)]
        for n in files:
            if not n.lower().endswith(".json"):
                continue
            f = r / n
            if (p := _e_progetto(f)) is not None:
                out.append({"path": str(f), **p, "modified": f.stat().st_mtime})
        if len(out) >= MAX_VIDEO:
            break
    return sorted(out, key=lambda v: -v["modified"])


def file_memoria(cartella: str | Path) -> Path:
    return Path(cartella) / "MEMORIA.md"


def info(cartella: str) -> dict:
    """Tutta la raccolta: dati, memoria, riferimenti, video."""
    c = trova(cartella)
    d = _dati(c)
    return {"path": str(c), "name": d.get("name") or c.name,
            "description": d.get("description", ""),
            "formato": d.get("formato") if isinstance(d.get("formato"), dict) else None,
            "memoria": memoria.leggi(file_memoria(c)), "riferimenti": riferimenti(c),
            "documenti": documenti(c), "skill": skill(c),
            "video": video(c)}


def breve(cartella: Path) -> dict:
    d = _dati(cartella)
    return {"path": str(cartella), "name": d.get("name") or cartella.name}


def elenco() -> list[dict]:
    """Le raccolte conosciute, dall'ultima aperta o creata; quelle sparite no."""
    out, viste = [], set()
    for v in _letti():
        c = Path(v)
        if str(c) in viste or not _e_raccolta(c):
            continue
        viste.add(str(c))
        d = _dati(c)
        rif = cartella_rif(c)
        out.append({"path": str(c), "name": d.get("name") or c.name,
                    "description": d.get("description", ""),
                    "riferimenti": sum(1 for f in rif.iterdir() if f.suffix.lower() in IMMAGINI)
                    if rif.is_dir() else 0})
    return out


def usa(cartella: Path | None) -> None:
    """La raccolta torna in cima all'elenco: e' quella su cui si sta lavorando."""
    if cartella and _e_raccolta(cartella):
        _registra(cartella)


def percorso_video(cartella: str, nome: str) -> str:
    """Dove mettere un video nuovo: una cartella per video, perche' accanto al
    progetto vedit crea media/, web/, <nome>_gen/... e mischiarli farebbe confusione."""
    c = trova(cartella)
    n = nome_file(nome)
    d, i = c / n, 2
    while d.exists():      # anche una cartella rimasta con i media di un video eliminato
        d, i = c / f"{n} {i}", i + 1
    return str(d / f"{d.name}.json")


def nome_nuovo(cartella: str) -> str:
    """Il nome di un video nuovo senza titolo: Video 1, Video 2... il primo libero."""
    c = trova(cartella)
    usati = {v["name"].lower() for v in video(c)}
    i = len(usati) + 1
    while f"video {i}" in usati or (c / f"Video {i}").exists():
        i += 1
    return f"Video {i}"


def ricorda_formato(cartella: str, preset: str, size: int | None) -> None:
    """Il formato dell'ultimo video creato: il prossimo parte da li'."""
    c = trova(cartella)
    with _lock:
        d = _dati(c)
        d["formato"] = {"preset": preset, "size": size}
        _scrivi_dati(c, d)


def dentro(cartella: Path, path: str) -> str:
    """``path`` relativo alla raccolta, o assoluto ma dentro la raccolta."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = cartella / p
    p = p.resolve()
    if not p.is_relative_to(cartella):
        raise RaccoltaError(f"{p} is outside the collection folder {cartella}")
    return str(p)


# --------------------------------------------------------------------------
# riferimenti
# --------------------------------------------------------------------------


def cartella_rif(cartella: str | Path) -> Path:
    return Path(cartella) / CARTELLA_RIF


def _note(c: Path) -> dict:
    try:
        d = json.loads((cartella_rif(c) / NOTE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _salva_note(c: Path, note: dict) -> None:
    d = cartella_rif(c)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"~{NOTE}"
    tmp.write_text(json.dumps(note, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, d / NOTE)


def riferimenti(cartella: str | Path) -> list[dict]:
    c = Path(cartella)
    d = cartella_rif(c)
    if not d.is_dir():
        return []
    note = _note(c)
    return [{"file": f.name, "path": str(f), "nota": note.get(f.name, "")}
            for f in sorted(d.iterdir(), key=lambda f: f.name.lower())
            if f.is_file() and f.suffix.lower() in IMMAGINI and not f.name.startswith(("~", "."))]


def libero(cartella: str | Path, nome: str) -> Path:
    """Un percorso libero in riferimenti/ per un file che si chiama ``nome``."""
    d = cartella_rif(cartella)
    d.mkdir(parents=True, exist_ok=True)
    nome = Path(nome).name
    if Path(nome).suffix.lower() not in IMMAGINI:
        raise RaccoltaError(f"{nome}: references are images ({', '.join(sorted(IMMAGINI))})")
    base, ext = Path(nome_file(Path(nome).stem)).name, Path(nome).suffix.lower()
    f, i = d / f"{base}{ext}", 2
    while f.exists():
        f, i = d / f"{base}_{i}{ext}", i + 1
    return f


def aggiungi(cartella: str, paths: list[str], nota: str = "") -> dict:
    """Copia le immagini in riferimenti/: la raccolta non dipende da dove stavano."""
    c = trova(cartella)
    if not paths:
        raise RaccoltaError("give the images to add in paths")
    nuovi = []
    for p in paths:
        src = Path(p).expanduser()
        if not src.is_file():
            raise RaccoltaError(f"file not found: {p}")
        dest = libero(c, src.name)
        shutil.copy2(src, dest)
        nuovi.append(dest.name)
    if nota:
        annota(str(c), {n: nota for n in nuovi})
    return {"aggiunti": nuovi, "riferimenti": riferimenti(c)}


def annota(cartella: str, note: dict[str, str]) -> dict:
    """Nota per immagine: che cosa e' e come usarla ("logo: sempre in alto a destra")."""
    c = trova(cartella)
    presenti = {r["file"] for r in riferimenti(c)}
    with _lock:
        tutte = _note(c)
        for f, n in note.items():
            if f not in presenti:
                raise RaccoltaError(f"no reference called {f!r}. References: "
                                    f"{', '.join(sorted(presenti)) or 'none'}")
            n = " ".join((n or "").split())
            if len(n) > 500:
                raise RaccoltaError("a reference note is at most 500 characters")
            if n:
                tutte[f] = n
            else:
                tutte.pop(f, None)
        _salva_note(c, tutte)
    return {"riferimenti": riferimenti(c)}


def togli(cartella: str, files: list[str]) -> dict:
    c = trova(cartella)
    presenti = {r["file"]: Path(r["path"]) for r in riferimenti(c)}
    tolti = []
    with _lock:
        note = _note(c)
        for f in files:
            if (p := presenti.get(Path(f).name)) is None:
                raise RaccoltaError(f"no reference called {f!r}")
            p.unlink()
            note.pop(p.name, None)
            tolti.append(p.name)
        _salva_note(c, note)
    return {"tolti": tolti, "riferimenti": riferimenti(c)}


def immagine(cartella: str, file: str) -> Path:
    """Il file di un riferimento, solo se e' davvero uno dei riferimenti."""
    c = trova(cartella)
    for r in riferimenti(c):
        if r["file"] == file:
            return Path(r["path"])
    raise RaccoltaError(f"no reference called {file!r}")


# --------------------------------------------------------------------------
# documenti: file di informazioni per tutti i video
# --------------------------------------------------------------------------


def cartella_doc(cartella: str | Path) -> Path:
    return Path(cartella) / CARTELLA_DOC


def documenti(cartella: str | Path) -> list[dict]:
    d = cartella_doc(cartella)
    if not d.is_dir():
        return []
    return [{"file": f.name, "path": str(f), "size": f.stat().st_size,
             "testo": f.suffix.lower() in TESTI}
            for f in sorted(d.iterdir(), key=lambda f: f.name.lower())
            if f.is_file() and f.suffix.lower() in DOCUMENTI and not f.name.startswith(("~", "."))]


def libero_doc(cartella: str | Path, nome: str) -> Path:
    """Un percorso libero in documenti/ per un file che si chiama ``nome``."""
    d = cartella_doc(cartella)
    d.mkdir(parents=True, exist_ok=True)
    nome = Path(nome).name
    ext = Path(nome).suffix.lower()
    if ext not in DOCUMENTI:
        raise RaccoltaError(f"{nome}: information files are text or pdf "
                            f"({', '.join(sorted(DOCUMENTI))})")
    base = Path(nome_file(Path(nome).stem)).name
    f, i = d / f"{base}{ext}", 2
    while f.exists():
        f, i = d / f"{base}_{i}{ext}", i + 1
    return f


def aggiungi_documenti(cartella: str, paths: list[str]) -> dict:
    """Copia i file in documenti/: la raccolta non dipende da dove stavano."""
    c = trova(cartella)
    if not paths:
        raise RaccoltaError("give the files to add in paths")
    nuovi = []
    for p in paths:
        src = Path(p).expanduser()
        if not src.is_file():
            raise RaccoltaError(f"file not found: {p}")
        if src.stat().st_size > MAX_DOCUMENTO:
            raise RaccoltaError(f"{src.name} is too big (max {MAX_DOCUMENTO // 2**20} MB)")
        dest = libero_doc(c, src.name)
        shutil.copy2(src, dest)
        nuovi.append(dest.name)
    return {"aggiunti": nuovi, "documenti": documenti(c)}


def _documento(c: Path, file: str) -> Path:
    for x in documenti(c):
        if x["file"] == Path(file).name:
            return Path(x["path"])
    nomi = ", ".join(x["file"] for x in documenti(c)) or "none"
    raise RaccoltaError(f"no information file called {file!r}. Files: {nomi}")


def scrivi_documento(cartella: str, file: str, testo: str) -> dict:
    """Scrive (o riscrive) un file di testo in documenti/: note, brief, copioni."""
    c = trova(cartella)
    nome = Path(file or "").name.strip()
    if not nome:
        raise RaccoltaError("give the file a name")
    if not Path(nome).suffix:
        nome += ".md"
    if Path(nome).suffix.lower() not in TESTI:
        raise RaccoltaError(f"{nome}: only text files can be written ({', '.join(sorted(TESTI))})")
    if len(testo) > MAX_LETTURA:
        raise RaccoltaError(f"the text is at most {MAX_LETTURA} characters")
    d = cartella_doc(c)
    d.mkdir(parents=True, exist_ok=True)
    f = d / (Path(nome_file(Path(nome).stem)).name + Path(nome).suffix.lower())
    tmp = f.with_name(f"~{f.name}")
    tmp.write_text(testo, encoding="utf-8")
    os.replace(tmp, f)
    return {"file": f.name, "documenti": documenti(c)}


def leggi_documento(cartella: str | None, file: str, progetto: str | None = None) -> dict:
    c = trova(cartella, progetto)
    f = _documento(c, file)
    if f.suffix.lower() not in TESTI:
        return {"file": f.name, "path": str(f),
                "testo": None, "nota": "not a text file: read it from its path if you can open it"}
    testo = f.read_text(encoding="utf-8", errors="replace")
    tagliato = len(testo) > MAX_LETTURA
    return {"file": f.name, "path": str(f), "testo": testo[:MAX_LETTURA],
            **({"tagliato": True} if tagliato else {})}


def togli_documenti(cartella: str, files: list[str]) -> dict:
    c = trova(cartella)
    tolti = []
    for x in files:
        f = _documento(c, x)
        f.unlink()
        tolti.append(f.name)
    return {"tolti": tolti, "documenti": documenti(c)}


# --------------------------------------------------------------------------
# skill della raccolta: <raccolta>/skills/<nome>/SKILL.md
# --------------------------------------------------------------------------
# Le stesse skill di vedit (estensioni.py), ma valgono solo per i video della
# raccolta: estensioni._cartelle_skill le mette prima di tutte le altre.


def cartella_skill(cartella: str | Path) -> Path:
    return Path(cartella) / CARTELLA_SKILL


def skill(cartella: str | Path) -> list[dict]:
    from . import estensioni
    return estensioni.skill_in(cartella_skill(cartella))


def foglio(cartella: str | Path, lato: int = 360, colonne: int = 4) -> str | None:
    """I riferimenti in un'immagine sola, col nome sotto ciascuno: e' cosi' che
    arrivano a un modello, che vede tutto in un'immagine invece che in dieci."""
    rif = riferimenti(cartella)
    if not rif:
        return None
    from PIL import Image, ImageDraw, ImageOps

    from .proxy import cache_dir

    firma = hashlib.sha1("|".join(f"{r['path']}:{Path(r['path']).stat().st_mtime_ns}"
                                  for r in rif).encode()).hexdigest()[:16]
    out = cache_dir("raccolte") / f"{firma}.jpg"
    if out.is_file():
        return str(out)
    rif = rif[:24]
    col = min(colonne, len(rif))
    righe = -(-len(rif) // col)
    etichetta = 22
    tela = Image.new("RGB", (col * lato, righe * (lato + etichetta)), (24, 24, 28))
    disegno = ImageDraw.Draw(tela)
    for i, r in enumerate(rif):
        x, y = (i % col) * lato, (i // col) * (lato + etichetta)
        try:
            with Image.open(r["path"]) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((lato - 8, lato - 8))
                fondo = Image.new("RGB", im.size, (40, 40, 46))
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    fondo.paste(im, mask=im.split()[-1])
                else:
                    fondo.paste(im.convert("RGB"))
                tela.paste(fondo, (x + (lato - im.width) // 2, y + (lato - im.height) // 2))
        except OSError:
            disegno.text((x + 8, y + lato // 2), "unreadable", fill=(200, 80, 80))
        disegno.text((x + 6, y + lato + 4), r["file"][:48], fill=(230, 230, 230))
    tela.save(out, quality=88)
    return str(out)


# --------------------------------------------------------------------------
# memoria e contesto
# --------------------------------------------------------------------------


def ricorda(cartella: str | None, nota: str, sezione: str = "general",
            progetto: str | None = None) -> dict:
    c = trova(cartella, progetto)
    return {**memoria.ricorda(nota, sezione, file_memoria(c), _INTESTAZIONE),
            "raccolta": _dati(c).get("name") or c.name}


def dimentica(cartella: str | None, testo: str, progetto: str | None = None) -> dict:
    return memoria.dimentica(testo, file_memoria(trova(cartella, progetto)))


def scrivi_memoria(cartella: str, testo: str) -> dict:
    return memoria.sostituisci(testo, file_memoria(trova(cartella)))


def contesto(progetto: str | None, limite: int = memoria.MAX_CONTESTO) -> str:
    """La raccolta del progetto come blocco di contesto, o "" se non ne fa parte."""
    c = di_progetto(progetto)
    if c is None:
        return ""
    d = _dati(c)
    righe = [f"Questo video fa parte della raccolta \"{d.get('name') or c.name}\" ({c}): un "
             "gruppo di video con qualcosa in comune (un canale, una serie, una famiglia, un "
             "cliente...). Cio' che segue vale per tutti i suoi video: seguilo se la richiesta "
             "non dice altro."]
    if desc := (d.get("description") or "").strip():
        righe += ["", "Descrizione della raccolta:", desc]
    if m := memoria.corpo(file_memoria(c), limite):
        righe += ["", "Memoria della raccolta:", m]
    if rif := riferimenti(c):
        righe += ["", "Riferimenti visivi della raccolta (immagini da rispettare per grafica, "
                      "colori, persone, miniature; si importano come media se servono in timeline):"]
        righe += [f"- {r['path']}" + (f" — {r['nota']}" if r["nota"] else "") for r in rif]
    if doc := documenti(c):
        righe += ["", "File di informazioni della raccolta (brief, copioni, dati: valgono per "
                      "ogni video; quelli non riportati qui si leggono con collection_file):"]
        resto = MAX_DOC_CONTESTO
        for x in doc:
            righe.append(f"- {x['path']}")
            if not x["testo"] or resto <= 0:
                continue
            try:
                t = Path(x["path"]).read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if t and len(t) <= resto:
                righe += [f"  --- {x['file']} ---", t, f"  --- fine di {x['file']} ---"]
                resto -= len(t)
    if sk := skill(c):
        righe += ["", "Skill della raccolta (procedure da seguire in questi video; use_skill col "
                      "nome per le istruzioni):"]
        righe += [f"- {x['name']}: {x['description']}" for x in sk]
    righe += ["", "Le preferenze che valgono per questa raccolta (e non per tutti i video "
                  "dell'utente) si salvano con remember(scope=\"collection\")."]
    return "\n".join(righe)
