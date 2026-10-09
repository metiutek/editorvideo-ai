"""Stili di montaggio che l'utente sceglie per l'assistente.

Uno stile non e' un filtro: e' un modo di montare. Ritmo dei tagli,
transizioni, colore, testi, musica, apertura e chiusura. Lo stile scelto
arriva al modello a ogni messaggio, cosi' "fammi il video" ha gia' una
direzione invece di diventare una media di tutto.

``piano`` e' lo stile di ``story.STYLES`` (i numeri di plan_edit) piu' vicino.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

STILI: list[dict] = [
    {"id": "cinematico", "nome": "Cinematografico", "piano": "cinematic",
     "breve": "Lento, immagini tenute, colore da film",
     "guida": "Inquadrature tenute 3-8 s, tagli sul respiro e non sul beat. Dissolvenze morbide "
              "(0.6-1 s) solo dove il tempo passa. Colore: contrasto morbido, ombre fredde e pelle "
              "calda, con mano leggera sul master. Movimento lento dentro l'inquadratura (spinte "
              "con set_transform). Titoli sottili e piccoli, molto spazio. Musica con un arco vero "
              "e silenzio prima del momento forte. Si chiude su un'immagine tenuta."},
    {"id": "dinamico", "nome": "Dinamico / Social", "piano": "shortform",
     "breve": "Tagli veloci sul beat, testi grandi",
     "guida": "Il gancio nei primi 2 secondi. Tagli di 0.5-1.5 s sul battito (music_beats), "
              "punch-in con scala animata, testi grandi e animati che si leggono senza audio, "
              "sottotitoli. Niente pause morte. Se il materiale lo consente, formato verticale. "
              "Ogni 3-4 secondi cambia qualcosa: inquadratura, scala o testo."},
    {"id": "documentario", "nome": "Documentario", "piano": "documentary",
     "breve": "Guidato dal parlato, sobrio",
     "guida": "Il parlato decide i tagli: J e L cut (jl_cut), sottopancia con nome e ruolo, "
              "b-roll che illustra quello che si dice. Colore naturale. Musica bassa sotto la "
              "voce (duck_music). Transizioni rare e motivate. Si apre calmi e si costruisce."},
    {"id": "vlog", "nome": "Vlog", "piano": "vlog",
     "breve": "Jump cut, ritmo personale",
     "guida": "Jump cut sul parlato (tighten_speech) per togliere le pause, b-roll e dettagli fra "
              "le frasi, titoli giocosi, zoom leggeri per enfasi. Ritmo sostenuto ma respirabile, "
              "musica allegra bassa. Chiusura con un saluto o una call to action."},
    {"id": "trailer", "nome": "Trailer", "piano": "cinematic",
     "breve": "Tre atti, crescendo, cartelli",
     "guida": "Tre atti: presentazione lenta, tensione che cresce, raffica finale. Cartelli di "
              "testo su nero tra le scene, tagli che accelerano verso il picco, un attimo di "
              "silenzio prima dell'ultimo colpo, poi titolo e data. Transizioni secche, qualche "
              "flash bianco sui colpi."},
    {"id": "videoclip", "nome": "Videoclip musicale", "piano": "shortform",
     "breve": "Tutto a tempo di musica",
     "guida": "La musica comanda: stacchi sui battiti e cambi di scena sulle battute "
              "(music_beats con every=4). Sezioni diverse per strofa, ritornello e break, con "
              "colore e grafica che cambiano con l'energia. Effetti sincronizzati sui colpi."},
    {"id": "minimal", "nome": "Minimal / Pulito", "piano": "documentary",
     "breve": "Pochi tagli, niente effetti",
     "guida": "Pochi tagli e tenuti, transizioni secche, niente effetti vistosi. Tipografia "
              "sobria, molto spazio vuoto, colore neutro. Ogni elemento sullo schermo deve "
              "guadagnarsi il posto."},
    {"id": "retro", "nome": "Retro / VHS", "piano": "vlog",
     "breve": "Grana, glitch, anni '90",
     "guida": "Look videocassetta: grana, leggera sfocatura, saturazione e colori anni '90, "
              "scritte in stile timecode o pixel. Transizioni glitch brevi, qualche salto di "
              "fotogramma voluto. Formato 4:3 se il materiale lo permette."},
]


# ---------------------------------------------------------------------------
# stili personali: scritti dall'utente, restano su questo computer
# ---------------------------------------------------------------------------

PIANI = ("cinematic", "shortform", "documentary", "vlog")
MAX_GUIDA = 4000


def _file() -> Path:
    """Accanto a llm.json: e' una preferenza di chi monta, non del progetto."""
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "stili.json"


def personali() -> list[dict]:
    try:
        dati = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [s for s in dati if isinstance(s, dict) and s.get("id") and s.get("guida")]         if isinstance(dati, list) else []


def _scrivi(lista: list[dict]) -> None:
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def salva(nome: str, guida: str, breve: str = "", piano: str = "vlog",
          stile_id: str | None = None) -> dict:
    """Crea o aggiorna uno stile personale; restituisce lo stile salvato.

    ``guida`` e' il testo che arriva al modello a ogni messaggio: come montare,
    con parole proprie. ``piano`` sceglie i numeri di plan_edit piu' vicini.
    """
    nome, guida, breve = (nome or "").strip(), (guida or "").strip(), (breve or "").strip()
    if not nome:
        raise ValueError("dai un nome allo stile")
    if not guida:
        raise ValueError("scrivi come deve montare l'assistente con questo stile")
    if len(guida) > MAX_GUIDA:
        raise ValueError(f"istruzioni troppo lunghe ({len(guida)} caratteri, massimo {MAX_GUIDA})")
    if piano not in PIANI:
        raise ValueError(f"ritmo di base sconosciuto {piano!r}; ammessi: {', '.join(PIANI)}")
    lista = personali()
    if stile_id:
        if not any(s["id"] == stile_id for s in lista):
            raise ValueError(f"stile personale {stile_id!r} inesistente")
    else:
        radice = "mio-" + (re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-") or "stile")
        stile_id, n = radice, 2
        while any(s["id"] == stile_id for s in lista):
            stile_id, n = f"{radice}-{n}", n + 1
    nuovo = {"id": stile_id, "nome": nome[:60], "breve": breve[:120] or guida[:80],
             "guida": guida, "piano": piano, "personale": True}
    lista = [nuovo if s["id"] == stile_id else s for s in lista]
    if not any(s["id"] == stile_id for s in lista):
        lista.append(nuovo)
    _scrivi(lista)
    return nuovo


def elimina(stile_id: str) -> None:
    lista = personali()
    if not any(s["id"] == stile_id for s in lista):
        raise ValueError(f"stile personale {stile_id!r} inesistente")
    _scrivi([s for s in lista if s["id"] != stile_id])


def tutti() -> list[dict]:
    return [*STILI, *personali()]


def trova(stile_id: str | None) -> dict | None:
    if not stile_id:
        return None
    return next((s for s in tutti() if s["id"] == stile_id), None)


def descrivi() -> list[dict]:
    """Quello che vede la UI. La guida c'e' solo per gli stili personali: si modificano."""
    out = []
    for s in tutti():
        d = {"id": s["id"], "nome": s["nome"], "breve": s["breve"]}
        if s.get("personale"):
            d.update(personale=True, guida=s["guida"], piano=s.get("piano", "vlog"))
        out.append(d)
    return out


def blocco(stile_id: str | None) -> str:
    """Testo che accompagna il messaggio quando l'utente ha scelto uno stile."""
    s = trova(stile_id)
    if s is None:
        return ""
    chi = "scritto dall'utente stesso" if s.get("personale") else "scelto dall'utente"
    return (f"Stile di montaggio {chi}: {s['nome']}. Seguilo in ogni scelta "
            f"(per plan_edit usa style='{s.get('piano', 'vlog')}'). {s['guida']}")
