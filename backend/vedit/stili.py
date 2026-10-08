"""Stili di montaggio che l'utente sceglie per l'assistente.

Uno stile non e' un filtro: e' un modo di montare. Ritmo dei tagli,
transizioni, colore, testi, musica, apertura e chiusura. Lo stile scelto
arriva al modello a ogni messaggio, cosi' "fammi il video" ha gia' una
direzione invece di diventare una media di tutto.

``piano`` e' lo stile di ``story.STYLES`` (i numeri di plan_edit) piu' vicino.
"""

from __future__ import annotations

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


def trova(stile_id: str | None) -> dict | None:
    if not stile_id:
        return None
    return next((s for s in STILI if s["id"] == stile_id), None)


def descrivi() -> list[dict]:
    """Quello che vede la UI: senza la guida lunga."""
    return [{"id": s["id"], "nome": s["nome"], "breve": s["breve"]} for s in STILI]


def blocco(stile_id: str | None) -> str:
    """Testo che accompagna il messaggio quando l'utente ha scelto uno stile."""
    s = trova(stile_id)
    if s is None:
        return ""
    return (f"Stile di montaggio scelto dall'utente: {s['nome']}. Seguilo in ogni scelta "
            f"(per plan_edit usa style='{s['piano']}'). {s['guida']}")
