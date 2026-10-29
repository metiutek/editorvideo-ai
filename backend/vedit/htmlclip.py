"""Clip HTML: grafica animata scritta in HTML/CSS/JS, composta sopra il video.

Lo stesso documento gira in due posti:

- nell'interfaccia, dentro un iframe guidato dalla testina: e' l'anteprima in
  tempo reale, si vede mentre la si scrive e senza renderizzare niente;
- al render, dentro Chromium (Playwright), che lo fotografa fotogramma per
  fotogramma con lo sfondo trasparente. ffmpeg ne fa un ``.mov`` con canale
  alpha (FFV1, senza perdita) che il grafo tratta come una sorgente qualsiasi.

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

import base64
import hashlib
import json
import math
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, NamedTuple

from . import ffmpeg

# Si cambia quando cambia il modo di fotografare: invalida tutta la cache.
# 2: FFV1 al posto di qtrle.
VERSIONE = 2

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
        "no usable Chromium browser for HTML clips ("
        + "; ".join(errori)
        + "). Install Chrome or Edge, or: python -m playwright install chromium"
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


# Le clip si fotografano a blocchi fissi, allineati al tempo della clip: un
# tratto qualsiasi (un segmento d'anteprima, un fotogramma, un pezzo d'export)
# riusa i blocchi gia' fatti. Con la cache per tratto ogni segmento nuovo
# rifotografava tutto: 4 s d'anteprima costavano un minuto di Chromium.
BLOCCO_S = 4.0
# sotto questi fotogrammi (lo scrub chiede un fotogramma) si fotografa il solo
# tratto, se i blocchi non ci sono gia': un blocco intero costerebbe 120 schermate
FOTOGRAMMI_SOLI = 8


def _blocchi(duration: float, fps: float, t0: float, t1: float | None) -> list[tuple[int, int]]:
    """Blocchi ``[da, a)`` di fotogrammi che coprono il tratto [t0, t1] della clip."""
    da, a = frame_range(duration, fps, t0, t1)
    totale = max(1, math.ceil(duration * fps - 1e-6))
    b = max(1, round(BLOCCO_S * fps))
    return [(j * b, min(totale, (j + 1) * b)) for j in range(da // b, (a - 1) // b + 1)]


# Ogni ritocco a una grafica ne lascia una versione nuova in cache, e a piena
# misura una clip lunga pesa piu' di un giga: senza tetto si arrivava a 12 GB.
CACHE_HTML_MB = 4096


def _usato(path: Path, *altri: Path) -> str:
    """Segna i file come usati adesso, per la potatura; ritorna il primo come stringa."""
    for f in (path, *altri):
        try:
            os.utime(f)
        except OSError:
            pass
    return str(path)


def _pronto(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _mancanti(html: str, base: str | None, duration: float, width: int, height: int,
              fps: float, page_w: int, page_h: int, t0: float = 0.0,
              t1: float | None = None) -> list[tuple[int, int, Path]]:
    """Blocchi del tratto ancora da fotografare, ``(da, a, file)``.

    Vuoto se la clip intera c'e' gia', o se il tratto e' un fotogramma dello
    scrub: quello lo fotografa ``rasterize`` da solo, senza blocchi.
    """
    def file(da: int, a: int) -> Path:
        return _cache_dir() / f"{firma(html, base, width, height, fps, page_w, page_h, da, a)}.mov"

    tutta = frame_range(duration, fps)
    for intera in (file(*tutta), _cache_dir() / (
            f"{firma(html, base, page_w, page_h, fps, page_w, page_h, *tutta)}.mov")):
        if _pronto(intera):
            return []
    mancano = [(da, a, file(da, a)) for da, a in _blocchi(duration, fps, t0, t1)
               if not _pronto(file(da, a))]
    da, a = frame_range(duration, fps, t0, t1)
    if mancano and a - da <= FOTOGRAMMI_SOLI:
        return []
    return mancano


def rasterize(html: str, *, base: str | None, duration: float, width: int, height: int,
              fps: float, page_w: int, page_h: int, t0: float = 0.0,
              t1: float | None = None) -> tuple[str, float]:
    """Fotografa il tratto della clip e ritorna ``(file, tempo del primo fotogramma)``.

    Il file e' un .mov se il tratto sta in un blocco, altrimenti un elenco
    ``ffconcat`` dei blocchi, che ffmpeg legge in fila senza ricodifica. I
    blocchi stanno in cache per contenuto: rifare il render di un progetto con
    la stessa grafica non riapre il browser.
    """
    def file(da: int, a: int) -> Path:
        return _cache_dir() / f"{firma(html, base, width, height, fps, page_w, page_h, da, a)}.mov"

    def lavoro(da: int, a: int, out: Path) -> _Lavoro:
        return _Lavoro(html, base, width, height, fps, page_w, page_h, da, a, out)

    # la clip intera gia' fotografata (un export di prima) copre ogni tratto,
    # anche a piena misura per un'anteprima piu' piccola: il grafo la riduce
    tutta = frame_range(duration, fps)
    for intera in (file(*tutta), _cache_dir() / (
            f"{firma(html, base, page_w, page_h, fps, page_w, page_h, *tutta)}.mov")):
        if _pronto(intera):
            return _usato(intera), 0.0
    blocchi = [(da, a, file(da, a)) for da, a in _blocchi(duration, fps, t0, t1)]
    mancano = [x for x in blocchi if not _pronto(x[2])]
    da, a = frame_range(duration, fps, t0, t1)
    if mancano and a - da <= FOTOGRAMMI_SOLI:
        # un fotogramma dello scrub: i suoi soli fotogrammi, non 4 s per clip
        solo = file(da, a)
        if not _pronto(solo):
            _fotografa([lavoro(da, a, solo)])
        return _usato(solo), da / fps
    if mancano:
        _fotografa([lavoro(*x) for x in mancano])
    primo = blocchi[0][0] / fps
    if len(blocchi) == 1:
        return _usato(blocchi[0][2]), primo
    # Con la durata di ogni blocco scritta, ffmpeg salta dritto al blocco
    # dell'attacco; senza, per sapere dove cade decodificava tutti quelli
    # prima: un pezzo d'export al minuto otto rileggeva otto minuti di
    # grafica, e un video di nove minuti restava a lungo fermo al 93%.
    righe = [f"file '{x[2].name}'\nduration {(x[1] - x[0]) / fps!r}\n" for x in blocchi]
    elenco = _cache_dir() / f"{hashlib.sha1(''.join(righe).encode()).hexdigest()[:20]}.ffconcat"
    if not _pronto(elenco):
        tmp = elenco.with_name(f"~{os.getpid()}_{elenco.name}")
        tmp.write_text("ffconcat version 1.0\n" + "".join(righe), encoding="utf-8")
        os.replace(tmp, elenco)
    return _usato(elenco, *(x[2] for x in blocchi)), primo


class _Lavoro(NamedTuple):
    """Un blocco di fotogrammi ``[da, a)`` di una clip, da scrivere in ``out``."""
    html: str
    base: str | None
    width: int
    height: int
    fps: float
    page_w: int
    page_h: int
    da: int
    a: int
    out: Path


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise HtmlNonDisponibile(
            "HTML clips need Playwright: pip install \"vedit-mcp[html]\" "
            "(or pip install playwright). It uses Chrome or Edge if installed; "
            "if they are missing: python -m playwright install chromium"
        ) from exc
    return sync_playwright


def _fotografa(lavori: list[_Lavoro], paralleli: int = 1,
               avanza: Callable[[int], None] | None = None) -> None:
    """Fotografa i blocchi con ``paralleli`` browser che si dividono la coda.

    Un blocco non dipende dagli altri (la pagina avanza dal suo zero fino al
    primo fotogramma del blocco), quindi anche una clip lunga si divide tra
    piu' browser. Fotografare e' quasi tutto attesa di Chromium: con un browser
    per clip, nove minuti di grafica in tre clip lunghe erano due ore e mezza
    di export.
    """
    sync_playwright = _playwright()
    coda: queue.Queue[_Lavoro] = queue.Queue()
    for x in lavori:
        coda.put(x)
    errori: list[BaseException] = []

    def operaio() -> None:
        pagina: _Pagina | None = None
        try:
            with sync_playwright() as pw:
                browser = _lancia(pw)
                try:
                    while not errori:
                        try:
                            x = coda.get_nowait()
                        except queue.Empty:
                            return
                        if pagina is None or not pagina.serve(x):
                            # una clip alla volta per browser: quella di prima non serve piu'
                            if pagina is not None:
                                pagina.chiudi()
                            pagina = None
                            pagina = _Pagina(browser, x)
                        pagina.blocco(x, avanza)
                finally:
                    if pagina is not None:
                        pagina.chiudi()
                    browser.close()
        except BaseException as exc:  # noqa: BLE001 - riportato a chi ha chiesto
            errori.append(exc)

    quanti = max(1, min(paralleli, len(lavori)))
    if quanti == 1:
        operaio()
    else:
        fili = [threading.Thread(target=operaio, name=f"html-{i}", daemon=True)
                for i in range(quanti)]
        for f in fili:
            f.start()
        for f in fili:
            f.join()
    if errori:
        raise errori[0]


class _Pagina:
    """Una clip aperta in Chromium, pronta a fotografarne i blocchi."""

    def __init__(self, browser, x: _Lavoro):
        self.x = x
        base_href = Path(x.base).resolve().as_uri() + "/" if x.base else None
        self.file = _cache_dir() / f"~{os.getpid()}_{threading.get_ident()}_{x.out.stem}.html"
        self.file.write_text(compose(x.html, x.fps, base_href), encoding="utf-8")
        self.errori_js: list[str] = []
        self.page = browser.new_page(
            viewport={"width": int(x.page_w), "height": int(x.page_h)},
            device_scale_factor=max(0.05, x.width / float(x.page_w)),
        )
        self.page.on("pageerror", lambda e: self.errori_js.append(str(e)))
        self._carica()
        # cattura diretta, sfondo trasparente impostato una volta: page.screenshot()
        # rifa' a ogni scatto quel giro e l'attesa dei font, e costava il doppio
        self.cdp = self.page.context.new_cdp_session(self.page)
        self.cdp.send("Emulation.setDefaultBackgroundColorOverride",
                      {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})

    def serve(self, x: _Lavoro) -> bool:
        return x[:7] == self.x[:7]

    def _carica(self) -> None:
        self.page.goto(self.file.as_uri(), wait_until="load", timeout=60_000)
        self.page.evaluate("() => document.fonts ? document.fonts.ready.then(() => 1) : 1")

    def seek(self, t: float) -> None:
        # una pagina con stato script non torna indietro: si ricarica e si riparte
        if self.page.evaluate("(t) => window.__vedit.seek(t)", t) == "reload":
            self._carica()
            self.page.evaluate("(t) => window.__vedit.seek(t)", t)

    def blocco(self, x: _Lavoro, avanza: Callable[[int], None] | None = None) -> None:
        tmp = x.out.with_name(f"~{os.getpid()}_{threading.get_ident()}_{x.out.name}")
        args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "image2pipe", "-framerate", repr(float(x.fps)), "-c:v", "png", "-i", "-",
                # dimensioni esatte: il fattore di scala del browser arrotonda
                "-vf", f"scale={x.width}:{x.height}:flags=bicubic,format=bgra",
                # FFV1 e non qtrle: sempre senza perdita, alpha compreso, ma un
                # blocco 1080p da 4 s pesa 100-150 MB invece di 500-700, e si
                # scrive tre volte piu' in fretta. Con qtrle l'export di un video
                # di nove minuti tutto in html riempiva 71 GB di disco.
                "-c:v", "ffv1", "-level", "3", "-slices", "16", "-g", "1",
                "-f", "mov", str(tmp)]
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for i in range(x.da, x.a):
                self.seek(i / x.fps)
                png = _schermata(self.page, self.cdp)
                assert proc.stdin is not None
                proc.stdin.write(png)
                if avanza:
                    avanza(1)
            assert proc.stdin is not None
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            if proc.wait() != 0:
                raise RuntimeError(f"ffmpeg did not accept the frames of the HTML clip: {err[-400:]}")
            os.replace(tmp, x.out)
        except BaseException:
            proc.kill()
            tmp.unlink(missing_ok=True)
            raise

    def chiudi(self) -> None:
        try:
            self.page.close()
        except Exception:  # noqa: BLE001 - il browser puo' essere gia' andato
            pass
        self.file.unlink(missing_ok=True)
        if self.errori_js:
            # non blocca: la pagina puo' avere un errore innocuo, ma va detto
            (_cache_dir() / f"{self.x.out.stem}.log").write_text(
                "\n".join(self.errori_js), encoding="utf-8")


def _schermata(page, cdp=None) -> bytes:
    """Una schermata, riprovata: sotto carico Chromium ogni tanto non la consegna.

    ``Unable to capture screenshot`` con la CPU piena di ffmpeg buttava via
    l'intero export per un fotogramma. Il primo tentativo passa da CDP con
    ``optimizeForSpeed`` (compressione png leggera, meta' del tempo); i
    ripieghi dalla strada di Playwright.
    """
    for prova in range(3):
        try:
            if cdp is not None and prova == 0:
                dati = cdp.send("Page.captureScreenshot",
                                {"format": "png", "optimizeForSpeed": True})["data"]
                return base64.b64decode(dati)
            return page.screenshot(type="png", omit_background=True)
        except Exception:  # noqa: BLE001 - l'errore di Playwright non ha un tipo utile
            if prova == 2:
                raise
            time.sleep(0.2 * (prova + 1))
    raise AssertionError("irraggiungibile")


def prepare(project, *, width: int, height: int, fps: float,
            start: float | None = None, end: float | None = None,
            on_progress: Callable[[int, int], None] | None = None) -> dict[str, tuple[str, float]]:
    """Rasterizza le clip HTML che cadono nel tratto [start, end) della timeline.

    Ritorna ``clip_id -> (file, tempo del primo fotogramma)`` per CompileOptions.
    Nel render di un solo fotogramma si fotografa solo quel pezzetto, non tutta
    la clip. ``on_progress(fatti, totale)`` conta i fotogrammi fotografati: in
    un export di sola grafica sono quasi tutto il tempo, e senza la barra
    restava a zero per minuti.
    """
    s = project.settings
    a = 0.0 if start is None else float(start)
    b = project.duration() if end is None else float(end)
    clip = []
    for track in project.live_tracks("video"):
        for c in track.clips:
            if c.type != "html" or not c.enabled or c.duration <= 0:
                continue
            if c.end <= a or c.start >= b:
                continue
            clip.append((c, max(0.0, a - c.start), min(c.duration, b - c.start)))

    def misure(c) -> dict:
        return dict(base=c.html_base, duration=c.duration, width=width, height=height,
                    fps=fps, page_w=int(s.width), page_h=int(s.height))

    # Prima i blocchi mancanti di tutte le clip, divisi tra i browser; poi
    # rasterize li trova pronti e mette solo insieme i file.
    lavori = []
    for c, t0, t1 in clip:
        m = misure(c)
        lavori += [_Lavoro(c.html or "", m["base"], width, height, fps, m["page_w"], m["page_h"],
                           da, a_, out)
                   for da, a_, out in _mancanti(c.html or "", t0=t0, t1=t1, **m)]
    if lavori:
        from . import proxy

        # prima di fotografare, non solo dopo: le versioni vecchie liberano il
        # posto per le nuove, invece di trovare il disco gia' pieno
        proxy.pota(_cache_dir(), proxy.tetto_mb("VEDIT_CACHE_HTML_MB", CACHE_HTML_MB))
        totale = sum(x.a - x.da for x in lavori)
        contati = [0]
        lock = threading.Lock()

        def avanza(n: int) -> None:
            with lock:
                contati[0] += n
                k = contati[0]
            if on_progress:
                on_progress(k, totale)

        _fotografa(lavori, _browser_paralleli(len(lavori)), avanza)

    fatti = {c.id: rasterize(c.html or "", t0=t0, t1=t1, **misure(c)) for c, t0, t1 in clip}
    if clip:
        from . import proxy

        proxy.pota(_cache_dir(), proxy.tetto_mb("VEDIT_CACHE_HTML_MB", CACHE_HTML_MB))
    return fatti


# Memoria di un Chromium headless con una pagina 1080p: misurati 115 MB
# privati, il doppio per le pagine con canvas. La stima di 500 MB, con il
# margine dei pezzi di ffmpeg, lasciava un browser solo su un PC da 16 GB con
# un paio di giga liberi: un export di sola grafica andava a un quinto.
MEMORIA_BROWSER = 250 * 2**20
MEMORIA_RISERVA_BROWSER = 512 * 2**20


def _browser_paralleli(n: int) -> int:
    from .render import memoria_libera

    # misurato a 1080p: quattro browser fotografano cinque volte uno solo,
    # otto quanto quattro (il compositore e' gia' saturo)
    quanti = min(n, 4, max(1, (os.cpu_count() or 2) // 4))
    libera = memoria_libera()
    if libera is not None:
        quanti = min(quanti, max(1, int((libera - MEMORIA_RISERVA_BROWSER) // MEMORIA_BROWSER)))
    return max(1, quanti)
