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
from . import ffmpeg, htmlclip, hw, plugins, probe
from .graph import CompileOptions, compile_project
from .model import Project

Progress = Callable[[dict], None]

CONTAINER_DEFAULTS = {
    ".mp4": ("h264", "aac"),
    ".mov": ("h264", "aac"),
    ".mkv": ("h264", "aac"),
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
    codec: str = "h264"  # h264 | hevc | av1 | vp9
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
            raise RuntimeError("il progetto non ha audio da misurare")

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
            raise RuntimeError("misura loudness fallita:\n" + log[-1000:])
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
        if opts.codec in ("vp9", "gif") or def_v in ("vp9", "gif"):
            enc = {"vp9": "libvpx-vp9", "gif": "gif"}.get(opts.codec if opts.codec in ("vp9", "gif") else def_v, "libvpx-vp9")
        else:
            enc = info.encoder_for(opts.codec, opts.prefer_hw)

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
            args += ["-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-r", str(opts.fps or project.settings.fps)]
    if c.audio_label:
        acodec = opts.audio_codec if opts.audio_codec else def_a
        if ext in (".wav", ".flac"):
            acodec = def_a
        args += ["-c:a", acodec]
        if acodec not in ("pcm_s16le", "flac"):
            args += ["-b:a", opts.audio_bitrate]
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


def render(project: Project, opts: RenderOptions, on_progress: Progress | None = None) -> RenderResult:
    if not opts.output:
        raise ValueError("percorso di output mancante")
    out_path = Path(opts.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="vedit_"))
    t0 = time.time()
    try:
        confini = _confini_se_conviene(project, opts)
        if confini:
            args, duration, warnings, enc = render_a_pezzi(project, opts, confini, workdir,
                                                           on_progress, t0)
        else:
            args, duration, warnings, enc = _passaggio(project, opts, workdir, on_progress, t0)

        size = out_path.stat().st_size if out_path.exists() else 0
        if size == 0:
            raise RuntimeError(f"render terminato ma il file e' vuoto: {out_path}")
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
_PEZZO_EXT = {"h264": ".ts", "hevc": ".ts"}


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

    codec = opts.codec if opts.codec in ("h264", "hevc", "av1", "vp9") else def_v
    pext = _PEZZO_EXT.get(codec, ".mkv") if def_v != "vp9" else ".mkv"
    pezzi = [(i, a, b, workdir / f"pezzo_{i:04d}{pext}")
             for i, (a, b) in enumerate(zip(confini, confini[1:]))]

    def uno(pezzo, o: RenderOptions):
        i, a, b, path = pezzo
        po = replace(o, output=str(path), start=a, end=b, audio=False, jobs=1)
        return _passaggio(project, po, workdir, avanzamento(f"v{i}"), t0, pre)

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
        audio = workdir / f"audio{ext}"
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
    avvisi.append(f"render a {len(pezzi)} pezzi, fino a {stato['picco']} alla volta")
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
        a, b = max(0.0, t), max(0.0, t) + max(2.0 / fps, 0.05)
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
