"""Registro degli effetti: dichiarazione parametri + costruzione filtri ffmpeg.

Ogni effetto e' una funzione pura ``(params, ctx) -> [stringhe filtro]``.
I parametri marcati ``anim=True`` accettano keyframe, perche' il filtro ffmpeg
corrispondente rivaluta l'espressione a ogni frame; gli altri vengono
campionati a t=0.

Aggiungere un effetto = aggiungere una voce a EFFECTS. Il server MCP e la UI
si auto-descrivono da questo registro, non serve toccare altro.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from . import keyframes as kf


@dataclass
class Ctx:
    """Contesto di compilazione di una catena di effetti."""

    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    sample_rate: int = 48000
    tvar: str = "t"  # espressione del tempo locale alla clip
    duration: float = 0.0
    # rapporto tra risoluzione di render e risoluzione del progetto: in preview
    # vale <1 e i parametri espressi in pixel vanno riscalati di conseguenza
    scale: float = 1.0
    # tempo della clip al primo fotogramma (>0 nei segmenti di anteprima): serve
    # ai filtri che contano i fotogrammi invece di leggere t
    offset: float = 0.0
    extra: dict = field(default_factory=dict)  # es. file .trf per la stabilizzazione
    _counter: list = field(default_factory=lambda: [0])

    def uid(self, prefix: str) -> str:
        """Etichetta univoca per gli effetti che aprono sotto-grafi."""
        self._counter[0] += 1
        return f"{prefix}{self._counter[0]}"


@dataclass
class Param:
    name: str
    default: Any = 0.0
    kind: str = "number"  # number | bool | string | color | file | enum
    min: float | None = None
    max: float | None = None
    anim: bool = False
    choices: tuple[str, ...] = ()
    desc: str = ""


@dataclass
class EffectDef:
    name: str
    kind: str  # video | audio
    label: str
    params: tuple[Param, ...]
    build: Callable[[dict, Ctx], list[str]]
    desc: str = ""

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------


def esc_str(s: str) -> str:
    """Escape di un valore stringa dentro un argomento di filtro."""
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


def esc_path(p: str) -> str:
    """Path Windows dentro un filtro: slash avanti e due punti protetti."""
    return str(p).replace("\\", "/").replace(":", "\\:")


def quoted(expr: str) -> str:
    """Espressione come argomento di filtro (virgole/duepunti al sicuro)."""
    return "'" + str(expr).replace("'", "") + "'"


def _spec(effect: str) -> EffectDef:
    if effect not in EFFECTS:
        raise KeyError(f"effetto sconosciuto: {effect!r}")
    return EFFECTS[effect]


def val(params: dict, name: str, default: Any = 0.0, t: float = 0.0) -> Any:
    """Valore statico (keyframe campionati a ``t``)."""
    v = params.get(name, default)
    if kf.is_kf(v):
        return kf.sample(v, t)
    return v


def num(params: dict, name: str, default: float = 0.0) -> float:
    try:
        return float(val(params, name, default))
    except (TypeError, ValueError):
        return float(default)


def anim(params: dict, name: str, default: float, ctx: Ctx) -> str:
    """Espressione animabile (gia' pronta per essere messa tra apici)."""
    return kf.expr(params.get(name, default), ctx.tvar, default)


def flag(params: dict, name: str, default: bool = False) -> bool:
    v = params.get(name, default)
    return bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")


def fnum(x: float) -> str:
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return s or "0"


# --------------------------------------------------------------------------
# effetti video
# --------------------------------------------------------------------------


def _f_color(p: dict, c: Ctx) -> list[str]:
    args = [
        f"brightness={quoted(anim(p, 'brightness', 0.0, c))}",
        f"contrast={quoted(anim(p, 'contrast', 1.0, c))}",
        f"saturation={quoted(anim(p, 'saturation', 1.0, c))}",
        f"gamma={quoted(anim(p, 'gamma', 1.0, c))}",
        "eval=frame",
    ]
    return ["eq=" + ":".join(args)]


def _f_colorbalance(p: dict, c: Ctx) -> list[str]:
    """Ombre, mezzitoni e luci per canale: lift, gamma e gain del color grading.

    Non usa il filtro colorbalance di ffmpeg: i suoi mezzitoni sono
    imprevedibili (+0.5 di rosso trasforma un grigio scuro in rosso pieno e
    lascia identico un grigio medio). Qui per ogni canale, con x fra 0 e 1:

        out = (x * gain + lift * (1 - x)) ^ (1 / gamma)

    lift sposta soprattutto le ombre, gain soprattutto le luci, gamma i toni
    di mezzo; a zero l'immagine resta identica.
    """
    if all(abs(num(p, f"{ch}{z}", 0.0)) < 1e-6 for ch in "rgb" for z in "smh"):
        return []
    args = []
    for ch in "rgb":
        lift = num(p, f"{ch}s", 0.0) * 0.3
        gamma = 1.0 + num(p, f"{ch}m", 0.0) * 0.6
        gain = 1.0 + num(p, f"{ch}h", 0.0) * 0.5
        x = "(val/255)"
        espr = (f"255*pow(clip({x}*{fnum(gain)}+{fnum(lift)}*(1-{x}),0,1),"
                f"{fnum(1.0 / max(gamma, 0.05))})")
        args.append(f"{ch}='clip({espr},0,255)'")
    return ["lutrgb=" + ":".join(args)]


def _f_temperature(p: dict, c: Ctx) -> list[str]:
    return [f"colortemperature=temperature={fnum(num(p, 'temperature', 6500))}:mix={fnum(num(p, 'mix', 1.0))}"]


def _f_curves(p: dict, c: Ctx) -> list[str]:
    preset = str(val(p, "preset", "none"))
    if preset and preset != "none":
        return [f"curves=preset={preset}"]
    master = str(val(p, "master", "")).strip()
    return [f"curves=master={quoted(master)}"] if master else []


def _f_lut(p: dict, c: Ctx) -> list[str]:
    path = str(val(p, "file", "")).strip()
    if not path:
        return []
    return [f"lut3d=file='{esc_path(path)}':interp={val(p, 'interp', 'tetrahedral')}"]


def _f_colormatch(p: dict, c: Ctx) -> list[str]:
    """Guadagno e offset per canale: la correzione lineare del color transfer.

    Si usa ``lutrgb`` con un'espressione invece di ``colorlevels`` perche'
    quest'ultimo accetta punti di uscita solo tra 0 e 1: un guadagno sotto 1 o
    un offset negativo non sarebbero rappresentabili.
    """
    args = []
    for ch in "rgb":
        gain = fnum(num(p, f"{ch}_gain", 1.0))
        off = num(p, f"{ch}_off", 0.0) * 255.0
        segno = "+" if off >= 0 else "-"
        args.append(f"{ch}='clip(val*{gain}{segno}{fnum(abs(off))},0,255)'")
    return ["lutrgb=" + ":".join(args)]


def _f_blur(p: dict, c: Ctx) -> list[str]:
    return [f"gblur=sigma={fnum(num(p, 'sigma', 8) * c.scale)}:steps={int(num(p, 'steps', 1))}"]


def _f_sharpen(p: dict, c: Ctx) -> list[str]:
    a = fnum(num(p, "amount", 1.0))
    return [f"unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount={a}:chroma_amount={fnum(num(p, 'chroma', 0.0))}"]


def _f_glow(p: dict, c: Ctx) -> list[str]:
    """Sotto-grafo: split -> ramo sfocato -> blend screen.

    Restituisce un blocco con ``;`` interni: resta valido perche' il primo
    filtro riceve dalla virgola precedente e l'ultimo non ha etichetta di
    uscita, quindi la catena prosegue normalmente.
    """
    sigma = fnum(num(p, "sigma", 12) * c.scale)
    amount = fnum(num(p, "amount", 0.5))
    a, b, bb = c.uid("glwa"), c.uid("glwb"), c.uid("glwc")
    return [
        f"split[{a}][{b}];[{b}]gblur=sigma={sigma}[{bb}];"
        f"[{a}][{bb}]blend=all_mode=screen:all_opacity={amount}"
    ]


def _f_vignette(p: dict, c: Ctx) -> list[str]:
    angle = fnum(num(p, "angle", 0.8))
    return [f"vignette=angle={angle}:mode={val(p, 'mode', 'forward')}"]


def _f_grain(p: dict, c: Ctx) -> list[str]:
    return [f"noise=alls={int(num(p, 'strength', 12))}:allf=t+u"]


def _f_denoise(p: dict, c: Ctx) -> list[str]:
    s = num(p, "strength", 4)
    return [f"hqdn3d={fnum(s)}:{fnum(s * 0.75)}:{fnum(s * 1.5)}:{fnum(s * 1.5)}"]


def _f_chromakey(p: dict, c: Ctx) -> list[str]:
    color = str(val(p, "color", "green"))
    out = [
        "format=yuva420p",
        f"chromakey=color={esc_str(color)}:similarity={fnum(num(p, 'similarity', 0.20))}"
        f":blend={fnum(num(p, 'blend', 0.05))}",
    ]
    if flag(p, "despill", True):
        out.append(f"chromanr=thres={fnum(num(p, 'despill_amount', 20))}")
    return out


def _f_crop(p: dict, c: Ctx) -> list[str]:
    """Ritaglia e riporta al canvas (zona tagliata trasparente)."""
    w = int(num(p, "w", c.width) * c.scale)
    h = int(num(p, "h", c.height) * c.scale)
    x = int(num(p, "x", 0) * c.scale)
    y = int(num(p, "y", 0) * c.scale)
    w = max(2, min(w, c.width))
    h = max(2, min(h, c.height))
    return [
        f"crop={w}:{h}:{x}:{y}",
        "format=yuva420p",
        f"pad={c.width}:{c.height}:{x}:{y}:color=black@0",
    ]


def _f_pixelate(p: dict, c: Ctx) -> list[str]:
    n = max(2, int(num(p, "size", 16) * c.scale))
    return [
        f"scale=iw/{n}:ih/{n}:flags=neighbor",
        f"scale={c.width}:{c.height}:flags=neighbor",
    ]


def parse_ranges(s: Any) -> list[tuple[float, float]]:
    """``"1.2-1.8;4-4.5"`` -> [(1.2, 1.8), (4.0, 4.5)]. Ordinati e senza vuoti."""
    out: list[tuple[float, float]] = []
    for chunk in str(s or "").replace(",", ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        a, _, b = chunk.partition("-")
        try:
            t0, t1 = float(a), float(b)
        except ValueError:
            continue
        if t1 > t0:
            out.append((t0, t1))
    return sorted(out)


def enable_expr(p: dict, c: Ctx) -> str:
    """``:enable='...'`` per gli intervalli dichiarati, stringa vuota se sempre."""
    r = parse_ranges(val(p, "ranges", ""))
    if not r:
        return ""
    cond = "+".join(f"between({c.tvar},{fnum(a)},{fnum(b)})" for a, b in r)
    return f":enable='{cond}'"


def _px(expr: str, c: Ctx) -> str:
    """Espressione in pixel di progetto -> pixel di render (preview ridotta)."""
    return expr if abs(c.scale - 1.0) < 1e-6 else f"(({expr})*{fnum(c.scale)})"


def _box(p: dict, c: Ctx) -> tuple[int, int, str, str]:
    """Rettangolo della maschera, sempre dentro il fotogramma.

    Il ritaglio non puo' eccedere il canvas (ffmpeg rifiuta un crop piu' grande
    dell'ingresso) e nemmeno uscirne muovendosi: x/y sono animabili, quindi il
    limite va messo nell'espressione, non nel valore.
    """
    w = max(2, min(int(num(p, "w", 300) * c.scale) // 2 * 2, c.width))
    h = max(2, min(int(num(p, "h", 300) * c.scale) // 2 * 2, c.height))
    x = f"min(max({_px(anim(p, 'x', 0, c), c)},0),{c.width - w})"
    y = f"min(max({_px(anim(p, 'y', 0, c), c)},0),{c.height - h})"
    return w, h, x, y


def _f_mask_blur(p: dict, c: Ctx) -> list[str]:
    """Sfoca solo un rettangolo: volto, targa, schermo, documento.

    x/y sono animabili, quindi la maschera segue il soggetto con i keyframe.
    """
    w, h, x, y = _box(p, c)
    sigma = fnum(max(0.1, num(p, "sigma", 20) * c.scale))
    a, b, m = c.uid("mka"), c.uid("mkb"), c.uid("mkm")
    return [
        f"split[{a}][{b}];"
        f"[{b}]crop=w={w}:h={h}:x='{x}':y='{y}',gblur=sigma={sigma}:steps=2[{m}];"
        f"[{a}][{m}]overlay=x='{x}':y='{y}'{enable_expr(p, c)}"
    ]


def _f_mask_pixelate(p: dict, c: Ctx) -> list[str]:
    """Come mask_blur ma a mosaico: censura riconoscibile come tale."""
    w, h, x, y = _box(p, c)
    n = max(2, int(num(p, "size", 16) * c.scale))
    a, b, m = c.uid("mpa"), c.uid("mpb"), c.uid("mpm")
    return [
        f"split[{a}][{b}];"
        f"[{b}]crop=w={w}:h={h}:x='{x}':y='{y}',"
        f"scale=iw/{n}:ih/{n}:flags=neighbor,scale={w}:{h}:flags=neighbor[{m}];"
        f"[{a}][{m}]overlay=x='{x}':y='{y}'{enable_expr(p, c)}"
    ]


def _f_mask_box(p: dict, c: Ctx) -> list[str]:
    """Rettangolo pieno: la censura piu' netta, o una barra grafica."""
    w, h, x, y = _box(p, c)
    color = esc_str(str(val(p, "color", "black")))
    alpha = fnum(max(0.0, min(1.0, num(p, "opacity", 1.0))))
    return [
        f"drawbox=x='{x}':y='{y}':w={w}:h={h}:color={color}@{alpha}:t=fill"
        + enable_expr(p, c)
    ]


def _f_subtitles(p: dict, c: Ctx) -> list[str]:
    """Imprime un file di sottotitoli (.ass, .srt, .vtt) nell'immagine.

    Con .ass lo stile e il karaoke arrivano dal file; con .srt si puo' forzare
    l'aspetto con ``force_style``. I tempi del file sono relativi alla clip.
    """
    path = str(val(p, "file", "")).strip()
    if not path:
        return []
    args = [f"filename='{esc_path(path)}'"]
    forza = str(val(p, "force_style", "")).strip()
    if forza:
        args.append(f"force_style='{esc_str(forza)}'")
    if abs(c.scale - 1.0) > 1e-6:
        # in preview il fotogramma e' piu' piccolo: senza questo i sottotitoli
        # verrebbero disegnati alla dimensione del progetto e uscirebbero
        args.append(f"original_size={int(c.width / c.scale)}x{int(c.height / c.scale)}")
    return ["subtitles=" + ":".join(args)]


def _f_mirror(p: dict, c: Ctx) -> list[str]:
    out = []
    if flag(p, "horizontal", True):
        out.append("hflip")
    if flag(p, "vertical", False):
        out.append("vflip")
    return out


def _f_stabilize(p: dict, c: Ctx) -> list[str]:
    """Usa il file .trf se l'analisi e' gia' stata fatta, altrimenti deshake."""
    trf = c.extra.get("trf")
    if trf:
        return [
            f"vidstabtransform=input='{esc_path(trf)}':smoothing={int(num(p, 'smoothing', 15))}"
            f":zoom={fnum(num(p, 'zoom', 0))}:optzoom=1:interpol=bilinear",
            "unsharp=5:5:0.8:3:3:0.4",
        ]
    return ["deshake=rx=32:ry=32:edge=mirror"]


def _f_fps_blend(p: dict, c: Ctx) -> list[str]:
    """Motion blur/interpolazione per slow motion morbido."""
    mode = str(val(p, "mode", "blend"))
    if mode == "interpolate":
        return [f"minterpolate=fps={fnum(c.fps)}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"]
    return [f"tmix=frames={int(num(p, 'frames', 3))}:weights='1 1 1'"]


def _f_exposure(p: dict, c: Ctx) -> list[str]:
    """Esposizione in stop, come in fotografia: +1 raddoppia la luce."""
    return [f"exposure=exposure={fnum(num(p, 'exposure', 0.0))}:black={fnum(num(p, 'black', 0.0))}"]


def _f_vibrance(p: dict, c: Ctx) -> list[str]:
    """Saturazione intelligente: spinge i colori spenti, risparmia quelli gia' carichi e la pelle."""
    return [f"vibrance=intensity={fnum(num(p, 'intensity', 0.3))}"]


def _f_whitebalance(p: dict, c: Ctx) -> list[str]:
    """Bilanciamento del bianco: temperatura (blu-arancio) e tinta (verde-magenta).

    colortemperature simula la luce di quella temperatura: sotto 6500 K
    l'immagine si scalda (arancio), sopra si raffredda (blu). La tinta sposta
    i mezzitoni: positiva verso il magenta, negativa verso il verde.
    """
    out = []
    k = num(p, "temperature", 6500)
    if abs(k - 6500) > 1:
        out.append(f"colortemperature=temperature={fnum(k)}")
    tinta = num(p, "tint", 0.0)
    if abs(tinta) > 1e-6:
        # magenta = piu' rosso e blu, meno verde; verde il contrario
        out.append(f"colorchannelmixer=rr={fnum(1 + tinta * 0.1)}:gg={fnum(1 - tinta * 0.2)}"
                   f":bb={fnum(1 + tinta * 0.1)}")
    return out


def _f_autowhite(p: dict, c: Ctx) -> list[str]:
    """Bilanciamento automatico: in media la scena dev'essere grigia (gray world)."""
    return ["format=gbrpf32le", "grayworld"]


def _f_hue(p: dict, c: Ctx) -> list[str]:
    return [f"hue=h={quoted(anim(p, 'hue', 0.0, c))}"]


_COLORI = {"rossi": "r", "gialli": "y", "verdi": "g", "ciano": "c", "blu": "b",
           "magenta": "m", "tutti": "a"}


def _f_hsl(p: dict, c: Ctx) -> list[str]:
    """Correzione secondaria: tocca una sola famiglia di colori (il cielo, l'erba, la pelle)."""
    colori = _COLORI.get(str(val(p, "colors", "blu")), "b")
    return [
        f"huesaturation=hue={fnum(num(p, 'hue', 0.0))}:saturation={fnum(num(p, 'saturation', 0.0))}"
        f":intensity={fnum(num(p, 'brightness', 0.0))}:colors={colori}"
        f":strength={fnum(num(p, 'softness', 5.0))}"
    ]


def _f_levels(p: dict, c: Ctx) -> list[str]:
    """Livelli: punto del nero e del bianco in ingresso e in uscita."""
    bi, wi = num(p, "black_in", 0.0), num(p, "white_in", 1.0)
    bo, wo = num(p, "black_out", 0.0), num(p, "white_out", 1.0)
    args = []
    for ch in "rgb":
        args += [f"{ch}imin={fnum(bi)}", f"{ch}imax={fnum(wi)}",
                 f"{ch}omin={fnum(bo)}", f"{ch}omax={fnum(wo)}"]
    return ["colorlevels=" + ":".join(args)]


# --------------------------------------------------------------------------
# effetti speciali: distorsioni, glitch, 3D, scontorni
# --------------------------------------------------------------------------


def _hash(x: str) -> str:
    """Pseudo-casuale in 0..1 da un'espressione: frac(sin(x)*43758.5453).

    Non si usa random() di ffmpeg: il render e' una funzione pura del progetto,
    e lo stesso glitch deve cadere sugli stessi fotogrammi a ogni render e
    nell'anteprima.
    """
    v = f"sin({x})*43758.5453"
    return f"(({v})-floor({v}))"


def _geq_rgba(sx: str, sy: str) -> list[str]:
    """Rimappa ogni pixel prendendolo da (sx, sy): la base di ogni distorsione.

    In RGB con alpha, cosi' una clip gia' scontornata resta scontornata; le
    coordinate fuori dall'immagine vengono limitate al bordo da geq stesso.
    """
    return [
        "format=gbrap",
        f"geq=r='r({sx},{sy})':g='g({sx},{sy})':b='b({sx},{sy})':a='alpha({sx},{sy})'",
    ]


def _f_rgb_split(p: dict, c: Ctx) -> list[str]:
    """Aberrazione cromatica: rosso e blu scivolano in direzioni opposte."""
    a = int(round(num(p, "amount", 6) * c.scale))
    if a == 0:
        return []
    ang = math.radians(num(p, "angle", 0.0))
    dx, dy = int(round(a * math.cos(ang))), int(round(a * math.sin(ang)))
    dx, dy = max(-255, min(255, dx)), max(-255, min(255, dy))
    return [f"rgbashift=rh={-dx}:rv={-dy}:bh={dx}:bv={dy}:edge=smear"]


def _f_glitch(p: dict, c: Ctx) -> list[str]:
    """Disturbo digitale a raffiche: fasce che scivolano e canali che si separano.

    Il tempo e' diviso in passi (``rate`` al secondo); per ogni passo un hash
    decide se c'e' una raffica (probabilita' ``intensity``) e, dentro la
    raffica, quali fasce orizzontali spostare e di quanto. Fuori dalle raffiche
    l'immagine passa intatta: ``enable`` spegne i filtri e geq non costa nulla.
    """
    inten = max(0.0, min(1.0, num(p, "intensity", 0.3)))
    if inten <= 0:
        return []
    amount = num(p, "amount", 40) * c.scale
    rate = max(1.0, num(p, "rate", 12))
    band = max(2.0, num(p, "band", 24) * c.scale)
    seed = num(p, "seed", 1)

    def raffica(tv: str) -> str:
        return f"lt({_hash(f'floor({tv}*{fnum(rate)})*91.345+{fnum(seed)}*7.13')},{fnum(inten)})"

    fascia = f"floor(Y/{fnum(band)})"
    passo = f"floor(T*{fnum(rate)})"
    h1 = _hash(f"{fascia}*12.9898+{passo}*78.233+{fnum(seed)}")
    h2 = _hash(f"{fascia}*4.1414+{passo}*3.7719+{fnum(seed)}")
    dx = f"gt({h1},0.72)*({h2}*2-1)*{fnum(amount)}"
    en = f":enable='{raffica('t')}'"
    split = max(1, int(round(amount * 0.25)))
    return [
        "format=gbrap",
        f"geq=r='r(X+{dx},Y)':g='g(X+{dx},Y)':b='b(X+{dx},Y)':a='alpha(X+{dx},Y)'{en}",
        f"rgbashift=rh={-min(255, split)}:bh={min(255, split)}{en}",
    ]


def _f_warp(p: dict, c: Ctx) -> list[str]:
    """Distorsioni geometriche: onda, increspatura, vortice, rigonfiamento.

    Tutte rimappano i pixel con geq (piu' lento dei filtri dedicati, ma ffmpeg
    non ha un warp generico). ``amount`` e' animabile: con i keyframe l'onda
    arriva e se ne va invece di restare accesa per tutta la clip.
    """
    mode = str(val(p, "mode", "wave"))
    amt = f"({kf.expr(p.get('amount', 20), 'T', 20)})"
    k = fnum(c.scale)
    lam = fnum(max(2.0, num(p, "wavelength", 120) * c.scale))
    spd = fnum(num(p, "speed", 1.0))
    cx = f"(W*{fnum(num(p, 'cx', 0.5))})"
    cy = f"(H*{fnum(num(p, 'cy', 0.5))})"
    r = f"hypot(X-{cx},Y-{cy})"
    rad = f"(hypot(W,H)*{fnum(max(0.01, num(p, 'radius', 0.5)))})"
    if mode == "wave":
        d = f"{amt}*{k}*sin(2*PI*(Y/{lam}+T*{spd}))"
        return _geq_rgba(f"X+{d}", "Y")
    if mode == "ripple":
        d = f"{amt}*{k}*sin(2*PI*({r}/{lam}-T*{spd}))/max({r},1)"
        return _geq_rgba(f"X+(X-{cx})*{d}", f"Y+(Y-{cy})*{d}")
    if mode == "swirl":
        # angolo in gradi al centro, che si spegne al bordo del raggio
        a = f"({amt}*PI/180*pow(max(0,1-{r}/{rad}),2))"
        return _geq_rgba(f"{cx}+(X-{cx})*cos({a})-(Y-{cy})*sin({a})",
                         f"{cy}+(X-{cx})*sin({a})+(Y-{cy})*cos({a})")
    # bulge: amount positivo gonfia il centro, negativo lo risucchia
    f = f"if(lt({r},{rad}),pow({r}/{rad},{amt}/100),1)"
    return _geq_rgba(f"{cx}+(X-{cx})*{f}", f"{cy}+(Y-{cy})*{f}")


def _f_lens(p: dict, c: Ctx) -> list[str]:
    """Distorsione dell'obiettivo: barile (k1 > 0, fisheye) o cuscino (k1 < 0)."""
    k1, k2 = num(p, "k1", 0.3), num(p, "k2", 0.0)
    if abs(k1) < 1e-6 and abs(k2) < 1e-6:
        return []
    # lenscorrection corregge: per *ottenere* il barile il segno va invertito
    return ["format=yuva420p",
            f"lenscorrection=k1={fnum(-k1)}:k2={fnum(-k2)}:i=bilinear:fc=black@0"]


def _f_shake(p: dict, c: Ctx) -> list[str]:
    """Camera a mano o colpo: l'inquadratura trema senza mai mostrare i bordi.

    Si ritaglia un margine pari all'ampiezza massima e si sposta il ritaglio
    con una somma di sinusoidi a frequenze non multiple (rumore liscio e
    ripetibile); poi si riporta alla dimensione del canvas.
    """
    a_max = max(1, int(num(p, "amount", 12) * c.scale))
    if 2 * a_max >= min(c.width, c.height) // 2:
        a_max = min(c.width, c.height) // 4
    amt = kf.expr(p.get("amount", 12), c.tvar, 12)
    a = f"(min({amt},{a_max / max(c.scale, 1e-6):.6f})*{fnum(c.scale)})"
    f = fnum(max(0.1, num(p, "frequency", 6)))
    tv = c.tvar

    def rumore(fase: float) -> str:
        return (f"(0.6*sin(2*PI*{f}*{tv}+{fase})+0.3*sin(2*PI*{f}*2.31*{tv}+{fase * 1.7 + 1.3})"
                f"+0.1*sin(2*PI*{f}*5.13*{tv}+{fase * 2.9 + 2.1}))")

    w, h = c.width - 2 * a_max, c.height - 2 * a_max
    w -= w % 2
    h -= h % 2
    return [
        f"crop=w={w}:h={h}:x='{a_max}+{a}*{rumore(0.0)}':y='{a_max}+{a}*{rumore(4.7)}'",
        f"scale={c.width}:{c.height}:flags=bicubic",
    ]


def _f_tilt3d(p: dict, c: Ctx) -> list[str]:
    """La clip come una carta nello spazio: rotazione attorno agli assi X e Y.

    I quattro angoli vengono proiettati con una prospettiva vera (distanza
    focale ``depth`` volte la larghezza) e passati a ``perspective``; fuori
    dalla carta resta trasparente, quindi sotto si vede la traccia inferiore.
    yaw e pitch sono animabili: un giro su se stessa e' un keyframe da 0 a 360.
    """
    # perspective non conosce t: il tempo si ricava dal numero di fotogramma
    tv = f"(in/{fnum(c.fps)}+{fnum(c.offset)})"
    yaw = f"(({kf.expr(p.get('yaw', 25), tv, 25)})*PI/180)"
    pitch = f"(({kf.expr(p.get('pitch', 0), tv, 0)})*PI/180)"
    W, H = c.width + 4, c.height + 4
    foc = fnum(max(0.3, num(p, "depth", 2.0)) * W)
    angoli = []
    for (u, v) in ((-W / 2, -H / 2), (W / 2, -H / 2), (-W / 2, H / 2), (W / 2, H / 2)):
        x1 = f"({fnum(u)}*cos({yaw}))"
        z1 = f"({fnum(u)}*sin({yaw}))"
        y2 = f"({fnum(v)}*cos({pitch})-{z1}*sin({pitch}))"
        z2 = f"({fnum(v)}*sin({pitch})+{z1}*cos({pitch}))"
        s = f"({foc}/max({foc}+{z2},1))"
        angoli.append((f"{fnum(W / 2)}+{x1}*{s}", f"{fnum(H / 2)}+{y2}*{s}"))
    args = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(angoli))
    # il bordo trasparente evita che perspective stiri i pixel del contorno
    return [
        "format=yuva420p",
        f"pad={W}:{H}:2:2:color=black@0",
        f"perspective={args}:sense=destination:eval=frame:interpolation=linear",
        f"crop={c.width}:{c.height}:2:2",
    ]


def _f_sky_key(p: dict, c: Ctx) -> list[str]:
    """Rende trasparente il cielo: sotto, su un'altra traccia, va il cielo nuovo.

    Chiave di colore limitata alla parte alta del fotogramma: sotto
    ``horizon`` (frazione dell'altezza) niente diventa trasparente, cosi'
    un'auto blu o un lago non spariscono insieme al cielo. ``feather`` sfuma
    il confine per non vedere la linea.
    """
    color = esc_str(str(val(p, "color", "#7fb0e0")))
    oriz = max(0.05, min(1.0, num(p, "horizon", 0.6)))
    sfuma = max(1.0, num(p, "feather", 0.08) * c.height)
    a = f"max(alpha(X,Y),255*clip((Y-H*{fnum(oriz)})/{fnum(sfuma)}+1,0,1))"
    return [
        "format=yuva420p",
        f"colorkey=color={color}:similarity={fnum(num(p, 'similarity', 0.3))}"
        f":blend={fnum(num(p, 'blend', 0.15))}",
        f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='{a}'",
    ]


def _f_remove_object(p: dict, c: Ctx) -> list[str]:
    """Cancella un oggetto ricostruendo il rettangolo dai pixel attorno.

    Funziona bene su loghi, scritte, cavi, piccoli oggetti su sfondi
    uniformi; su sfondi ricchi si vede una macchia morbida. x/y animabili per
    seguire un oggetto che si muove (track_mask calcola i keyframe).
    """
    w, h, x, y = _box(p, c)
    # delogo vuole il rettangolo strettamente dentro il fotogramma
    w = min(w, c.width - 4)
    h = min(h, c.height - 4)
    x = f"min(max({_px(anim(p, 'x', 0, c), c)},1),{c.width - w - 2})"
    y = f"min(max({_px(anim(p, 'y', 0, c), c)},1),{c.height - h - 2})"
    return [f"delogo=x='{x}':y='{y}':w={w}:h={h}{enable_expr(p, c)}"]


def _f_matte(p: dict, c: Ctx) -> list[str]:
    """Scontorno con l'IA: la maschera la calcola remove_background.

    Il file della maschera e' un video in scala di grigi che il grafo prepara
    allineato fotogramma per fotogramma alla clip (stesso attacco, velocita' e
    inquadratura) e passa qui come etichetta in ``ctx.extra["matte"]``.
    """
    lab = c.extra.get("matte")
    if not lab:
        return []
    m = c.uid("mtm")
    return [f"format=yuva420p[{m}];[{m}][{lab}]alphamerge"]


# --------------------------------------------------------------------------
# effetti audio
# --------------------------------------------------------------------------


def _a_eq3(p: dict, c: Ctx) -> list[str]:
    return [
        f"bass=g={fnum(num(p, 'bass', 0))}:f=110",
        f"equalizer=f=1000:width_type=o:width=2:g={fnum(num(p, 'mid', 0))}",
        f"treble=g={fnum(num(p, 'treble', 0))}:f=8000",
    ]


def _a_compressor(p: dict, c: Ctx) -> list[str]:
    return [
        f"acompressor=threshold={fnum(num(p, 'threshold', -18))}dB:ratio={fnum(num(p, 'ratio', 3))}"
        f":attack={fnum(num(p, 'attack', 20))}:release={fnum(num(p, 'release', 250))}"
        f":makeup={fnum(num(p, 'makeup', 1))}"
    ]


def _a_limiter(p: dict, c: Ctx) -> list[str]:
    return [f"alimiter=limit={fnum(num(p, 'limit', 0.95))}:level=false"]


def _a_denoise(p: dict, c: Ctx) -> list[str]:
    return [f"afftdn=nr={fnum(num(p, 'reduction', 12))}:nf={fnum(num(p, 'floor', -40))}:tn=1"]


def _a_highpass(p: dict, c: Ctx) -> list[str]:
    return [f"highpass=f={fnum(num(p, 'freq', 80))}:poles=2"]


def _a_lowpass(p: dict, c: Ctx) -> list[str]:
    return [f"lowpass=f={fnum(num(p, 'freq', 16000))}:poles=2"]


def _a_echo(p: dict, c: Ctx) -> list[str]:
    d = int(num(p, "delay_ms", 300))
    dec = fnum(num(p, "decay", 0.4))
    return [f"aecho=0.8:0.85:{d}:{dec}"]


def _a_reverb(p: dict, c: Ctx) -> list[str]:
    amount = max(0.05, min(0.9, num(p, "amount", 0.3)))
    size = max(0.1, min(1.0, num(p, "size", 0.5)))
    d1 = int(30 + 90 * size)
    return [f"aecho=0.8:0.9:{d1}|{d1 * 2}|{d1 * 3}:{fnum(amount)}|{fnum(amount * 0.6)}|{fnum(amount * 0.35)}"]


def _a_pitch(p: dict, c: Ctx) -> list[str]:
    semitones = num(p, "semitones", 0)
    if abs(semitones) < 1e-6:
        return []
    return [f"rubberband=pitch={fnum(2 ** (semitones / 12.0))}"]


def _a_gate(p: dict, c: Ctx) -> list[str]:
    return [
        f"agate=threshold={fnum(num(p, 'threshold', 0.02))}:ratio={fnum(num(p, 'ratio', 4))}"
        f":attack={fnum(num(p, 'attack', 20))}:release={fnum(num(p, 'release', 250))}"
    ]


def _a_censor(p: dict, c: Ctx) -> list[str]:
    """Copre intervalli di parlato: muto o voce resa incomprensibile.

    Gli intervalli arrivano da ``analyze.censor_spans``, che li ricava dai
    timestamp per parola della trascrizione.
    """
    en = enable_expr(p, c)
    if not en:
        return []
    if str(val(p, "mode", "mute")) == "scramble":
        shift = fnum(num(p, "shift", 400))
        return [f"afreqshift=shift={shift}{en}"]
    return [f"volume=volume=0{en}"]


def _a_deesser(p: dict, c: Ctx) -> list[str]:
    """Smorza le "s" e le "z" sibilanti della voce senza spegnere il resto.

    Non usa il filtro deesser di ffmpeg: su questa versione non rileva mai
    niente e lascia l'audio identico. Si fa come in studio: il suono si divide
    in due bande (acrossover), si comprime solo quella acuta, dove stanno le
    sibilanti, e si rimettono insieme.
    """
    quanto = max(0.0, min(1.0, num(p, "amount", 0.6)))
    soglia = 10 ** ((-12 - 30 * quanto) / 20)
    rapporto = 2 + 10 * quanto
    f = fnum(max(2000.0, min(12000.0, num(p, "frequency", 5500))))
    lo, hi, hc = c.uid("dslo"), c.uid("dshi"), c.uid("dshc")
    return [
        f"acrossover=split={f}[{lo}][{hi}];"
        f"[{hi}]acompressor=threshold={fnum(soglia)}:ratio={fnum(rapporto)}:attack=1:release=60[{hc}];"
        f"[{lo}][{hc}]amix=inputs=2:normalize=0"
    ]


TIPI_BANDA = ("peak", "lowshelf", "highshelf", "highpass", "lowpass", "notch")
MAX_BANDE = 10
BANDE_DEFAULT = [
    {"type": "highpass", "freq": 70, "q": 0.7},
    {"type": "lowshelf", "freq": 200, "gain": 0, "q": 0.7},
    {"type": "peak", "freq": 1000, "gain": 0, "q": 1.0},
    {"type": "peak", "freq": 3500, "gain": 0, "q": 1.0},
    {"type": "highshelf", "freq": 9000, "gain": 0, "q": 0.7},
]


def bande_valide(bands) -> list[dict]:
    """Normalizza le bande dell'equalizzatore parametrico; ValueError se impossibili."""
    if isinstance(bands, str):
        import json

        bands = json.loads(bands or "[]")
    if not isinstance(bands, list):
        raise ValueError("bands dev'essere una lista di bande")
    if len(bands) > MAX_BANDE:
        raise ValueError(f"al massimo {MAX_BANDE} bande")
    out = []
    for b in bands:
        if not isinstance(b, dict):
            raise ValueError("ogni banda e' un oggetto {type, freq, gain, q}")
        tipo = str(b.get("type", "peak"))
        if tipo not in TIPI_BANDA:
            raise ValueError(f"tipo di banda {tipo!r} non ammesso: {list(TIPI_BANDA)}")
        freq = float(b.get("freq", 1000))
        gain = float(b.get("gain", 0))
        q = float(b.get("q", 1.0))
        if not 20 <= freq <= 20000:
            raise ValueError(f"frequenza {freq} fuori da 20-20000 Hz")
        if not -24 <= gain <= 24:
            raise ValueError(f"guadagno {gain} fuori da -24..24 dB")
        if not 0.1 <= q <= 18:
            raise ValueError(f"Q {q} fuori da 0.1-18")
        out.append({"type": tipo, "freq": freq, "gain": gain, "q": q,
                    "on": bool(b.get("on", True))})
    return out


def _a_eqparam(p: dict, c: Ctx) -> list[str]:
    """Equalizzatore parametrico: fino a dieci bande, ognuna col suo filtro."""
    out = []
    for b in bande_valide(p.get("bands", BANDE_DEFAULT)):
        if not b["on"]:
            continue
        f, g, q = fnum(b["freq"]), fnum(b["gain"]), fnum(b["q"])
        if b["type"] == "peak":
            if abs(b["gain"]) > 1e-6:
                out.append(f"equalizer=f={f}:t=q:w={q}:g={g}")
        elif b["type"] in ("lowshelf", "highshelf"):
            if abs(b["gain"]) > 1e-6:
                out.append(f"{b['type']}=f={f}:g={g}:t=q:w={q}")
        elif b["type"] in ("highpass", "lowpass"):
            out.append(f"{b['type']}=f={f}:t=q:w={q}")
        else:  # notch
            out.append(f"bandreject=f={f}:t=q:w={q}")
    uscita = num(p, "output", 0.0)
    if abs(uscita) > 1e-6:
        out.append(f"volume={fnum(uscita)}dB")
    return out


def _a_vst(p: dict, c: Ctx) -> list[str]:
    """Il plugin non e' un filtro ffmpeg: il suono arriva gia' lavorato (plugins.py)."""
    return []


def _a_dynnorm(p: dict, c: Ctx) -> list[str]:
    return [f"dynaudnorm=f={int(num(p, 'frame_ms', 200))}:g={int(num(p, 'gauss', 15))}:p={fnum(num(p, 'peak', 0.9))}"]


# --------------------------------------------------------------------------
# registro
# --------------------------------------------------------------------------

_DEFS: tuple[EffectDef, ...] = (
    EffectDef(
        "color", "video", "Correzione colore",
        (
            Param("brightness", 0.0, min=-1, max=1, anim=True, desc="-1..1"),
            Param("contrast", 1.0, min=0, max=4, anim=True),
            Param("saturation", 1.0, min=0, max=3, anim=True, desc="0 = bianco e nero"),
            Param("gamma", 1.0, min=0.1, max=10, anim=True),
        ),
        _f_color, "Luminosita', contrasto, saturazione, gamma. Tutti animabili.",
    ),
    EffectDef(
        "colorbalance", "video", "Bilanciamento colore",
        tuple(Param(k, 0.0, min=-1, max=1) for k in ("rs", "gs", "bs", "rm", "gm", "bm", "rh", "gh", "bh")),
        _f_colorbalance, "Ombre (s), mezzitoni (m), alte luci (h) per canale RGB: lift, gamma, gain.",
    ),
    EffectDef(
        "temperature", "video", "Temperatura colore",
        (Param("temperature", 6500, min=1000, max=40000), Param("mix", 1.0, min=0, max=1)),
        _f_temperature, "Kelvin: sotto 6500 scalda (arancio), sopra raffredda (blu).",
    ),
    EffectDef(
        "curves", "video", "Curve",
        (
            Param("preset", "none", kind="enum",
                  choices=("none", "color_negative", "cross_process", "darker", "increase_contrast",
                           "lighter", "linear_contrast", "medium_contrast", "negative",
                           "strong_contrast", "vintage")),
            Param("master", "", kind="string", desc="punti 'x0/y0 x1/y1' se preset=none"),
        ),
        _f_curves,
    ),
    EffectDef(
        "lut", "video", "LUT 3D",
        (Param("file", "", kind="file", desc="file .cube"),
         Param("interp", "tetrahedral", kind="enum", choices=("nearest", "trilinear", "tetrahedral"))),
        _f_lut, "Applica una look-up table .cube.",
    ),
    EffectDef(
        "colormatch", "video", "Uniforma colore",
        tuple(Param(f"{ch}_{k}", 1.0 if k == "gain" else 0.0, min=-1, max=3)
              for ch in ("r", "g", "b") for k in ("gain", "off")),
        _f_colormatch,
        "Guadagno e offset per canale. Non si impostano a mano: li calcola "
        "match_color confrontando la clip con quella di riferimento.",
    ),
    EffectDef(
        "blur", "video", "Sfocatura",
        (Param("sigma", 8, min=0, max=100), Param("steps", 1, min=1, max=6)),
        _f_blur,
    ),
    EffectDef(
        "sharpen", "video", "Nitidezza",
        (Param("amount", 1.0, min=-2, max=5), Param("chroma", 0.0, min=-2, max=2)),
        _f_sharpen,
    ),
    EffectDef(
        "glow", "video", "Glow",
        (Param("sigma", 12, min=1, max=60), Param("amount", 0.5, min=0, max=1)),
        _f_glow, "Bagliore morbido sulle alte luci.",
    ),
    EffectDef(
        "vignette", "video", "Vignettatura",
        (Param("angle", 0.8, min=0, max=1.57),
         Param("mode", "forward", kind="enum", choices=("forward", "backward"))),
        _f_vignette,
    ),
    EffectDef("grain", "video", "Grana", (Param("strength", 12, min=0, max=100),), _f_grain),
    EffectDef("denoise", "video", "Riduzione rumore", (Param("strength", 4, min=0, max=20),), _f_denoise),
    EffectDef(
        "chromakey", "video", "Chroma key",
        (
            Param("color", "green", kind="color"),
            Param("similarity", 0.20, min=0.01, max=1),
            Param("blend", 0.05, min=0, max=1),
            Param("despill", True, kind="bool"),
            Param("despill_amount", 20, min=0, max=100),
        ),
        _f_chromakey, "Rimuove il fondale verde/blu rendendolo trasparente.",
    ),
    EffectDef(
        "crop", "video", "Ritaglio",
        (Param("w", 1920), Param("h", 1080), Param("x", 0), Param("y", 0)),
        _f_crop, "Ritaglia un rettangolo, il resto diventa trasparente.",
    ),
    EffectDef("pixelate", "video", "Pixel", (Param("size", 16, min=2, max=200),), _f_pixelate),
    EffectDef(
        "mask_blur", "video", "Maschera sfocata",
        (
            Param("x", 0, anim=True, desc="px, angolo in alto a sinistra"),
            Param("y", 0, anim=True),
            Param("w", 300, min=2), Param("h", 300, min=2),
            Param("sigma", 20, min=1, max=100),
            Param("ranges", "", kind="string", desc="'1.2-1.8;4-4.5' = solo in quegli istanti"),
        ),
        _f_mask_blur,
        "Sfoca solo un rettangolo (volto, targa, schermo). x/y animabili: con i "
        "keyframe la maschera segue il soggetto. ranges vuoto = sempre attiva.",
    ),
    EffectDef(
        "mask_pixelate", "video", "Maschera a mosaico",
        (
            Param("x", 0, anim=True), Param("y", 0, anim=True),
            Param("w", 300, min=2), Param("h", 300, min=2),
            Param("size", 16, min=2, max=200),
            Param("ranges", "", kind="string"),
        ),
        _f_mask_pixelate, "Come mask_blur ma a mosaico: censura evidente.",
    ),
    EffectDef(
        "mask_box", "video", "Barra piena",
        (
            Param("x", 0, anim=True), Param("y", 0, anim=True),
            Param("w", 300, min=2), Param("h", 120, min=2),
            Param("color", "black", kind="color"),
            Param("opacity", 1.0, min=0, max=1),
            Param("ranges", "", kind="string"),
        ),
        _f_mask_box, "Rettangolo pieno: censura netta o barra grafica.",
    ),
    EffectDef(
        "subtitles", "video", "Sottotitoli",
        (Param("file", "", kind="file", desc="file .ass (karaoke) o .srt"),
         Param("force_style", "", kind="string",
               desc="solo per .srt, es. 'Fontsize=48,Bold=1'")),
        _f_subtitles,
        "Imprime i sottotitoli nell'immagine. Generali con make_captions: il "
        "formato .ass porta anche l'evidenziazione parola per parola.",
    ),
    EffectDef(
        "mirror", "video", "Specchia",
        (Param("horizontal", True, kind="bool"), Param("vertical", False, kind="bool")),
        _f_mirror,
    ),
    EffectDef(
        "stabilize", "video", "Stabilizzazione",
        (Param("smoothing", 15, min=1, max=100), Param("zoom", 0, min=-10, max=10)),
        _f_stabilize, "Richiede analisi vidstab (fatta in automatico al render); senza analisi usa deshake.",
    ),
    EffectDef(
        "motionblur", "video", "Motion blur",
        (Param("mode", "blend", kind="enum", choices=("blend", "interpolate")), Param("frames", 3, min=2, max=9)),
        _f_fps_blend, "blend = scia morbida; interpolate = frame interpolati (lento).",
    ),
    EffectDef(
        "exposure", "video", "Esposizione",
        (Param("exposure", 0.0, min=-3, max=3, desc="stop: +1 = il doppio della luce"),
         Param("black", 0.0, min=-0.1, max=0.1, desc="livello del nero")),
        _f_exposure, "Schiarisce o scurisce come il diaframma, senza appiattire il contrasto.",
    ),
    EffectDef(
        "vibrance", "video", "Vividezza",
        (Param("intensity", 0.3, min=-2, max=2),),
        _f_vibrance, "Satura i colori spenti e risparmia quelli gia' carichi e la pelle.",
    ),
    EffectDef(
        "whitebalance", "video", "Bilanciamento del bianco",
        (Param("temperature", 6500, min=2000, max=12000,
               desc="K: sotto 6500 scalda (arancio), sopra raffredda (blu)"),
         Param("tint", 0.0, min=-1, max=1, desc="negativa verso il verde, positiva verso il magenta")),
        _f_whitebalance, "Temperatura e tinta: toglie la dominante di una luce sbagliata.",
    ),
    EffectDef(
        "autowhite", "video", "Bilanciamento automatico", (),
        _f_autowhite, "Neutralizza da solo la dominante di colore (gray world).",
    ),
    EffectDef(
        "hue", "video", "Tonalita'",
        (Param("hue", 0.0, min=-180, max=180, anim=True, desc="gradi sulla ruota dei colori"),),
        _f_hue, "Ruota tutti i colori; animabile.",
    ),
    EffectDef(
        "hsl", "video", "Correzione di un colore",
        (Param("colors", "blu", kind="enum", choices=tuple(_COLORI)),
         Param("hue", 0.0, min=-180, max=180, desc="sposta la tinta di quel colore"),
         Param("saturation", 0.0, min=-1, max=1),
         Param("brightness", 0.0, min=-1, max=1),
         Param("softness", 5.0, min=0, max=100,
               desc="forza della selezione: sotto 5 l'effetto arriva solo a meta'")),
        _f_hsl, "Tocca solo una famiglia di colori: cielo piu' blu, erba meno gialla, pelle piu' calda.",
    ),
    EffectDef(
        "levels", "video", "Livelli",
        (Param("black_in", 0.0, min=0, max=0.5), Param("white_in", 1.0, min=0.5, max=1),
         Param("black_out", 0.0, min=0, max=0.5), Param("white_out", 1.0, min=0.5, max=1)),
        _f_levels, "Punti del nero e del bianco: recupera un'immagine slavata o schiaccia i neri.",
    ),
    # ---- effetti speciali ----
    EffectDef(
        "rgb_split", "video", "Aberrazione cromatica",
        (Param("amount", 6, min=0, max=200, desc="px di separazione tra rosso e blu"),
         Param("angle", 0, min=-180, max=180, desc="direzione, 0 = orizzontale")),
        _f_rgb_split, "Rosso e blu separati ai lati: look da obiettivo economico o da glitch.",
    ),
    EffectDef(
        "glitch", "video", "Glitch",
        (Param("intensity", 0.3, min=0, max=1, desc="quanta parte del tempo e' disturbata"),
         Param("amount", 40, min=0, max=400, desc="px di scivolamento delle fasce"),
         Param("rate", 12, min=1, max=60, desc="cambi al secondo"),
         Param("band", 24, min=2, max=400, desc="altezza delle fasce in px"),
         Param("seed", 1, min=0, max=1000, desc="altro numero = altre raffiche")),
        _f_glitch,
        "Raffiche di disturbo digitale: fasce che scivolano e canali separati. "
        "Ripetibile: stesso seed, stessi fotogrammi colpiti.",
    ),
    EffectDef(
        "warp", "video", "Distorsione",
        (Param("mode", "wave", kind="enum", choices=("wave", "ripple", "swirl", "bulge")),
         Param("amount", 20, min=-720, max=720, anim=True,
               desc="wave/ripple: px; swirl: gradi; bulge: -100..100"),
         Param("wavelength", 120, min=2, max=4000, desc="px tra due creste (wave, ripple)"),
         Param("speed", 1.0, min=-20, max=20, desc="cicli al secondo (wave, ripple)"),
         Param("cx", 0.5, min=0, max=1), Param("cy", 0.5, min=0, max=1),
         Param("radius", 0.5, min=0.01, max=2, desc="frazione della diagonale (swirl, bulge)")),
        _f_warp,
        "Onda, increspatura dal centro, vortice, lente che gonfia. amount animabile. "
        "Pesante: geq ricalcola ogni pixel.",
    ),
    EffectDef(
        "lens", "video", "Obiettivo",
        (Param("k1", 0.3, min=-1, max=1, desc=">0 barile (fisheye), <0 cuscino"),
         Param("k2", 0.0, min=-1, max=1)),
        _f_lens, "Distorsione dell'obiettivo: fisheye o cuscino; gli angoli scoperti restano trasparenti.",
    ),
    EffectDef(
        "shake", "video", "Tremolio camera",
        (Param("amount", 12, min=0, max=200, anim=True, desc="px di ampiezza"),
         Param("frequency", 6, min=0.1, max=40, desc="oscillazioni al secondo")),
        _f_shake,
        "Camera a mano, impatto, terremoto. Mai bordi scoperti: ingrandisce quanto basta. "
        "amount a keyframe per un colpo che si smorza.",
    ),
    EffectDef(
        "tilt3d", "video", "Rotazione 3D",
        (Param("yaw", 25, min=-360, max=360, anim=True, desc="gradi attorno all'asse verticale"),
         Param("pitch", 0, min=-360, max=360, anim=True, desc="gradi attorno all'asse orizzontale"),
         Param("depth", 2.0, min=0.3, max=20, desc="distanza della camera: piccola = prospettiva forte")),
        _f_tilt3d,
        "La clip come una carta nello spazio, con prospettiva vera. Animabile: un giro "
        "completo e' yaw da 0 a 360. Fuori dalla carta si vede la traccia sotto.",
    ),
    EffectDef(
        "sky_key", "video", "Sostituzione cielo",
        (Param("color", "#7fb0e0", kind="color", desc="colore del cielo da togliere"),
         Param("similarity", 0.3, min=0.01, max=1),
         Param("blend", 0.15, min=0, max=1),
         Param("horizon", 0.6, min=0.05, max=1, desc="sotto questa altezza (frazione) niente si toglie"),
         Param("feather", 0.08, min=0, max=0.5, desc="sfumatura del confine")),
        _f_sky_key,
        "Rende trasparente il cielo sopra l'orizzonte; il cielo nuovo va su una traccia "
        "sotto. Campiona il colore con preview_frame o color_scopes.",
    ),
    EffectDef(
        "remove_object", "video", "Rimuovi oggetto",
        (Param("x", 0, anim=True, desc="px, angolo in alto a sinistra"), Param("y", 0, anim=True),
         Param("w", 120, min=4), Param("h", 80, min=4),
         Param("ranges", "", kind="string", desc="'1.2-1.8;4-4.5' = solo in quegli istanti")),
        _f_remove_object,
        "Cancella logo, scritta, cavo o piccolo oggetto ricostruendolo dai bordi. "
        "Ottimo su sfondi uniformi, su sfondi ricchi lascia una macchia morbida.",
    ),
    EffectDef(
        "matte", "video", "Scontorno IA",
        (Param("file", "", kind="file", desc="video maschera (bianco = tieni)"),
         Param("t0", 0.0, min=0, desc="secondo della sorgente su cui parte la maschera"),
         Param("feather", 2, min=0, max=40, desc="sfumatura del bordo in px"),
         Param("invert", False, kind="bool", desc="togli il soggetto invece dello sfondo")),
        _f_matte,
        "Toglie lo sfondo senza green screen. Non si imposta a mano: lo crea "
        "remove_background segmentando il soggetto fotogramma per fotogramma.",
    ),
    # ---- audio ----
    EffectDef(
        "eq3", "audio", "Equalizzatore",
        (Param("bass", 0, min=-20, max=20, desc="dB"), Param("mid", 0, min=-20, max=20),
         Param("treble", 0, min=-20, max=20)),
        _a_eq3,
    ),
    EffectDef(
        "compressor", "audio", "Compressore",
        (Param("threshold", -18, min=-60, max=0, desc="dB"), Param("ratio", 3, min=1, max=20),
         Param("attack", 20, min=0.01, max=2000), Param("release", 250, min=0.01, max=9000),
         Param("makeup", 1, min=1, max=64)),
        _a_compressor,
    ),
    EffectDef("limiter", "audio", "Limiter", (Param("limit", 0.95, min=0.1, max=1),), _a_limiter),
    EffectDef(
        "adenoise", "audio", "Riduzione rumore",
        (Param("reduction", 12, min=0.01, max=97, desc="dB"), Param("floor", -40, min=-80, max=-20)),
        _a_denoise, "Toglie fruscio/ronzio di fondo.",
    ),
    EffectDef("highpass", "audio", "Passa-alto", (Param("freq", 80, min=10, max=2000),), _a_highpass,
              "Taglia le basse: rimuove rimbombo e rumore di traffico."),
    EffectDef("lowpass", "audio", "Passa-basso", (Param("freq", 16000, min=500, max=20000),), _a_lowpass),
    EffectDef("echo", "audio", "Eco", (Param("delay_ms", 300, min=10, max=5000), Param("decay", 0.4, min=0, max=1)), _a_echo),
    EffectDef("reverb", "audio", "Riverbero", (Param("amount", 0.3, min=0, max=0.9), Param("size", 0.5, min=0.1, max=1)), _a_reverb),
    EffectDef("pitch", "audio", "Pitch", (Param("semitones", 0, min=-24, max=24),), _a_pitch,
              "Cambia intonazione senza cambiare durata."),
    EffectDef(
        "gate", "audio", "Noise gate",
        (Param("threshold", 0.02, min=0, max=1), Param("ratio", 4, min=1, max=20),
         Param("attack", 20), Param("release", 250)),
        _a_gate,
    ),
    EffectDef(
        "censor", "audio", "Censura parlato",
        (
            Param("ranges", "", kind="string", desc="'12.4-12.9;30.1-30.4' dalla trascrizione"),
            Param("mode", "mute", kind="enum", choices=("mute", "scramble")),
            Param("shift", 400, min=50, max=2000, desc="Hz, solo per scramble"),
        ),
        _a_censor,
        "Copre gli intervalli indicati: mute li azzera, scramble sposta le "
        "frequenze e rende la voce incomprensibile ma presente. Gli intervalli "
        "arrivano da analyze.censor_spans (timestamp per parola).",
    ),
    EffectDef(
        "deesser", "audio", "De-esser",
        (Param("amount", 0.6, min=0, max=1, desc="quanto smorza: 0 niente, 1 molto"),
         Param("frequency", 5500, min=2000, max=12000,
               desc="Hz da cui partono le sibilanti: 5000-6000 voce maschile, 6000-8000 femminile")),
        _a_deesser, "Smorza le 's' sibilanti della voce.",
    ),
    EffectDef(
        "eqparam", "audio", "Equalizzatore parametrico",
        (Param("bands", BANDE_DEFAULT, kind="bands",
               desc="lista di bande {type: peak|lowshelf|highshelf|highpass|lowpass|notch, "
                    "freq: Hz, gain: dB, q, on}"),
         Param("output", 0.0, min=-24, max=24, desc="guadagno finale in dB")),
        _a_eqparam, "Fino a dieci bande con frequenza, guadagno e larghezza a scelta.",
    ),
    EffectDef(
        "vst", "audio", "Plugin VST",
        (Param("file", "", kind="file", desc="plugin .vst3 (o .component su Mac)"),
         Param("values", {}, kind="dict", desc="valori dei parametri del plugin, per nome"),
         Param("mix", 1.0, min=0, max=1, desc="0 = suono originale, 1 = solo plugin")),
        _a_vst, "Un plugin audio esterno (VST3/AU): si applica prima degli altri effetti.",
    ),
    EffectDef(
        "dynnorm", "audio", "Normalizzazione dinamica",
        (Param("frame_ms", 200, min=10, max=8000), Param("gauss", 15, min=3, max=31), Param("peak", 0.9, min=0.1, max=1)),
        _a_dynnorm, "Livella il volume nel tempo (per parlato irregolare).",
    ),
)

EFFECTS: dict[str, EffectDef] = {d.name: d for d in _DEFS}


def build_chain(effects, ctx: Ctx, kind: str) -> list[str]:
    """Compila la lista di Effect del modello nella catena di filtri."""
    out: list[str] = []
    for e in effects:
        if not getattr(e, "enabled", True):
            continue
        d = EFFECTS.get(e.type)
        if d is None or d.kind != kind:
            continue
        out.extend(f for f in d.build(dict(e.params or {}), ctx) if f)
    return out


def describe(kind: str | None = None) -> list[dict]:
    """Descrizione JSON del registro (usata da MCP e UI)."""
    out = []
    for d in _DEFS:
        if kind and d.kind != kind:
            continue
        out.append({
            "name": d.name,
            "kind": d.kind,
            "label": d.label,
            "desc": d.desc,
            "params": [
                {
                    "name": p.name, "default": p.default, "type": p.kind,
                    "min": p.min, "max": p.max, "animatable": p.anim,
                    "choices": list(p.choices), "desc": p.desc,
                }
                for p in d.params
            ],
        })
    return out


def validate_effect(type_: str, params: dict) -> dict:
    """Verifica nome effetto e parametri, ritorna i parametri normalizzati."""
    d = _spec(type_)
    known = {p.name for p in d.params}
    unknown = set(params or {}) - known
    if unknown:
        raise ValueError(
            f"parametri sconosciuti per {type_!r}: {sorted(unknown)}; ammessi: {sorted(known)}"
        )
    clean = {}
    for p in d.params:
        if p.name not in (params or {}):
            continue
        v = params[p.name]
        if kf.is_kf(v):
            if not p.anim:
                raise ValueError(f"{type_}.{p.name} non e' animabile")
            kf.validate(v)
        elif p.kind == "number" and (p.min is not None or p.max is not None):
            fv = float(v)
            if p.min is not None and fv < p.min:
                raise ValueError(f"{type_}.{p.name}={fv} sotto il minimo {p.min}")
            if p.max is not None and fv > p.max:
                raise ValueError(f"{type_}.{p.name}={fv} sopra il massimo {p.max}")
            v = fv
        elif p.kind == "bands":
            v = bande_valide(v)
        elif p.kind == "dict":
            if not isinstance(v, dict) or not all(
                    isinstance(x, (int, float, str, bool)) for x in v.values()):
                raise ValueError(f"{type_}.{p.name} vuole un oggetto nome -> valore")
        elif p.kind == "enum" and p.choices and str(v) not in p.choices:
            raise ValueError(f"{type_}.{p.name}={v!r} non ammesso, scegli tra {list(p.choices)}")
        clean[p.name] = v
    return clean
