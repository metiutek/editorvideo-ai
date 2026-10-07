"""Clip HTML: grafica animata scritta in HTML/CSS/JS, composta sopra il video.

Lo stesso documento gira in due posti:

- nell'interfaccia, dentro un iframe guidato dalla testina: e' l'anteprima in
  tempo reale, si vede mentre la si scrive e senza renderizzare niente;
- al render, dentro Chromium (Playwright), che lo fotografa fotogramma per
  fotogramma con lo sfondo trasparente. ffmpeg ne fa un ``.mov`` con canale
  alpha (qtrle) che il grafo tratta come una sorgente qualsiasi.

Perche' le due cose mostrino lo stesso fotogramma, il tempo della pagina non e'
quello della macchina. ``OROLOGIO`` sostituisce ``performance.now``, ``Date``,
``requestAnimationFrame``, ``setTimeout``/``setInterval``, congela le animazioni
CSS e Web Animations e poi fa avanzare tutto a passi di ``1/fps``. Anteprima e
render fanno gli stessi passi: GSAP, anime.js, canvas con rAF, transizioni CSS
e keyframe CSS arrivano tutti allo stesso istante per la stessa strada.

Chi vuole il controllo totale definisce ``window.veditRender = (t) => {...}``:
viene chiamata a ogni fotogramma con il tempo locale della clip in secondi, ed
e' anche l'unico modo per tornare indietro nell'anteprima senza ricaricare la
pagina (lo stato di uno script non si riavvolge).

Le misure sono quelle del progetto: la pagina e' larga ``settings.width`` pixel
CSS e alta ``settings.height``, anche quando l'anteprima e' piu' piccola. Si
rimpicciolisce l'immagine, non si cambia l'impaginazione.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path

from . import ffmpeg

# Si cambia quando cambia il modo di fotografare: invalida tutta la cache.
VERSIONE = 1

MAX_HTML = 2_000_000  # caratteri: un documento piu' grande e' quasi certamente un errore

OROLOGIO = r"""
(() => {
  if (window.__vedit) return;
  const FPS = __FPS__;
  const PASSO = 1000 / FPS;
  const veri = {
    setTimeout: window.setTimeout.bind(window),
    Date: window.Date,
  };
  const epoca = veri.Date.now();
  let vt = 0;              // millisecondi virtuali dall'inizio della clip
  let fotogramma = 0;      // indice del fotogramma corrente
  let usaOrologio = false; // la pagina ha programmato qualcosa nel tempo
  let timers = new Map();
  let prossimo = 1;
  let raf = new Map();

  // ---- il tempo della pagina e' il nostro ---------------------------------
  try { performance.now = () => vt; } catch (e) {}
  try { Object.defineProperty(performance, 'now', { value: () => vt, configurable: true }); } catch (e) {}
  class VDate extends veri.Date {
    constructor(...a) { if (a.length) super(...a); else super(epoca + vt); }
    static now() { return epoca + vt; }
  }
  window.Date = VDate;
  window.requestAnimationFrame = (cb) => {
    usaOrologio = true;
    const id = prossimo++;
    raf.set(id, cb);
    return id;
  };
  window.cancelAnimationFrame = (id) => { raf.delete(id); };
  const programma = (cb, ms, args, ripeti) => {
    usaOrologio = true;
    const id = prossimo++;
    const passo = Math.max(ripeti ? 1 : 0, Number(ms) || 0);
    timers.set(id, { at: vt + passo, cb, args, ogni: ripeti ? passo : 0 });
    return id;
  };
  window.setTimeout = (cb, ms, ...args) => programma(cb, ms, args, false);
  window.setInterval = (cb, ms, ...args) => programma(cb, ms, args, true);
  window.clearTimeout = window.clearInterval = (id) => { timers.delete(id); };

  // ---- animazioni CSS e Web Animations: ferme, le muoviamo noi --------------
  // L'istante in cui un'animazione compare e' il suo zero: una transizione
  // innescata da una classe aggiunta a 1.2s parte da li', non da inizio pagina.
  const nate = new WeakMap();
  const muoviAnimazioni = () => {
    if (!document.getAnimations) return;
    for (const a of document.getAnimations()) {
      if (!nate.has(a)) nate.set(a, vt);
      try { a.pause(); a.currentTime = vt - nate.get(a); } catch (e) {}
    }
  };

  const chiama = (cb, args) => {
    try { if (typeof cb === 'function') cb(...args); } catch (e) { console.error(e); }
  };

  /** Un passo di orologio: timer scaduti in ordine, poi un giro di rAF. */
  const passo = (nuovo) => {
    vt = nuovo;
    for (let giri = 0; giri < 100000; giri++) {
      let primo = null;
      for (const [id, t] of timers) {
        if (t.at <= vt + 1e-6 && (!primo || t.at < primo[1].at)) primo = [id, t];
      }
      if (!primo) break;
      const [id, t] = primo;
      if (t.ogni) t.at += t.ogni; else timers.delete(id);
      chiama(t.cb, t.args);
    }
    const giro = [...raf.values()];
    raf = new Map();
    for (const cb of giro) chiama(cb, [vt]);
    muoviAnimazioni();
  };

  /**
   * Porta la pagina al tempo `sec` (secondi locali della clip).
   * Torna 'ok', oppure 'reload' se si chiede di tornare indietro a una pagina
   * che ha uno stato script: quello non si riavvolge, va ricaricata.
   */
  const seek = (sec) => {
    const meta = Math.max(0, Math.round((Number(sec) || 0) * FPS));
    const liscia = typeof window.veditRender === 'function' || !usaOrologio;
    if (meta < fotogramma) {
      if (!liscia) return 'reload';
      fotogramma = meta;
      vt = meta * PASSO;
      muoviAnimazioni();
    }
    while (fotogramma < meta) {
      fotogramma += 1;
      passo(fotogramma * PASSO);
    }
    if (meta === 0) muoviAnimazioni();
    if (typeof window.veditRender === 'function') chiama(window.veditRender, [vt / 1000]);
    try { window.dispatchEvent(new CustomEvent('vedit:frame', { detail: { t: vt / 1000 } })); } catch (e) {}
    return 'ok';
  };

  window.__vedit = { seek, get t() { return vt / 1000; }, fps: FPS };

  // ---- pilotaggio dall'interfaccia (iframe in sandbox: solo messaggi) -------
  // Fino al load i comandi si ignorano: un seek arrivato a meta' parsing
  // farebbe avanzare l'orologio prima che gli script della pagina esistano, e
  // i loro timer partirebbero gia' in ritardo. A load fatto si dice "ready" e
  // l'interfaccia rimanda il tempo della testina.
  let caricata = false;
  window.addEventListener('message', (ev) => {
    const d = ev.data;
    if (!caricata || !d || d.vedit !== 'seek') return;
    if (seek(d.t) === 'reload') parent.postMessage({ vedit: 'reload' }, '*');
  });
  const pronto = () => {
    caricata = true;
    seek(0);
    if (parent !== window) parent.postMessage({ vedit: 'ready' }, '*');
  };
  if (document.readyState === 'complete') veri.setTimeout(pronto, 0);
  else window.addEventListener('load', pronto);
})();
"""

# Un documento senza sfondo deve restare trasparente anche nell'iframe: senza
# questo Chromium dipinge il fondo opaco quando lo schema colori della pagina
# ospite (scuro) e' diverso da quello del documento.
_STILE_BASE = "<style>html,body{margin:0;background:transparent}:root{color-scheme:normal}</style>"


def esc_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def compose(html: str, fps: float, base_href: str | None = None) -> str:
    """Documento pronto da caricare: orologio virtuale prima di ogni script.

    L'orologio va iniettato *dentro* ``<head>``: messo prima del doctype la
    pagina finirebbe in quirks mode e impaginerebbe diversamente.
    """
    testa = ""
    if base_href:
        testa += f'<base href="{esc_attr(base_href)}">'
    testa += _STILE_BASE
    testa += "<script>" + OROLOGIO.replace("__FPS__", repr(float(fps))) + "</script>"

    for pattern in (r"<head\b[^>]*>", r"<html\b[^>]*>", r"<!doctype[^>]*>"):
        m = re.search(pattern, html, flags=re.IGNORECASE)
        if m:
            if pattern.startswith("<!doctype"):
                return html[: m.end()] + "<head>" + testa + "</head>" + html[m.end():]
            return html[: m.end()] + testa + html[m.end():]
    return "<!doctype html><html><head>" + testa + "</head><body>" + html + "</body></html>"


def template(width: int, height: int) -> str:
    """Punto di partenza per una clip nuova: un sottopancia che entra ed esce."""
    return f"""<!doctype html>
<html>
<head>
<style>
  /* la pagina e' grande quanto il progetto: {width}x{height} pixel */
  body {{ width: {width}px; height: {height}px; overflow: hidden;
         font-family: system-ui, Segoe UI, Helvetica, Arial, sans-serif; }}
  .barra {{ position: absolute; left: 6%; bottom: 12%; display: flex; align-items: stretch;
           animation: entra 0.7s cubic-bezier(.2,.8,.2,1) both, esce 0.5s ease-in 2.5s forwards; }}
  .accento {{ width: 12px; background: #ffcc00; }}
  .testo {{ background: rgba(10,10,14,.85); color: white; padding: 18px 28px; }}
  .nome {{ font-size: 54px; font-weight: 700; letter-spacing: .5px; }}
  .ruolo {{ font-size: 30px; opacity: .8; margin-top: 4px; }}
  @keyframes entra {{ from {{ transform: translateX(-120%); opacity: 0 }} to {{ transform: none; opacity: 1 }} }}
  @keyframes esce {{ to {{ transform: translateY(40px); opacity: 0 }} }}
</style>
</head>
<body>
  <div class="barra"><div class="accento"></div>
    <div class="testo"><div class="nome">Nome Cognome</div><div class="ruolo">Ruolo</div></div>
  </div>
</body>
</html>
"""


# --------------------------------------------------------------------------
# rasterizzazione
# --------------------------------------------------------------------------


class HtmlNonDisponibile(RuntimeError):
    """Manca Playwright o un browser Chromium: la clip HTML non si puo' rendere."""


def _cache_dir() -> Path:
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")) / "html"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _lancia(pw):
    """Chromium di Playwright, se scaricato; altrimenti Chrome o Edge di sistema.

    Edge c'e' su ogni Windows: cosi' basta ``pip install playwright`` senza il
    download del browser.
    """
    errori = []
    for canale in (None, "chrome", "msedge"):
        try:
            return pw.chromium.launch(channel=canale) if canale else pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - ogni canale fallisce a modo suo
            errori.append(f"{canale or 'chromium'}: {str(exc).splitlines()[0][:100]}")
    raise HtmlNonDisponibile(
        "nessun browser Chromium utilizzabile per le clip HTML ("
        + "; ".join(errori)
        + "). Installa Chrome o Edge, oppure: python -m playwright install chromium"
    )


def firma(html: str, base: str | None, width: int, height: int, fps: float,
          page_w: int, page_h: int, da: int, a: int) -> str:
    blob = json.dumps([VERSIONE, html, base or "", width, height, round(fps, 6),
                       page_w, page_h, da, a])
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]


def frame_range(duration: float, fps: float, t0: float = 0.0, t1: float | None = None) -> tuple[int, int]:
    """Fotogrammi [da, a) da fotografare per il tratto [t0, t1] della clip."""
    totale = max(1, math.ceil(duration * fps - 1e-6))
    t1 = duration if t1 is None else min(duration, t1)
    da = max(0, min(totale - 1, int(math.floor(t0 * fps + 1e-6))))
    a = max(da + 1, min(totale, int(math.ceil(t1 * fps - 1e-6)) + 1))
    return da, a


def rasterize(html: str, *, base: str | None, duration: float, width: int, height: int,
              fps: float, page_w: int, page_h: int, t0: float = 0.0,
              t1: float | None = None) -> tuple[str, float]:
    """Fotografa la clip e ritorna ``(percorso .mov, tempo del primo fotogramma)``.

    Il risultato sta in cache per contenuto: rifare il render di un progetto
    con la stessa grafica non riapre il browser.
    """
    da, a = frame_range(duration, fps, t0, t1)
    chiave = firma(html, base, width, height, fps, page_w, page_h, da, a)
    out = _cache_dir() / f"{chiave}.mov"
    if out.exists() and out.stat().st_size > 0:
        return str(out), da / fps

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise HtmlNonDisponibile(
            "le clip HTML vogliono Playwright: pip install \"vedit-mcp[html]\" "
            "(oppure pip install playwright). Usa Chrome o Edge gia' installati; "
            "se mancano: python -m playwright install chromium"
        ) from exc

    pagina = _cache_dir() / f"{chiave}.html"
    base_href = Path(base).resolve().as_uri() + "/" if base else None
    pagina.write_text(compose(html, fps, base_href), encoding="utf-8")

    tmp = out.with_name(f"~{chiave}.mov")
    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "image2pipe", "-framerate", repr(float(fps)), "-c:v", "png", "-i", "-",
            # dimensioni esatte: il fattore di scala del browser arrotonda
            "-vf", f"scale={width}:{height}:flags=bicubic,format=argb",
            "-c:v", "qtrle", "-f", "mov", str(tmp)]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    errore_js: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = _lancia(pw)
            try:
                page = browser.new_page(
                    viewport={"width": int(page_w), "height": int(page_h)},
                    device_scale_factor=max(0.05, width / float(page_w)),
                )
                page.on("pageerror", lambda e: errore_js.append(str(e)))
                page.goto(pagina.as_uri(), wait_until="load", timeout=60_000)
                page.evaluate("() => document.fonts ? document.fonts.ready.then(() => 1) : 1")
                for i in range(da, a):
                    page.evaluate("(t) => window.__vedit.seek(t)", i / fps)
                    png = page.screenshot(type="png", omit_background=True)
                    assert proc.stdin is not None
                    proc.stdin.write(png)
            finally:
                browser.close()
        assert proc.stdin is not None
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg non ha accettato i fotogrammi della clip HTML: {err[-400:]}")
        os.replace(tmp, out)
    except BaseException:
        proc.kill()
        tmp.unlink(missing_ok=True)
        raise
    finally:
        pagina.unlink(missing_ok=True)
    if errore_js:
        # non blocca: la pagina puo' avere un errore innocuo, ma va detto
        (_cache_dir() / f"{chiave}.log").write_text("\n".join(errore_js), encoding="utf-8")
    return str(out), da / fps


def prepare(project, *, width: int, height: int, fps: float,
            start: float | None = None, end: float | None = None) -> dict[str, tuple[str, float]]:
    """Rasterizza le clip HTML che cadono nel tratto [start, end) della timeline.

    Ritorna ``clip_id -> (file, tempo del primo fotogramma)`` per CompileOptions.
    Nel render di un solo fotogramma si fotografa solo quel pezzetto, non tutta
    la clip.
    """
    s = project.settings
    a = 0.0 if start is None else float(start)
    b = project.duration() if end is None else float(end)
    out: dict[str, tuple[str, float]] = {}
    for track in project.live_tracks("video"):
        for c in track.clips:
            if c.type != "html" or not c.enabled or c.duration <= 0:
                continue
            if c.end <= a or c.start >= b:
                continue
            t0 = max(0.0, a - c.start)
            t1 = min(c.duration, b - c.start)
            out[c.id] = rasterize(
                c.html or "", base=c.html_base, duration=c.duration, width=width,
                height=height, fps=fps, page_w=int(s.width), page_h=int(s.height),
                t0=t0, t1=t1,
            )
    return out
