"""Registro di cio' che non va, scritto da chi monta (agente o assistente).

Bug, strumenti scomodi, risultati sbagliati, cose che mancano per un compito:
l'agente li annota mentre lavora invece di aggirarli in silenzio, e da qui si
decide cosa migliorare. Il file e' Markdown in append: si legge a occhio e si
modifica a mano (si cancella una voce quando e' risolta).

Dove: ``SEGNALAZIONI.md`` alla radice della repo se il pacchetto gira da un
clone (installazione modificabile), altrimenti ``~/.vedit/SEGNALAZIONI.md``.
``VEDIT_SEGNALAZIONI`` lo sposta dove si vuole.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

TIPI = ("bug", "scomodo", "sbagliato", "manca", "lento")

_INTESTAZIONE = """\
# Segnalazioni

Cose che non funzionano, scomode, che danno risultati sbagliati o che mancano,
annotate da chi monta (strumento MCP `report_issue`). Una voce risolta si cancella.

Tipi: `bug` errore o crash, `scomodo` funziona ma costa troppi passi,
`sbagliato` risultato diverso da quello promesso, `manca` serve e non c'e',
`lento` troppo tempo per quello che fa.
"""

_lock = threading.Lock()


def percorso() -> Path:
    if env := os.environ.get("VEDIT_SEGNALAZIONI"):
        return Path(env)
    repo = Path(__file__).resolve().parents[2]
    if (repo / "pyproject.toml").is_file() and (repo / "backend" / "vedit").is_dir():
        return repo / "SEGNALAZIONI.md"
    return Path.home() / ".vedit" / "SEGNALAZIONI.md"


def segnala(tipo: str, cosa: str, compito: str = "", strumento: str = "",
            proposta: str = "") -> dict:
    tipo = (tipo or "").strip().lower()
    if tipo not in TIPI:
        raise ValueError(f"tipo sconosciuto: {tipo!r} (ammessi: {', '.join(TIPI)})")
    cosa = (cosa or "").strip()
    if not cosa:
        raise ValueError("descrivi cosa non va in 'cosa'")
    righe = [f"\n## [{tipo}] {strumento or 'generale'} — {time.strftime('%Y-%m-%d %H:%M')}\n",
             f"\n{cosa}\n"]
    if compito.strip():
        righe.append(f"\n- **compito:** {compito.strip()}\n")
    if proposta.strip():
        righe.append(f"- **proposta:** {proposta.strip()}\n")
    p = percorso()
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        nuovo = not p.exists()
        with p.open("a", encoding="utf-8") as f:
            if nuovo:
                f.write(_INTESTAZIONE)
            f.write("".join(righe))
    return {"salvata": True, "file": str(p)}
