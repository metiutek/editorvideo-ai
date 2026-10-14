"""Particelle: neve, pioggia, scintille, coriandoli, polvere, bokeh, stelle, lucciole.

Diventano una clip html (vedi htmlclip.py) con un canvas trasparente sopra la
ripresa. Ogni particella ha la posizione scritta in *forma chiusa* in funzione
del tempo - niente simulazione passo dopo passo - quindi il fotogramma al
secondo 3.2 e' sempre lo stesso, che lo si guardi in anteprima saltandoci
sopra o che lo si renderizzi partendo da zero. I numeri casuali vengono da un
generatore con seme: stesso ``seed``, stesse particelle.

Oltre ai tipi gia' tarati c'e' ``custom``: forma, moto, colori, dimensioni e
velocita' li decide chi monta (``valida`` dice cosa si puo' scrivere). Le
ricette personalizzate si salvano in ``~/.vedit/particelle.json`` e tornano nel
menu come i tipi integrati. I parametri con cui e' nata una clip viaggiano
dentro il suo html (``parametri``): e' cosi' che la si modifica dopo.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# tipo -> (colore predefinito, quante particelle a densita' 1 su 1920x1080)
KINDS: dict[str, tuple[str, int]] = {
    "snow": ("#ffffff", 260),
    "rain": ("#aac8ff", 420),
    "sparks": ("#ffa030", 280),
    "confetti": ("", 220),
    "dust": ("#fff4dc", 180),
    "bokeh": ("#ffd890", 40),
    "stars": ("#ffffff", 300),
    "fireflies": ("#d8ff70", 90),
}

DESCRIZIONI = {
    "snow": "neve che scende ondeggiando",
    "rain": "pioggia obliqua veloce",
    "sparks": "braci e scintille che salgono e si spengono",
    "confetti": "coriandoli colorati che cadono girando",
    "dust": "pulviscolo nella luce, lento",
    "bokeh": "grandi dischi sfocati che fluttuano",
    "stars": "cielo stellato che brilla",
    "fireflies": "lucciole che vagano e pulsano",
}

_JS = r"""
const W = __W__, H = __H__, O = __OPT__;
const cv = document.getElementById('c'), g = cv.getContext('2d');
function rng(a) { return function() { a |= 0; a = a + 0x6D2B79F5 | 0;
  let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
  return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const R = rng(O.seed * 9973 + 17);
const N = Math.max(1, Math.round(O.count));
const P = []; for (let i = 0; i < N; i++) P.push([R(), R(), R(), R(), R(), R()]);
const mod = (a, m) => ((a % m) + m) % m;
const S = O.size, V = O.speed, C = O.color;
const PAL = ['#ff3b5c', '#ffd23b', '#3bd1ff', '#7cff6b', '#c56bff', '#ff8a3b', '#ffffff'];
function disco(x, y, r, col, a, glow) {
  g.globalAlpha = Math.max(0, Math.min(1, a));
  if (glow) { g.shadowBlur = glow; g.shadowColor = col; } else g.shadowBlur = 0;
  g.fillStyle = col; g.beginPath(); g.arc(x, y, Math.max(0.3, r), 0, 6.2832); g.fill();
}
function frame(t) {
  g.clearRect(0, 0, W, H);
  for (let i = 0; i < N; i++) {
    const [a, b, c, d, e, f] = P[i];
    switch (O.kind) {
      case 'snow': {
        const r = (3 + 6 * c) * S, vy = (50 + 90 * c) * V;
        const y = mod(b * (H + 40) + t * vy, H + 40) - 20;
        const x = mod(a * W + Math.sin(t * (0.6 + d) + e * 6.28) * 30 * S + t * 12 * V, W + 20) - 10;
        disco(x, y, r, C, 0.55 + 0.45 * c, 0); break; }
      case 'rain': {
        const L = (30 + 45 * c) * S, vy = (900 + 700 * c) * V, vx = vy * 0.18;
        const y = mod(b * (H + L) + t * vy, H + L) - L;
        const x = mod(a * (W + 200) + t * vx, W + 200) - 100;
        g.shadowBlur = 0; g.globalAlpha = 0.25 + 0.4 * d; g.strokeStyle = C;
        g.lineWidth = (1.5 + 1.5 * c) * S; g.beginPath(); g.moveTo(x, y);
        g.lineTo(x - L * 0.18, y - L); g.stroke(); break; }
      case 'sparks': {
        const vida = 1.5 + 2.5 * c, fase = mod(t / vida * V + b, 1);
        const y = H + 20 - fase * H * (0.6 + 0.5 * d);
        const x = a * W + Math.sin(fase * 9 + e * 6.28) * 40 * S + (f - 0.5) * 120 * fase;
        disco(x, y, (5 + 7 * d) * S * (1 - fase * 0.5), fase < 0.3 ? '#fff0b0' : C,
              0.35 + (1 - fase) * 1.2, 30 * S); break; }
      case 'confetti': {
        const vy = (110 + 120 * c) * V;
        const y = mod(b * (H + 60) + t * vy, H + 60) - 30;
        const x = mod(a * W + Math.sin(t * (1 + d) + e * 6.28) * 50 * S, W);
        const rot = e * 6.28 + t * (2 + 5 * f) * (f > 0.5 ? 1 : -1);
        const w = 22 * S, h = 13 * S * Math.abs(Math.cos(t * (3 + 4 * d) + a * 6.28));
        g.save(); g.translate(x, y); g.rotate(rot); g.shadowBlur = 0; g.globalAlpha = 0.95;
        g.fillStyle = C || PAL[Math.floor(f * PAL.length) % PAL.length];
        g.fillRect(-w / 2, -h / 2, w, Math.max(1, h)); g.restore(); break; }
      case 'dust': {
        const x = mod(a * W + t * (8 + 14 * c) * V + Math.sin(t * 0.3 + e * 6.28) * 25, W);
        const y = mod(b * H - t * (3 + 8 * d) * V + Math.cos(t * 0.25 + f * 6.28) * 20, H);
        const luce = 0.15 + 0.35 * (0.5 + 0.5 * Math.sin(t * (0.5 + d) + e * 6.28));
        disco(x, y, (1.8 + 3 * c) * S, C, luce + 0.15, 8 * S); break; }
      case 'bokeh': {
        const r = (50 + 110 * c) * S;
        const x = mod(a * (W + 2 * r) + t * (6 + 10 * d) * V, W + 2 * r) - r;
        const y = b * H + Math.sin(t * 0.2 * V + e * 6.28) * 40;
        const al = 0.18 + 0.22 * (0.5 + 0.5 * Math.sin(t * (0.3 + 0.4 * f) + d * 6.28));
        const gr = g.createRadialGradient(x, y, 0, x, y, r);
        gr.addColorStop(0, C); gr.addColorStop(0.75, C); gr.addColorStop(1, 'rgba(0,0,0,0)');
        g.shadowBlur = 0; g.globalAlpha = al; g.fillStyle = gr;
        g.beginPath(); g.arc(x, y, r, 0, 6.2832); g.fill(); break; }
      case 'stars': {
        const tw = 0.5 + 0.5 * Math.sin(t * (1 + 4 * d) * V + e * 6.28);
        disco(a * W, b * H, (1.5 + 3 * c * c) * S, C, 0.25 + 0.75 * tw * (0.4 + 0.6 * c),
              c > 0.85 ? 6 * S : 0); break; }
      case 'fireflies': {
        const x = a * W + Math.sin(t * (0.3 + 0.4 * c) * V + e * 6.28) * 120 * S
                        + Math.sin(t * (0.9 + d) * V) * 30 * S;
        const y = b * H + Math.cos(t * (0.25 + 0.35 * d) * V + f * 6.28) * 90 * S;
        const puls = Math.pow(0.5 + 0.5 * Math.sin(t * (1.2 + 1.5 * c) + f * 6.28), 3);
        disco(x, y, (5 + 5 * c) * S, C, 0.25 + 0.75 * puls, 40 * S); break; }
    }
  }
  g.globalAlpha = 1; g.shadowBlur = 0;
}
function giro() { frame(performance.now() / 1000); requestAnimationFrame(giro); }
giro();
"""


def html(kind: str, width: int, height: int, color: str | None = None,
         density: float = 1.0, speed: float = 1.0, size: float = 1.0, seed: int = 1,
         custom: dict | None = None) -> str:
    """Documento html completo con le particelle richieste.

    Con ``kind="custom"`` la ricetta e' ``custom`` (vedi ``valida``); ``color``
    se c'e' sostituisce i suoi colori, density/speed/size la moltiplicano come
    per i tipi integrati.
    """
    area = (width * height) / (1920 * 1080)
    # le dimensioni sono pensate per 1080p: in 4K o in 720p si riscalano
    k = height / 1080.0
    par = {"kind": kind, "color": color or None, "density": float(density),
           "speed": float(speed), "size": float(size), "seed": int(seed)}
    if kind == CUSTOM:
        spec = valida(custom or {})
        par["custom"] = spec
        opt = {**spec, "seed": int(seed),
               "colors": [color] if color else spec["colors"],
               "count": max(1, round(spec["count"] * max(0.0, density) * max(area, 0.05))),
               "k": k, "ks": float(size) * k, "kv": float(speed) * k}
        js = (_JS_CUSTOM.replace("__W__", str(int(width))).replace("__H__", str(int(height)))
              .replace("__OPT__", json.dumps(opt)))
        nome = "personalizzate"
    else:
        if kind not in KINDS:
            raise ValueError(f"particelle sconosciute {kind!r}; scegli tra "
                             f"{', '.join(KINDS)} o {CUSTOM}")
        colore, base = KINDS[kind]
        opt = {
            "kind": kind, "seed": int(seed), "color": color or colore,
            "count": max(1, round(base * max(0.0, density) * max(area, 0.05))),
            "speed": float(speed) * k, "size": float(size) * k,
        }
        js = (_JS.replace("__W__", str(int(width))).replace("__H__", str(int(height)))
              .replace("__OPT__", json.dumps(opt)))
        nome = kind
    # dentro un <script> la sequenza "</" chiuderebbe il blocco
    dati = json.dumps(par, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html>
<head>
<style>
  html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: transparent; }}
  canvas {{ display: block; }}
</style>
</head>
<body>
<!-- particelle {nome}: generate da vedit (particelle.py) -->
<script type="application/json" id="vedit-particelle">{dati}</script>
<canvas id="c" width="{width}" height="{height}"></canvas>
<script>{js}</script>
</body>
</html>
"""


_PARAMETRI = re.compile(
    r'<script type="application/json" id="vedit-particelle">(.*?)</script>', re.S)


def parametri(doc: str | None) -> dict | None:
    """I parametri con cui ``html`` ha generato questo documento, o None."""
    m = _PARAMETRI.search(doc or "")
    if not m:
        return None
    try:
        par = json.loads(m.group(1))
    except ValueError:
        return None
    return par if isinstance(par, dict) and par.get("kind") else None


# --------------------------------------------------------------------------
# particelle personalizzate
# --------------------------------------------------------------------------

CUSTOM = "custom"
SHAPES = ("circle", "square", "triangle", "star", "heart", "ring", "line", "text")
MOTIONS = ("fall", "rise", "drift", "float", "burst", "still")

FORME = {"circle": "cerchio", "square": "quadrato", "triangle": "triangolo",
         "star": "stella", "heart": "cuore", "ring": "anello", "line": "trattino",
         "text": "testo o emoji"}
MOTI = {"fall": "cadono", "rise": "salgono", "drift": "vento (direzione a scelta)",
        "float": "fluttuano sul posto", "burst": "esplosione da un punto",
        "still": "ferme, compaiono e spariscono"}

# voce -> (predefinito, minimo, massimo); le coppie sono [da, a]
_NUMERI = {
    "count": (150, 1, 3000),          # quante, a 1920x1080
    "size": ([6, 14], 0.5, 400),      # raggio in px
    "speed": ([60, 160], 0, 4000),    # px/s
    "direction": (0, -360, 360),      # gradi: inclinazione per fall/rise, rotta per drift/burst
    "wobble": (25, 0, 600),           # ondeggio laterale in px
    "spin": (0, 0, 10),               # giri al secondo, al massimo
    "opacity": ([0.6, 1.0], 0, 1),
    "glow": (0, 0, 150),              # alone in px
    "twinkle": (0, 0, 1),             # quanto pulsano
    "life": (2.0, 0.1, 60),           # s: durata di un'esplosione o di un'apparizione
    "interval": (2.5, 0.1, 120),      # s fra un'esplosione e l'altra
    "spread": (360, 0, 360),          # gradi del ventaglio dell'esplosione
    "gravity": (300, -5000, 5000),    # px/s^2 per l'esplosione
    "origin": ([0.5, 0.5], 0, 1),     # punto dell'esplosione, frazioni del fotogramma
}
_COPPIE = {"size", "speed", "opacity", "origin"}
PREDEFINITA = {"shape": "circle", "motion": "fall", "colors": ["#ffffff"], "text": "",
               "fade": True, **{k: v[0] for k, v in _NUMERI.items()}}
_COLORE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
MAX_TESTO = 200


def valida(spec: dict) -> dict:
    """Ricetta completa e controllata a partire da quella scritta (anche parziale).

    shape: circle | square | triangle | star | heart | ring | line | text
    motion: fall | rise | drift | float | burst | still
    colors: lista di colori #rrggbb, uno a caso per particella
    text: per shape=text, simboli o emoji separati da spazi ("❤ ✨ 🎉")
    count, size [da,a], speed [da,a], direction, wobble, spin, opacity [da,a],
    glow, twinkle, life, interval, spread, gravity, origin [x,y], fade
    """
    if not isinstance(spec, dict):
        raise ValueError("le particelle personalizzate vogliono un oggetto di parametri")
    ignote = set(spec) - set(PREDEFINITA)
    if ignote:
        raise ValueError(f"voci sconosciute per le particelle: {', '.join(sorted(ignote))}; "
                         f"ammesse: {', '.join(PREDEFINITA)}")
    out = {**PREDEFINITA, **{k: v for k, v in spec.items() if v is not None}}
    if out["shape"] not in SHAPES:
        raise ValueError(f"forma sconosciuta {out['shape']!r}; ammesse: {', '.join(SHAPES)}")
    if out["motion"] not in MOTIONS:
        raise ValueError(f"moto sconosciuto {out['motion']!r}; ammessi: {', '.join(MOTIONS)}")
    colori = out["colors"]
    if isinstance(colori, str):
        colori = [c for c in re.split(r"[\s,]+", colori) if c]
    if not isinstance(colori, list) or not 1 <= len(colori) <= 12:
        raise ValueError("colors: da 1 a 12 colori")
    for c in colori:
        if not isinstance(c, str) or not _COLORE.match(c):
            raise ValueError(f"colore non valido {c!r}: scrivilo come #rrggbb")
    out["colors"] = list(colori)
    out["text"] = str(out["text"] or "").strip()
    if len(out["text"]) > MAX_TESTO:
        raise ValueError(f"text troppo lungo (massimo {MAX_TESTO} caratteri)")
    if out["shape"] == "text" and not out["text"]:
        raise ValueError("con shape=text scrivi in text i simboli o le emoji da usare")
    out["fade"] = bool(out["fade"])
    for k, (_, lo, hi) in _NUMERI.items():
        v = out[k]
        coppia = k in _COPPIE
        if coppia and isinstance(v, (int, float)):
            v = [v, v]
        if coppia and (not isinstance(v, (list, tuple)) or len(v) != 2):
            raise ValueError(f"{k}: una coppia [da, a]")
        try:
            vals = [float(x) for x in (v if coppia else [v])]
        except (TypeError, ValueError):
            raise ValueError(f"{k}: serve un numero") from None
        for x in vals:
            if not lo <= x <= hi:
                raise ValueError(f"{k} deve stare tra {lo:g} e {hi:g}")
        if coppia and k != "origin":
            vals.sort()
        out[k] = vals if coppia else vals[0]
    out["count"] = int(round(out["count"]))
    return out


def _file() -> Path:
    """Accanto a stili.json: sono preferenze di chi monta, non del progetto."""
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "particelle.json"


def personali() -> list[dict]:
    try:
        dati = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(dati, list):
        return []
    return [p for p in dati
            if isinstance(p, dict) and p.get("id") and isinstance(p.get("spec"), dict)]


def trova(pid: str) -> dict | None:
    return next((p for p in personali() if p["id"] == pid), None)


def _scrivi(lista: list[dict]) -> None:
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def salva(nome: str, spec: dict, pid: str | None = None) -> dict:
    """Crea (o con ``pid`` aggiorna) particelle personali; restituisce la voce salvata."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("dai un nome alle particelle")
    spec = valida(spec)
    lista = personali()
    if pid:
        if not any(p["id"] == pid for p in lista):
            raise ValueError(f"particelle personali {pid!r} inesistenti")
    else:
        radice = "mie-" + (re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-") or "particelle")
        pid, n = radice, 2
        while any(p["id"] == pid for p in lista):
            pid, n = f"{radice}-{n}", n + 1
    nuovo = {"id": pid, "nome": nome[:60], "spec": spec}
    if any(p["id"] == pid for p in lista):
        lista = [nuovo if p["id"] == pid else p for p in lista]
    else:
        lista.append(nuovo)
    _scrivi(lista)
    return nuovo


def elimina(pid: str) -> None:
    lista = personali()
    if not any(p["id"] == pid for p in lista):
        raise ValueError(f"particelle personali {pid!r} inesistenti")
    _scrivi([p for p in lista if p["id"] != pid])


def descrivi() -> dict:
    """Cosa si puo' scegliere, per la UI e per chi chiede."""
    return {"integrate": DESCRIZIONI, "forme": FORME, "moti": MOTI,
            "predefinita": PREDEFINITA,
            "limiti": {k: [lo, hi] for k, (_, lo, hi) in _NUMERI.items()},
            "personali": personali()}


_JS_CUSTOM = r"""
const W = __W__, H = __H__, O = __OPT__;
const cv = document.getElementById('c'), g = cv.getContext('2d');
function rng(a) { return function() { a |= 0; a = a + 0x6D2B79F5 | 0;
  let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
  return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const R = rng(O.seed * 9973 + 17);
const N = Math.max(1, Math.round(O.count));
const P = []; for (let i = 0; i < N; i++) P.push([R(), R(), R(), R(), R(), R(), R(), R()]);
const mod = (a, m) => ((a % m) + m) % m;
const lerp = (p, u) => p[0] + (p[1] - p[0]) * u;
const RAD = Math.PI / 180, TAU = Math.PI * 2;
const SIMBOLI = O.text ? O.text.split(/\s+/).filter(Boolean) : [];
const VOL = O.wobble * O.k;
const MARG = O.size[1] * O.ks * 2 + VOL + 20;
// rotta del moto lineare: cadere e' verso il basso, salire verso l'alto
const ROTTA = ((O.motion === 'fall' ? 90 : O.motion === 'rise' ? -90 : 0) + O.direction) * RAD;
function forma(x, y, r, rot, col, a, sym) {
  if (a <= 0.003 || r <= 0) return;
  g.save(); g.translate(x, y); if (rot) g.rotate(rot);
  g.globalAlpha = Math.min(1, a);
  if (O.glow) { g.shadowBlur = O.glow * O.k; g.shadowColor = col; }
  g.fillStyle = col; g.strokeStyle = col;
  switch (O.shape) {
    case 'square': g.fillRect(-r, -r, 2 * r, 2 * r); break;
    case 'triangle': g.beginPath(); g.moveTo(0, -r); g.lineTo(r * 0.87, r * 0.5);
      g.lineTo(-r * 0.87, r * 0.5); g.closePath(); g.fill(); break;
    case 'star': g.beginPath();
      for (let j = 0; j < 10; j++) { const q = j % 2 ? r * 0.45 : r, an = j * Math.PI / 5 - Math.PI / 2;
        g.lineTo(Math.cos(an) * q, Math.sin(an) * q); }
      g.closePath(); g.fill(); break;
    case 'heart': g.beginPath(); g.moveTo(0, r * 0.9);
      g.bezierCurveTo(-r * 1.6, -r * 0.2, -r * 0.6, -r * 1.3, 0, -r * 0.45);
      g.bezierCurveTo(r * 0.6, -r * 1.3, r * 1.6, -r * 0.2, 0, r * 0.9); g.fill(); break;
    case 'ring': g.lineWidth = Math.max(1, r * 0.3); g.beginPath();
      g.arc(0, 0, r * 0.85, 0, TAU); g.stroke(); break;
    case 'line': g.lineWidth = Math.max(1, r * 0.25); g.lineCap = 'round'; g.beginPath();
      g.moveTo(0, -r * 1.5); g.lineTo(0, r * 1.5); g.stroke(); break;
    case 'text': g.font = Math.round(r * 2) + 'px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif';
      g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(sym, 0, 0); break;
    default: g.beginPath(); g.arc(0, 0, Math.max(0.3, r), 0, TAU); g.fill();
  }
  g.restore();
}
function frame(t) {
  g.clearRect(0, 0, W, H);
  for (let i = 0; i < N; i++) {
    const [a, b, c, d, e, f, h, m] = P[i];
    // stesso numero per dimensione e velocita': le grandi corrono di piu', come in parallasse
    const r = lerp(O.size, c) * O.ks, v = lerp(O.speed, c) * O.kv;
    const col = O.colors[Math.floor(f * O.colors.length) % O.colors.length];
    const sym = SIMBOLI.length ? SIMBOLI[Math.floor(h * SIMBOLI.length) % SIMBOLI.length] : '';
    let al = lerp(O.opacity, d);
    let rot = O.spin ? e * TAU + t * O.spin * TAU * (0.3 + 0.7 * m) * (m > 0.5 ? 1 : -1) : 0;
    const osc = Math.sin(t * (0.6 + 1.2 * d) + e * TAU);
    let x, y, rotta = ROTTA;
    if (O.motion === 'fall' || O.motion === 'rise' || O.motion === 'drift') {
      const ux = Math.cos(ROTTA), uy = Math.sin(ROTTA);
      const LW = W + 2 * MARG, LH = H + 2 * MARG;
      x = mod(a * LW + ux * v * t - uy * osc * VOL, LW) - MARG;
      y = mod(b * LH + uy * v * t + ux * osc * VOL, LH) - MARG;
    } else if (O.motion === 'float') {
      const fr = 0.15 + v / 200;
      x = a * W + Math.sin(t * fr * (0.5 + c) + e * TAU) * VOL + Math.sin(t * fr * 1.7 + m * TAU) * VOL * 0.3;
      y = b * H + Math.cos(t * fr * (0.4 + d) + f * TAU) * VOL;
    } else if (O.motion === 'burst') {
      // ogni esplosione ha le sue rotte: i numeri della particella ruotano col giro
      const k = Math.floor(t / O.interval), tl = t - k * O.interval;
      if (tl > O.life) continue;
      rotta = O.direction * RAD + (mod(a + k * 0.618, 1) - 0.5) * O.spread * RAD;
      const vv = v * (0.35 + 0.65 * mod(b + k * 0.382, 1));
      x = O.origin[0] * W + Math.cos(rotta) * vv * tl;
      y = O.origin[1] * H + Math.sin(rotta) * vv * tl + 0.5 * O.gravity * O.k * tl * tl;
      if (O.fade) al *= 1 - tl / O.life;
    } else {
      x = a * W + osc * VOL * 0.2; y = b * H;
      if (O.fade) al *= Math.sin(Math.PI * mod(t / O.life + e, 1));
    }
    if (O.twinkle) al *= 1 - O.twinkle * (0.5 + 0.5 * Math.sin(t * (2 + 5 * d) + e * TAU));
    // il trattino senza rotazione propria segue il moto, come la pioggia
    if (O.shape === 'line' && !O.spin && O.motion !== 'float' && O.motion !== 'still')
      rot = rotta - Math.PI / 2;
    forma(x, y, r, rot, col, al, sym);
  }
}
function giro() { frame(performance.now() / 1000); requestAnimationFrame(giro); }
giro();
"""
