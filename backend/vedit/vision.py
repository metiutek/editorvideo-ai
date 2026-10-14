"""Dove sta il soggetto nel fotogramma.

Senza queste coordinate l'editor lavora alla cieca: non puo' mettere una
maschera su un volto, non puo' tenere una persona al centro quando si passa a
9:16, non puo' evitare di coprire chi parla con il testo.

Il rilevamento e' YOLO (ultralytics, modello nano: piccolo e veloce), applicato
a fotogrammi campionati - non a tutti: a 2 campioni al secondo il soggetto non
sparisce, e il costo scende di dieci volte.

Le posizioni grezze **non** si usano mai direttamente: saltano di qualche pixel
a ogni fotogramma e l'inquadratura risulterebbe nervosa. Passano prima per
:func:`smooth`, che e' quello che distingue un reframe guardabile da uno che fa
venire il mal di mare.
"""

from __future__ import annotations

import subprocess
import urllib.request

from . import ffmpeg, probe, proxy

MODEL_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/"
DEFAULT_MODEL = "yolo11n.pt"
SAMPLE_FPS = 2.0
CONF = 0.35
SMOOTH_WINDOW = 5          # campioni: a 2 fps sono 2.5 secondi di memoria


class VisionError(RuntimeError):
    pass


def model_path(name: str = DEFAULT_MODEL) -> str:
    """Percorso del modello nella cache, scaricandolo al primo uso."""
    dst = proxy.cache_dir("models") / name
    if dst.exists() and dst.stat().st_size > 0:
        return str(dst)
    tmp = dst.with_name("~" + name)
    try:
        urllib.request.urlretrieve(MODEL_URL + name, tmp)
        tmp.replace(dst)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise VisionError(f"cannot download the model {name}: {e}") from e
    return str(dst)


def _frames(path: str, fps: float, width: int):
    """Fotogrammi campionati come array BGR (la convenzione che YOLO si aspetta)."""
    import numpy as np

    m = probe.probe(path)
    if not m.has_video:
        raise VisionError(f"{path} has no video")
    h = max(2, int(width * (m.height or 9) / (m.width or 16)) // 2 * 2)
    proc = subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(path), "-an", "-sn",
        "-vf", f"fps={fps},scale={width}:{h},format=bgr24",
        "-f", "rawvideo", "-",
    ], capture_output=True, timeout=3600)
    raw = proc.stdout or b""
    size = width * h * 3
    n = len(raw) // size
    if n == 0:
        raise VisionError(f"no readable frames in {path}")
    buf = np.frombuffer(raw[: n * size], dtype=np.uint8).reshape(n, h, width, 3)
    return buf, (m.width or width, m.height or h), (width, h)


def detect(path: str, classes: tuple[str, ...] = ("person",), fps: float = SAMPLE_FPS,
           conf: float = CONF, width: int = 480, model: str = DEFAULT_MODEL,
           max_frames: int = 900) -> dict:
    """Rilevamenti per fotogramma, in coordinate del video originale."""
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise VisionError("ultralytics not installed: pip install ultralytics") from e

    buf, (ow, oh), (pw, ph) = _frames(path, fps, width)
    if len(buf) > max_frames:
        buf = buf[:max_frames]
    net = YOLO(model_path(model))
    nomi = net.names
    voluti = {c.lower() for c in classes} if classes else None
    kx, ky = ow / pw, oh / ph

    out = []
    for i, frame in enumerate(buf):
        res = net.predict(frame, conf=conf, verbose=False)[0]
        box = []
        for b in res.boxes:
            etichetta = str(nomi[int(b.cls)]).lower()
            if voluti and etichetta not in voluti:
                continue
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            box.append({
                "classe": etichetta, "conf": round(float(b.conf), 3),
                "x": round(x1 * kx, 1), "y": round(y1 * ky, 1),
                "w": round((x2 - x1) * kx, 1), "h": round((y2 - y1) * ky, 1),
            })
        out.append({"t": round(i / fps, 3), "box": box})
    return {"fps": fps, "larghezza": ow, "altezza": oh, "fotogrammi": out,
            "classi": sorted({b["classe"] for f in out for b in f["box"]})}


# --------------------------------------------------------------------------
# dal rilevamento al movimento di camera
# --------------------------------------------------------------------------


def main_subject(frames: list[dict]) -> list[dict]:
    """Un solo soggetto per fotogramma: il piu' grande tra i piu' sicuri.

    Area per confidenza: un rilevamento incerto ma enorme di solito e' lo sfondo,
    uno sicuro e minuscolo e' un passante.
    """
    out = []
    for f in frames:
        if not f["box"]:
            out.append({"t": f["t"], "cx": None, "cy": None, "box": None})
            continue
        b = max(f["box"], key=lambda x: x["w"] * x["h"] * x["conf"])
        out.append({"t": f["t"], "cx": b["x"] + b["w"] / 2,
                    "cy": b["y"] + b["h"] / 2, "box": b})
    return out


def fill_gaps(track: list[dict]) -> list[dict]:
    """Riempie i fotogrammi senza rilevamento tenendo l'ultima posizione nota."""
    out = [dict(p) for p in track]
    ultimo = None
    for p in out:
        if p["cx"] is None:
            if ultimo is not None:
                p["cx"], p["cy"] = ultimo
        else:
            ultimo = (p["cx"], p["cy"])
    # i primi fotogrammi senza rilevamento prendono il primo valore utile
    primo = next((p for p in out if p["cx"] is not None), None)
    if primo:
        for p in out:
            if p["cx"] is None:
                p["cx"], p["cy"] = primo["cx"], primo["cy"]
    return out


def smooth(track: list[dict], window: int = SMOOTH_WINDOW) -> list[dict]:
    """Media mobile centrata: toglie il tremolio senza inseguire ogni scatto."""
    if window <= 1 or not track:
        return [dict(p) for p in track]
    out = []
    meta = window // 2
    for i, p in enumerate(track):
        a, b = max(0, i - meta), min(len(track), i + meta + 1)
        finestra = [q for q in track[a:b] if q["cx"] is not None]
        if not finestra or p["cx"] is None:
            out.append(dict(p))
            continue
        q = dict(p)
        q["cx"] = round(sum(x["cx"] for x in finestra) / len(finestra), 2)
        q["cy"] = round(sum(x["cy"] for x in finestra) / len(finestra), 2)
        out.append(q)
    return out


def reframe_keyframes(track: list[dict], src_w: int, src_h: int,
                      out_w: int, out_h: int) -> dict:
    """Scala e panoramica per tenere il soggetto al centro nel nuovo formato.

    ``scale`` copre il canvas di destinazione; ``x``/``y`` sono offset in pixel
    dal centro (la convenzione di Transform) e vengono limitati perche' non
    compaia mai il vuoto oltre il bordo dell'immagine.
    """
    scale = max(out_w / src_w, out_h / src_h)
    vis_w, vis_h = src_w * scale, src_h * scale
    max_x = max(0.0, (vis_w - out_w) / 2)
    max_y = max(0.0, (vis_h - out_h) / 2)

    kx, ky = [], []
    for p in track:
        if p["cx"] is None:
            continue
        dx = -(p["cx"] - src_w / 2) * scale
        dy = -(p["cy"] - src_h / 2) * scale
        kx.append({"t": p["t"], "v": round(max(-max_x, min(max_x, dx)), 1)})
        ky.append({"t": p["t"], "v": round(max(-max_y, min(max_y, dy)), 1)})
    return {"scale": round(scale, 4), "x": {"kf": kx}, "y": {"kf": ky},
            "limite_x": round(max_x, 1), "limite_y": round(max_y, 1)}


def mask_keyframes(track: list[dict], padding: float = 1.25) -> dict:
    """Riquadro che segue il soggetto: parametri pronti per mask_blur/mask_box."""
    utili = [p for p in track if p["box"]]
    if not utili:
        raise VisionError("no subject detected: nothing to mask")
    w = max(p["box"]["w"] for p in utili) * padding
    h = max(p["box"]["h"] for p in utili) * padding
    kx = [{"t": p["t"], "v": round(p["cx"] - w / 2, 1)} for p in track if p["cx"] is not None]
    ky = [{"t": p["t"], "v": round(p["cy"] - h / 2, 1)} for p in track if p["cy"] is not None]
    return {"w": int(w), "h": int(h), "x": {"kf": kx}, "y": {"kf": ky}}


def to_canvas(track: list[dict], fit: str, src_w: int, src_h: int,
              out_w: int, out_h: int) -> list[dict]:
    """Traccia dai pixel della sorgente ai pixel del canvas.

    Gli effetti di una clip lavorano *dopo* l'adattamento al canvas (graph:
    ``_fit`` poi la catena), quindi una maschera in pixel della sorgente su un
    4K in un progetto 1080p finiva al doppio della distanza dall'angolo.
    """
    if fit == "none":
        kx = ky = 1.0
        ox = oy = 0.0
    elif fit == "stretch":
        kx, ky = out_w / src_w, out_h / src_h
        ox = oy = 0.0
    else:
        k = (max if fit == "cover" else min)(out_w / src_w, out_h / src_h)
        kx = ky = k
        ox, oy = out_w / 2 - src_w * k / 2, out_h / 2 - src_h * k / 2
    out = []
    for p in track:
        q = dict(p)
        if p.get("cx") is not None:
            q["cx"], q["cy"] = round(p["cx"] * kx + ox, 2), round(p["cy"] * ky + oy, 2)
        if p.get("box"):
            b = p["box"]
            q["box"] = {**b, "x": round(b["x"] * kx + ox, 1), "y": round(b["y"] * ky + oy, 1),
                        "w": round(b["w"] * kx, 1), "h": round(b["h"] * ky, 1)}
        out.append(q)
    return out


# --------------------------------------------------------------------------
# tracking di un oggetto qualsiasi: si indica il riquadro, lo si segue
# --------------------------------------------------------------------------

BOX_FPS = 8.0
BOX_MIN_SCORE = 0.45       # sotto, il riquadro trovato non somiglia all'oggetto


def box_in_pixel(box: list[float], src_w: int, src_h: int) -> tuple[float, float, float, float]:
    """``[x, y, w, h]`` in frazioni del fotogramma (0..1) oppure in pixel della sorgente."""
    if len(box) != 4:
        raise VisionError("box needs four numbers: [x, y, width, height]")
    x, y, w, h = (float(v) for v in box)
    if max(x, y, w, h) <= 1.0:
        x, y, w, h = x * src_w, y * src_h, w * src_w, h * src_h
    if w < 4 or h < 4:
        raise VisionError("box too small: at least a few pixels per side")
    x, y = max(0.0, min(x, src_w - w)), max(0.0, min(y, src_h - h))
    return x, y, min(w, src_w), min(h, src_h)


def _grigi(path: str, t0: float, t1: float, fps: float, width: int):
    """Fotogrammi in scala di grigi del tratto t0..t1, come float32."""
    import numpy as np

    m = probe.probe(path)
    if not m.has_video:
        raise VisionError(f"{path} has no video")
    width = min(width, m.width or width) // 2 * 2
    h = max(2, int(width * (m.height or 9) / (m.width or 16)) // 2 * 2)
    cmd = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error"]
    if t0 > 0:
        cmd += ["-ss", f"{t0:.3f}"]
    cmd += ["-t", f"{max(0.05, t1 - t0):.3f}", "-i", str(path), "-an", "-sn",
            "-vf", f"fps={fps},scale={width}:{h},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=3600).stdout or b""
    n = len(raw) // (width * h)
    if n == 0:
        raise VisionError(f"no readable frames in {path}")
    buf = np.frombuffer(raw[: n * width * h], dtype=np.uint8).reshape(n, h, width)
    return buf.astype(np.float32), (m.width or width, m.height or h), (width, h)


def ncc(regione, modello):
    """Correlazione normalizzata del modello in ogni posizione della regione.

    Con la FFT per il prodotto e le immagini integrali per media e varianza di
    ogni finestra: e' la stessa misura di cv2.matchTemplate(TM_CCOEFF_NORMED)
    senza tirarsi dietro OpenCV. Valori in -1..1, 1 = identico.
    """
    import numpy as np

    h, w = modello.shape
    H, W = regione.shape
    t = modello - modello.mean()
    tn = float(np.sqrt((t * t).sum()))
    if tn < 1e-3 or H < h or W < w:
        return None
    F = np.fft.rfft2(regione)
    T = np.fft.rfft2(t[::-1, ::-1], s=regione.shape)
    corr = np.fft.irfft2(F * T, s=regione.shape)[h - 1:, w - 1:]

    def finestre(a):
        ii = np.zeros((H + 1, W + 1), dtype=np.float64)
        ii[1:, 1:] = a.cumsum(0).cumsum(1)
        return ii[h:, w:] - ii[:-h, w:] - ii[h:, :-w] + ii[:-h, :-w]

    s1 = finestre(regione)
    s2 = finestre(regione.astype(np.float64) ** 2)
    var = np.maximum(s2 - s1 * s1 / (h * w), 1e-6)
    return corr / (np.sqrt(var) * tn)


def track_box(path: str, box: list[float], t: float, t0: float = 0.0,
              t1: float | None = None, fps: float = BOX_FPS, width: int = 320) -> dict:
    """Segue l'oggetto racchiuso da ``box`` al tempo ``t`` della sorgente.

    YOLO conosce ottanta classi: un logo, una tazza particolare, un pallone in
    mezzo al campo, una parte di macchina restano fuori. Qui l'oggetto lo indica
    chi monta: il riquadro diventa un modello che si cerca, fotogramma dopo
    fotogramma, in un intorno dell'ultima posizione — avanti e indietro da
    ``t``. Il modello si aggiorna piano (10% a passo) per seguire luce e
    rotazione senza scivolare sullo sfondo; quando la somiglianza crolla il
    punto e' perso e la ricerca si allarga.

    Ritorna la stessa forma di :func:`follow`, quindi maschere, aggancio e
    reframe funzionano identici. Non segue cambi di scala forti: il riquadro
    resta della misura indicata.
    """
    import numpy as np

    durata = probe.probe(path).duration or 0.0
    fine = t1 if t1 is not None else durata
    if fine <= t0:
        raise VisionError("empty range: nothing to track")
    t = max(t0, min(float(t), fine))
    buf, (ow, oh), (pw, ph) = _grigi(path, t0, fine, fps, width)
    k = pw / ow
    bx, by, bw, bh = box_in_pixel(box, ow, oh)
    bx, by = int(round(bx * k)), int(round(by * k))
    bw, bh = max(6, int(round(bw * k))), max(6, int(round(bh * k)))
    bx, by = min(bx, pw - bw), min(by, ph - bh)
    n = len(buf)
    i0 = max(0, min(n - 1, int(round((t - t0) * fps))))
    base = buf[i0][by:by + bh, bx:bx + bw].copy()

    pos: list[tuple[int, int] | None] = [None] * n
    punteggi = [0.0] * n
    pos[i0], punteggi[i0] = (bx, by), 1.0

    def corsa(indici):
        x, y = bx, by
        modello = base.copy()
        persi = 0
        for i in indici:
            r = int(max(bw, bh) * (0.6 + 0.6 * min(persi, 3))) + 6
            x0, y0 = max(0, x - r), max(0, y - r)
            x1, y1 = min(pw, x + bw + r), min(ph, y + bh + r)
            mappa = ncc(buf[i][y0:y1, x0:x1], modello)
            if mappa is None:
                persi += 1
                continue
            j = int(np.argmax(mappa))
            dy, dx = divmod(j, mappa.shape[1])
            s = float(mappa.flat[j])
            if s >= BOX_MIN_SCORE:
                x, y = x0 + dx, y0 + dy
                pos[i], punteggi[i] = (x, y), round(s, 3)
                modello = 0.9 * modello + 0.1 * buf[i][y:y + bh, x:x + bw]
                persi = 0
            else:
                persi += 1

    corsa(range(i0 + 1, n))
    corsa(range(i0 - 1, -1, -1))

    traccia = []
    for i, p in enumerate(pos):
        tt = round(t0 + i / fps, 3)
        if p is None:
            traccia.append({"t": tt, "cx": None, "cy": None, "box": None})
            continue
        x, y = p[0] / k, p[1] / k
        b = {"classe": "oggetto", "conf": punteggi[i], "x": round(x, 1), "y": round(y, 1),
             "w": round(bw / k, 1), "h": round(bh / k, 1)}
        traccia.append({"t": tt, "cx": round(x + b["w"] / 2, 2),
                        "cy": round(y + b["h"] / 2, 2), "box": b})
    visti = sum(1 for p in pos if p is not None)
    # i buchi prendono la posizione vicina; la media mobile corta toglie il
    # tremolio di un pixel del confronto senza ritardare il movimento
    piena = smooth(fill_gaps(traccia), 3)
    for p in piena:
        if p["box"] is None and p["cx"] is not None:
            p["box"] = {"classe": "oggetto", "conf": 0.0, "x": p["cx"] - bw / k / 2,
                        "y": p["cy"] - bh / k / 2, "w": round(bw / k, 1), "h": round(bh / k, 1)}
    return {"larghezza": ow, "altezza": oh, "fps": fps, "traccia": piena,
            "copertura": round(visti / max(1, n), 3), "classi": ["oggetto"]}


def follow(path: str, classes: tuple[str, ...] = ("person",), fps: float = SAMPLE_FPS,
           conf: float = CONF, window: int = SMOOTH_WINDOW, **kw) -> dict:
    """Rileva, sceglie il soggetto, riempie i buchi e leviga: la catena completa."""
    det = detect(path, classes, fps, conf, **kw)
    track = smooth(fill_gaps(main_subject(det["fotogrammi"])), window)
    visti = sum(1 for p in det["fotogrammi"] if p["box"])
    return {"larghezza": det["larghezza"], "altezza": det["altezza"],
            "fps": fps, "traccia": track,
            "copertura": round(visti / max(1, len(det["fotogrammi"])), 3),
            "classi": det["classi"]}


# --------------------------------------------------------------------------
# scontorno: maschera del soggetto fotogramma per fotogramma
# --------------------------------------------------------------------------

SEG_MODEL = "yolo11n-seg.pt"


def segment_matte(path: str, t0: float = 0.0, t1: float | None = None,
                  classes: tuple[str, ...] = ("person",), conf: float = 0.25,
                  width: int = 640, model: str = SEG_MODEL) -> dict:
    """Video maschera (bianco = soggetto) del tratto ``t0..t1`` della sorgente.

    A differenza del tracking qui serve *ogni* fotogramma, alla cadenza della
    sorgente: una maschera campionata a 2 fps farebbe saltare il bordo. I
    fotogrammi passano in streaming da ffmpeg al modello e di nuovo a ffmpeg,
    quindi la memoria non cresce con la durata. Il risultato sta in cache:
    stessa sorgente, tratto e classi -> stesso file, calcolato una volta.
    """
    import hashlib
    from pathlib import Path

    import numpy as np

    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise VisionError("ultralytics not installed: pip install 'vedit-mcp[vision]'") from e

    m = probe.probe(path)
    if not m.has_video:
        raise VisionError(f"{path} has no video")
    fps = m.fps or 25.0
    fine = t1 if t1 is not None else (m.duration or 0.0)
    if fine <= t0:
        raise VisionError("empty range: nothing to cut out")
    st = Path(path).stat()
    chiave = hashlib.sha1(
        f"{Path(path).resolve()}|{st.st_mtime_ns}|{st.st_size}|{t0:.3f}|{fine:.3f}|"
        f"{sorted(classes)}|{conf}|{width}|{model}".encode()).hexdigest()[:16]
    dst = proxy.cache_dir("mattes") / f"{chiave}.mkv"
    if dst.exists() and dst.stat().st_size > 0:
        return {"file": str(dst), "t0": t0, "t1": fine, "fps": fps, "cache": True}

    h = max(2, int(width * (m.height or 9) / (m.width or 16)) // 2 * 2)
    ff = ffmpeg.binary("ffmpeg")
    lettore = subprocess.Popen([
        ff, "-hide_banner", "-nostdin", "-loglevel", "error",
        "-ss", f"{t0:.3f}", "-t", f"{fine - t0:.3f}", "-i", str(path), "-an", "-sn",
        "-vf", f"scale={width}:{h},format=bgr24", "-f", "rawvideo", "-",
    ], stdout=subprocess.PIPE)
    tmp = dst.with_name("~" + dst.name)
    scrittore = subprocess.Popen([
        ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{width}x{h}", "-r", f"{fps:.6f}",
        "-i", "-", "-c:v", "ffv1", "-f", "matroska", str(tmp),
    ], stdin=subprocess.PIPE)

    net = YOLO(model_path(model))
    voluti = {c.lower() for c in classes} if classes else None
    ids = [i for i, nome in net.names.items() if voluti is None or str(nome).lower() in voluti]
    if not ids:
        raise VisionError(f"classes unknown to the model: {sorted(voluti or [])}")
    size = width * h * 3
    n = visti = 0
    try:
        while True:
            raw = lettore.stdout.read(size)
            if len(raw) < size:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(h, width, 3)
            res = net.predict(frame, conf=conf, classes=ids, retina_masks=True, verbose=False)[0]
            mask = np.zeros((h, width), dtype=np.uint8)
            if res.masks is not None and len(res.masks.data):
                dati = res.masks.data.cpu().numpy()
                unione = dati.max(axis=0)
                if unione.shape != mask.shape:  # per sicurezza: retina_masks dovrebbe evitarlo
                    ys = (np.arange(h) * unione.shape[0] / h).astype(int)
                    xs = (np.arange(width) * unione.shape[1] / width).astype(int)
                    unione = unione[ys][:, xs]
                mask = (unione > 0.5).astype(np.uint8) * 255
                visti += 1
            scrittore.stdin.write(mask.tobytes())
            n += 1
    finally:
        lettore.stdout.close()
        lettore.wait()
        scrittore.stdin.close()
        scrittore.wait()
    if n == 0 or scrittore.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise VisionError(f"cut-out failed: no frames read from {path}")
    tmp.replace(dst)
    return {"file": str(dst), "t0": t0, "t1": fine, "fps": fps, "cache": False,
            "fotogrammi": n, "copertura": round(visti / n, 3)}
