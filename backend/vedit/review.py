"""Guardare il montaggio invece di indovinarlo.

Un fotogramma non basta per giudicare un montaggio: servono il ritmo degli
stacchi, l'andamento dell'audio e la prova che quello che c'e' nel file
renderizzato sia davvero quello che la timeline dichiara.

Tre strumenti, tre domande:

- :func:`contact_sheet` - *com'e' fatta questa sequenza?* Una griglia di
  fotogrammi con il loro tempo sopra: stacchi, continuita' e buchi si vedono
  tutti insieme.
- :func:`waveform` - *dove sta il suono?* Picchi di un intervallo, piu' i
  livelli: serve a capire se un taglio cade in mezzo a una parola.
- :func:`verify` - *quello che ho montato e' quello che esce?* Renderizza un
  tratto a bassa risoluzione e lo ri-analizza, poi confronta le misure con
  quello che la timeline prometteva. E' il controllo che chiude il ciclo.
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from . import analyze, ffmpeg, render

CUT_TOLERANCE = 0.25       # uno stacco misurato entro questo scarto e' "quello li'"


# --------------------------------------------------------------------------
# contact sheet
# --------------------------------------------------------------------------


def _range(project, start: float | None, end: float | None) -> tuple[float, float]:
    dur = project.duration()
    a = max(0.0, start if start is not None else 0.0)
    b = min(dur, end if end is not None else dur)
    if b <= a:
        raise ValueError(f"intervallo vuoto: {a}-{b} (timeline lunga {dur:.3f}s)")
    return a, b


def sample_times(project, count: int, start: float | None = None,
                 end: float | None = None) -> list[float]:
    """Istanti da campionare: mai sul bordo esatto di uno stacco.

    Sul bordo si rischia di prendere il fotogramma della clip sbagliata, che e'
    proprio l'informazione che si sta cercando di leggere.
    """
    a, b = _range(project, start, end)
    n = max(1, int(count))
    passo = (b - a) / n
    return [round(a + passo * (i + 0.5), 3) for i in range(n)]


def _timecode(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):d}:{s:05.2f}"


def contact_sheet(project, output: str, count: int = 12, width: int = 320,
                  cols: int = 4, start: float | None = None,
                  end: float | None = None, use_proxy: bool = True) -> dict:
    """Griglia di fotogrammi della timeline, con il tempo stampato su ognuno."""
    tempi = sample_times(project, count, start, end)
    tmp = Path(tempfile.mkdtemp(prefix="vedit_sheet_"))
    frames = []
    for i, t in enumerate(tempi):
        f = tmp / f"{i:03d}.jpg"
        render.render_frame(project, t, str(f), width, use_proxy)
        frames.append((t, str(f)))

    res = griglia([(f"{i}  {_timecode(t)}", f) for i, (t, f) in enumerate(frames)],
                  output, cols)
    return {"file": res["file"], "fotogrammi": len(frames),
            "tempi": tempi, "griglia": res["griglia"]}


def griglia(frames: list[tuple[str, str]], output: str, cols: int = 4,
            guide: bool = False) -> dict:
    """Affianca i fotogrammi in una griglia, con l'etichetta stampata su ognuno.

    ``guide`` disegna una rete al 10% con le frazioni sui bordi: serve a chi
    guarda l'immagine per dire *dove* sta un oggetto (il ``box`` di track_mask
    in frazioni del fotogramma) invece di tirare a indovinare i pixel.
    """
    from PIL import Image, ImageDraw

    prima = Image.open(frames[0][1])
    fw, fh = prima.size
    cols = max(1, min(cols, len(frames)))
    righe = math.ceil(len(frames) / cols)
    sheet = Image.new("RGB", (cols * fw, righe * fh), (12, 12, 14))
    disegna = ImageDraw.Draw(sheet)

    for i, (etichetta, f) in enumerate(frames):
        img = Image.open(f).convert("RGB")
        if img.size != (fw, fh):
            img = img.resize((fw, fh))
        x, y = (i % cols) * fw, (i // cols) * fh
        sheet.paste(img, (x, y))
        if guide:
            for k in range(1, 10):
                gx, gy = x + fw * k // 10, y + fh * k // 10
                colore = (255, 80, 80) if k == 5 else (0, 230, 255)
                disegna.line([gx, y, gx, y + fh], fill=colore, width=1)
                disegna.line([x, gy, x + fw, gy], fill=colore, width=1)
                disegna.text((gx + 2, y + fh - 12), f".{k}", fill=colore)
                disegna.text((x + 2, gy + 1), f".{k}", fill=colore)
        # riquadro scuro dietro al testo: sul chiaro sarebbe illeggibile
        disegna.rectangle([x + 4, y + 4, x + 4 + 8 * len(etichetta), y + 22],
                          fill=(0, 0, 0))
        disegna.text((x + 8, y + 8), etichetta, fill=(255, 240, 120))

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out), quality=88)
    return {"file": str(out.resolve()), "griglia": [cols, righe]}


def media_sheet(path: str, output: str, count: int = 8, width: int = 320,
                cols: int = 4, start: float | None = None, end: float | None = None,
                t: float | None = None, guide: bool = False) -> dict:
    """Fotogrammi di un file sorgente, senza passare dalla timeline.

    Per scegliere il materiale bisogna vederlo prima di montarlo: mettere ogni
    ripresa in timeline solo per guardarla sporca il progetto e la cronologia.
    Con ``t`` restituisce un solo fotogramma (largo ``width``); altrimenti una
    griglia di ``count`` istanti presi a meta' di tratti uguali fra ``start``
    ed ``end`` della sorgente.
    """
    from . import probe

    m = probe.probe(path)
    if not m.has_video:
        raise ValueError(f"{Path(path).name} non ha video: niente da guardare")
    dur = m.duration or 0.0
    if t is not None:
        tempi = [max(0.0, min(float(t), max(0.0, dur - 0.05)))]
    else:
        a = max(0.0, start or 0.0)
        b = min(dur, end) if end is not None else dur
        if b <= a:
            raise ValueError(f"intervallo vuoto: {a}-{b} (il file dura {dur:.2f}s)")
        n = max(1, int(count))
        tempi = [round(a + (b - a) / n * (i + 0.5), 3) for i in range(n)]
    tmp = Path(tempfile.mkdtemp(prefix="vedit_media_"))
    frames = []
    for i, tt in enumerate(tempi):
        f = tmp / f"{i:03d}.jpg"
        subprocess.run([
            ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
            "-y", "-ss", f"{tt:.3f}", "-i", str(path), "-frames:v", "1",
            "-vf", f"scale={int(width)}:-2", "-q:v", "3", str(f),
        ], capture_output=True, timeout=120)
        if f.exists() and f.stat().st_size > 0:
            frames.append((f"{i}  {_timecode(tt)}", str(f), tt))
    if not frames:
        raise ValueError(f"nessun fotogramma leggibile da {Path(path).name}")
    res = griglia([(e, f) for e, f, _ in frames], output, cols, guide)
    return {"file": res["file"], "tempi": [tt for _, _, tt in frames],
            "durata_sorgente": round(dur, 3), "risoluzione": [m.width, m.height]}


# --------------------------------------------------------------------------
# anteprima guardabile
# --------------------------------------------------------------------------

MAX_PREVIEW = 30.0         # oltre, un'anteprima non e' piu' un'anteprima


def preview_clip(project, output: str | None = None, start: float | None = None,
                 end: float | None = None, height: int = 360,
                 max_seconds: float = MAX_PREVIEW, audio: bool = True) -> dict:
    """Renderizza un tratto e **lo tiene**: un file da guardare davvero.

    Il contact sheet mostra la struttura, questo mostra il risultato. E' l'unico
    modo perche' una persona possa dire "qui non funziona" invece di fidarsi.

    La durata e' limitata di proposito: un'anteprima lunga e' un render, e va
    chiesto con ``render_video``.
    """
    a, b = _range(project, start, end)
    tagliato = False
    if b - a > max_seconds:
        b, tagliato = a + max_seconds, True

    out = Path(output) if output else Path(tempfile.mkdtemp(prefix="vedit_prev_")) / "anteprima.mp4"
    w = int(round(height * project.settings.width / project.settings.height))
    w += w % 2
    render.render(project, render.RenderOptions(
        output=str(out), start=a, end=b, quality="draft", width=w, height=height,
        use_proxy=True, audio=audio and has_audio(project, a, b)))
    return {
        "file": str(out.resolve()),
        "inizio": round(a, 3), "fine": round(b, 3),
        "durata": round(b - a, 3),
        "risoluzione": f"{w}x{height}",
        "byte": out.stat().st_size if out.exists() else 0,
        "troncata": tagliato,
        "nota": (f"anteprima limitata a {max_seconds:.0f}s: per il resto usa "
                 "render_video") if tagliato else None,
    }


# --------------------------------------------------------------------------
# scopes: misurare il colore invece di guardarlo a occhio
# --------------------------------------------------------------------------


def scopes(project, t: float, width: int = 480) -> dict:
    """Misure del colore su un fotogramma: esposizione, clipping, dominante.

    Un jpeg su uno schermo non calibrato non dice se una ripresa e' sottoesposta
    o se le alte luci sono bruciate. Questi numeri si'.
    """
    import numpy as np
    from PIL import Image as PILImage

    tmp = Path(tempfile.mkdtemp(prefix="vedit_scope_")) / "f.png"
    render.render_frame(project, t, str(tmp), width, True)
    img = np.asarray(PILImage.open(tmp).convert("RGB")).astype(np.float32)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    # Rec.709: l'occhio pesa il verde molto piu' del blu
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    piatta = luma.ravel()

    def pct(q: float) -> float:
        return round(float(np.percentile(piatta, q)), 1)

    massimo = img.max(axis=2)
    minimo = img.min(axis=2)
    sat = np.where(massimo > 0, (massimo - minimo) / np.maximum(massimo, 1e-6), 0.0)

    medie = [round(float(c.mean()), 1) for c in (r, g, b)]
    grigio = sum(medie) / 3.0 or 1.0
    dominante = [round(m / grigio, 3) for m in medie]

    bruciato = round(float((piatta > 250).mean()), 4)
    spento = round(float((piatta < 5).mean()), 4)

    avvisi = []
    if pct(50) < 45:
        avvisi.append("sottoesposta: la mediana della luminanza e' bassa")
    if pct(50) > 200:
        avvisi.append("sovraesposta")
    if bruciato > 0.02:
        avvisi.append(f"alte luci bruciate sul {bruciato * 100:.1f}% dei pixel")
    if spento > 0.05 and pct(1) < 2:
        avvisi.append(f"ombre chiuse sul {spento * 100:.1f}% dei pixel")
    if max(dominante) > 1.12:
        canale = "rossa" if dominante[0] == max(dominante) else (
            "verde" if dominante[1] == max(dominante) else "blu")
        avvisi.append(f"dominante {canale} ({max(dominante):.2f}x sul grigio)")
    if float(piatta.std()) < 25:
        avvisi.append("contrasto molto basso: immagine piatta")

    return {
        "t": round(t, 3),
        "luma": {"min": pct(0), "p1": pct(1), "mediana": pct(50), "p99": pct(99),
                 "max": pct(100), "media": round(float(piatta.mean()), 1),
                 "contrasto": round(float(piatta.std()), 1)},
        "clipping": {"alte_luci": bruciato, "ombre": spento},
        "canali_medi": {"r": medie[0], "g": medie[1], "b": medie[2]},
        "dominante": {"r": dominante[0], "g": dominante[1], "b": dominante[2]},
        "saturazione_media": round(float(sat.mean()), 3),
        "avvisi": avvisi,
        "ok": not avvisi,
    }


# --------------------------------------------------------------------------
# livelli per traccia: i misuratori del mixer
# --------------------------------------------------------------------------

LIVELLI_PASSO = 0.05          # una misura ogni 50 ms: abbastanza per un misuratore
LIVELLI_SR = 16000            # i livelli non hanno bisogno di 48 kHz
PAVIMENTO_DB = -90.0


def _db(v):
    import numpy as np
    return np.maximum(PAVIMENTO_DB, 20 * np.log10(np.maximum(v, 1e-9)))


def _inviluppo(wav: Path, passo: float) -> dict:
    """Picco e RMS (dBFS, sul canale piu' forte) per finestre di ``passo`` secondi."""
    import wave

    import numpy as np
    with wave.open(str(wav), "rb") as w:
        ch, sr = w.getnchannels(), w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    x = x.reshape(-1, ch)
    n = max(1, int(round(sr * passo)))
    finestre = len(x) // n
    if finestre == 0:
        return {"picco": [], "rms": [], "max_db": PAVIMENTO_DB}
    blocchi = x[: finestre * n].reshape(finestre, n, ch)
    picco = np.abs(blocchi).max(axis=(1, 2))
    rms = np.sqrt((blocchi ** 2).mean(axis=1)).max(axis=1)
    return {"picco": [round(float(v), 1) for v in _db(picco)],
            "rms": [round(float(v), 1) for v in _db(rms)],
            "max_db": round(float(_db(np.array([picco.max()]))[0]), 1)}


def livelli(project, passo: float = LIVELLI_PASSO) -> dict:
    """Inviluppo dei livelli di ogni traccia e del master, per i misuratori del mixer.

    Ogni traccia si renderizza da sola, con i suoi effetti e il suo fader ma
    senza la catena del master: e' quello che si vedrebbe sul canale di un
    banco. Il master e' il mix vero, loudnorm e limiter compresi. Muto e solo
    non contano: il misuratore dice quanto suonerebbe la traccia.
    """
    import copy
    from concurrent.futures import ThreadPoolExecutor

    from .graph import CompileOptions, compile_project

    durata = project.duration()
    if durata <= 0:
        return {"passo": passo, "durata": 0.0, "tracce": {}, "master": None}
    base = copy.deepcopy(project)
    base.settings.sample_rate = LIVELLI_SR
    for t in base.tracks:
        t.solo = False

    def da_sola(tid: str | None):
        p = copy.deepcopy(base)
        for t in p.tracks:
            t.muted = tid is not None and t.id != tid
        if tid is not None:
            # il canale prima del master: niente effetti, loudnorm o fader generale
            p.master.effects, p.master.volume = [], 1.0
            p.master.loudnorm.enabled = False
        return p

    def misura(tid: str | None):
        p = da_sola(tid)
        if compile_project(p, CompileOptions(video=False, audio=True)).audio_label is None:
            return tid, None
        cartella = Path(tempfile.mkdtemp(prefix="vedit_livelli_"))
        try:
            out = cartella / "a.wav"
            render.render(p, render.RenderOptions(output=str(out), video=False, jobs=1))
            return tid, _inviluppo(out, passo)
        finally:
            import shutil
            shutil.rmtree(cartella, ignore_errors=True)

    voci = [None] + [t.id for t in base.tracks if t.clips]
    with ThreadPoolExecutor(max_workers=3) as ex:
        esiti = dict(ex.map(misura, voci))
    return {"passo": passo, "durata": round(durata, 3),
            "tracce": {k: v for k, v in esiti.items() if k is not None and v is not None},
            "master": esiti.get(None)}


# scope -> filtro ffmpeg applicato al fotogramma (gia' ridotto a SCOPE_W). Il
# fotogramma si stringe prima del filtro: la waveform e' larga quanto l'immagine
# e la parade il triplo, senza riduzione uscivano nastri alti un dito
SCOPE_W = 512
SCOPI = {
    "waveform": "format=yuv444p,waveform=intensity=0.2:graticule=green:flags=numbers+dots:scale=ire",
    "parade": "scale=256:-2,format=gbrp,waveform=display=parade:components=7:intensity=0.2"
              ":graticule=green:flags=numbers+dots",
    "vectorscope": "format=yuv444p,vectorscope=mode=color3:graticule=color:flags=name"
                   ":envelope=instant,scale=360:360",
    "histogram": None,     # disegnato qui: quello di ffmpeg in sovrapposizione e' illeggibile
}


def scope_immagine(project, t: float, tipo: str, output: str) -> str:
    """Scope grafico del fotogramma al tempo ``t``: waveform, parade, vettorscopio, istogramma.

    Il fotogramma viene dagli originali, non dai proxy: un proxy ricodificato
    sposta il colore quanto basta a falsare la misura.
    """
    if tipo not in SCOPI:
        raise ValueError(f"scope sconosciuto {tipo!r}; ammessi: {', '.join(SCOPI)}")
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="vedit_scope_")) / "f.png"
    render.render_frame(project, t, str(tmp), SCOPE_W, use_proxy=False)
    if tipo == "histogram":
        return _istogramma(tmp, out)
    proc = ffmpeg.run([ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                       "-i", str(tmp), "-vf", SCOPI[tipo], "-frames:v", "1", str(out)],
                      check=False, timeout=60)
    if proc.returncode != 0:
        raise ffmpeg.FFmpegError([], proc.returncode, (proc.stderr or "")[-1000:])
    return str(out)


def _istogramma(frame: Path, out: Path) -> str:
    """R, G, B e luma su scala logaritmica: i picchi non schiacciano il resto."""
    import numpy as np
    from PIL import Image as PILImage
    from PIL import ImageDraw

    img = np.asarray(PILImage.open(frame).convert("RGB")).astype(np.float32)
    luma = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
    W, H = 512, 200
    tela = PILImage.new("RGB", (W, H), (12, 13, 17))
    disegno = ImageDraw.Draw(tela, "RGBA")
    for x in (W // 4, W // 2, 3 * W // 4):
        disegno.line([(x, 0), (x, H)], fill=(255, 255, 255, 28))
    canali = [(img[..., 0], (255, 70, 70)), (img[..., 1], (70, 230, 90)),
              (img[..., 2], (80, 140, 255)), (luma, (235, 235, 235))]
    for dati, colore in canali:
        h, _ = np.histogram(dati, bins=256, range=(0, 256))
        h = np.log1p(h)
        h = h / (h.max() or 1.0)
        punti = [(i * (W - 1) / 255, H - 1 - v * (H - 6)) for i, v in enumerate(h)]
        if dati is not luma:      # il luma resta una linea: riempito copriva i canali
            disegno.polygon([(0, H - 1), *punti, (W - 1, H - 1)], fill=(*colore, 26))
        disegno.line(punti, fill=(*colore, 200 if dati is luma else 230), width=1)
    tela.save(out)
    return str(out)


# --------------------------------------------------------------------------
# forma d'onda
# --------------------------------------------------------------------------


def has_audio(project, start: float, end: float) -> bool:
    """C'e' almeno una clip con audio vero che suona in questo intervallo?"""
    for kind in ("video", "audio"):
        for track in project.live_tracks(kind):
            for c in track.clips:
                if not c.enabled or c.end <= start or c.start >= end:
                    continue
                if getattr(c, "audio", None) is not None and getattr(c.audio, "mute", False):
                    continue
                m = project.media_by_id(c.media) if c.media else None
                if m is not None and m.has_audio:
                    return True
    return False


def waveform(project, start: float | None = None, end: float | None = None,
             points: int = 120) -> dict:
    """Picchi audio del mix in un intervallo, piu' i livelli di picco e medio.

    L'audio viene renderizzato davvero: cosi' i picchi tengono conto di gain,
    dissolvenze ed effetti, non solo del file sorgente.
    """
    import array

    a, b = _range(project, start, end)
    if not has_audio(project, a, b):
        # senza sorgenti audio il render non avrebbe nessun filtro da costruire e
        # ffmpeg fallirebbe: il muto e' una risposta legittima, non un errore
        return {"picchi": [], "durata": round(b - a, 3), "inizio": round(a, 3),
                "picco_db": None, "medio_db": None, "silenzio_ratio": 1.0,
                "nota": "nessuna sorgente audio nell'intervallo"}
    tmp = Path(tempfile.mkdtemp(prefix="vedit_wave_")) / "mix.wav"
    render.render(project, render.RenderOptions(
        output=str(tmp), start=a, end=b, video=False, audio=True,
        audio_codec="pcm_s16le", quality="draft"))

    rate = 8000
    proc = subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(tmp), "-vn", "-ac", "1", "-ar", str(rate),
        "-f", "s16le", "-acodec", "pcm_s16le", "-",
    ], capture_output=True, timeout=900)
    raw = proc.stdout or b""
    campioni = array.array("h")
    campioni.frombytes(raw[: len(raw) - (len(raw) % 2)])
    if not campioni:
        return {"picchi": [], "durata": round(b - a, 3), "picco_db": None,
                "medio_db": None, "nota": "nessun audio nell'intervallo"}

    n = max(1, min(points, len(campioni)))
    blocco = max(1, len(campioni) // n)
    picchi, somma = [], 0.0
    for i in range(0, len(campioni), blocco):
        pezzo = campioni[i: i + blocco]
        if not pezzo:
            break
        p = max(abs(min(pezzo)), abs(max(pezzo))) / 32768.0
        picchi.append(round(p, 4))
        somma += sum(x * x for x in pezzo) / len(pezzo)

    def db(x: float) -> float | None:
        return round(20 * math.log10(x), 1) if x > 1e-6 else None

    blocchi = max(1, len(picchi))
    return {
        "picchi": picchi[:points],
        "durata": round(b - a, 3),
        "inizio": round(a, 3),
        "picco_db": db(max(picchi)),
        "medio_db": db(math.sqrt(somma / blocchi) / 32768.0),
        "silenzio_ratio": round(sum(1 for p in picchi if p < 0.01) / blocchi, 3),
    }


def cuts_on_speech(store, clip_id: str, model_size: str = "small",
                   language: str | None = None, margin: float = 0.06) -> dict:
    """Verifica che i bordi di una clip non cadano in mezzo a una parola.

    E' l'errore piu' comune del taglio automatico e il piu' fastidioso da
    ascoltare: la parola mozzata si sente subito.
    """
    _, clip = store.clip_or_die(clip_id)
    if not clip.media:
        raise ValueError(f"la clip {clip_id} non ha un file sorgente")
    path = store.media_or_die(clip.media).path
    tr = analyze.transcribe(path, model_size, language)

    inizio, fine = clip.in_, clip.in_ + clip.source_duration()
    problemi = []
    for seg in tr["segments"]:
        for w in seg["words"]:
            for nome, t in (("attacco", inizio), ("stacco", fine)):
                if w["t"] + margin < t < w["e"] - margin:
                    problemi.append({
                        "dove": nome, "t": round(t, 3), "parola": w["w"],
                        "parola_inizio": w["t"], "parola_fine": w["e"],
                        "suggerito": round(w["t"] if nome == "attacco" else w["e"], 3),
                    })
    return {"ok": not problemi, "problemi": problemi}


# --------------------------------------------------------------------------
# verifica del render
# --------------------------------------------------------------------------


def expected_cuts(project, start: float, end: float) -> list[float]:
    """Gli stacchi che la timeline promette: i bordi delle clip nell'intervallo."""
    bordi = set()
    for track in project.tracks:
        if track.kind != "video" or getattr(track, "hidden", False):
            continue
        for c in track.clips:
            for t in (c.start, c.end):
                if start + 0.05 < t < end - 0.05:
                    bordi.add(round(t - start, 3))
    return sorted(bordi)


def verify(project, start: float | None = None, end: float | None = None,
           height: int = 270, keep: bool = False) -> dict:
    """Renderizza un tratto e controlla che sia quello che la timeline dichiara.

    Confronta stacchi attesi e stacchi misurati, la durata e i tratti neri o
    muti. E' la differenza tra "credo di aver montato" e "ho verificato".
    """
    a, b = _range(project, start, end)
    tmp = Path(tempfile.mkdtemp(prefix="vedit_verify_")) / "check.mp4"
    w = int(round(height * project.settings.width / project.settings.height))
    w += w % 2
    render.render(project, render.RenderOptions(
        output=str(tmp), start=a, end=b, quality="draft", width=w, height=height,
        use_proxy=True))

    misurati = [t for t in analyze.scenes(str(tmp), force=True) if t > 0.05]
    attesi = expected_cuts(project, a, b)
    trovati, mancanti = [], []
    residui = list(misurati)
    for t in attesi:
        vicino = min(residui, key=lambda x: abs(x - t), default=None)
        if vicino is not None and abs(vicino - t) <= CUT_TOLERANCE:
            trovati.append({"atteso": t, "misurato": vicino,
                            "scarto": round(vicino - t, 3)})
            residui.remove(vicino)
        else:
            mancanti.append(t)

    rep = analyze.report(str(tmp))
    m = rep["measures"]
    durata_attesa = round(b - a, 3)
    esito = {
        "durata_attesa": durata_attesa,
        "durata_misurata": rep["duration"],
        "stacchi_attesi": attesi,
        "stacchi_confermati": trovati,
        "stacchi_mancanti": mancanti,
        "stacchi_inattesi": [round(t, 3) for t in residui],
        "nero": m["black"], "muto": m["silence"], "fuori_fuoco": m["blurry"],
        "file": str(tmp) if keep else None,
    }
    avvisi = []
    if abs(rep["duration"] - durata_attesa) > 0.2:
        avvisi.append(f"durata diversa dal previsto: {rep['duration']}s invece di "
                      f"{durata_attesa}s")
    if mancanti:
        avvisi.append(f"{len(mancanti)} stacchi non si vedono nel render: due clip "
                      "adiacenti troppo simili, oppure una transizione li ha fusi")
    if m["black"] > 0.1:
        avvisi.append(f"nero per il {m['black'] * 100:.0f}% del tratto: buchi in timeline?")
    if m["silence"] > 0.9:
        avvisi.append("tratto praticamente muto")
    esito["avvisi"] = avvisi
    esito["ok"] = not avvisi
    if not keep:
        try:
            tmp.unlink()
        except OSError:
            pass
    return esito


# --------------------------------------------------------------------------
# montaggio piatto: quello che manca, letto dalla timeline
# --------------------------------------------------------------------------

# cosa ci si aspetta da un montaggio quando lo stile non dice altro
ATTESE_DEFAULT = ("movimento", "colore", "musica_viva", "ritmo_vario")

_RIMEDI = {
    "movimento": "nessun movimento dentro l'inquadratura: spinte lente o punch-in con "
                 "set_transform(scale={'kf':...}), oppure apply_style",
    "colore": "nessun look: un preset di colore sul master (apply_preset / add_effect) "
              "da' unita' a riprese diverse",
    "transizioni": "solo stacchi secchi: almeno i cambi di sezione vogliono una "
                   "transizione o una dissolvenza motivata",
    "grafica": "nessun testo o grafica: titolo d'apertura, sottopancia o cartelli "
               "(add_text, add_html)",
    "musica_viva": "musica a volume fisso: automatizza gain_db con i keyframe sulle "
                   "sezioni di music_beats (o apply_style)",
    "ritmo_vario": "tagli tutti della stessa durata: il ritmo e' un metronomo, alterna "
                   "inquadrature tenute e raffiche",
    "effetti": "nessun effetto sulle clip: per questo stile servono accenti (glow, "
               "rgb_split, shake, velocita') sui momenti forti",
}


def ricchezza(project, attese: tuple[str, ...] | list[str] | None = None) -> dict:
    """Quanto il montaggio e' *fatto* e non solo tagliato.

    Non guarda le immagini: conta le scelte che stanno nella timeline —
    movimento, colore, transizioni, grafica, musica automatizzata, durate dei
    tagli. Un montaggio con solo tagli secchi su volume fisso esce piatto anche
    con materiale buono, ed e' esattamente l'errore che un agente fa quando si
    ferma dopo aver messo le clip in fila. ``attese`` sono le voci che lo stile
    richiede: le altre mancanze non sono un difetto.
    """
    from . import keyframes as kf

    attese = tuple(attese) if attese else ATTESE_DEFAULT
    video = [c for t in project.tracks if t.kind == "video" for c in t.clips
             if c.type == "media" and c.enabled]
    audio_tr = [t for t in project.tracks if t.kind == "audio"]
    musica = [c for t in audio_tr for c in t.clips if c.type == "media" and c.duration >= 8]

    def mosso(c) -> bool:
        tf = c.transform
        if any(kf.is_kf(v) for v in (tf.x, tf.y, tf.scale, tf.rotation)):
            return True
        return abs(float(kf.sample(tf.scale, 0, 1.0)) - 1.0) > 0.02

    colore_fx = {"color", "colorbalance", "temperature", "curves", "lut", "colormatch",
                 "exposure", "vibrance", "hsl", "levels", "tint", "hue", "whitebalance"}
    tutti_fx = [e.type for c in video for e in c.effects if e.type != "matte"]
    master_fx = [e.type for e in project.master.effects]
    durate = [c.duration for c in video]
    media_d = sum(durate) / len(durate) if durate else 0.0
    cv = (math.sqrt(sum((d - media_d) ** 2 for d in durate) / len(durate)) / media_d
          if len(durate) > 1 and media_d > 0 else 1.0)

    conti = {
        "clip_video": len(video),
        "con_movimento": sum(1 for c in video if mosso(c)),
        "effetti_clip": len(tutti_fx),
        "effetti_master": len(master_fx),
        "transizioni": sum(1 for c in video if c.transition_out.duration > 0
                           or c.fade_in > 0 or c.fade_out > 0),
        "grafica": sum(1 for t in project.tracks for c in t.clips
                       if c.type in ("text", "html")),
        "cambi_velocita": sum(1 for c in video if abs(c.speed - 1.0) > 1e-3 or c.reverse),
        "musica_automatizzata": sum(1 for c in musica if kf.is_kf(c.audio.gain_db))
                                + sum(1 for t in audio_tr if t.sidechain),
        "tracce_musica": len(musica),
        "variazione_durate": round(cv, 3),
    }
    presenti = {
        "movimento": conti["con_movimento"] >= max(1, len(video) // 4),
        "colore": bool(colore_fx & set(tutti_fx + master_fx)),
        "transizioni": conti["transizioni"] > 0,
        "grafica": conti["grafica"] > 0,
        "musica_viva": not musica or conti["musica_automatizzata"] > 0,
        "ritmo_vario": len(video) < 6 or cv >= 0.15,
        "effetti": bool(set(tutti_fx) - colore_fx) or conti["cambi_velocita"] > 0,
    }
    mancano = [k for k in attese if not presenti.get(k, True)]
    avvisi = [_RIMEDI[k] for k in mancano]
    solo_tagli = (len(video) > 1 and not any(presenti[k] for k in
                  ("movimento", "colore", "transizioni", "grafica", "effetti"))
                  and conti["musica_automatizzata"] == 0)
    if solo_tagli:
        avvisi.insert(0, "il montaggio e' solo tagli: nessun movimento, colore, transizione, "
                         "grafica o automazione. Non e' finito: applica lo stile "
                         "(apply_style) e poi rifinisci i momenti forti")
    voto = sum(1 for k in attese if presenti.get(k, True))
    return {"voto": f"{voto}/{len(attese)}", "solo_tagli": solo_tagli, "mancano": mancano,
            "presenti": [k for k, v in presenti.items() if v], "conti": conti,
            "avvisi": avvisi, "ok": not avvisi}
