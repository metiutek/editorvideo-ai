"""Quando la voce dice cosa, in secondi di timeline.

Un video spiegato a voce si monta al contrario di un montaggio su musica:
**l'audio comanda, il video obbedisce**. Prima la voce, poi si misura quando
dice ogni frase, e solo dopo ogni animazione parte da quell'istante. Un tempo
scritto a occhio nel codice di una grafica va fuori sincrono appena la voce
cambia (un'altra ripresa, una velocita' diversa, una battuta in piu').

I tempi della trascrizione sono in secondi della *sorgente*: qui diventano
secondi della *timeline*, tenendo conto di attacco, velocita' e posizione
della clip. Senza faster-whisper, per le battute generate da ``generate_voice``
(il nome della clip e' il testo) le parole si distribuiscono sulla durata in
proporzione ai caratteri: una stima, segnata come tale.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from . import analyze
from .model import Clip

# nomi di traccia che vogliono dire "qui c'e' la voce"
_VOCE = re.compile(r"^(vo|v\.o\.|voice|voce|narr|dialog|speech|parlato)", re.I)


class AllineaError(ValueError):
    pass


def e_traccia_voce(track: Any) -> bool:
    return track.kind == "audio" and bool(_VOCE.match((track.name or track.id or "").strip()))


_UNITA = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
          "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_DECINE = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _in_lettere(n: int) -> list[str]:
    """Un intero in parole inglesi: il copione per il TTS scrive i numeri cosi',
    la trascrizione spesso li riporta in cifre ("$725 billion")."""
    if n < 20:
        return [_UNITA[n]]
    if n < 100:
        return [_DECINE[n // 10]] + (_in_lettere(n % 10) if n % 10 else [])
    if n < 1000:
        return [_UNITA[n // 100], "hundred"] + (_in_lettere(n % 100) if n % 100 else [])
    for valore, nome in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= valore:
            resto = n % valore
            return _in_lettere(n // valore) + [nome] + (_in_lettere(resto) if resto else [])
    return [str(n)]


def _norm(parola: str) -> list[str]:
    """Una parola in token confrontabili: minuscole, niente punteggiatura,
    cifre in lettere (inglesi), % come "percent"."""
    p = parola.lower().replace("’", "'").replace("'", "").replace("%", " percent")
    p = re.sub(r"(?<=\d),(?=\d{3})", "", p)   # 1,000 -> 1000
    out: list[str] = []
    for t in re.split(r"[^\w]+", p):
        if t:
            out += _in_lettere(int(t)) if t.isdigit() and len(t) < 13 else [t]
    return out


def _clip_scelte(store: Any, clips: list[str] | None, track: str | None) -> list[tuple[Any, Clip]]:
    p = store.project
    if clips:
        return [store.clip_or_die(cid) for cid in clips]
    if track:
        tracce = [store.track_or_die(track)]
    else:
        tracce = [t for t in p.tracks if e_traccia_voce(t)]
        if not tracce:
            raise AllineaError("no voice track (VO, voice...): pass track= or clips= with the voice")
    return [(t, c) for t in tracce for c in t.clips if c.type == "media"]


def _a_timeline(c: Clip, s: float) -> float | None:
    k = abs(c.speed or 1.0)
    span = c.duration * k
    if not (c.in_ - 0.05 <= s <= c.in_ + span + 0.05):
        return None
    d = (c.in_ + span - s) if c.reverse else (s - c.in_)
    return c.start + max(0.0, min(span, d)) / k


def _stima(c: Clip, testo: str) -> list[dict]:
    """Parole distribuite in proporzione ai caratteri sulla durata della clip."""
    parole = testo.split()
    if not parole:
        return []
    margine = min(0.12, c.duration * 0.05)
    a, b = c.start + margine, c.end - margine
    tot = sum(len(w) + 1 for w in parole)
    out, pos = [], 0
    for w in parole:
        t0 = a + (b - a) * pos / tot
        pos += len(w) + 1
        out.append({"w": w, "t": round(t0, 3), "e": round(a + (b - a) * pos / tot, 3)})
    return out


def parole(store: Any, clips: list[str] | None = None, track: str | None = None,
           model: str = "small", language: str | None = None) -> tuple[list[dict], bool]:
    """Le parole della voce in timeline, in ordine: [{w, t, e}], e se sono stimate."""
    out: list[dict] = []
    stimate = False
    for _t, c in _clip_scelte(store, clips, track):
        media = store.media_or_die(c.media)
        try:
            tr = analyze.transcribe(media.path, model, language)
        except analyze.AnalysisError as exc:
            if "not installed" not in str(exc) or not (c.name or "").strip():
                raise
            out += _stima(c, c.name)
            stimate = True
            continue
        for seg in tr["segments"]:
            for w in seg["words"]:
                t = _a_timeline(c, w["t"])
                e = _a_timeline(c, w["e"])
                if t is None or e is None:
                    continue
                out.append({"w": w["w"], "t": round(min(t, e), 3), "e": round(max(t, e), 3)})
    out.sort(key=lambda w: w["t"])
    return out, stimate


def trova(ws: list[dict], frase: str, dopo: float = 0.0) -> dict:
    """Il primo punto, non prima di ``dopo``, in cui la voce dice ``frase``."""
    toks: list[tuple[str, int]] = [(tok, i) for i, w in enumerate(ws) for tok in _norm(w["w"])]
    cerca = [t for p in frase.split() for t in _norm(p)]
    if not cerca or not toks:
        return {"phrase": frase, "t": None}
    n = len(cerca)
    validi = [j for j in range(len(toks)) if ws[toks[j][1]]["t"] >= dopo - 0.01]
    for j in validi:
        if [x for x, _ in toks[j:j + n]] == cerca:
            a, b = toks[j][1], toks[min(j + n, len(toks)) - 1][1]
            return {"phrase": frase, "t": ws[a]["t"], "end": ws[b]["e"]}
    # la trascrizione scrive "$725 billion" dove il copione dice "seven hundred
    # twenty-five billion": si prende la finestra che somiglia di piu'
    # Va la prima finestra quasi uguale (l'ordine del copione conta), altrimenti
    # la piu' simile di tutte.
    bersaglio = " ".join(cerca)
    meglio, dove = 0.0, None
    for j in validi:
        for m in (n - 2, n - 1, n, n + 1, n + 2):
            if m < 1 or j + m > len(toks):
                continue
            r = difflib.SequenceMatcher(None, bersaglio, " ".join(x for x, _ in toks[j:j + m])).ratio()
            if r > meglio + 0.001:
                meglio, dove = r, (j, j + m)
        if meglio >= 0.85:
            break
    if dove and meglio >= 0.55:
        a, b = toks[dove[0]][1], toks[dove[1] - 1][1]
        return {"phrase": frase, "t": ws[a]["t"], "end": ws[b]["e"], "approx": round(meglio, 2)}
    return {"phrase": frase, "t": None}


def frasi_da_parole(ws: list[dict], pausa: float = 0.35) -> list[list]:
    """Le parole raggruppate in frasi: [inizio, fine, testo]."""
    out: list[list] = []
    cur: list[dict] = []
    for w in ws:
        if cur and (w["t"] - cur[-1]["e"] > pausa or cur[-1]["w"].rstrip()[-1:] in ".?!:"):
            out.append([cur[0]["t"], cur[-1]["e"], " ".join(x["w"].strip() for x in cur)])
            cur = []
        cur.append(w)
    if cur:
        out.append([cur[0]["t"], cur[-1]["e"], " ".join(x["w"].strip() for x in cur)])
    return out


def tempi(store: Any, phrases: list | None = None, clips: list[str] | None = None,
          track: str | None = None, words: bool = False, model: str = "small",
          language: str | None = None) -> dict:
    """I tempi della voce in timeline.

    Con ``phrases`` (nell'ordine del copione) restituisce quando inizia e finisce
    ognuna: la ricerca riparte da dove ha trovato la precedente, cosi' una frase
    che compare due volte ("twenty-five billion") prende l'occorrenza giusta.
    Una voce puo' essere ``{"text", "after"}`` per forzare l'istante di partenza.
    Senza, restituisce le frasi dette con i loro tempi.
    """
    ws, stimate = parole(store, clips, track, model, language)
    if not ws:
        raise AllineaError("no speech found in the chosen clips")
    out: dict[str, Any] = {"duration": round(ws[-1]["e"], 3)}
    if stimate:
        out["estimated"] = ("faster-whisper is not installed: times are estimated from the "
                            "text length (pip install faster-whisper for exact times)")
    if phrases:
        trovate, dopo = [], 0.0
        for f in phrases:
            testo, da = (f.get("text", ""), f.get("after")) if isinstance(f, dict) else (str(f), None)
            r = trova(ws, testo, float(da) if da is not None else dopo)
            if r["t"] is not None:
                dopo = r["t"] + 0.01
            trovate.append(r)
        out["phrases"] = trovate
        mancanti = [r["phrase"] for r in trovate if r["t"] is None]
        if mancanti:
            out["missing"] = mancanti
    else:
        out["sentences"] = frasi_da_parole(ws)
    if words:
        out["words"] = [[w["t"], w["w"].strip()] for w in ws]
    return out


# Il metodo per i video raccontati da una voce. Sta qui e non in tre copie:
# lo leggono le istruzioni MCP, la chat con i modelli via API e Claude Code.
# Nasce dal confronto fra uno short venuto male (una pagina html unica per 40
# secondi, voce accelerata con set_speed, tempi scritti a occhio, cartelli di
# testo) e uno venuto bene (voce prima, tempi misurati, una scena per capitolo,
# metafore animate, sei giri di controllo sui fotogrammi).
METODO = """\
VIDEO RACCONTATI DA UNA VOCE (explainer, faceless, animazioni senza girato).
L'audio comanda, il video obbedisce:
1. Fatti: cerca e leggi le fonti; ogni numero ne ha una. Se le fonti non
   concordano non citare la cifra, di' la direzione ("earns billions, spends
   more"). Le stime restano stime ("about", "reportedly").
2. Copione per la voce: capitoli brevi, ognuno risponde a una domanda e passa la
   mano al successivo con un'altra ("Where does the money come from?"). Il numero
   piu' forte nei primi 2 secondi. Frasi corte, punteggiatura netta, numeri
   scritti in lettere.
3. Prima la voce (generate_voice, o il file dell'utente). Il ritmo si chiede al
   motore (style: "fast, punchy explainer", o speed): MAI set_speed sulla voce,
   rende la voce artificiale e sposta tutti i tempi.
4. Poi i tempi: speech_times con le frasi chiave del copione, in ordine. Ogni
   animazione, numero e stacco parte da quei secondi, nessun tempo a occhio. Se
   la voce cambia, si rileggono.
5. Le scene: una clip html per capitolo, con lo stacco sul tempo del capitolo
   (non una pagina sola per tutto il video), da un modello con {{segnaposto}}
   per i tempi (add_html vars). Dentro, metafore che raccontano il meccanismo:
   torri che crescono, tubi di monete, serbatoi che si svuotano, anelli che si
   chiudono. Oggetti che si muovono, non cartelli di testo. Un solo numero grande
   alla volta con 3-6 parole sotto. I valori guidano la geometria (altezze in
   proporzione ai dati). Un colore fisso per ogni soggetto per tutto il video.
   Profondita' (2.5D/isometrico, ombre, bagliori, parallasse), entrate con
   rimbalzo, camera che si muove, barra di avanzamento dei capitoli.
6. Controllo da contact sheet: preview_frame(t=[...]) sugli istanti di
   speech_times di ogni scena. Cerca testi sovrapposti, numeri illeggibili,
   oggetti tagliati dal bordo, animazioni fuori sincrono. Correggi e riguarda
   finche' e' pulito: piu' giri sono normali.
7. Suono: musica bassa sotto la voce (duck_music), un whoosh a ogni cambio di
   capitolo, sottotitoli con make_captions. La traccia della voce non e' musica:
   tienila a volume pieno.
"""
