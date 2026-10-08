"""Domande all'utente: l'assistente si ferma e chiede, invece di decidere da solo.

E' l'equivalente della schermata di domande di Claude Code: da una a quattro
domande, ognuna con due-sei opzioni cliccabili (piu' "altro" per scrivere).
Serve per tutto quello che spetta a chi guarda il video — lo stile, la durata,
quale versione tenere — e soprattutto per l'export: un file si scrive solo
quando l'utente dice di si'.

Qui sta la parte pura (forma delle domande e delle risposte). L'attesa vera,
che tiene ferma la chiamata finche' nel browser non si risponde, sta in
``api.chiedi``: e' li' che c'e' l'interfaccia.
"""

from __future__ import annotations

from typing import Any

MAX_DOMANDE = 4
MAX_OPZIONI = 6

SCHEMA = {
    "type": "object",
    "properties": {
        "domande": {
            "type": "array", "minItems": 1, "maxItems": MAX_DOMANDE,
            "items": {
                "type": "object",
                "properties": {
                    "domanda": {"type": "string", "description": "la domanda, chiara e completa"},
                    "titolo": {"type": "string", "description": "etichetta brevissima (max 12 caratteri)"},
                    "opzioni": {
                        "type": "array", "minItems": 2, "maxItems": MAX_OPZIONI,
                        "items": {"type": "object", "properties": {
                            "etichetta": {"type": "string"},
                            "descrizione": {"type": "string"}},
                            "required": ["etichetta"]},
                    },
                    "multipla": {"type": "boolean", "description": "si possono scegliere piu' opzioni"},
                },
                "required": ["domanda", "opzioni"],
            },
        },
    },
    "required": ["domande"],
}

DESCRIZIONE = (
    "Fa all'utente da 1 a 4 domande con opzioni cliccabili e aspetta la risposta "
    "(l'utente puo' sempre scrivere un'alternativa). Usalo quando una scelta spetta a "
    "lui — stile, durata, formato, quale versione tenere, se esportare — invece di "
    "decidere a caso o di fare domande nel testo. Metti per prima l'opzione che "
    "consigli. Torna le risposte, oppure che l'utente ha annullato.")


def valida(domande: Any) -> list[dict]:
    """Normalizza le domande; un errore qui torna al modello come messaggio."""
    if isinstance(domande, dict) and "domande" in domande:
        domande = domande["domande"]
    if not isinstance(domande, list) or not domande:
        raise ValueError("serve una lista di domande")
    if len(domande) > MAX_DOMANDE:
        raise ValueError(f"al massimo {MAX_DOMANDE} domande per volta")
    out = []
    for d in domande:
        if not isinstance(d, dict) or not str(d.get("domanda", "")).strip():
            raise ValueError("ogni domanda vuole il campo 'domanda'")
        opz = []
        for o in d.get("opzioni") or []:
            if isinstance(o, str):
                o = {"etichetta": o}
            if isinstance(o, dict) and str(o.get("etichetta", "")).strip():
                opz.append({"etichetta": str(o["etichetta"]).strip()[:80],
                            "descrizione": str(o.get("descrizione", "")).strip()[:240]})
        if len(opz) < 2:
            raise ValueError(f"la domanda {d['domanda']!r} vuole almeno due opzioni")
        out.append({
            "domanda": str(d["domanda"]).strip(),
            "titolo": str(d.get("titolo") or "").strip()[:24],
            "opzioni": opz[:MAX_OPZIONI],
            "multipla": bool(d.get("multipla", False)),
        })
    return out


def conferma_export(output: str, quality: str) -> list[dict]:
    """La domanda che precede ogni export chiesto dall'assistente.

    Il nome del file nella domanda, la cartella nella descrizione: un percorso
    intero e' una riga illeggibile proprio dove si deve decidere.
    """
    from pathlib import Path

    f = Path(output)
    return [{
        "domanda": f"L'assistente vuole esportare il video come \"{f.name}\". Procedo?",
        "titolo": "Export",
        "opzioni": [
            {"etichetta": "Si', esporta",
             "descrizione": f"qualita' {quality}, nella cartella {f.parent}"},
            {"etichetta": "No, non ancora", "descrizione": "il video resta nell'editor, continuo a lavorarci"},
        ],
        "multipla": False,
    }]


def approvato(esito: dict) -> bool:
    """Vero solo se l'utente ha scelto esplicitamente di esportare."""
    if esito.get("annullata"):
        return False
    risposte = list((esito.get("risposte") or {}).values())
    if not risposte:
        return False
    r = risposte[0]
    r = r[0] if isinstance(r, list) and r else r
    return isinstance(r, str) and r.lower().startswith("si")
