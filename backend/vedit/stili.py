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
    {"id": "cinematico", "nome": "Cinematic", "piano": "cinematic",
     "breve": "Slow, held shots, film colour",
     "guida": "Inquadrature tenute 3-8 s, tagli sul respiro e non sul beat. Dissolvenze morbide "
              "(0.6-1 s) solo dove il tempo passa. Colore: contrasto morbido, ombre fredde e pelle "
              "calda, con mano leggera sul master. Movimento lento dentro l'inquadratura (spinte "
              "con set_transform). Titoli sottili e piccoli, molto spazio. Musica con un arco vero "
              "e silenzio prima del momento forte. Si chiude su un'immagine tenuta."},
    {"id": "dinamico", "nome": "Dynamic / Social", "piano": "shortform",
     "breve": "Fast cuts on the beat, big text",
     "guida": "Il gancio nei primi 2 secondi. Tagli di 0.5-1.5 s sul battito (music_beats), "
              "punch-in con scala animata, testi grandi e animati che si leggono senza audio, "
              "sottotitoli. Niente pause morte. Se il materiale lo consente, formato verticale. "
              "Ogni 3-4 secondi cambia qualcosa: inquadratura, scala o testo."},
    {"id": "documentario", "nome": "Documentary", "piano": "documentary",
     "breve": "Driven by speech, understated",
     "guida": "Il parlato decide i tagli: J e L cut (jl_cut), sottopancia con nome e ruolo, "
              "b-roll che illustra quello che si dice. Colore naturale. Musica bassa sotto la "
              "voce (duck_music). Transizioni rare e motivate. Si apre calmi e si costruisce."},
    {"id": "vlog", "nome": "Vlog", "piano": "vlog",
     "breve": "Jump cuts, personal pace",
     "guida": "Jump cut sul parlato (tighten_speech) per togliere le pause, b-roll e dettagli fra "
              "le frasi, titoli giocosi, zoom leggeri per enfasi. Ritmo sostenuto ma respirabile, "
              "musica allegra bassa. Chiusura con un saluto o una call to action."},
    {"id": "trailer", "nome": "Trailer", "piano": "cinematic",
     "breve": "Three acts, crescendo, title cards",
     "guida": "Tre atti: presentazione lenta, tensione che cresce, raffica finale. Cartelli di "
              "testo su nero tra le scene, tagli che accelerano verso il picco, un attimo di "
              "silenzio prima dell'ultimo colpo, poi titolo e data. Transizioni secche, qualche "
              "flash bianco sui colpi."},
    {"id": "videoclip", "nome": "Music video", "piano": "shortform",
     "breve": "Everything on the beat",
     "guida": "La musica comanda: stacchi sui battiti e cambi di scena sulle battute "
              "(music_beats con every=4). Sezioni diverse per strofa, ritornello e break, con "
              "colore e grafica che cambiano con l'energia. Effetti sincronizzati sui colpi."},
    {"id": "minimal", "nome": "Minimal / Clean", "piano": "documentary",
     "breve": "Few cuts, no effects",
     "guida": "Pochi tagli e tenuti, transizioni secche, niente effetti vistosi. Tipografia "
              "sobria, molto spazio vuoto, colore neutro. Ogni elemento sullo schermo deve "
              "guadagnarsi il posto."},
    {"id": "retro", "nome": "Retro / VHS", "piano": "vlog",
     "breve": "Grain, glitch, the 90s",
     "guida": "Look videocassetta: grana, leggera sfocatura, saturazione e colori anni '90, "
              "scritte in stile timecode o pixel. Transizioni glitch brevi, qualche salto di "
              "fotogramma voluto. Formato 4:3 se il materiale lo permette."},
]


# ---------------------------------------------------------------------------
# stili personali: scritti dall'utente, restano su questo computer
# ---------------------------------------------------------------------------

PIANI = ("cinematic", "shortform", "documentary", "vlog")
# le istruzioni di uno stile arrivano al modello a ogni messaggio: 20k caratteri
# sono circa 5k token, abbastanza per una guida di montaggio dettagliata
MAX_GUIDA = 20000


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
          stile_id: str | None = None, ricetta: dict | None = None) -> dict:
    """Crea o aggiorna uno stile personale; restituisce lo stile salvato.

    ``guida`` e' il testo che arriva al modello a ogni messaggio: come montare,
    con parole proprie. ``piano`` sceglie i numeri di plan_edit piu' vicini.
    ``ricetta`` (facoltativa) corregge la ricetta presa dal ritmo di base: e'
    quello che apply_style applichera' davvero (vedi ``valida_ricetta``).
    ``None`` in un aggiornamento tiene la ricetta che lo stile aveva gia'.
    """
    nome, guida, breve = (nome or "").strip(), (guida or "").strip(), (breve or "").strip()
    if not nome:
        raise ValueError("give the style a name")
    if not guida:
        raise ValueError("write how the assistant should edit with this style")
    if len(guida) > MAX_GUIDA:
        raise ValueError(f"instructions too long ({len(guida)} characters, at most {MAX_GUIDA})")
    if piano not in PIANI:
        raise ValueError(f"unknown base pace {piano!r}; allowed: {', '.join(PIANI)}")
    propria = valida_ricetta(ricetta) if ricetta is not None else None
    lista = personali()
    if stile_id:
        if not any(s["id"] == stile_id for s in lista):
            raise ValueError(f"personal style {stile_id!r} does not exist")
    else:
        radice = "mio-" + (re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-") or "stile")
        stile_id, n = radice, 2
        while any(s["id"] == stile_id for s in lista):
            stile_id, n = f"{radice}-{n}", n + 1
    nuovo = {"id": stile_id, "nome": nome[:60], "breve": breve[:120] or guida[:80],
             "guida": guida, "piano": piano, "personale": True}
    if propria is None:
        propria = next((s.get("ricetta") for s in lista if s["id"] == stile_id), None)
    if propria:
        nuovo["ricetta"] = propria
    lista =[nuovo if s["id"] == stile_id else s for s in lista]
    if not any(s["id"] == stile_id for s in lista):
        lista.append(nuovo)
    _scrivi(lista)
    return nuovo


def elimina(stile_id: str) -> None:
    lista = personali()
    if not any(s["id"] == stile_id for s in lista):
        raise ValueError(f"personal style {stile_id!r} does not exist")
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
            if s.get("ricetta"):
                d["ricetta"] = s["ricetta"]
        out.append(d)
    return out


def blocco(stile_id: str | None) -> str:
    """Testo che accompagna il messaggio quando l'utente ha scelto uno stile."""
    s = trova(stile_id)
    if s is None:
        return ""
    chi = "scritto dall'utente stesso" if s.get("personale") else "scelto dall'utente"
    return (f"Stile di montaggio {chi}: {s['nome']}. Seguilo in ogni scelta "
            f"(per plan_edit usa style='{s.get('piano', 'vlog')}'). {s['guida']}\n"
            f"Dopo aver messo le clip in timeline chiama apply_style(style='{s['id']}'): "
            "applica la base dello stile (colore, movimento, transizioni, musica). Poi "
            "fai tu quello che una ricetta non puo' fare - testi, grafica, accenti sui "
            "momenti forti - e non dire che hai finito finche' review_edit da' avvisi.")


# ---------------------------------------------------------------------------
# ricette: la parte di uno stile che si puo' applicare senza capire il girato
# ---------------------------------------------------------------------------
#
# La guida e' testo per il modello, e un testo si puo' leggere e poi ignorare:
# la via piu' corta — mettere le clip in fila e fermarsi — vince sempre. La
# ricetta e' la base che arriva comunque: colore, movimento dentro
# l'inquadratura, transizioni, aperture e chiusure, musica che si muove.
# Quello che dipende dal contenuto (quali parole nei titoli, dove sta il
# momento forte) resta al modello, e la ricetta lo elenca in ``da_fare``.
#
# movimento: spinta = zoom lento alternato dentro/fuori; punch = ingrandimento
#   netto a clip alterne (il taglio sembra uno stacco di macchina); None.
# transizioni: (tipo, durata, ogni quante clip); None = solo stacchi.
# musica: arco | crescendo | sotto_voce | None.
# accenti: effetto sul primo istante di una clip ogni N (shake, glitch).
# attese: le voci di review.ricchezza che lo stile pretende.

RICETTE: dict[str, dict] = {
    "cinematico": {"look": "cinema_teal_orange", "movimento": "spinta", "zoom": 0.06,
                   "transizioni": ("dissolve", 0.8, 4), "apertura": 1.0, "chiusura": 1.5,
                   "musica": "arco", "accenti": None,
                   "attese": ["movimento", "colore", "musica_viva", "ritmo_vario"],
                   "da_fare": ["un titolo sottile, piccolo, con molto spazio",
                               "silenzio o calo della musica prima del momento forte",
                               "chiudi su un'immagine tenuta almeno 3 s"]},
    "dinamico": {"look": "nitido", "movimento": "punch", "zoom": 0.14,
                 "transizioni": None, "apertura": 0.0, "chiusura": 0.4,
                 "musica": "arco", "accenti": ("shake", 4),
                 "attese": ["movimento", "grafica", "musica_viva", "ritmo_vario"],
                 "da_fare": ["gancio nei primi 2 s: la ripresa piu' forte per prima",
                             "testi grandi e animati (add_html) leggibili senza audio",
                             "tagli sui battiti: music_beats every=1"]},
    "documentario": {"look": None, "movimento": "spinta", "zoom": 0.03,
                     "transizioni": ("dissolve", 0.6, 6), "apertura": 1.0, "chiusura": 1.5,
                     "musica": "sotto_voce", "accenti": None,
                     "attese": ["grafica", "musica_viva"],
                     "da_fare": ["sottopancia con nome e ruolo di chi parla",
                                 "J e L cut sul parlato (jl_cut)",
                                 "b-roll che illustra quello che si dice"]},
    "vlog": {"look": "caldo_tramonto", "movimento": "punch", "zoom": 0.08,
             "transizioni": None, "apertura": 0.0, "chiusura": 0.8,
             "musica": "sotto_voce", "accenti": None,
             "attese": ["movimento", "grafica", "musica_viva"],
             "da_fare": ["jump cut sulle pause (tighten_speech)",
                         "titoli giocosi sulle frasi chiave",
                         "chiusura con saluto o call to action"]},
    "trailer": {"look": "cinema_teal_orange", "movimento": "spinta", "zoom": 0.08,
                "transizioni": None, "apertura": 0.6, "chiusura": 0.3,
                "musica": "crescendo", "accenti": ("shake", 3), "atti": True,
                "attese": ["movimento", "colore", "musica_viva", "ritmo_vario", "grafica"],
                "da_fare": ["cartelli di testo su nero tra gli atti",
                            "tagli che accelerano verso il picco",
                            "titolo e data alla fine"]},
    "videoclip": {"look": "cinema_teal_orange", "movimento": "punch", "zoom": 0.12,
                  "transizioni": None, "apertura": 0.0, "chiusura": 1.0,
                  "musica": "arco", "accenti": ("shake", 4),
                  "attese": ["movimento", "colore", "musica_viva", "effetti"],
                  "da_fare": ["stacchi sui battiti, cambi di scena sulle battute "
                              "(music_beats every=4)",
                              "colore o grafica che cambiano col ritornello"]},
    "minimal": {"look": None, "movimento": None, "zoom": 0.0,
                "transizioni": None, "apertura": 0.5, "chiusura": 0.8,
                "musica": "arco", "accenti": None,
                "attese": ["musica_viva"],
                "da_fare": ["tipografia sobria, molto spazio vuoto"]},
    "retro": {"look": "vhs", "movimento": None, "zoom": 0.0,
              "transizioni": None, "apertura": 0.4, "chiusura": 0.6,
              "musica": "arco", "accenti": ("glitch", 4),
              "attese": ["colore", "effetti", "musica_viva"],
              "da_fare": ["scritte stile timecode o pixel (add_html)",
                          "formato 4:3 se il materiale lo permette"]},
}

# uno stile personale parte dalla ricetta dello stile integrato col ritmo piu'
# vicino, senza il look (il colore lo descrive l'utente); la sua ``ricetta``
# corregge solo le voci che nomina
_DA_PIANO = {"cinematic": "cinematico", "shortform": "dinamico",
             "documentary": "documentario", "vlog": "vlog"}

MOVIMENTI = ("spinta", "punch")
MUSICHE = ("arco", "crescendo", "sotto_voce")
ACCENTI = ("shake", "glitch")
VOCI_RICETTA = ("look", "movimento", "zoom", "transizioni", "apertura", "chiusura",
                "musica", "accenti", "atti", "attese", "da_fare", "colore")
# quanto apply_style porta le riprese verso il colore di un riferimento: al 100%
# le statistiche di un contenuto diverso (cielo contro volto) trascinerebbero troppo
FORZA_COLORE = 0.6


def valida_ricetta(r: dict) -> dict:
    """Controlla e normalizza una ricetta parziale scritta da un agente o dall'utente.

    Accetta le forme comode da JSON: ``transizioni`` come
    ``{"tipo","durata","ogni"}`` o ``[tipo, durata, ogni]``, ``accenti`` come
    ``{"effetto","ogni"}`` o ``[effetto, ogni]``; ``null`` spegne la voce.
    Ogni errore elenca i valori ammessi: chi scrive la ricetta e' spesso un
    modello, e deve potersi correggere da solo.
    """
    from . import presets, review
    from .model import TRANSITIONS

    if not isinstance(r, dict):
        raise ValueError('the recipe is an object, e.g. {"movimento": "punch", "zoom": 0.1}')
    ignote = [k for k in r if k not in VOCI_RICETTA]
    if ignote:
        raise ValueError(f"unknown recipe entries: {', '.join(ignote)}; "
                         f"allowed: {', '.join(VOCI_RICETTA)}")

    def numero(k, lo, hi):
        try:
            v = float(r[k])
        except (TypeError, ValueError):
            raise ValueError(f"{k} must be a number between {lo} and {hi}") from None
        if not lo <= v <= hi:
            raise ValueError(f"{k} out of range ({v}): between {lo} and {hi}")
        return round(v, 3)

    def scelta(k, ammessi):
        v = r[k]
        if v is not None and v not in ammessi:
            raise ValueError(f"unknown {k} {v!r}; allowed: {', '.join(ammessi)} or null")
        return v

    out: dict = {}
    if "look" in r:
        looks = [p["id"] for p in presets.LOOKS]
        if r["look"] is not None and r["look"] not in looks:
            raise ValueError(f"unknown look {r['look']!r}; allowed: {', '.join(looks)} or null")
        out["look"] = r["look"]
    if "movimento" in r:
        out["movimento"] = scelta("movimento", MOVIMENTI)
    if "zoom" in r:
        out["zoom"] = numero("zoom", 0.0, 0.5)
    for k in ("apertura", "chiusura"):
        if k in r:
            out[k] = numero(k, 0.0, 5.0)
    if "musica" in r:
        out["musica"] = scelta("musica", MUSICHE)
    if "atti" in r:
        out["atti"] = bool(r["atti"])
    if "transizioni" in r:
        v = r["transizioni"]
        if v is not None:
            if isinstance(v, dict):
                v = [v.get("tipo", v.get("type")), v.get("durata", v.get("duration", 0.6)),
                     v.get("ogni", v.get("every", 4))]
            try:
                tipo, dur, ogni = v
                dur, ogni = float(dur), int(ogni)
            except (TypeError, ValueError):
                raise ValueError('transizioni: {"tipo": "dissolve", "durata": 0.6, "ogni": 4} '
                                 "or null") from None
            ammesse = [t for t in TRANSITIONS if t != "none"]
            if tipo not in ammesse:
                raise ValueError(f"unknown transition {tipo!r}; allowed: {', '.join(ammesse)}")
            if not 0.1 <= dur <= 3.0 or not 1 <= ogni <= 50:
                raise ValueError("transizioni: duration between 0.1 and 3 s, every between 1 and 50 clips")
            v = [tipo, round(dur, 3), ogni]
        out["transizioni"] = v
    if "accenti" in r:
        v = r["accenti"]
        if v is not None:
            if isinstance(v, dict):
                v = [v.get("effetto", v.get("effect")), v.get("ogni", v.get("every", 4))]
            try:
                nome, ogni = v
                ogni = int(ogni)
            except (TypeError, ValueError):
                raise ValueError('accenti: {"effetto": "shake", "ogni": 4} or null') from None
            if nome not in ACCENTI or not 1 <= ogni <= 50:
                raise ValueError(f"accenti: effect among {', '.join(ACCENTI)}, every between 1 and 50")
            v = [nome, ogni]
        out["accenti"] = v
    if "attese" in r:
        v = list(r["attese"] or [])
        ignote = [a for a in v if a not in review._RIMEDI]
        if ignote:
            raise ValueError(f"unknown expectations: {', '.join(map(str, ignote))}; "
                             f"allowed: {', '.join(review._RIMEDI)}")
        out["attese"] = v
    if "colore" in r:
        v = r["colore"]
        if v is not None:
            try:
                v = {k: [round(float(x), 5) for x in v[k]] for k in ("mean", "std")}
            except (TypeError, ValueError, KeyError):
                raise ValueError('colore: {"mean": [r, g, b], "std": [r, g, b]} in 0..1, '
                                 "or null") from None
            if any(len(x) != 3 or not all(0 <= c <= 1 for c in x) for x in v.values()):
                raise ValueError("colore: three values between 0 and 1 for mean and for std")
        out["colore"] = v
    if "da_fare" in r:
        v = r["da_fare"] or []
        if isinstance(v, str):
            v = [v]
        out["da_fare"] = [str(x).strip()[:300] for x in v if str(x).strip()][:10]
    return out


def _da_json(r: dict) -> dict:
    """Nel file le coppie sono liste: ``applica`` le spacchetta come tuple."""
    r = dict(r)
    for k in ("transizioni", "accenti"):
        if r.get(k) is not None:
            r[k] = tuple(r[k])
    return r


def ricetta(stile_id: str) -> dict:
    s = trova(stile_id)
    if s is None:
        raise ValueError(f"unknown style {stile_id!r}; available: "
                         + ", ".join(x["id"] for x in tutti()))
    if s["id"] in RICETTE:
        return RICETTE[s["id"]]
    base = dict(RICETTE[_DA_PIANO.get(s.get("piano", "vlog"), "vlog")])
    base["look"] = None
    base["da_fare"] = ["segui la guida dello stile: " + s["guida"][:300]]
    propria = _da_json(s.get("ricetta") or {})
    if "da_fare" in propria:
        propria["da_fare"] = [*propria["da_fare"], *base["da_fare"]]
    base.update(propria)
    return base


def curva_musica(forma: str, durata: float, base: float) -> dict:
    """Keyframe di gain_db per una traccia musicale lunga ``durata`` secondi.

    Non conosce la canzone: disegna un arco plausibile (intro piu' bassa,
    respiro a due terzi, picco verso la fine, uscita in dissolvenza). Con
    music_beats si spostano i punti sulle sezioni vere.
    """
    d = max(2.0, durata)
    fine = max(0.5, min(2.0, d * 0.08))

    def k(t, v, ease="ease_in_out"):
        return {"t": round(max(0.0, min(d, t)), 3), "v": round(v, 2), "ease": ease}

    if forma == "crescendo":
        punti = [k(0, base - 10), k(d * 0.3, base - 6), k(d * 0.6, base - 3),
                 k(d * 0.84, base), k(d * 0.86, base - 30, "linear"),
                 k(d * 0.89, base + 1, "linear"), k(d - fine, base + 1), k(d, base - 40)]
    elif forma == "sotto_voce":
        punti = [k(0, base - 8), k(min(3.0, d * 0.1), base - 16), k(d - 4.0, base - 16),
                 k(d - fine, base - 8), k(d, base - 40)]
    else:  # arco
        punti = [k(0, base - 8), k(d * 0.12, base - 3), k(d * 0.45, base),
                 k(d * 0.68, base - 5), k(d * 0.82, base + 1), k(d - fine, base + 1),
                 k(d, base - 40)]
    # due punti nello stesso istante confondono l'interpolazione
    pulito: list[dict] = []
    for p in sorted(punti, key=lambda q: q["t"]):
        if pulito and p["t"] <= pulito[-1]["t"]:
            continue
        pulito.append(p)
    return {"kf": pulito}


def applica(store, stile_id: str, track: str | None = None) -> dict:
    """Applica la ricetta dello stile alla timeline, come un gesto solo.

    Tocca solo quello che non e' gia' stato deciso: una clip con un movimento
    suo, una transizione gia' messa, un master che ha gia' un look, una musica
    gia' automatizzata restano come sono. Si puo' quindi rilanciare dopo aver
    aggiunto clip senza rifare il lavoro a mano.
    """
    from . import keyframes as kf
    from . import presets, review

    r = ricetta(stile_id)
    p = store.project
    tracce = [t for t in p.tracks if t.kind == "video" and (track is None or t.id == track)]
    if track is not None and not tracce:
        raise ValueError(f"video track {track!r} does not exist")
    # uno spot fatto solo di grafica html non ha riprese: la grafica e' il materiale
    tipo = "media" if any(c.type == "media" for t in tracce for c in t.clips) else "html"
    principale = next((t for t in tracce if any(c.type == tipo for c in t.clips)), None)
    if principale is None:
        raise ValueError("no video clips in the timeline: lay down the footage first "
                         "(add_clips or plan_edit apply=True)")
    ids = [c.id for c in sorted((c for c in principale.clips
                                 if c.type == tipo and c.enabled), key=lambda c: c.start)]
    fatto: dict[str, object] = {}
    saltati: list[str] = []

    def clip(cid):
        return store.clip_or_die(cid)[1]

    def mosso(c) -> bool:
        tf = c.transform
        return (any(kf.is_kf(v) for v in (tf.x, tf.y, tf.scale, tf.rotation))
                or abs(float(kf.sample(tf.scale, 0, 1.0)) - 1.0) > 1e-3)

    with store.batch():
        # colore: sul master, una volta sola, cosi' le riprese si somigliano
        if r["look"]:
            colore = {"color", "colorbalance", "temperature", "curves", "lut", "sharpen",
                      "grain", "blur", "glow", "vignette"}
            if any(e.type in colore for e in store.project.master.effects):
                saltati.append("look: il master ha gia' un colore")
            else:
                store.add_effects(None, presets.find(r["look"])["effects"])
                fatto["look"] = r["look"]

        # colore di un video di riferimento (stile imparato): ogni ripresa portata
        # verso le sue statistiche, una correzione per sorgente
        if r.get("colore") and tipo == "media":
            from . import colormatch
            misure: dict[str, dict] = {}
            allineate = 0
            for t in tracce:
                for c in t.clips:
                    if c.type != "media" or any(e.type == "colormatch" for e in c.effects):
                        continue
                    path = store.media_or_die(c.media).path
                    try:
                        if path not in misure:
                            misure[path] = colormatch.stats(path, 6)
                    except (ValueError, OSError):
                        continue  # un'immagine o un file illeggibile: resta com'e'
                    store.add_effect(c.id, "colormatch", colormatch.match_params(
                        misure[path], r["colore"], FORZA_COLORE))
                    allineate += 1
            fatto["colore"] = f"colore del riferimento su {allineate} clip"

        # movimento dentro l'inquadratura
        if r["movimento"]:
            z, mossi = r["zoom"], 0
            for i, cid in enumerate(ids):
                c = clip(cid)
                if mosso(c):
                    continue
                d = round(c.duration, 3)
                if r["movimento"] == "spinta":
                    a, b = (1.0, 1.0 + z) if i % 2 == 0 else (1.0 + z, 1.0)
                elif i % 2 == 1:   # punch: una clip si' e una no, il contrasto e' il colpo
                    a, b = 1.0 + z, 1.0 + z * 1.25
                else:
                    continue
                store.set_transform(cid, scale={"kf": [{"t": 0, "v": round(a, 3)},
                                                       {"t": d, "v": round(b, 3)}]})
                mossi += 1
            fatto["movimento"] = f"{r['movimento']} su {mossi} clip"

        # transizioni ai cambi di sezione, non a ogni taglio
        if r["transizioni"] and len(ids) > 1:
            tipo, dur, ogni = r["transizioni"]
            messe = 0
            for i, cid in enumerate(ids[:-1]):
                c = clip(cid)
                # dissolve senza sovrapposizione e' una dissolvenza al nero
                if (i + 1) % ogni or c.transition_out.duration > 0 or c.fade_out > 0:
                    continue
                store.set_transition(cid, tipo, min(dur, c.duration / 3))
                messe += 1
            fatto["transizioni"] = f"{messe} {tipo}"

        # trailer: tre atti separati dal nero
        if r.get("atti") and len(ids) >= 6:
            fine_tl = clip(ids[-1]).end
            for frazione in (1 / 3, 2 / 3):
                j = min(range(len(ids) - 1), key=lambda i: abs(clip(ids[i]).end - fine_tl * frazione))
                prima, dopo = clip(ids[j]), clip(ids[j + 1])
                store.set_fades(prima.id, fade_out=min(0.4, prima.duration / 3))
                store.set_fades(dopo.id, fade_in=min(0.3, dopo.duration / 3))
            fatto["atti"] = "dissolvenze al nero a 1/3 e 2/3"

        # apertura e chiusura
        primo, ultimo = clip(ids[0]), clip(ids[-1])
        if r["apertura"] and primo.fade_in == 0:
            store.set_fades(primo.id, fade_in=min(r["apertura"], primo.duration / 3))
            fatto["apertura"] = r["apertura"]
        if r["chiusura"] and ultimo.fade_out == 0:
            store.set_fades(ultimo.id, fade_out=min(r["chiusura"], ultimo.duration / 3))
            fatto["chiusura"] = r["chiusura"]

        # accenti: un colpo sul primo istante di una clip ogni N
        if r["accenti"]:
            nome, ogni = r["accenti"]
            colpi = 0
            for i, cid in enumerate(ids):
                c = clip(cid)
                if i == 0 or i % ogni or any(e.type == nome for e in c.effects):
                    continue
                if nome == "shake":
                    params = {"amount": {"kf": [
                        {"t": 0, "v": 28},
                        {"t": round(min(0.45, c.duration), 3), "v": 0, "ease": "ease_out"}]},
                        "frequency": 9}
                else:
                    params = {"intensity": 0.18, "amount": 50, "seed": i}
                store.add_effect(cid, nome, params)
                colpi += 1
            fatto["accenti"] = f"{nome} su {colpi} clip"

        # musica che si muove
        if r["musica"]:
            fine_tl = clip(ids[-1]).end
            # la voce fuori campo non e' musica: abbassarla la copre
            from .allinea import e_traccia_voce
            musiche = [c.id for t in store.project.tracks
                       if t.kind == "audio" and not e_traccia_voce(t)
                       for c in t.clips if c.type == "media" and c.duration >= 8
                       and getattr(store.project.media_by_id(c.media), "folder", "") != "voice"]
            for mid in musiche:
                m = clip(mid)
                if kf.is_kf(m.audio.gain_db):
                    saltati.append(f"musica {mid}: gia' automatizzata")
                    continue
                durata = min(m.duration, max(2.0, fine_tl - m.start))
                base = float(kf.sample(m.audio.gain_db, 0, 0.0))
                store.set_audio(mid, gain_db=curva_musica(r["musica"], durata, base))
                fatto.setdefault("musica", []).append(f"{mid}: {r['musica']}")
            if not musiche:
                saltati.append("musica: nessuna traccia musicale lunga in timeline")

    return {"stile": stile_id, "applicato": fatto, "saltati": saltati,
            "da_fare": r["da_fare"],
            "controllo": review.ricchezza(store.project, r["attese"])}
