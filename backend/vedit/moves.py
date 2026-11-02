"""Movimenti di camera: ricette a keyframe per una clip (spinta, panoramica, impatto...).

Uno stile (``stili.RICETTE``) conosce solo ``spinta`` e ``punch``; chi monta davvero sceglie
il movimento per quello che l'inquadratura deve dire. Ogni ricetta qui restituisce i
keyframe di ``x``, ``y``, ``scale`` e ``rotation`` della clip: niente di nuovo da
renderizzare, e ``set_transform`` resta l'unico punto in cui si scrive il documento.

Regole che valgono per tutte:

- una panoramica o un'inclinazione *entra* nell'immagine: la scala parte da quanto serve
  perche' i bordi non si vedano mai (il nero ai lati e' il difetto piu' comune);
- gli arrivi si fermano su una coda lunga (``ease_out_cubic``), gli spostamenti di camera
  vanno e vengono dolci (``ease_in_out_cubic``), le uscite accelerano (``ease_in_cubic``);
- il tremolio non usa ``random``: e' un hash di ``sin``, quindi stessa clip, stessi
  keyframe, stesso render.
"""

from __future__ import annotations

import math
from typing import Any, Callable

MIN_INTENSITA, MAX_INTENSITA = 0.1, 3.0
MAX_KEYFRAME = 240                      # un tremolio lungo non riempie il progetto di punti


def _kf(*punti: tuple) -> dict:
    """(t, v) o (t, v, ease): il blocco keyframe, con l'ease sul tratto che parte da li'."""
    out = []
    for p in punti:
        voce = {"t": round(float(p[0]), 3), "v": round(float(p[1]), 4)}
        if len(p) > 2 and p[2]:
            voce["ease"] = p[2]
        out.append(voce)
    return {"kf": out}


def _hash(i: int, k: int, seme: int) -> float:
    """Numero in [-1, 1) che dipende solo da (i, k, seme): il 'caso' del render."""
    x = math.sin(i * 12.9898 + k * 78.233 + seme * 37.719) * 43758.5453
    return 2.0 * (x - math.floor(x)) - 1.0


def _copre(gradi: float, w: int, h: int) -> float:
    """Scala minima perche' un fotogramma ruotato di ``gradi`` copra ancora il canvas."""
    a = math.radians(abs(gradi))
    return math.cos(a) + max(w / h, h / w) * math.sin(a)


# --------------------------------------------------------------------------
# ricette: (durata, w, h, k, bpm, seme) -> {campo: valore o blocco keyframe}
# --------------------------------------------------------------------------

_IO, _OUT, _IN = "ease_in_out_cubic", "ease_out_cubic", "ease_in_cubic"


def _push_in(d, w, h, k, bpm, seme):
    return {"scale": _kf((0, 1, _IO), (d, 1 + 0.12 * k))}


def _pull_out(d, w, h, k, bpm, seme):
    return {"scale": _kf((0, 1 + 0.12 * k, _IO), (d, 1))}


def _slow_push(d, w, h, k, bpm, seme):
    return {"scale": _kf((0, 1, _IO), (d, 1 + 0.045 * k))}


def _pan(d, w, h, k, verso):
    corsa = 0.05 * k * w
    return {"scale": round(1 + 2 * corsa / w, 4),
            "x": _kf((0, -verso * corsa, _IO), (d, verso * corsa))}


def _pan_left(d, w, h, k, bpm, seme):      # la camera gira a sinistra: l'immagine scorre a destra
    return _pan(d, w, h, k, 1)


def _pan_right(d, w, h, k, bpm, seme):
    return _pan(d, w, h, k, -1)


def _tilt(d, w, h, k, verso):
    corsa = 0.05 * k * h
    return {"scale": round(1 + 2 * corsa / h, 4),
            "y": _kf((0, -verso * corsa, _IO), (d, verso * corsa))}


def _tilt_up(d, w, h, k, bpm, seme):       # la camera alza lo sguardo: l'immagine scende
    return _tilt(d, w, h, k, 1)


def _tilt_down(d, w, h, k, bpm, seme):
    return _tilt(d, w, h, k, -1)


def _drift(d, w, h, k, bpm, seme):
    """Ken Burns: un lento ingrandimento con la deriva in diagonale."""
    z = 0.14 * k
    corsa_x, corsa_y = 0.15 * z * w, 0.15 * z * h       # dentro quanto la scala di partenza copre
    return {"scale": _kf((0, 1 + z * 0.35, _IO), (d, 1 + z)),
            "x": _kf((0, -corsa_x, _IO), (d, corsa_x)),
            "y": _kf((0, corsa_y, _IO), (d, -corsa_y))}


def _punch_in(d, w, h, k, bpm, seme):
    """Colpo d'ingrandimento a inizio clip: sul battito, poi tiene."""
    t = min(0.28, d * 0.4)
    return {"scale": _kf((0, 1, _OUT), (t, 1 + 0.18 * k))}


def _zoom_burst(d, w, h, k, bpm, seme):
    """Resta fermo e si lancia dentro l'immagine alla fine: per uno stacco in avanti."""
    t = min(0.45, d * 0.5)
    return {"scale": _kf((0, 1), (d - t, 1, _IN), (d, 1 + 0.4 * k))}


def _whip_pan(d, w, h, k, bpm, seme):
    """Entra di scatto da un lato e si assesta: la camera che arriva sul soggetto."""
    t = min(0.35, d * 0.5)
    corsa = 0.12 * k * w
    return {"scale": round(1 + 2 * corsa / w, 4), "x": _kf((0, corsa, _OUT), (t, 0))}


def _dutch_tilt(d, w, h, k, bpm, seme):
    gradi = 5.0 * k
    return {"scale": round(_copre(gradi, w, h) * 1.01, 4),
            "rotation": _kf((0, 0, _IO), (d, -gradi))}


def _sway(d, w, h, k, bpm, seme):
    """Dondolio lento, come una camera su una barca: x e rotazione sfasati."""
    n = max(4, min(MAX_KEYFRAME, int(d / 0.5) + 1))
    ax, ar = 0.012 * k * w, 0.6 * k
    xs, rs = [], []
    for i in range(n):
        t = d * i / (n - 1)
        fase = 2 * math.pi * t / 3.2
        xs.append((t, ax * math.sin(fase), _IO))
        rs.append((t, ar * math.sin(fase + math.pi / 2), _IO))
    return {"scale": round((1 + 2 * ax / w) * _copre(ar, w, h) * 1.01, 4), "x": _kf(*xs), "rotation": _kf(*rs)}


def _handheld(d, w, h, k, bpm, seme):
    """Camera a mano: spostamenti e rotazioni piccoli, a scatti irregolari ma ripetibili."""
    passo = max(0.18, d / MAX_KEYFRAME)
    n = max(2, int(d / passo) + 1)
    ax, ay, ar = 0.007 * k * w, 0.007 * k * h, 0.35 * k
    xs, ys, rs = [], [], []
    for i in range(n):
        t = min(d, i * passo)
        xs.append((t, ax * _hash(i, 1, seme), "ease_in_out"))
        ys.append((t, ay * _hash(i, 2, seme), "ease_in_out"))
        rs.append((t, ar * _hash(i, 3, seme), "ease_in_out"))
    sc = max(1 + 2 * ax / w, 1 + 2 * ay / h) * _copre(ar, w, h) * 1.01
    return {"scale": round(sc, 4), "x": _kf(*xs), "y": _kf(*ys), "rotation": _kf(*rs)}


def _impact_shake(d, w, h, k, bpm, seme):
    """Scossa che si smorza in mezzo secondo: per un colpo, un'esplosione, un bass drop."""
    t = min(0.6, d)
    n = max(4, int(t / 0.05) + 1)
    ax, ay, ar = 0.03 * k * w, 0.03 * k * h, 1.4 * k
    xs, ys, rs = [], [], []
    for i in range(n):
        tt = t * i / (n - 1)
        smorza = (1 - tt / t) ** 2
        xs.append((tt, ax * smorza * _hash(i, 1, seme)))
        ys.append((tt, ay * smorza * _hash(i, 2, seme)))
        rs.append((tt, ar * smorza * _hash(i, 3, seme)))
    sc = max(1 + 2 * ax / w, 1 + 2 * ay / h) * _copre(ar, w, h) * 1.01
    return {"scale": round(sc, 4), "x": _kf(*xs), "y": _kf(*ys), "rotation": _kf(*rs)}


def _beat_pulse(d, w, h, k, bpm, seme):
    """Un battito di scala su ogni colpo della musica (serve ``bpm``, da music_beats)."""
    if not bpm:
        raise ValueError("beat_pulse needs bpm: take it from music_beats")
    periodo = 60.0 / bpm
    if periodo < 0.2:
        raise ValueError("bpm too high for a pulse (at most 300)")
    ampiezza = 0.06 * k
    pt: list[tuple] = []
    n = int(d / periodo) + 1
    if n * 3 > MAX_KEYFRAME:
        raise ValueError("clip too long for a pulse on every beat: shorten the clip or use every second beat")
    for i in range(n):
        t = i * periodo
        if t > d:
            break
        pt.append((t, 1 + ampiezza, _OUT))
        if t + periodo * 0.85 < d:
            pt.append((t + periodo * 0.85, 1.0))
    if pt[-1][0] < d:
        pt.append((d, pt[-1][1]))
    return {"scale": _kf(*pt)}


MOSSE: dict[str, dict[str, Any]] = {
    "push_in": {"fn": _push_in, "gruppo": "push / pull",
                "descrizione": "Steady move toward the subject: attention, tension, a reveal."},
    "pull_out": {"fn": _pull_out, "gruppo": "push / pull",
                 "descrizione": "Backs away from the subject: context, aftermath, a closing beat."},
    "slow_push": {"fn": _slow_push, "gruppo": "push / pull",
                  "descrizione": "Barely-there creep that keeps a long hold alive (interviews, documentary)."},
    "pan_left": {"fn": _pan_left, "gruppo": "pan / tilt",
                 "descrizione": "Camera turns left (the image slides right). Follows or reveals; keeps edges covered."},
    "pan_right": {"fn": _pan_right, "gruppo": "pan / tilt",
                  "descrizione": "Camera turns right (the image slides left)."},
    "tilt_up": {"fn": _tilt_up, "gruppo": "pan / tilt",
                "descrizione": "Camera looks up (the image slides down): scale, awe, a tall subject."},
    "tilt_down": {"fn": _tilt_down, "gruppo": "pan / tilt",
                  "descrizione": "Camera looks down (the image slides up)."},
    "drift": {"fn": _drift, "gruppo": "pan / tilt",
              "descrizione": "Ken Burns: slow zoom with a diagonal drift. Best for still photos and maps."},
    "punch_in": {"fn": _punch_in, "gruppo": "impact",
                 "descrizione": "Quick zoom at the start of the clip, then holds: lands on a beat or a cut."},
    "zoom_burst": {"fn": _zoom_burst, "gruppo": "impact",
                   "descrizione": "Holds, then lunges into the image at the end: a cut that goes forward."},
    "whip_pan": {"fn": _whip_pan, "gruppo": "impact",
                 "descrizione": "Arrives sideways in a snap and settles: pair it with a blur effect for the smear."},
    "impact_shake": {"fn": _impact_shake, "gruppo": "impact",
                     "descrizione": "Half a second of decaying shake: a hit, a bang, a bass drop."},
    "beat_pulse": {"fn": _beat_pulse, "gruppo": "rhythm",
                   "descrizione": "Scale pulse on every beat of the music. Needs bpm (from music_beats)."},
    "handheld": {"fn": _handheld, "gruppo": "organic",
                 "descrizione": "Hand-held camera: small irregular shifts and tilts. Reads as real, raw, present."},
    "sway": {"fn": _sway, "gruppo": "organic",
             "descrizione": "Slow rocking, like a camera on a boat: dreamy, floaty, uneasy."},
    "dutch_tilt": {"fn": _dutch_tilt, "gruppo": "organic",
                   "descrizione": "Slowly tips the horizon (up to 5 degrees): something is wrong."},
}


def elenco() -> list[dict]:
    return [{"id": n, "gruppo": m["gruppo"], "descrizione": m["descrizione"]} for n, m in MOSSE.items()]


def costruisci(nome: str, durata: float, larghezza: int, altezza: int, intensita: float = 1.0,
               bpm: float | None = None, seme: int = 1) -> dict[str, Any]:
    """I valori per ``set_transform`` di un movimento: tutti e quattro i campi, quelli che
    il movimento non usa tornano al valore neutro (cosi' non resta un vecchio spostamento
    sotto un ingrandimento che non lo copre)."""
    if nome not in MOSSE:
        raise ValueError(f"unknown move {nome!r}; allowed: {', '.join(MOSSE)}")
    if not MIN_INTENSITA <= float(intensita) <= MAX_INTENSITA:
        raise ValueError(f"intensity out of range ({intensita}): between {MIN_INTENSITA} and {MAX_INTENSITA}")
    if float(durata) < 0.2:
        raise ValueError("the clip is too short for a camera move (under 0.2 s)")
    if bpm is not None and not 40 <= float(bpm) <= 300:
        raise ValueError(f"bpm out of range ({bpm}): between 40 and 300")
    r = MOSSE[nome]["fn"](float(durata), int(larghezza), int(altezza), float(intensita),
                          float(bpm) if bpm else None, int(seme))
    return {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, **r}
