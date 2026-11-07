"""Memoria condivisa fra tutti i progetti.

Un file Markdown, ``~/.vedit/MEMORIA.md``, dove l'agente (MCP) e l'assistente
della chat annotano cio' che vale al di la' del progetto aperto: preferenze di
chi monta (formato, stile, ritmo, musica, voce), canali e pubblico, nomi e
grafiche ricorrenti, errori da non ripetere. Si legge a ogni progetto: aprirne
uno nuovo non riparte da zero.

E' testo da leggere e modificare a mano: voci ``- ...`` sotto titoli ``## ``.
``VEDIT_MEMORIA`` lo sposta; senza, segue ``VEDIT_CACHE`` come le altre
impostazioni (i test la isolano cosi').
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

# quanto ne entra da solo nel contesto (assistente, apertura progetto):
# oltre, l'agente la legge per intero con lo strumento apposta
MAX_CONTESTO = 4000

_INTESTAZIONE = """\
# Memoria di vedit

Cose da ricordare in tutti i progetti: preferenze, stile, pubblico, scelte gia'
fatte, errori da non ripetere. La scrivono l'assistente e l'agente (`remember`);
si puo' modificare a mano: una voce per riga sotto il suo titolo.
"""

_lock = threading.Lock()


def percorso() -> Path:
    if env := os.environ.get("VEDIT_MEMORIA"):
        return Path(env)
    return Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")) / "MEMORIA.md"


# Ogni funzione lavora su ``file`` se c'e': e' cosi' che la memoria di un canale
# (canali.py, ``<canale>/MEMORIA.md``) usa lo stesso formato e le stesse regole.


def leggi(file: Path | None = None) -> str:
    try:
        return (file or percorso()).read_text(encoding="utf-8")
    except OSError:
        return ""


def _scrivi(testo: str, file: Path | None = None) -> None:
    p = file or percorso()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"~{p.name}")
    tmp.write_text(testo, encoding="utf-8")
    os.replace(tmp, p)


def voci(file: Path | None = None) -> list[str]:
    """Solo le voci, senza intestazione: per sapere se c'e' qualcosa da dire."""
    return [r[2:].strip() for r in leggi(file).splitlines() if r.startswith("- ")]


def ricorda(nota: str, sezione: str = "general", file: Path | None = None,
            intestazione: str = _INTESTAZIONE) -> dict:
    """Aggiunge una voce sotto ``## sezione``; una voce identica non si ripete."""
    nota = " ".join((nota or "").split())
    if not nota:
        raise ValueError("write what to remember in 'note'")
    if len(nota) > 500:
        raise ValueError("one memory is at most 500 characters: split it or summarise it")
    sezione = " ".join((sezione or "general").split())[:60] or "general"
    dove = str(file or percorso())
    with _lock:
        testo = leggi(file) or intestazione
        if any(v == nota or v.rsplit(" (", 1)[0] == nota for v in voci(file)):
            return {"salvata": False, "motivo": "already remembered", "file": dove}
        voce = f"- {nota} ({time.strftime('%Y-%m-%d')})"
        righe = testo.rstrip("\n").split("\n")
        titolo = f"## {sezione}"
        if titolo.lower() in (r.strip().lower() for r in righe):
            i = next(k for k, r in enumerate(righe) if r.strip().lower() == titolo.lower())
            fine = i + 1
            while fine < len(righe) and not righe[fine].startswith("## "):
                fine += 1
            # dopo l'ultima voce della sezione, non dopo le righe vuote
            while fine > i + 1 and not righe[fine - 1].strip():
                fine -= 1
            righe.insert(fine, voce)
        else:
            righe += ["", titolo, voce]
        _scrivi("\n".join(righe) + "\n", file)
    return {"salvata": True, "file": dove}


def dimentica(testo: str, file: Path | None = None) -> dict:
    """Toglie le voci che contengono ``testo`` (maiuscole indifferenti)."""
    cerca = (testo or "").strip().lower()
    if not cerca:
        raise ValueError("say which memory to forget")
    with _lock:
        righe = leggi(file).split("\n")
        tenute = [r for r in righe if not (r.startswith("- ") and cerca in r.lower())]
        tolte = len(righe) - len(tenute)
        if tolte:
            _scrivi("\n".join(tenute), file)
    return {"tolte": tolte}


def sostituisci(testo: str, file: Path | None = None) -> dict:
    """Riscrive tutto il file: e' l'editor della memoria nell'interfaccia."""
    if len(testo) > 200_000:
        raise ValueError("the memory file is too large (200k characters at most)")
    with _lock:
        _scrivi(testo.replace("\r\n", "\n"), file)
    return {"file": str(file or percorso()), "voci": len(voci(file))}


def corpo(file: Path | None = None, limite: int = MAX_CONTESTO) -> str:
    """Le voci sotto i loro titoli, senza l'intestazione (che e' istruzione per
    chi apre il file a mano), o "" se non ce ne sono. Se e' troppo lunga si
    tiene la coda: le voci scritte per ultime sono quelle che correggono le prime.
    """
    if not voci(file):
        return ""
    testo = re.sub(r"\A# .*?(?=^## |\Z)", "", leggi(file), flags=re.S | re.M).strip()
    if len(testo) > limite:
        testo = "[...voci piu' vecchie tagliate: memory per leggerle tutte]\n" + testo[-limite:]
    return testo


def contesto(limite: int = MAX_CONTESTO) -> str:
    """La memoria comune come blocco di contesto, o "" se e' vuota."""
    if not (testo := corpo(None, limite)):
        return ""
    return ("Memoria di chi monta, valida per tutti i progetti (preferenze e scelte gia' "
            "fatte: seguile se la richiesta non dice altro):\n" + testo)
