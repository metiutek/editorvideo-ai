"""Particelle: neve, pioggia, scintille, coriandoli, polvere, bokeh, stelle, lucciole.

Diventano una clip html (vedi htmlclip.py) con un canvas trasparente sopra la
ripresa. Ogni particella ha la posizione scritta in *forma chiusa* in funzione
del tempo - niente simulazione passo dopo passo - quindi il fotogramma al
secondo 3.2 e' sempre lo stesso, che lo si guardi in anteprima saltandoci
sopra o che lo si renderizzi partendo da zero. I numeri casuali vengono da un
generatore con seme: stesso ``seed``, stesse particelle.
"""

from __future__ import annotations

import json

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
         density: float = 1.0, speed: float = 1.0, size: float = 1.0, seed: int = 1) -> str:
    """Documento html completo con le particelle richieste."""
    if kind not in KINDS:
        raise ValueError(f"particelle sconosciute {kind!r}; scegli tra {', '.join(KINDS)}")
    colore, base = KINDS[kind]
    area = (width * height) / (1920 * 1080)
    # le dimensioni sono pensate per 1080p: in 4K o in 720p si riscalano
    k = height / 1080.0
    opt = {
        "kind": kind, "seed": int(seed), "color": color or colore,
        "count": max(1, round(base * max(0.0, density) * max(area, 0.05))),
        "speed": float(speed) * k, "size": float(size) * k,
    }
    js = (_JS.replace("__W__", str(int(width))).replace("__H__", str(int(height)))
          .replace("__OPT__", json.dumps(opt)))
    return f"""<!doctype html>
<html>
<head>
<style>
  html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: transparent; }}
  canvas {{ display: block; }}
</style>
</head>
<body>
<!-- particelle {kind}: generate da vedit (particelle.py) -->
<canvas id="c" width="{width}" height="{height}"></canvas>
<script>{js}</script>
</body>
</html>
"""
