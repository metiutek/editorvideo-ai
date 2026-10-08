"""Plugin audio esterni (VST3, e AU su Mac) attraverso pedalboard.

ffmpeg non carica plugin: il suono di una clip passa nel plugin *prima* del
render, con i parametri scelti, e il risultato finisce in cache come wav. Il
grafo poi usa quel file al posto della sorgente (``CompileOptions.audio_files``),
quindi tagli, velocita', dissolvenze e gli altri effetti funzionano come sempre.

I plugin vengono applicati per primi, nell'ordine in cui compaiono fra gli
effetti della clip; gli effetti ffmpeg arrivano dopo.

Serve l'extra ``plugin`` (pedalboard). I VST2 (.dll) non sono supportati da
pedalboard: serve la versione VST3 del plugin.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import ffmpeg

VERSIONE = 1


class PluginNonDisponibile(RuntimeError):
    """Manca pedalboard o il plugin non si carica."""


def cartelle_standard() -> list[Path]:
    if sys.platform == "win32":
        base = [os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files"),
                os.environ.get("CommonProgramFiles(x86)", r"C:\Program Files (x86)\Common Files")]
        return [Path(b) / "VST3" for b in base] + [Path.home() / "AppData" / "Local" / "Programs" / "Common" / "VST3"]
    if sys.platform == "darwin":
        return [Path("/Library/Audio/Plug-Ins/VST3"), Path.home() / "Library/Audio/Plug-Ins/VST3",
                Path("/Library/Audio/Plug-Ins/Components"), Path.home() / "Library/Audio/Plug-Ins/Components"]
    return [Path("/usr/lib/vst3"), Path("/usr/local/lib/vst3"), Path.home() / ".vst3"]


def elenco() -> list[dict]:
    """Plugin installati nelle cartelle standard (solo i nomi, senza caricarli)."""
    out, visti = [], set()
    for cartella in cartelle_standard():
        if not cartella.is_dir():
            continue
        for p in sorted(cartella.iterdir()):
            if p.suffix.lower() in (".vst3", ".component") and p.name not in visti:
                visti.add(p.name)
                out.append({"nome": p.stem, "path": str(p)})
    return out


def risolvi(path: str) -> str:
    """Il file da caricare: un pacchetto .vst3 e' una cartella, il plugin sta dentro."""
    p = Path(path)
    if p.is_dir() and p.suffix.lower() == ".vst3":
        arch = "x86_64-win" if sys.platform == "win32" else ("x86_64-linux" if sys.platform.startswith("linux") else "")
        candidati = list((p / "Contents" / arch).glob("*.vst3")) if arch else []
        candidati += list((p / "Contents").rglob("*.vst3"))
        if candidati:
            return str(candidati[0])
    if not p.exists():
        raise PluginNonDisponibile(f"plugin non trovato: {path}")
    if p.suffix.lower() == ".dll":
        raise PluginNonDisponibile("i plugin VST2 (.dll) non sono supportati: serve la versione VST3")
    return str(p)


def _pedalboard():
    try:
        import pedalboard
    except ImportError as exc:
        raise PluginNonDisponibile(
            "i plugin VST vogliono pedalboard: pip install \"vedit-mcp[plugin]\" "
            "(oppure pip install pedalboard)") from exc
    return pedalboard


@lru_cache(maxsize=16)
def _carica(path: str):
    pb = _pedalboard()
    try:
        return pb.load_plugin(risolvi(path))
    except PluginNonDisponibile:
        raise
    except Exception as exc:  # noqa: BLE001 - ogni plugin fallisce a modo suo
        raise PluginNonDisponibile(f"il plugin non si carica: {str(exc).splitlines()[0][:200]}") from exc


def _finito(x, silenzio: float = -96.0):
    """-inf (il "spento" dei volumi in dB) non passa in JSON: diventa -96."""
    if isinstance(x, float) and not np.isfinite(x):
        return silenzio if x < 0 else None
    return x


def parametri(path: str) -> dict:
    """Nome del plugin e i suoi parametri, con limiti e valore attuale."""
    pl = _carica(path)
    out = []
    for nome, par in pl.parameters.items():
        voce = {"nome": nome, "etichetta": getattr(par, "name", nome)}
        try:
            valore = getattr(pl, nome)
        except Exception:  # noqa: BLE001
            valore = None
        validi = getattr(par, "valid_values", None)
        if isinstance(valore, bool):
            voce.update(tipo="bool", valore=valore)
        elif validi and not isinstance(valore, (int, float)):
            voce.update(tipo="scelta", valore=str(valore), scelte=[str(v) for v in validi][:64])
        else:
            voce.update(tipo="numero", valore=_finito(valore),
                        min=_finito(getattr(par, "min_value", None)),
                        max=_finito(getattr(par, "max_value", None)),
                        unita=getattr(par, "label", "") or "")
        out.append(voce)
    return {"nome": getattr(pl, "name", Path(path).stem), "parametri": out}


def _imposta(pl, valori: dict) -> None:
    for nome, v in (valori or {}).items():
        if nome not in pl.parameters:
            continue
        try:
            setattr(pl, nome, v)
        except Exception as exc:  # noqa: BLE001
            raise PluginNonDisponibile(f"parametro {nome}={v!r} non accettato: {exc}") from exc


def _leggi(path: str, inizio: float, durata: float, sr: int) -> np.ndarray:
    args = [ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-nostdin"]
    if inizio > 0:
        args += ["-ss", f"{inizio:.6f}"]
    args += ["-t", f"{durata:.6f}", "-i", path, "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(args, check=True, capture_output=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).T.copy()


def _scrivi(audio: np.ndarray, sr: int, dest: Path) -> None:
    tmp = dest.with_name("~" + dest.name)
    dati = np.ascontiguousarray(audio.T.astype(np.float32)).tobytes()
    subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(sr),
                    "-ac", str(audio.shape[0]), "-i", "-", "-c:a", "pcm_f32le", str(tmp)],
                   input=dati, check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    os.replace(tmp, dest)


def _cache() -> Path:
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")) / "plugin"
    base.mkdir(parents=True, exist_ok=True)
    return base


def processa(sorgente: str, inizio: float, durata: float, catena: list[dict], sr: int) -> str:
    """Passa il tratto [inizio, inizio+durata] della sorgente nei plugin, in ordine.

    ``catena``: [{"file": ..., "values": {...}, "mix": 0..1}]. Torna il wav in cache.
    """
    try:
        mtime = Path(sorgente).stat().st_mtime
    except OSError:
        mtime = 0
    firma = hashlib.sha1(json.dumps([VERSIONE, sorgente, mtime, round(inizio, 4), round(durata, 4),
                                     catena, sr], sort_keys=True, default=str).encode()).hexdigest()[:20]
    dest = _cache() / f"{firma}.wav"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    audio = _leggi(sorgente, inizio, durata, sr)
    for anello in catena:
        pl = _carica(str(anello["file"]))
        pl.reset()
        _imposta(pl, anello.get("values") or {})
        mix = max(0.0, min(1.0, float(anello.get("mix", 1.0))))
        lavorato = pl(audio, sr)
        if lavorato.shape != audio.shape:   # alcuni plugin cambiano i canali
            lavorato = np.resize(lavorato, audio.shape)
        audio = (mix * lavorato + (1 - mix) * audio).astype(np.float32)
    _scrivi(audio, sr, dest)
    return str(dest)


def catena_di(clip) -> list[dict]:
    return [{"file": e.params.get("file", ""), "values": e.params.get("values") or {},
             "mix": e.params.get("mix", 1.0)}
            for e in clip.effects if e.type == "vst" and e.enabled and e.params.get("file")]


def prepare(project, start: float | None = None, end: float | None = None) -> dict[str, tuple[str, float]]:
    """Clip con plugin nel tratto [start, end): ``clip_id -> (wav lavorato, attacco)``."""
    a = 0.0 if start is None else float(start)
    b = project.duration() if end is None else float(end)
    sr = int(project.settings.sample_rate)
    out: dict[str, tuple[str, float]] = {}
    for track in project.tracks:
        for c in track.clips:
            if c.type != "media" or not c.enabled or c.end <= a or c.start >= b:
                continue
            catena = catena_di(c)
            if not catena:
                continue
            media = project.media_by_id(c.media)
            if media is None or not media.has_audio:
                continue
            out[c.id] = (processa(media.path, c.in_, c.source_duration() + 0.05, catena, sr), c.in_)
    return out
