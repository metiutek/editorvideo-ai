"""I file dei progetti: duplicare, rinominare, spostare, eliminare (nel cestino).

Un progetto e' ``<nome>.json`` piu' i file che vedit gli mette accanto con lo
stesso nome: ``<nome>.chat.json`` (la conversazione), ``<nome>.piano.json`` (il
piano approvato) e ``<nome>.versioni/`` (le istantanee). Quelli viaggiano
sempre col progetto. Le cartelle di media (``media/``, ``<nome>_gen/``,
``<nome>_voice/``...) invece sono *media*: il progetto le nomina per percorso
assoluto, una copia le condivide, e restano dove sono quando il progetto si
sposta o si elimina — tranne quando il progetto ha una cartella tutta sua
(``<cartella>/<nome>/<nome>.json``, come i video delle raccolte): allora si
sposta la cartella intera e i percorsi dentro il documento la seguono
(``Store.relocate``).

Eliminare non cancella: il progetto va in ``~/.vedit/cestino/<id>/`` e si
ripristina da li'. Dopo ``GIORNI_CESTINO`` giorni il cestino si svuota da solo.
Le modifiche al documento (nome, percorsi) passano da ``Store`` come tutte.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from . import proxy, raccolte
from .store import Store, porta_percorsi

COMPAGNI = (".chat.json", ".piano.json")      # file <nome><suffisso>
CARTELLA_VERSIONI = ".versioni"                # cartella <nome>.versioni
GIORNI_CESTINO = 30


class ProgettoError(ValueError):
    """Operazione impossibile su un progetto: il testo va a chi l'ha chiesta."""


def _progetto(path: str | Path) -> Path:
    f = Path(path).expanduser().resolve()
    if not f.is_file():
        raise ProgettoError(f"project not found: {f}")
    if raccolte._e_progetto(f) is None:
        raise ProgettoError(f"{f.name} is not a vedit project")
    return f


def compagni(f: Path) -> list[Path]:
    """I file che viaggiano col progetto, quelli che esistono."""
    out = [f.with_name(f.stem + s) for s in COMPAGNI]
    out.append(f.with_name(f.stem + CARTELLA_VERSIONI))
    return [p for p in out if p.exists()]


def _rinominato(p: Path, vecchio: str, nuovo: str) -> str:
    """Il nome di un pezzo del progetto quando il progetto cambia nome."""
    return nuovo + p.name[len(vecchio):] if p.name.startswith(vecchio) else p.name


def cartella_propria(f: Path) -> bool:
    """Il progetto ha una cartella tutta sua: ``<x>/<nome>/<nome>.json``, senza
    altri progetti dentro e che non sia la cartella di una raccolta."""
    d = f.parent
    if d.name != f.stem or raccolte._e_raccolta(d):
        return False
    for g in d.glob("*.json"):
        if g != f and raccolte._e_progetto(g) is not None:
            return False
    return True


def _libero_file(cartella: Path, nome: str) -> Path:
    """``<nome>.json`` in ``cartella``, o ``<nome> 2.json``... se c'e' gia'."""
    n = raccolte.nome_file(nome)
    f, i = cartella / f"{n}.json", 2
    while f.exists() or any(f.with_name(f.stem + s).exists() for s in (*COMPAGNI, CARTELLA_VERSIONI)):
        f, i = cartella / f"{n} {i}.json", i + 1
    return f


def _libera_cartella(sopra: Path, nome: str) -> Path:
    """``<sopra>/<nome>/<nome>.json`` con una cartella che non c'e' ancora."""
    n = raccolte.nome_file(nome)
    d, i = sopra / n, 2
    while d.exists():
        d, i = sopra / f"{n} {i}", i + 1
    return d / f"{d.name}.json"


def _togli_vuote(d: Path) -> None:
    """Toglie ``d`` se dentro restano solo cartelle vuote (quelle che vedit crea)."""
    if not d.is_dir() or any(p.is_file() for p in d.rglob("*")):
        return
    shutil.rmtree(d, ignore_errors=True)


def _nome_di(f: Path) -> str:
    return (raccolte._e_progetto(f) or {}).get("name") or f.stem


def _copia_nome(nome: str) -> str:
    return nome if nome.endswith(" copy") else f"{nome} copy"


def _documento(f: Path, store: Store | None) -> Store:
    """Lo Store con cui toccare il documento: quello aperto, se e' lui."""
    if store is not None and store.path and Path(store.path).resolve() == f:
        return store
    return Store.open(str(f))


def _trasferisci(f: Path, dest: Path, store: Store | None) -> tuple[Path, Store]:
    """Sposta il progetto ``f`` in ``dest`` (un ``.json``) con i suoi pezzi.

    Se il progetto ha una cartella sua e anche ``dest`` e' fatto cosi', si
    sposta la cartella intera (media compresi) e i percorsi la seguono;
    altrimenti si spostano il progetto e i suoi compagni, e i media restano."""
    if dest.exists():
        raise ProgettoError(f"{dest} already exists")
    s = _documento(f, store)
    vecchio, nuovo = f.stem, dest.stem
    intera = cartella_propria(f) and dest.parent.name == dest.stem and not dest.parent.exists()
    if intera:
        dest.parent.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(f.parent), str(dest.parent))
        except OSError as exc:
            raise ProgettoError(f"cannot move {f.parent}: {exc}. Close the programs using its "
                                "files and try again") from exc
        for p in [dest.parent / f.name, *compagni(dest.parent / f.name)]:
            if (n := _rinominato(p, vecchio, nuovo)) != p.name:
                p.rename(p.with_name(n))
        s.path = str(dest)
        s.relocate(str(f.parent), str(dest.parent))
        _riporta_versioni(dest, str(f.parent), str(dest.parent))
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        pezzi = [f, *compagni(f)]
        fatti: list[tuple[Path, Path]] = []
        try:
            for p in pezzi:
                q = dest.parent / _rinominato(p, vecchio, nuovo)
                shutil.move(str(p), str(q))
                fatti.append((p, q))
        except OSError as exc:
            for p, q in reversed(fatti):     # o tutto o niente
                shutil.move(str(q), str(p))
            raise ProgettoError(f"cannot move {f.name}: {exc}") from exc
        s.path = str(dest)
        _togli_se_sua(f)
    return dest, s


def _togli_se_sua(f: Path) -> None:
    """Andato via il progetto, la sua cartella (``<nome>/<nome>.json``) se e' rimasta vuota."""
    d = f.parent
    if d.name == f.stem and d.is_dir() and not any(d.glob("*.json")):
        _togli_vuote(d)


def _riporta_versioni(f: Path, vecchio: str, nuovo: str) -> None:
    """Le istantanee nominano i media come il progetto: seguono la cartella."""
    d = f.with_name(f.stem + CARTELLA_VERSIONI)
    for g in d.glob("*.json") if d.is_dir() else []:
        try:
            dati, n = porta_percorsi(json.loads(g.read_text(encoding="utf-8")), vecchio, nuovo)
            if n:
                g.write_text(json.dumps(dati, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            pass   # un'istantanea illeggibile non ferma lo spostamento


def _esito(f: Path, s: Store, **extra) -> dict:
    c = raccolte.di_progetto(str(f))
    return {"path": str(f), "name": s.project.name,
            "raccolta": raccolte.breve(c) if c else None, **extra}


# --------------------------------------------------------------------------
# operazioni
# --------------------------------------------------------------------------


def duplica(path: str, nome: str | None = None, raccolta: str | None = None) -> dict:
    """Una copia del progetto, che si monta per conto suo. I media sono gli
    stessi file (la copia non duplica gigabyte di girato); conversazione e
    istantanee no: la copia riparte pulita."""
    f = _progetto(path)
    originale = Store.open(str(f))
    nome = " ".join((nome or "").split()) or _copia_nome(originale.project.name)
    if raccolta:
        dest = Path(raccolte.percorso_video(raccolta, nome))
    elif cartella_propria(f):
        dest = _libera_cartella(f.parent.parent, nome)
    else:
        dest = _libero_file(f.parent, nome)
    copia = Store(originale.project, str(dest))
    copia.rename(nome)      # salva: lo Store ha gia' il percorso nuovo
    return _esito(dest, copia, da=str(f))


def rinomina(path: str, nome: str, store: Store | None = None) -> dict:
    """Nuovo nome al progetto, e ai suoi file quando si puo' (la cartella sua
    compresa). Se il nome del file e' occupato cambia solo il nome mostrato."""
    f = _progetto(path)
    nome = " ".join((nome or "").split())
    if not nome:
        raise ProgettoError("the project name cannot be empty")
    n = raccolte.nome_file(nome)
    if n == f.stem:
        dest, s = f, _documento(f, store)
    elif cartella_propria(f) and not (f.parent.parent / n).exists():
        dest, s = _trasferisci(f, f.parent.parent / n / f"{n}.json", store)
    elif not (f.with_name(f"{n}.json")).exists() and not cartella_propria(f):
        dest, s = _trasferisci(f, f.with_name(f"{n}.json"), store)
    else:
        dest, s = f, _documento(f, store)
    s.rename(nome)
    return _esito(dest, s, da=str(f))


def sposta(path: str, raccolta: str | None = None, cartella: str | None = None,
           store: Store | None = None) -> dict:
    """Porta il progetto in una raccolta (nella sua cartella per video) o in
    una cartella qualunque. Fuori da ogni raccolta: ``cartella`` e basta."""
    f = _progetto(path)
    if bool(raccolta) == bool(cartella):
        raise ProgettoError("give collection= (to move it into a collection) or folder=")
    nome = _nome_di(f)
    if raccolta:
        c = raccolte.trova(raccolta)
        if raccolte.di_progetto(str(f)) == c:
            raise ProgettoError(f"the project is already in the collection {raccolte.breve(c)['name']}")
        dest = Path(raccolte.percorso_video(str(c), nome))
    else:
        d = Path(cartella).expanduser().resolve()
        if d.is_file():
            raise ProgettoError(f"{d} is a file, not a folder")
        if d == f.parent or (cartella_propria(f) and d == f.parent.parent):
            raise ProgettoError("the project is already in that folder")
        dest = _libera_cartella(d, f.stem) if cartella_propria(f) else _libero_file(d, f.stem)
    dest, s = _trasferisci(f, dest, store)
    return _esito(dest, s, da=str(f))


# --------------------------------------------------------------------------
# cestino
# --------------------------------------------------------------------------


def _cestino() -> Path:
    return proxy.cache_dir("cestino")


def elimina(path: str) -> dict:
    """Il progetto va nel cestino di vedit, da cui si ripristina. I media
    restano dove sono: possono servire ad altri progetti o a una copia."""
    f = _progetto(path)
    nome = _nome_di(f)
    c = raccolte.di_progetto(str(f))
    vid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    d = _cestino() / vid
    (d / "file").mkdir(parents=True)
    pezzi = [f, *compagni(f)]
    fatti: list[tuple[Path, Path]] = []
    try:
        for p in pezzi:
            q = d / "file" / p.name
            shutil.move(str(p), str(q))
            fatti.append((p, q))
    except OSError as exc:
        for p, q in reversed(fatti):
            shutil.move(str(q), str(p))
        shutil.rmtree(d, ignore_errors=True)
        raise ProgettoError(f"cannot delete {f.name}: {exc}") from exc
    voce = {"id": vid, "name": nome, "path": str(f), "quando": time.time(),
            "file": [p.name for p in pezzi], "raccolta": raccolte.breve(c)["name"] if c else None}
    (d / "voce.json").write_text(json.dumps(voce, ensure_ascii=False, indent=1), encoding="utf-8")
    _togli_se_sua(f)
    restano = f.parent if f.parent.is_dir() and f.parent.name == f.stem else None
    return {**voce, "restano": str(restano) if restano else None}


def _voci() -> list[tuple[Path, dict]]:
    out = []
    for d in _cestino().iterdir():
        try:
            v = json.loads((d / "voce.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append((d, v))
    return out


def cestino() -> list[dict]:
    """I progetti eliminati, dal piu' recente. Quelli troppo vecchi se ne vanno."""
    limite = time.time() - GIORNI_CESTINO * 86400
    out = []
    for d, v in _voci():
        if float(v.get("quando", 0)) < limite:
            shutil.rmtree(d, ignore_errors=True)
            continue
        out.append({k: v.get(k) for k in ("id", "name", "path", "quando", "raccolta")})
    return sorted(out, key=lambda v: -float(v["quando"] or 0))


def _voce(vid: str) -> tuple[Path, dict]:
    for d, v in _voci():
        if v.get("id") == vid:
            return d, v
    raise ProgettoError(f"{vid!r} is not in the trash")


def ripristina(vid: str) -> dict:
    """Rimette il progetto dov'era. Se li' c'e' gia' un progetto con quel nome,
    torna accanto con un numero."""
    d, v = _voce(vid)
    f = Path(v["path"])
    dest = f if not f.exists() else _libero_file(f.parent, f.stem)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for n in v.get("file", []):
        p = d / "file" / n
        if p.exists():
            shutil.move(str(p), str(dest.parent / _rinominato(p, f.stem, dest.stem)))
    shutil.rmtree(d, ignore_errors=True)
    s = Store.open(str(dest))
    return _esito(dest, s)


def svuota(vid: str | None = None) -> dict:
    """Cancella per sempre dal cestino un progetto, o tutti senza ``vid``."""
    voci = [_voce(vid)] if vid else _voci()
    for d, _ in voci:
        shutil.rmtree(d, ignore_errors=True)
    return {"cancellati": len(voci)}
