"""La chat di ogni progetto, salvata accanto al progetto.

Riaprire un progetto e trovare l'assistente senza memoria di quello che si e'
gia' deciso costringe a rispiegare tutto. Qui la conversazione vive in
``<progetto>.chat.json``, accanto al file del progetto come le cartelle
``_voice`` e ``_web``: due cose insieme.

- ``vista``: i turni come li mostra la chat (testo, passi, errori);
- ``stato``: quello che serve al modello per riprendere — la cronologia dei
  modelli via API, l'id della sessione di Claude Code (``--resume``).

La cronologia su disco e' ripulita: niente immagini (pesano e si rigenerano
con preview_frame), niente blocchi di ragionamento (valgono solo nella
conversazione che li ha prodotti), solo gli ultimi messaggi. Se il modello non
puo' riprendere la cronologia, la ``vista`` diventa testo di contesto
(``testo``): il contesto non riparte mai vuoto.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MAX_MESSAGGI = 80
MAX_TURNI = 300
_VERSIONE = 1


def percorso(progetto: str | None) -> Path | None:
    if not progetto:
        return None
    p = Path(progetto)
    return p.with_name(f"{p.stem}.chat.json")


def _blocco(b: Any) -> dict | None:
    """Un blocco di contenuto in forma JSON, o None se non va salvato."""
    if not isinstance(b, dict):
        tipo = getattr(b, "type", None)
        if tipo == "text":
            return {"type": "text", "text": b.text}
        if tipo == "tool_use":
            return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
        return None   # ragionamento, blocchi dei server: non si rimandano
    tipo = b.get("type")
    if tipo in ("image", "document"):
        return {"type": "text", "text": "(immagine)" if tipo == "image" else "(documento)"}
    if tipo == "image_url":
        return {"type": "text", "text": "(immagine)"}
    if tipo in ("thinking", "redacted_thinking"):
        return None
    if tipo == "tool_result":
        c = b.get("content")
        if isinstance(c, list):
            c = "\n".join(x.get("text", "(immagine)") if isinstance(x, dict) else str(x) for x in c)
        out = {"type": "tool_result", "tool_use_id": b.get("tool_use_id"), "content": str(c or "")}
        if b.get("is_error"):
            out["is_error"] = True
        return out
    return json.loads(json.dumps(b, default=str))


def _messaggio(m: dict) -> dict:
    c = m.get("content")
    if isinstance(c, list):
        blocchi = [x for x in (_blocco(b) for b in c) if x is not None]
        if not blocchi:
            blocchi = [{"type": "text", "text": "…"}]
        return {**{k: v for k, v in m.items() if k != "content"}, "content": blocchi}
    return json.loads(json.dumps(m, default=str))


def _inizio_valido(m: dict) -> bool:
    """Un messaggio da cui una cronologia puo' cominciare: l'utente che scrive,
    non il risultato di uno strumento chiesto in un messaggio tagliato via."""
    if m.get("role") != "user":
        return False
    c = m.get("content")
    return not (isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                            for b in c))


def pulisci(messaggi: list) -> list[dict]:
    msgs = [_messaggio(m) for m in messaggi]
    if len(msgs) > MAX_MESSAGGI:
        da = len(msgs) - MAX_MESSAGGI
        while da < len(msgs) and not _inizio_valido(msgs[da]):
            da += 1
        msgs = msgs[da:]
    return msgs


def salva(progetto: str | None, stato: dict, vista: list[dict]) -> None:
    f = percorso(progetto)
    if f is None:
        return
    if not vista and not stato.get("messaggi") and not stato.get("sessione"):
        f.unlink(missing_ok=True)
        return
    dati = {"versione": _VERSIONE,
            "stato": {**{k: v for k, v in stato.items() if k != "messaggi"},
                      "messaggi": pulisci(stato.get("messaggi") or [])},
            "vista": vista[-MAX_TURNI:]}
    tmp = f.with_name(f"~{f.name}")
    tmp.write_text(json.dumps(dati, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, f)


def carica(progetto: str | None) -> tuple[dict, list[dict]]:
    f = percorso(progetto)
    if f is None or not f.is_file():
        return {}, []
    try:
        dati = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, []
    stato = dati.get("stato") if isinstance(dati.get("stato"), dict) else {}
    vista = dati.get("vista") if isinstance(dati.get("vista"), list) else []
    return stato, vista


def testo(vista: list[dict], limite: int = 8000) -> str:
    """La conversazione in parole, dalla fine: contesto per un modello che non
    puo' riprendere la cronologia vera."""
    righe: list[str] = []
    for t in vista:
        if t.get("role") == "user":
            righe.append(f"Utente: {t.get('text', '')}")
        else:
            passi = ", ".join(x.get("name", "") for x in t.get("tools") or [])
            riga = f"Assistente: {t.get('text', '')}".rstrip()
            if passi:
                riga += f" [strumenti: {passi}]"
            righe.append(riga)
    out, tot = [], 0
    for r in reversed(righe):
        r = r[:1500]
        if tot + len(r) > limite:
            break
        out.append(r)
        tot += len(r)
    return "\n".join(reversed(out))
