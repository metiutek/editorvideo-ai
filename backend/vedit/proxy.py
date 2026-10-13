"""Proxy a bassa risoluzione, forme d'onda e miniature.

Montare direttamente su file 4K o H.265 rende ogni preview lentissima. I proxy
sono H.264 all-intra a 540p: decodifica quasi istantanea e seek preciso su
qualsiasi frame. Il render finale usa sempre le sorgenti originali.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from . import ffmpeg, hw
from .model import Media, Project


def _quanti_pesanti() -> int:
    v = os.environ.get("VEDIT_LAVORI", "").strip()
    if v.isdigit() and int(v) > 0:
        return int(v)
    return max(1, min(4, (os.cpu_count() or 2) // 2))


# Strisce e forme d'onda decodificano il file intero. La UI le chiede per ogni
# media appena importato e il server ne eseguiva fino a 40 insieme (i thread di
# FastAPI): con qualche centinaio di file la macchina si sedeva, anteprima
# compresa. Come le code in background degli editor desktop: pochi alla volta,
# gli altri aspettano il turno.
_PESANTI = threading.BoundedSemaphore(_quanti_pesanti())
_in_corso: dict[str, threading.Lock] = {}
_in_corso_lock = threading.Lock()


@contextmanager
def lavoro_pesante(chiave: str):
    """Un posto nella coda dei lavori pesanti, e uno solo per lo stesso risultato.

    Due richieste per la stessa striscia (timeline e pannello media) aspettano
    la stessa generazione invece di farla due volte: chi arriva secondo trova
    il file in cache quando entra.
    """
    # i lucchetti restano: uno per risultato, pochi byte, e toglierli mentre
    # qualcuno ci aspetta sopra farebbe partire due generazioni dello stesso file
    with _in_corso_lock:
        mio = _in_corso.setdefault(chiave, threading.Lock())
    with mio, _PESANTI:
        yield


def cache_dir(sub: str = "") -> Path:
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    p = base / sub if sub else base
    p.mkdir(parents=True, exist_ok=True)
    return p


def _key(path: str, tag: str) -> str:
    try:
        st = Path(path).stat()
        sig = f"{path}|{st.st_size}|{int(st.st_mtime)}|{tag}"
    except OSError:
        sig = f"{path}|{tag}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def proxy_path(media: Media, height: int = 540) -> Path:
    ext = ".m4a" if media.kind == "audio" else ".mp4"
    return cache_dir("proxy") / f"{_key(media.path, f'p{height}')}{ext}"


def generate(media: Media, height: int = 540, force: bool = False) -> str:
    """Crea il proxy se manca e ritorna il percorso."""
    if media.kind == "image":
        return media.path
    dst = proxy_path(media, height)
    if dst.exists() and not force and dst.stat().st_size > 0:
        return str(dst)

    args = ffmpeg.base_cmd() + ["-i", media.path]
    if media.kind == "audio" or not media.has_video:
        args += ["-vn", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
    else:
        info = hw.detect()
        enc = info.encoder_for("h264", prefer_hw=True)
        args += [
            "-vf", f"scale=-2:{height}:flags=fast_bilinear",
            *hw.encoder_args(enc, "draft"),
            "-g", "12", "-pix_fmt", "yuv420p",
        ]
        if media.has_audio:
            args += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
        else:
            args += ["-an"]
    # su un file a parte: un proxy interrotto a meta' non deve sembrare pronto
    tmp = dst.with_name(f"~{dst.stem}{dst.suffix}")
    args += [str(tmp)]
    try:
        ffmpeg.run(args, timeout=7200)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return str(dst)


# Quello che Chrome ed Edge riproducono da soli in un <video>. Il resto (DNxHR e
# ProRes dai programmi di montaggio, H.265, 10 bit, 4:2:2, MXF, AVI, MTS, PCM
# dentro un .mov) nel monitor resta nero e muto: serve un proxy H.264/AAC, come
# gli "optimized media" di Resolve o la transcodifica che CapCut fa all'import.
# H.265 e' escluso apposta: dipende dalla scheda video del singolo PC.
_CONTENITORI_OK = {".mp4", ".m4v", ".mov", ".webm", ".mp3", ".m4a", ".aac", ".wav",
                   ".ogg", ".oga", ".opus", ".flac"}
_VIDEO_OK = {"h264", "vp8", "vp9", "av1"}
_PIXEL_OK = {"yuv420p", "yuvj420p", "nv12"}
_AUDIO_OK = {"aac", "mp3", "opus", "vorbis", "flac"}


def completa_codec(media: Media) -> None:
    """I progetti salvati prima del campo codec: lo si legge una volta dal file."""
    if media.vcodec or media.acodec or media.kind == "image":
        return
    from .probe import probe_raw

    try:
        streams = probe_raw(media.path).get("streams", [])
    except Exception:
        return
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    media.vcodec = str(v.get("codec_name") or "")
    media.acodec = str(a.get("codec_name") or "")
    media.pix_fmt = str(v.get("pix_fmt") or "")


def serve_proxy(media: Media) -> bool:
    """Vero se il browser non sa riprodurre il file com'e'."""
    if media.kind == "image":
        return False
    ext = Path(media.path).suffix.lower()
    if ext not in _CONTENITORI_OK:
        return True
    if media.has_video and media.kind == "video":
        if media.vcodec not in _VIDEO_OK or media.pix_fmt not in _PIXEL_OK:
            return True
    if media.has_audio:
        if media.acodec in _AUDIO_OK:
            return False
        # il PCM si', ma solo dentro un .wav
        return not (ext == ".wav" and media.acodec.startswith("pcm_"))
    return False


def proxy_pronto(media: Media) -> bool:
    return bool(media.proxy) and Path(media.proxy).is_file()


def da_preparare(project: Project) -> list[Media]:
    """I media che nel monitor resterebbero neri o muti senza un proxy."""
    out = []
    for m in project.media:
        if proxy_pronto(m) or m.kind == "image" or not Path(m.path).is_file():
            continue
        completa_codec(m)
        if (m.vcodec or m.acodec) and serve_proxy(m):
            out.append(m)
    return out


def ensure(project: Project, height: int = 540, force: bool = False) -> dict:
    """Genera i proxy mancanti per tutti i media del progetto."""
    done = {}
    for m in project.media:
        if m.kind == "image":
            continue
        p = generate(m, height, force)
        m.proxy = p
        done[m.id] = p
    return done


def waveform(media: Media, points_per_second: int = 40, max_points: int = 40000) -> list[float]:
    """Picchi audio normalizzati 0..1, per disegnare la traccia in timeline.

    Il risultato sta in cache su disco come la striscia di fotogrammi: ricavarlo
    vuol dire decodificare tutto l'audio del file, e viene chiesto a ogni
    caricamento della pagina e da ogni pannello che lo disegna.
    """
    if not media.has_audio:
        return []

    cache = cache_dir("wave") / f"{_key(media.path, f'w{points_per_second}x{max_points}')}.json"

    def letta() -> list[float] | None:
        if cache.exists() and cache.stat().st_size > 0:
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass  # cache illeggibile: si rifa'
        return None

    if (pronta := letta()) is not None:
        return pronta
    with lavoro_pesante(str(cache)):
        # chi aspettava il turno trova spesso il lavoro gia' fatto da un altro
        if (pronta := letta()) is not None:
            return pronta
        peaks = _picchi(media.path, points_per_second, max_points)
    if not peaks:
        return []

    tmp = cache.with_name(f"~{cache.name}")
    try:
        tmp.write_text(json.dumps(peaks), encoding="utf-8")
        os.replace(tmp, cache)   # atomico: nessuno legge un file a meta'
    except OSError:
        tmp.unlink(missing_ok=True)   # senza cache si ricalcola, non e' un errore
    return peaks


def _picchi(path: str, points_per_second: int, max_points: int) -> list[float]:
    """Decodifica l'audio a 8 kHz mono e ne tiene il picco per blocco."""
    import subprocess

    import numpy as np

    rate = 8000
    args = [
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", path, "-vn", "-sn", "-ac", "1", "-ar", str(rate),
        "-f", "s16le", "-acodec", "pcm_s16le", "-",
    ]
    proc = subprocess.run(args, capture_output=True, timeout=1800,
                          creationflags=0x08000000 if os.name == "nt" else 0)
    raw = proc.stdout
    if not raw:
        return []
    samples = np.frombuffer(raw[: len(raw) - (len(raw) % 2)], dtype="<i2")

    total_points = min(max_points, max(1, int((len(samples) / rate) * points_per_second)))
    block = max(1, len(samples) // total_points)
    # stessi blocchi del ciclo in Python di prima (l'ultimo puo' essere corto),
    # ma in numpy: un'ora di audio passava secondi nel ciclo
    n = len(samples) // block * block
    pieni = np.abs(samples[:n].astype(np.int32)).reshape(-1, block).max(axis=1)
    if n < len(samples):
        pieni = np.append(pieni, np.abs(samples[n:].astype(np.int32)).max())
    return [round(float(v) / 32768.0, 4) for v in pieni]


def thumbnails(media: Media, count: int = 10, height: int = 90) -> list[str]:
    """Strip di miniature per la traccia video."""
    if not media.has_video or media.duration <= 0:
        return []
    out_dir = cache_dir("thumbs") / _key(media.path, f"t{count}x{height}")
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("*.jpg"))
    if len(existing) >= count:
        return [str(p) for p in existing[:count]]

    step = media.duration / count
    paths = []
    for i in range(count):
        dst = out_dir / f"{i:04d}.jpg"
        if not dst.exists():
            args = ffmpeg.base_cmd() + [
                "-ss", f"{i * step:.3f}", "-i", media.path, "-frames:v", "1",
                "-vf", f"scale=-2:{height}", "-q:v", "5", str(dst),
            ]
            ffmpeg.run(args, check=False, timeout=120)
        if dst.exists():
            paths.append(str(dst))
    return paths


def filmstrip(media: Media, height: int = 44, max_tiles: int = 240) -> dict:
    """Striscia unica con un fotogramma ogni N secondi, per il fondo delle clip.

    Una sola immagine invece di decine di richieste: la timeline la usa come
    background-image e sposta la finestra in base al punto di attacco e allo zoom.
    """
    if not media.has_video or media.duration <= 0:
        return {}
    tiles = max(1, min(max_tiles, int(media.duration)))
    interval = media.duration / tiles
    tile_w = max(2, int(round(height * (media.width or 16) / (media.height or 9))))
    tile_w += tile_w % 2

    dst = cache_dir("strip") / f"{_key(media.path, f's{height}x{tiles}')}.jpg"

    def pronta() -> bool:
        return dst.exists() and dst.stat().st_size > 0

    if not pronta():
        with lavoro_pesante(str(dst)):
            if not pronta():
                src = media.proxy if media.proxy and Path(media.proxy).exists() else media.path
                _genera_striscia(src, dst, interval, tile_w, height, tiles)
        if not pronta():
            return {}
    return {"path": str(dst), "tiles": tiles, "interval": round(interval, 6),
            "tile_width": tile_w, "tile_height": height}


def _genera_striscia(src: str, dst: Path, interval: float, tile_w: int, height: int,
                     tiles: int) -> None:
    """Un fotogramma ogni ``interval`` secondi, affiancati in un'unica immagine.

    Decodificare ogni fotogramma di un'ora di 4K per tenerne 240 era la parte
    lenta. Con un fotogramma ogni due secondi o piu' bastano i keyframe
    (``-skip_frame nokey``): il decoder salta tutto il resto, ed e' quello che
    fanno gli editor desktop per le miniature. Sulle clip corte resta la
    decodifica completa, che costa poco e prende il fotogramma giusto; se coi
    soli keyframe non esce niente (file senza keyframe utili) si rifa' per intero.
    """
    tmp = dst.with_name(f"~{dst.name}")
    vf = f"fps=1/{interval:.6f},scale={tile_w}:{height}:flags=fast_bilinear,tile={tiles}x1"
    tentativi = [["-skip_frame", "nokey"], []] if interval >= 2.0 else [[]]
    for salta in tentativi:
        args = ffmpeg.base_cmd() + [*salta, "-i", src, "-an", "-sn", "-vf", vf,
                                    "-frames:v", "1", "-q:v", "6", "-f", "image2", str(tmp)]
        ffmpeg.run(args, timeout=1800, check=False)
        if tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, dst)   # nessuno legge una striscia scritta a meta'
            return
    tmp.unlink(missing_ok=True)


def clear(kind: str | None = None) -> int:
    """Svuota la cache (proxy/thumbs/stab/pezzi di render/grafiche html). Ritorna i byte liberati."""
    import shutil

    freed = 0
    targets = [kind] if kind else ["proxy", "thumbs", "strip", "wave", "preview", "stab", "pezzi", "html"]
    for t in targets:
        d = cache_dir(t)
        for f in d.rglob("*"):
            if f.is_file():
                freed += f.stat().st_size
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    return freed


def tetto_mb(variabile: str, predefinito: int) -> int:
    """Byte concessi a una cache: la variabile d'ambiente vince, ``0`` = niente cache."""
    v = os.environ.get(variabile, "").strip()
    return (int(v) if v.isdigit() else predefinito) * 2**20


def pota(cartella: Path, tetto: int, riposo_s: float = 3600.0) -> int:
    """Tiene la cartella sotto il tetto buttando i file usati meno di recente.

    Le cache di render (pezzi, grafiche html, anteprime) crescono a ogni
    modifica: una versione nuova per ogni ritocco, e le vecchie non servono
    piu'. Senza potatura la cache delle grafiche html era arrivata a 12 GB.
    "Usato" e' la data di modifica, che chi legge dalla cache aggiorna. I file
    toccati da meno di ``riposo_s`` non si toccano: un export in corso li
    puo' ancora aprire. Ritorna i byte liberati.
    """
    import time

    try:
        file = [f for f in cartella.iterdir() if f.is_file() and not f.name.startswith("~")]
        info = [(f, f.stat()) for f in file]
    except OSError:
        return 0
    totale = sum(s.st_size for _, s in info)
    if totale <= tetto:
        return 0
    limite = time.time() - riposo_s
    liberati = 0
    for f, s in sorted(info, key=lambda x: x[1].st_mtime):
        if totale <= tetto * 0.8 or s.st_mtime > limite:
            break
        try:
            f.unlink()
        except OSError:
            continue   # aperto da qualcuno (Windows): resta
        totale -= s.st_size
        liberati += s.st_size
    return liberati
