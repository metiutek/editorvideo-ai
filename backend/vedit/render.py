"""Esecuzione del render: dal progetto al file finale.

Il filtergraph viene scritto su file e passato con ``-filter_complex_script``:
su timeline lunghe supera facilmente il limite di 32k caratteri della riga di
comando di Windows.

Le timeline lunghe si rendono **a pezzi** (``render_a_pezzi``): un grafo unico
per tutto il progetto tiene aperte tutte le clip per tutta la durata, e ogni
clip non ancora iniziata produce fotogrammi trasparenti di attesa a ogni
istante. Il costo cresce col quadrato delle clip: su 370 tagli in due minuti
il render andava a 1/69 del tempo reale. Ogni pezzo compila solo le clip che
lo toccano (``graph.slice_project``), i pezzi girano in parallelo, l'audio
si fa in un passaggio solo e alla fine si incolla tutto senza ricodificare.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from . import effects as fx
from . import captions, ffmpeg, htmlclip, hw, plugins, probe, proxy
from .graph import CompileOptions, compile_project
from .model import Project

Progress = Callable[[dict], None]

CONTAINER_DEFAULTS = {
    ".mp4": ("h264", "aac"),
    ".mov": ("h264", "aac"),
    ".mkv": ("h264", "aac"),
    ".mxf": ("dnxhr", "pcm_s24le"),
    ".webm": ("vp9", "libopus"),
    ".gif": ("gif", None),
    ".mp3": (None, "libmp3lame"),
    ".wav": (None, "pcm_s16le"),
    ".m4a": (None, "aac"),
    ".flac": (None, "flac"),
}


@dataclass
class RenderOptions:
    output: str = ""
    codec: str = "h264"  # h264 | hevc | av1 | vp9 | prores | dnxhr
    quality: str = "high"  # draft | medium | high | max
    bitrate: str | None = None
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    start: float | None = None
    end: float | None = None
    use_proxy: bool = False
    prefer_hw: bool = True
    # Decodifica accelerata: si spegne da sola al primo ripiego, tenendo pero'
    # l'encoder GPU. Sono due meta' separabili e non valgono lo stesso.
    hwaccel_decode: bool = True
    video: bool = True
    audio: bool = True
    threads: int | None = None
    keep_workdir: bool = False
    # render a pezzi paralleli: None = deciso da ``_pezzi_paralleli`` (o da
    # VEDIT_RENDER_JOBS), 1 = un grafo solo come prima
    jobs: int | None = None
    # sottotitoli come traccia nel file (soft): da una traccia di testi o da un
    # file .srt/.vtt/.ass. Di norma la traccia scelta non si imprime
    # nell'immagine, se no si vedrebbero due volte; ``burn_subtitles`` la tiene
    subtitle_track: str | None = None
    subtitle_file: str | None = None
    subtitle_lang: str = "ita"
    burn_subtitles: bool = False


@dataclass
class RenderResult:
    output: str
    duration: float
    seconds: float
    encoder: str
    size: int
    warnings: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)


def _cache_dir() -> Path:
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    base.mkdir(parents=True, exist_ok=True)
    return base


# --------------------------------------------------------------------------
# analisi preliminari
# --------------------------------------------------------------------------


def analyze_stabilization(project: Project, force: bool = False) -> dict:
    """Primo passaggio vidstab per ogni clip con l'effetto ``stabilize``."""
    out: dict[str, str] = {}
    if "vidstabdetect" not in ffmpeg.filters():
        return out
    stab_dir = _cache_dir() / "stab"
    stab_dir.mkdir(parents=True, exist_ok=True)

    for track in project.video_tracks():
        for clip in track.clips:
            if not clip.enabled or not any(e.type == "stabilize" and e.enabled for e in clip.effects):
                continue
            media = project.media_by_id(clip.media)
            if media is None:
                continue
            # hashlib e non hash(): quello delle stringhe cambia a ogni processo,
            # e la cache non veniva mai ritrovata — l'analisi, che e' un
            # passaggio intero sul file, si rifaceva a ogni render
            firma = f"{media.path}|{clip.in_:.4f}|{clip.source_duration():.4f}"
            trf = stab_dir / f"{clip.id}_{hashlib.sha1(firma.encode()).hexdigest()[:10]}.trf"
            if trf.exists() and not force:
                out[clip.id] = str(trf)
                continue
            args = ffmpeg.base_cmd()
            if clip.in_:
                args += ["-ss", str(clip.in_)]
            args += ["-t", str(clip.source_duration()), "-i", media.path,
                     "-vf", f"vidstabdetect=shakiness=6:accuracy=15:result='{fx.esc_path(str(trf))}'",
                     "-f", "null", "NUL" if os.name == "nt" else "/dev/null"]
            ffmpeg.run(args, timeout=3600)
            out[clip.id] = str(trf)
    return out


def measure_loudness(project: Project) -> dict:
    """Misura il mix completo per la normalizzazione lineare a due passaggi."""
    work = Path(tempfile.mkdtemp(prefix="vedit_ln_"))
    try:
        ln = project.master.loudnorm
        was = ln.enabled
        ln.enabled = False  # il primo passaggio misura il mix grezzo
        try:
            c = compile_project(project, CompileOptions(video=False, audio=True, workdir=str(work),
                                                        audio_files=_plugin_files(project, None, None)))
        finally:
            ln.enabled = was
        if not c.audio_label:
            raise RuntimeError("the project has no audio to measure")

        script = work / "fg.txt"
        graph = c.filtergraph + f";[{c.audio_label}]loudnorm=I={ln.i}:TP={ln.tp}:LRA={ln.lra}:print_format=json[lnout]"
        script.write_text(graph, encoding="utf-8")

        args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-y"]
        args += c.inputs
        args += ["-filter_complex_script", str(script), "-map", "[lnout]",
                 "-f", "null", "NUL" if os.name == "nt" else "/dev/null"]
        proc = ffmpeg.run(args, check=False, timeout=7200)
        log = (proc.stderr or "") + (proc.stdout or "")
        i, j = log.rfind("{"), log.rfind("}")
        if i == -1 or j == -1:
            raise RuntimeError("loudness measurement failed:\n" + log[-1000:])
        import json

        return json.loads(log[i : j + 1])
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------


def _html_files(project: Project, width: int | None, height: int | None, fps: float | None,
                start: float | None, end: float | None) -> dict:
    """Clip html fotografate alla risoluzione e cadenza di questo render."""
    if not any(c.type == "html" for t in project.tracks for c in t.clips):
        return {}
    s = project.settings
    return htmlclip.prepare(project, width=int(width or s.width), height=int(height or s.height),
                            fps=float(fps or s.fps), start=start, end=end)


def _plugin_files(project: Project, start: float | None, end: float | None) -> dict:
    """Clip con plugin VST: il loro suono passa nel plugin prima del render."""
    if not any(e.type == "vst" for t in project.tracks for c in t.clips for e in c.effects):
        return {}
    return plugins.prepare(project, start, end)


def _preparativi(project: Project, opts: RenderOptions, want_video: bool, want_audio: bool) -> dict:
    """Lavoro fuori da ffmpeg (stabilizzazione, html, plugin): una volta sola per render."""
    return {
        "stab": analyze_stabilization(project),
        "html": _html_files(project, opts.width, opts.height, opts.fps, opts.start, opts.end)
        if want_video else {},
        "suoni": _plugin_files(project, opts.start, opts.end) if want_audio else {},
    }


# dove stanno i codec da montaggio: MXF e' il contenitore di Avid e del broadcast
CONTENITORI_MEZZANINE = (".mov", ".mxf", ".mkv")
CODEC = ("h264", "hevc", "av1", "vp9", "prores", "dnxhr")


def controlla_codec(codec: str, output: str) -> None:
    """Rifiuta prima di partire le coppie codec/contenitore che ffmpeg non scrive.

    Un .mxf con un codec di consegna non e' un errore: come .webm impone VP9,
    .mxf impone DNxHR.
    """
    ext = Path(output).suffix.lower()
    if codec not in CODEC and codec != "gif":
        raise ValueError(f"unknown codec {codec!r}; allowed: {', '.join(CODEC)}")
    def_v = CONTAINER_DEFAULTS.get(ext, ("h264", "aac"))[0]
    if codec in hw.MEZZANINE and def_v is not None and ext not in CONTENITORI_MEZZANINE:
        raise ValueError(f"{codec} goes in a .mov, .mxf or .mkv file, not {ext or 'no extension'}")


def _codec_video(opts: RenderOptions, def_v: str | None) -> str:
    """Il codec che si usa davvero: il contenitore lo impone per webm, gif e mxf."""
    if def_v in ("vp9", "gif"):
        return def_v
    if def_v == "dnxhr" and opts.codec not in hw.MEZZANINE:
        return def_v
    return opts.codec


# contenitori che accettano solo certi codec audio. L'AAC predefinito di
# RenderOptions faceva fallire ogni .webm con audio e ogni .mp3
_AUDIO_AMMESSI = {".webm": ("libopus", "libvorbis"), ".mp3": ("libmp3lame",),
                  ".wav": ("pcm_s16le", "pcm_s24le"), ".flac": ("flac",)}


def _codec_audio(opts: RenderOptions, ext: str, def_a: str) -> str:
    # accanto a un mezzanine l'audio resta non compresso, come se lo aspetta chi lo riceve
    if opts.codec in hw.MEZZANINE or ext == ".mxf":
        return "pcm_s24le"
    if ext in _AUDIO_AMMESSI and opts.audio_codec not in _AUDIO_AMMESSI[ext]:
        return def_a
    return opts.audio_codec or def_a


def _bitrate_audio(b: str, k: float) -> str:
    try:
        return f"{int(float(b.rstrip('kK')) * k)}k" if b.lower().endswith("k") else b
    except ValueError:
        return b


def build_command(project: Project, opts: RenderOptions, workdir: Path,
                  pre: dict | None = None) -> tuple[list[str], float, list[str], str]:
    out_path = Path(opts.output)
    ext = out_path.suffix.lower()
    def_v, def_a = CONTAINER_DEFAULTS.get(ext, ("h264", "aac"))
    want_video = opts.video and def_v is not None
    want_audio = opts.audio and def_a is not None

    info = hw.detect()
    enc = "libx264"
    if want_video:
        codec = _codec_video(opts, def_v)
        if opts.codec in ("vp9", "gif") or codec in ("vp9", "gif"):
            enc = {"vp9": "libvpx-vp9", "gif": "gif"}.get(opts.codec if opts.codec in ("vp9", "gif") else codec, "libvpx-vp9")
        else:
            enc = info.encoder_for(codec, opts.prefer_hw)

    pre = pre if pre is not None else _preparativi(project, opts, want_video, want_audio)
    stab, html, suoni = pre["stab"], pre["html"], pre["suoni"]
    copts = CompileOptions(
        width=opts.width, height=opts.height, fps=opts.fps,
        use_proxy=opts.use_proxy, audio=want_audio, video=want_video,
        start=opts.start, end=opts.end, workdir=str(workdir),
        hwaccel=info.hwaccel if (opts.prefer_hw and opts.hwaccel_decode and info.is_hw(enc)) else "",
        stab_files=stab, html_files=html, audio_files=suoni,
    )
    c = compile_project(project, copts)

    # nome legato all'uscita: i pezzi di un render parallelo condividono workdir
    script = workdir / f"filtergraph_{out_path.stem}.txt"
    script.write_text(c.filtergraph, encoding="utf-8")

    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if opts.threads:
        args += ["-threads", str(opts.threads)]
    args += c.inputs
    args += ["-filter_complex_script", str(script)]

    if c.video_label:
        args += ["-map", f"[{c.video_label}]"]
    if c.audio_label:
        args += ["-map", f"[{c.audio_label}]"]

    if c.video_label:
        if enc == "gif":
            args += ["-loop", "0"]
        else:
            args += hw.encoder_args(enc, opts.quality, opts.bitrate)
            args += ["-pix_fmt", hw.pix_fmt(enc, opts.quality), "-fps_mode", "cfr",
                     "-r", str(opts.fps or project.settings.fps)]
    if c.audio_label:
        acodec = _codec_audio(opts, ext, def_a)
        args += ["-c:a", acodec]
        surround = getattr(project.settings, "audio_layout", "stereo") == "5.1"
        if surround and acodec == "libmp3lame":
            # l'mp3 non ha il 5.1: si ripiega in stereo invece di fallire
            args += ["-ac", "2"]
            surround = False
        if not acodec.startswith("pcm_") and acodec != "flac":
            # sei canali a 192k suonerebbero peggio dello stereo: il doppio
            args += ["-b:a", _bitrate_audio(opts.audio_bitrate, 2.0 if surround else 1.0)]
        if surround and acodec == "libopus":
            args += ["-mapping_family", "1"]
        args += ["-ar", str(project.settings.sample_rate)]

    args += ["-t", f"{c.duration:.6f}"]
    if ext in (".mp4", ".mov", ".m4a"):
        args += ["-movflags", "+faststart"]
    args += ["-progress", "pipe:1", "-nostats", str(out_path)]
    return args, c.duration, c.warnings, enc


_TIME_RE = re.compile(r"out_time_us=(\d+)")


def _run_pass(args: list[str], duration: float, on_progress: Progress | None,
              t0: float) -> tuple[int, list[str]]:
    """Esegue ffmpeg riportando l'avanzamento. Ritorna (codice, righe di log)."""
    proc = ffmpeg.popen(args)
    log_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        m = _TIME_RE.match(line)
        if m and on_progress:
            done = int(m.group(1)) / 1e6
            on_progress({
                "seconds": round(done, 3),
                "duration": round(duration, 3),
                "percent": round(min(100.0, done / duration * 100), 2) if duration else 0.0,
                "elapsed": round(time.time() - t0, 2),
            })
        elif not line.startswith(("frame=", "fps=", "bitrate=", "total_size=", "out_time",
                                  "dup_frames=", "drop_frames=", "speed=", "progress=", "stream_")):
            log_lines.append(line)
    return proc.wait(), log_lines


# Righe di contorno: dicono che qualcosa e' andato storto, non che cosa.
_RUMORE = ("Error sending frames", "Task finished with error", "Terminating thread",
           "Could not open encoder before EOF", "Nothing was written into output",
           "Conversion failed", "Error while filtering")


def _perche(log_lines: list[str]) -> str:
    """La riga di ffmpeg che spiega davvero il fallimento, per il messaggio.

    Senza questo il ripiego era muto: si sapeva che la GPU non era stata usata,
    mai perche'. Una diagnosi come ``no encode device`` cambia cosa si va a
    guardare, quindi va portata a galla invece di finire nel niente.
    """
    utile = [r for r in log_lines if r.strip() and not any(n in r for n in _RUMORE)]
    if not utile:
        return ""
    riga = re.sub(r"@ [0-9a-fx]+ ", "", utile[0]).strip()
    return f" ({riga[:160]})"


def _passaggio(project: Project, opts: RenderOptions, workdir: Path, on_progress: Progress | None,
               t0: float, pre: dict | None = None) -> tuple[list[str], float, list[str], str]:
    """Un render ffmpeg con i ripieghi dell'accelerazione. Ritorna (comando, durata, avvisi, encoder)."""
    args, duration, warnings, enc = build_command(project, opts, workdir, pre)
    code, log_lines = _run_pass(args, duration, on_progress, t0)
    warnings = list(warnings)

    # L'accelerazione hardware e' un'ottimizzazione: non vale un render
    # perso. La GPU puo' mancare al momento giusto — device che non nasce,
    # sessioni dell'encoder gia' tutte occupate da altri processi, driver
    # che cede sotto carico — e ffmpeg non se ne accorge con grazia: esce
    # di schianto.
    #
    # Si ripiega pero' a gradini, non tutto in una volta: le due meta'
    # dell'accelerazione non valgono lo stesso e non falliscono insieme. Il
    # caso tipico e' la coppia che non regge — decodifica accelerata che
    # crea il device sull'adattatore sbagliato e ne fa morire l'encoder —
    # dove basta togliere la decodifica per riavere il render su GPU.
    # Buttare subito anche l'encoder e' quello che trasformava trenta
    # secondi di render in tre minuti, senza dirlo.
    if code != 0 and opts.prefer_hw and "-hwaccel" in args:
        warnings.append(
            "decodifica accelerata fallita: rifatto senza, encoder GPU mantenuto"
            + _perche(log_lines))
        args, duration, _, enc = build_command(
            project, replace(opts, hwaccel_decode=False), workdir, pre)
        code, log_lines = _run_pass(args, duration, on_progress, t0)

    if code != 0 and opts.prefer_hw and hw.detect().is_hw(enc):
        warnings.append(
            "accelerazione hardware fallita: rifatto in software (piu' lento)"
            + _perche(log_lines))
        args, duration, _, enc = build_command(
            project, replace(opts, prefer_hw=False, hwaccel_decode=False), workdir, pre)
        code, log_lines = _run_pass(args, duration, on_progress, t0)

    if code != 0:
        raise ffmpeg.FFmpegError(args, code, "\n".join(log_lines[-40:]))
    return args, duration, warnings, enc


# contenitore -> codec dei sottotitoli soft; MXF e GIF non ne portano
SOTTOTITOLI_CODEC = {".mp4": "mov_text", ".mov": "mov_text", ".m4v": "mov_text",
                     ".mkv": "srt", ".webm": "webvtt"}


def _righe_sottotitoli(project: Project, opts: RenderOptions) -> list[dict] | None:
    """Le righe da mettere nel file, gia' riportate al tratto renderizzato."""
    if not opts.subtitle_track and not opts.subtitle_file:
        return None
    ext = Path(opts.output).suffix.lower()
    if ext not in SOTTOTITOLI_CODEC:
        raise ValueError(f"a {ext} file cannot carry a subtitle stream: use .mp4, .mov, "
                         ".mkv or .webm, or burn them in")
    a = opts.start or 0.0
    if opts.subtitle_track:
        return captions.da_traccia(project, opts.subtitle_track, a, opts.end)
    p = Path(opts.subtitle_file)
    fmt = p.suffix.lower().lstrip(".")
    righe = captions.leggi(p.read_text(encoding="utf-8-sig", errors="replace"),
                           "ass" if fmt == "ssa" else fmt)
    b = opts.end if opts.end is not None else float("inf")
    return [{**r, "start": max(r["start"], a) - a, "end": min(r["end"], b) - a}
            for r in righe if min(r["end"], b) - max(r["start"], a) > 1e-3]


def _metti_sottotitoli(out_path: Path, righe: list[dict], lingua: str, workdir: Path) -> None:
    """Rimuxa il file con i sottotitoli come traccia a se': video e audio non si ricodificano."""
    srt = workdir / "sottotitoli.srt"
    srt.write_text(captions.to_srt(righe), encoding="utf-8", newline="\n")
    tmp = out_path.with_name(f"~sub_{out_path.name}")
    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(out_path), "-i", str(srt), "-map", "0", "-map", "1", "-c", "copy",
            "-c:s", SOTTOTITOLI_CODEC[out_path.suffix.lower()],
            "-metadata:s:s:0", f"language={lingua or 'und'}", "-disposition:s:0", "default"]
    if out_path.suffix.lower() in (".mp4", ".mov", ".m4v"):
        args += ["-movflags", "+faststart"]
    args.append(str(tmp))
    proc = ffmpeg.run(args, check=False, timeout=3600)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise ffmpeg.FFmpegError(args, proc.returncode, (proc.stderr or "")[-2000:])
    os.replace(tmp, out_path)


def render(project: Project, opts: RenderOptions, on_progress: Progress | None = None) -> RenderResult:
    if not opts.output:
        raise ValueError("output path missing")
    controlla_codec(opts.codec, opts.output)
    out_path = Path(opts.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    righe = _righe_sottotitoli(project, opts)
    if opts.subtitle_track and not opts.burn_subtitles:
        # la traccia diventa sottotitoli del file: nell'immagine non si imprime
        project = Project.from_obj(project.to_dict())
        for t in project.tracks:
            if t.id == opts.subtitle_track:
                t.hidden = True

    workdir = Path(tempfile.mkdtemp(prefix="vedit_"))
    t0 = time.time()
    try:
        confini = _confini_se_conviene(project, opts)
        if confini:
            args, duration, warnings, enc = render_a_pezzi(project, opts, confini, workdir,
                                                           on_progress, t0)
        else:
            args, duration, warnings, enc = _passaggio(project, opts, workdir, on_progress, t0)

        if righe:
            _metti_sottotitoli(out_path, righe, opts.subtitle_lang, workdir)
            warnings = [*warnings, f"{len(righe)} sottotitoli nel file come traccia "
                        f"({opts.subtitle_lang})"]
        size = out_path.stat().st_size if out_path.exists() else 0
        if size == 0:
            raise RuntimeError(f"render finished but the file is empty: {out_path}")
        return RenderResult(
            output=str(out_path.resolve()), duration=duration, seconds=round(time.time() - t0, 2),
            encoder=enc, size=size, warnings=warnings, command=args,
        )
    finally:
        if opts.keep_workdir:
            print(f"workdir conservata: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


# --------------------------------------------------------------------------
# render a pezzi
# --------------------------------------------------------------------------

# Pezzi corti: la memoria di un pezzo cresce con le clip che contiene (ogni
# clip e' una catena di filtri a piena risoluzione con i suoi buffer), e
# avviare un ffmpeg costa pochi decimi di secondo.
PEZZO_S = 4.0      # durata cercata di un pezzo
PEZZO_MIN = 1.5
PEZZO_MAX = 8.0
# sotto questa durata un grafo solo costa meno dell'avvio di piu' ffmpeg
SOGLIA_PEZZI_S = 20.0
# effetti che ricordano i fotogrammi precedenti (o li contano dall'inizio
# della clip): un confine dentro la clip cambierebbe il risultato
_CON_MEMORIA = {"stabilize", "motionblur", "denoise"}
# contenitore dei pezzi per codec: TS ha il tempo a 90 kHz e si incolla senza
# edit list; vp9 e av1 non ci stanno e vanno in matroska
_PEZZO_EXT = {"h264": ".ts", "hevc": ".ts", "prores": ".mov", "dnxhr": ".mov"}


def _pezzi_paralleli(opts: RenderOptions) -> int:
    """Quanti pezzi alla volta.

    Ogni ffmpeg usa gia' piu' thread: oltre tre pezzi si guadagna poco, si
    moltiplica la memoria e si rischia di finire le sessioni NVENC dei driver
    vecchi, che farebbero ripiegare un pezzo su un altro encoder.
    """
    if opts.jobs:
        return max(1, int(opts.jobs))
    env = os.environ.get("VEDIT_RENDER_JOBS", "").strip()
    if env.isdigit():
        return max(1, int(env))
    return max(1, min(3, (os.cpu_count() or 2) // 4))


# Misurato su un progetto vero a 1080p (pezzi da 6 s, effetti pesanti): circa
# 300 MB fissi piu' 130 MB per clip. E' una stima prudente, non un tetto.
MEMORIA_BASE = 300 * 2**20
MEMORIA_CLIP = 130 * 2**20
MEMORIA_RISERVA = 1024 * 2**20


def stima_memoria(project: Project, a: float, b: float, w: int, h: int) -> int:
    """Byte che un pezzo [a, b) occupera' durante il render."""
    n = sum(1 for t in project.live_tracks("video") for c in t.clips
            if c.enabled and c.duration > 0 and c.end > a and c.start < b)
    k = max(0.1, (w * h) / (1920 * 1080))
    return int(MEMORIA_BASE + MEMORIA_CLIP * n * k)


def memoria_libera() -> int | None:
    """Byte di RAM disponibili adesso, o None se il sistema non lo dice."""
    try:
        if os.name == "nt":
            import ctypes

            class _Stato(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = _Stato()
            st.dwLength = ctypes.sizeof(_Stato)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullAvailPhys)
            return None
        with open("/proc/meminfo", encoding="ascii") as f:
            for riga in f:
                if riga.startswith("MemAvailable:"):
                    return int(riga.split()[1]) * 1024
    except (OSError, ValueError, AttributeError):
        return None
    return None


def confini_pezzi(project: Project, a: float, b: float, fps: float) -> list[float]:
    """Dove tagliare [a, b) in pezzi: sui fotogrammi, possibilmente sugli stacchi.

    Un confine non cade mai dentro una clip con un effetto che ha memoria dei
    fotogrammi passati (stabilizzazione, mosso, denoise temporale): li' il
    pezzo si allunga fino alla fine della clip.
    """
    def frame(x: float) -> float:
        return round(x * fps) / fps

    a, b = frame(a), frame(b)
    clip = [c for t in project.live_tracks("video") for c in t.clips
            if c.enabled and c.duration > 0]
    vietati = [(c.start, c.end) for c in clip
               if any(e.enabled and e.type in _CON_MEMORIA for e in c.effects)]

    def dentro(x: float) -> list[float]:
        return [e for s, e in vietati if s + 1e-6 < x < e - 1e-6]

    stacchi = sorted({frame(x) for c in clip for x in (c.start, c.end) if a < x < b})
    stacchi = [x for x in stacchi if not dentro(x)]
    out, cur = [a], a
    while b - cur > PEZZO_MAX:
        voluti = [x for x in stacchi
                  if cur + PEZZO_MIN <= x <= cur + PEZZO_MAX and x < b - 1 / fps]
        if voluti:
            nxt = min(voluti, key=lambda x: abs(x - (cur + PEZZO_S)))
        else:
            nxt = frame(cur + PEZZO_S)
            while dentro(nxt):
                nxt = frame(max(dentro(nxt)))
            if nxt >= b - 1 / fps:
                break
        out.append(nxt)
        cur = nxt
    out.append(b)
    return out


def _confini_se_conviene(project: Project, opts: RenderOptions) -> list[float] | None:
    ext = Path(opts.output).suffix.lower()
    def_v, _ = CONTAINER_DEFAULTS.get(ext, ("h264", "aac"))
    if not opts.video or def_v is None or def_v == "gif" or opts.codec == "gif":
        return None
    if opts.jobs == 1:
        return None
    a = opts.start or 0.0
    b = opts.end if opts.end is not None else project.duration()
    if b - a < SOGLIA_PEZZI_S:
        return None
    confini = confini_pezzi(project, a, b, float(opts.fps or project.settings.fps))
    return confini if len(confini) > 2 else None


# --------------------------------------------------------------------------
# cache dei pezzi
# --------------------------------------------------------------------------
#
# Il render e' una funzione pura del progetto, e un pezzo e' gia' nel formato
# finale (si incolla senza ricodifica): un pezzo con lo stesso comando e gli
# stessi file d'ingresso esce identico. Si conserva per contenuto, come il
# Render in Place di Resolve o le anteprime di Premiere: correggere un taglio
# e riesportare rifa' solo i pezzi che quel taglio tocca.

CACHE_PEZZI_MB = 4096
_FILE_NEL_GRAFO = re.compile(r"(?:file|filename|fontfile|textfile|input)='([^']*)'")


def _firma_file(path: str, workdir: Path, h) -> None:
    """Un file usato dal pezzo: il contenuto se e' temporaneo, altrimenti misura e data."""
    p = Path(path)
    try:
        if workdir in p.parents:
            h.update(p.relative_to(workdir).as_posix().encode())
            h.update(p.read_bytes())
        elif _cache_dir() in p.parents:
            # la cache di vedit (grafiche html, proxy, stabilizzazione) ha gia'
            # il contenuto nel nome; la data no, perche' la potatura la
            # aggiorna a ogni uso e cambierebbe la chiave senza motivo
            h.update(f"{p}|{p.stat().st_size}".encode())
        else:
            st = p.stat()
            h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
    except OSError:
        h.update(f"{p}|assente".encode())


def chiave_pezzo(args: list[str], workdir: Path) -> str:
    """Firma del comando di un pezzo, senza i percorsi che cambiano a ogni render."""
    h = hashlib.sha256()
    wd = str(workdir)
    segnaposto = (wd, wd.replace("\\", "/"), fx.esc_path(wd))
    exe = Path(args[0])
    try:
        h.update(f"{exe}|{exe.stat().st_mtime_ns}".encode())
    except OSError:
        h.update(str(exe).encode())
    salta = False
    for i, a in enumerate(args[1:-1], 1):   # l'ultimo e' l'uscita
        if salta:
            salta = False
            continue
        if args[i - 1] == "-i":
            _firma_file(a, workdir, h)
        elif a == "-filter_complex_script":
            grafo = Path(args[i + 1]).read_text(encoding="utf-8")
            for f in _FILE_NEL_GRAFO.findall(grafo):
                _firma_file(f.replace("\\:", ":"), workdir, h)
            for s in segnaposto:
                grafo = grafo.replace(s, "<WD>")
            h.update(grafo.encode())
            salta = True
        else:
            h.update(a.encode())
        h.update(b"\0")
    return h.hexdigest()[:32]


def _cache_pezzi() -> Path:
    d = _cache_dir() / "pezzi"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tetto_cache_pezzi() -> int:
    """Byte concessi alla cache dei pezzi; ``VEDIT_CACHE_PEZZI_MB=0`` la spegne."""
    return proxy.tetto_mb("VEDIT_CACHE_PEZZI_MB", CACHE_PEZZI_MB)


def _pota_cache_pezzi() -> None:
    """Tiene la cache sotto il tetto, buttando i pezzi usati meno di recente.

    Nessun riposo: un pezzo ripreso si copia nella cartella del render, quindi
    toglierlo dalla cache non disturba un export in corso.
    """
    proxy.pota(_cache_pezzi(), _tetto_cache_pezzi(), riposo_s=0)


def render_a_pezzi(project: Project, opts: RenderOptions, confini: list[float], workdir: Path,
                   on_progress: Progress | None, t0: float) -> tuple[list[str], float, list[str], str]:
    """Video a pezzi in parallelo, audio in un passaggio, poi un incollaggio senza ricodifica."""
    out_path = Path(opts.output)
    ext = out_path.suffix.lower()
    def_v, def_a = CONTAINER_DEFAULTS.get(ext, ("h264", "aac"))
    want_audio = opts.audio and def_a is not None
    durata = confini[-1] - confini[0]
    pre = _preparativi(project, opts, True, want_audio)

    fatto: dict[str, float] = {}
    lock = threading.Lock()

    def avanzamento(chiave: str):
        def cb(info: dict) -> None:
            if on_progress is None:
                return
            with lock:
                fatto[chiave] = info["seconds"]
                done = min(durata, sum(fatto.values()))
                on_progress({"seconds": round(done, 3), "duration": round(durata, 3),
                             "percent": round(done / durata * 100, 2) if durata else 0.0,
                             "elapsed": round(time.time() - t0, 2)})
        return cb

    codec = _codec_video(opts, def_v) if opts.codec in CODEC else def_v
    pext = _PEZZO_EXT.get(codec, ".mkv") if def_v != "vp9" else ".mkv"
    pezzi = [(i, a, b, workdir / f"pezzo_{i:04d}{pext}")
             for i, (a, b) in enumerate(zip(confini, confini[1:]))]

    riusati = [0]
    con_cache = _tetto_cache_pezzi() > 0

    def uno(pezzo, o: RenderOptions):
        i, a, b, path = pezzo
        po = replace(o, output=str(path), start=a, end=b, audio=False, jobs=1)
        if not con_cache:
            return _passaggio(project, po, workdir, avanzamento(f"v{i}"), t0, pre)
        args, _, _, _ = build_command(project, po, workdir, pre)
        chiave = chiave_pezzo(args, workdir)
        salvato = _cache_pezzi() / f"{chiave}{path.suffix}"
        meta = salvato.with_suffix(".json")
        if salvato.exists() and meta.exists():
            try:
                info = json.loads(meta.read_text(encoding="utf-8"))
                shutil.copyfile(salvato, path)
                os.utime(salvato)   # usato adesso: la potatura lo tiene
                os.utime(meta)
                avanzamento(f"v{i}")({"seconds": b - a})
                with lock:
                    riusati[0] += 1
                return args, b - a, info["avvisi"], info["encoder"]
            except (OSError, ValueError, KeyError):
                pass   # cache rovinata: si rifa' il pezzo
        esito = _passaggio(project, po, workdir, avanzamento(f"v{i}"), t0, pre)
        # la chiave e' quella del comando chiesto; se c'e' stato un ripiego
        # l'encoder vero e' scritto accanto, e l'incollaggio lo controlla
        try:
            tmp = salvato.with_name(f"~{os.getpid()}_{i}_{salvato.name}")
            shutil.copyfile(path, tmp)
            os.replace(tmp, salvato)
            meta.write_text(json.dumps({"encoder": esito[3], "avvisi": esito[2]}), encoding="utf-8")
        except OSError:
            pass   # senza cache il render vale lo stesso
        return esito

    # Quanti pezzi alla volta lo decide anche la memoria: un pezzo parte solo
    # se la sua stima ci sta in quella libera all'inizio del render. Il primo
    # parte comunque, da solo: meglio lento che fermo. Senza questo, tre pezzi
    # da due giga su un PC con poca RAM libera facevano chiudere i programmi.
    s = project.settings
    w, h = int(opts.width or s.width), int(opts.height or s.height)
    libera = memoria_libera()
    budget = float("inf") if libera is None else libera - MEMORIA_RISERVA
    massimo = _pezzi_paralleli(opts)
    cond = threading.Condition()
    stato = {"uso": 0, "attivi": 0, "picco": 0}

    def con_budget(pezzo, o: RenderOptions):
        serve = stima_memoria(project, pezzo[1], pezzo[2], w, h)
        with cond:
            while stato["attivi"]:
                # la memoria la usano anche gli altri programmi: si riguarda
                # quella vera a ogni pezzo, non solo la stima di partenza
                adesso = memoria_libera()
                if (stato["attivi"] < massimo and stato["uso"] + serve <= budget
                        and (adesso is None or adesso - MEMORIA_RISERVA >= serve)):
                    break
                cond.wait(timeout=1.0)
            stato["uso"] += serve
            stato["attivi"] += 1
            stato["picco"] = max(stato["picco"], stato["attivi"])
        try:
            return uno(pezzo, o)
        finally:
            with cond:
                stato["uso"] -= serve
                stato["attivi"] -= 1
                cond.notify_all()

    def tutti(lista, o: RenderOptions):
        with ThreadPoolExecutor(max_workers=massimo) as ex:
            futuri = [ex.submit(con_budget, p, o) for p in lista]
            try:
                return [f.result() for f in futuri]
            except BaseException:
                for f in futuri:
                    f.cancel()
                raise

    # l'audio non aspetta il video: e' un passaggio leggero, gira accanto ai pezzi
    audio = None
    lavoro_audio = None
    sfondo = ThreadPoolExecutor(max_workers=1)
    if want_audio and compile_project(project, CompileOptions(
            video=False, audio=True, start=confini[0], end=confini[-1],
            audio_files=pre["suoni"], workdir=str(workdir))).audio_label:
        # un .mxf di solo audio non serve a nessuno: l'audio dei mezzanine passa da un .mov
        audio = workdir / f"audio{'.mov' if codec in hw.MEZZANINE else ext}"
        lavoro_audio = sfondo.submit(
            _passaggio, project, replace(opts, output=str(audio), video=False, jobs=1),
            workdir, None, t0, pre)
    try:
        esiti = tutti(pezzi, opts)
    except BaseException:
        sfondo.shutdown(wait=True, cancel_futures=True)
        raise
    avvisi: list[str] = []
    for _, _, w, _ in esiti:
        avvisi += [x for x in w if x not in avvisi]

    # pezzi con encoder diversi (un ripiego della GPU) non si incollano senza
    # ricodifica: si rifanno quelli rimasti sull'encoder GPU come gli altri
    encoder = [e for _, _, _, e in esiti]
    if len(set(encoder)) > 1:
        sw = next(e for e in encoder if not hw.detect().is_hw(e))
        rifare = [p for p, e in zip(pezzi, encoder) if e != sw]
        avvisi.append(f"encoder GPU caduto su una parte dei pezzi: {len(rifare)} rifatti con {sw}")
        tutti(rifare, replace(opts, prefer_hw=False, hwaccel_decode=False))
        encoder = [sw]

    try:
        if lavoro_audio is not None:
            _, _, w, _ = lavoro_audio.result()
            avvisi += [x for x in w if x not in avvisi]
    finally:
        sfondo.shutdown(wait=True)

    elenco = workdir / "pezzi.txt"
    righe = []
    for _, _, _, path in pezzi:
        righe.append("file '{}'\n".format(str(path).replace("\\", "/").replace("'", "'\\''")))
    elenco.write_text("".join(righe), encoding="utf-8")
    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(elenco)]
    if audio is not None and audio.exists():
        args += ["-i", str(audio), "-map", "0:v", "-map", "1:a"]
    else:
        args += ["-map", "0:v"]
    args += ["-c", "copy"]
    if codec == "hevc" and ext in (".mp4", ".mov"):
        args += ["-tag:v", "hvc1"]
    args += ["-t", f"{durata:.6f}"]
    if ext in (".mp4", ".mov"):
        args += ["-movflags", "+faststart"]
    args.append(str(out_path))
    proc = ffmpeg.run(args, check=False, timeout=3600)
    if proc.returncode != 0:
        raise ffmpeg.FFmpegError(args, proc.returncode, (proc.stderr or "")[-2000:])
    avvisi.append(f"render a {len(pezzi)} pezzi, fino a {stato['picco']} alla volta"
                  + (f", {riusati[0]} ripresi dalla cache" if riusati[0] else ""))
    try:
        _pota_cache_pezzi()
    except OSError:
        pass
    return args, durata, avvisi, encoder[0]


def render_frame(project: Project, t: float, output: str, width: int | None = None,
                 use_proxy: bool = True) -> str:
    """Estrae un singolo frame della timeline al tempo ``t`` (thumbnail/ispezione)."""
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="vedit_frame_"))
    try:
        fps = project.settings.fps
        w = width or project.settings.width
        h = int(round(w * project.settings.height / project.settings.width))
        h += h % 2
        # l'istante va all'inizio del suo fotogramma, che e' quello che il render
        # mostra li': a meta' dell'ultimo fotogramma di una clip il tratto
        # visibile era troppo corto per produrne uno e l'anteprima usciva nera
        t = math.floor(max(0.0, t) * fps + 1e-6) / fps
        a, b = t, t + max(2.0 / fps, 0.05)
        copts = CompileOptions(
            width=w, height=h, fps=fps, use_proxy=use_proxy, audio=False, video=True,
            start=a, end=b, workdir=str(workdir),
            html_files=_html_files(project, w, h, fps, a, b),
        )
        c = compile_project(project, copts)
        script = workdir / "fg.txt"
        script.write_text(c.filtergraph, encoding="utf-8")
        args = ffmpeg.base_cmd() + c.inputs + [
            "-filter_complex_script", str(script), "-map", f"[{c.video_label}]",
            "-frames:v", "1", "-q:v", "3", str(out),
        ]
        ffmpeg.run(args, timeout=600)
        return str(out.resolve())
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def probe_output(path: str) -> dict:
    """Riepilogo del file prodotto (per verificare il risultato)."""
    m = probe.probe(path)
    return {
        "path": m.path, "duration": m.duration, "width": m.width, "height": m.height,
        "fps": m.fps, "has_audio": m.has_audio,
        "size_mb": round(Path(path).stat().st_size / 1e6, 2),
    }
