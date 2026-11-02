"""Piano del video, da approvare *prima* di montare o di spendere.

Un montaggio lungo costa giri e, se genera immagini o video, crediti. Chiedere a meta'
lavoro "va bene cosi'?" e' tardi: il piano va davanti all'utente quando e' ancora solo
una lista. Qui sta la parte pura: la forma delle scene, i totali (durata, generazioni,
costo dichiarato dall'agente), la domanda da mostrare e il file ``<progetto>.piano.json``
accanto al progetto, cosi' un'altra sessione (o un altro agente) sa cosa e' stato approvato.

Il costo non lo calcola vedit: i servizi cambiano prezzo, e un numero sbagliato qui sarebbe
peggio di nessuno. Lo scrive l'agente (dopo aver letto il listino) e la domanda lo etichetta
come stima sua.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

FONTI = ("footage", "graphic", "text", "stock", "generated_image", "generated_video", "voiceover", "music")
GENERATE = ("generated_image", "generated_video")
MAX_SCENE = 40


def percorso(progetto: str | None) -> Path | None:
    if not progetto:
        return None
    p = Path(progetto)
    return p.with_name(f"{p.stem}.piano.json")


def valida(scene: Any) -> list[dict]:
    """Normalizza le scene; un errore torna al modello come messaggio."""
    if not isinstance(scene, list) or not scene:
        raise ValueError("scenes must be a non-empty list of {what, duration, source, cost?, note?}")
    if len(scene) > MAX_SCENE:
        raise ValueError(f"at most {MAX_SCENE} scenes: group them in sections")
    out = []
    for i, s in enumerate(scene, 1):
        if not isinstance(s, dict) or not str(s.get("what", "")).strip():
            raise ValueError(f"scene {i} needs the 'what' field: what the viewer sees and hears")
        try:
            dur = float(s.get("duration"))
        except (TypeError, ValueError):
            raise ValueError(f"scene {i} needs 'duration' in seconds") from None
        if not 0.2 <= dur <= 600:
            raise ValueError(f"scene {i}: duration out of range ({dur}): between 0.2 and 600 seconds")
        fonte = str(s.get("source") or "footage")
        if fonte not in FONTI:
            raise ValueError(f"scene {i}: unknown source {fonte!r}; allowed: {', '.join(FONTI)}")
        voce = {"what": " ".join(str(s["what"]).split())[:240], "duration": round(dur, 2), "source": fonte}
        if s.get("cost") not in (None, ""):
            try:
                costo = float(s["cost"])
            except (TypeError, ValueError):
                raise ValueError(f"scene {i}: cost must be a number") from None
            if costo < 0:
                raise ValueError(f"scene {i}: cost cannot be negative")
            voce["cost"] = round(costo, 2)
        elif fonte in GENERATE:
            voce["cost"] = None            # genera e costa: l'utente deve saperlo anche senza stima
        if str(s.get("note") or "").strip():
            voce["note"] = " ".join(str(s["note"]).split())[:240]
        out.append(voce)
    return out


def totali(scene: list[dict]) -> dict:
    gen = [s for s in scene if s["source"] in GENERATE]
    stimato = [s["cost"] for s in scene if s.get("cost") is not None]
    return {"scene": len(scene), "durata": round(sum(s["duration"] for s in scene), 2),
            "generazioni": len(gen),
            "senza_stima": sum(1 for s in gen if s.get("cost") is None),
            "costo_stimato": round(sum(stimato), 2) if stimato else None}


def _tempo(t: float) -> str:
    m, s = divmod(int(round(t)), 60)
    return f"{m}:{s:02d}"


def testo(titolo: str, scene: list[dict], note: str = "") -> str:
    """Il piano come testo: una riga a scena con i tempi, poi i totali."""
    righe, t = [], 0.0
    for i, s in enumerate(scene, 1):
        extra = f" ({s['note']})" if s.get("note") else ""
        costo = ""
        if s["source"] in GENERATE:
            costo = f" - generated, ~{s['cost']:g}" if s.get("cost") is not None else " - generated, cost unknown"
        righe.append(f"{i}. {_tempo(t)}-{_tempo(t + s['duration'])}  [{s['source']}] {s['what']}{extra}{costo}")
        t += s["duration"]
    tot = totali(scene)
    chiusa = f"{tot['scene']} scenes, {_tempo(tot['durata'])} long"
    if tot["generazioni"]:
        chiusa += f"; {tot['generazioni']} generated (these cost credits"
        if tot["costo_stimato"] is not None:
            chiusa += f", estimated {tot['costo_stimato']:g} by the assistant"
        if tot["senza_stima"]:
            chiusa += f", {tot['senza_stima']} without an estimate"
        chiusa += ")"
    testata = f"{titolo}\n" if titolo else ""
    coda = f"\n{note}" if note else ""
    return f"{testata}" + "\n".join(righe) + f"\n{chiusa}{coda}"


def domanda(titolo: str, scene: list[dict], note: str = "") -> list[dict]:
    """La domanda mostrata nell'editor: il piano, e due strade."""
    tot = totali(scene)
    costa = tot["generazioni"] > 0
    return [{
        "domanda": "Here is the plan. Build it?\n\n" + testo(titolo, scene, note),
        "titolo": "Plan",
        "opzioni": [
            {"etichetta": "Yes, build it",
             "descrizione": "generations may start and spend credits" if costa
             else "the assistant starts editing"},
            {"etichetta": "No, change it", "descrizione": "write what to change in 'other'"},
        ],
        "multipla": False,
    }]


def salva(progetto: str | None, titolo: str, scene: list[dict], note: str = "") -> bool:
    """Scrive il piano approvato accanto al progetto. Falso se il progetto non ha un file."""
    p = percorso(progetto)
    if p is None:
        return False
    dati = {"titolo": titolo, "note": note, "scene": scene, "totali": totali(scene), "approvato": True}
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        return False
    return True


def carica(progetto: str | None) -> dict | None:
    p = percorso(progetto)
    if p is None or not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def feedback(esito: dict) -> str:
    """Cosa ha scritto l'utente quando non approva ('other', o l'etichetta scelta)."""
    r = list((esito.get("risposte") or {}).values())
    if not r:
        return ""
    r = r[0][0] if isinstance(r[0], list) and r[0] else r[0]
    r = str(r or "").strip()
    return "" if r.lower().startswith("no, change") else r
