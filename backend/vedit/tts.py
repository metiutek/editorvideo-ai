"""Voce generata dal testo (TTS): servizi via API o motori sul computer.

Motori:

- ``openai``: ``/audio/speech`` di OpenAI, e di qualunque servizio con la stessa
  forma — anche in locale, come Kokoro-FastAPI (``http://localhost:8880/v1``)
  o LocalAI: basta cambiare l'indirizzo;
- ``elevenlabs``: le voci di ElevenLabs, multilingua;
- ``piper``: Piper in locale, offline, con un modello ``.onnx`` scaricato;
- ``system``: la voce del sistema operativo (SAPI su Windows, ``say`` su macOS,
  ``espeak-ng`` su Linux). Niente da installare ne' da pagare: e' la scelta di
  ripiego, buona per un provino.

Chiavi, voci e indirizzi stanno in ``~/.vedit/tts.json`` come quelle del modello
in ``llm.json``: solo su questa macchina, mai nel progetto. Per OpenAI vale anche
la chiave gia' data all'assistente o ``OPENAI_API_KEY``.

Il file generato ha nome dall'impronta di testo e parametri: rigenerare la
stessa battuta non chiama di nuovo il servizio, e il progetto resta una
funzione dei file su disco come per ogni altro media.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import ffmpeg

MOTORI: list[dict] = [
    {"id": "openai", "nome": "OpenAI (or compatible)", "chiave": True, "env": "OPENAI_API_KEY",
     "base": "https://api.openai.com/v1", "modello": "gpt-4o-mini-tts", "voce": "alloy",
     "voci": ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"],
     "nota": "OpenAI key, or any /audio/speech service: change the address for a local "
             "server (Kokoro-FastAPI http://localhost:8880/v1, LocalAI...)."},
    {"id": "elevenlabs", "nome": "ElevenLabs", "chiave": True, "env": "ELEVENLABS_API_KEY",
     "base": "https://api.elevenlabs.io/v1", "modello": "eleven_multilingual_v2",
     "voce": "21m00Tcm4TlvDq8ikWAM", "voci": [],
     "nota": "Key from elevenlabs.io; the voice is a voice id from your voice library."},
    {"id": "piper", "nome": "Piper (offline)", "chiave": False, "modello": "", "voce": "",
     "voci": [],
     "nota": "Local and free: install piper (pip install piper-tts) and give the path of "
             "a voice model .onnx as the voice (github.com/rhasspy/piper)."},
    {"id": "system", "nome": "System voice", "chiave": False, "modello": "", "voce": "",
     "voci": [],
     "nota": "The operating system's voice: nothing to install. Good for a draft."},
]


class TtsError(RuntimeError):
    """Configurazione mancante o servizio che rifiuta: il messaggio dice cosa fare."""


def motore(mid: str) -> dict:
    m = next((m for m in MOTORI if m["id"] == mid), None)
    if m is None:
        raise TtsError(f"unknown voice engine {mid!r}; available: "
                       f"{', '.join(x['id'] for x in MOTORI)}")
    return m


# --------------------------------------------------------------------------
# configurazione (solo su questa macchina)
# --------------------------------------------------------------------------


def _base() -> Path:
    return Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))


def _file() -> Path:
    return _base() / "tts.json"


def carica() -> dict:
    try:
        cfg = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("motore", "")
    for k in ("chiavi", "voci", "modelli", "indirizzi"):
        cfg.setdefault(k, {})
    return cfg


def _salva(cfg: dict) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"~{f.name}")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def imposta(motore_id: str, chiave: str | None = None, voce: str | None = None,
            modello: str | None = None, indirizzo: str | None = None,
            predefinito: bool = True) -> dict:
    """Aggiorna la configurazione. ``chiave=""`` la cancella, ``None`` la lascia."""
    motore(motore_id)
    cfg = carica()
    if chiave is not None:
        if chiave.strip():
            cfg["chiavi"][motore_id] = chiave.strip()
        else:
            cfg["chiavi"].pop(motore_id, None)
    for campo, v in (("voci", voce), ("modelli", modello)):
        if v is not None:
            cfg[campo][motore_id] = v.strip()
    if indirizzo is not None:
        cfg["indirizzi"][motore_id] = indirizzo.strip().rstrip("/")
    if predefinito:
        cfg["motore"] = motore_id
    _salva(cfg)
    return stato()


def _chiave(m: dict, cfg: dict) -> str:
    if k := cfg["chiavi"].get(m["id"]):
        return k
    if m["id"] == "openai":
        # la stessa chiave gia' data all'assistente della chat
        from . import llm
        if k := llm.carica()["chiavi"].get("openai"):
            return k
    return os.environ.get(m.get("env") or "", "")


def _sistema_disponibile() -> str | None:
    s = platform.system()
    if s == "Windows":
        return None if shutil.which("powershell") or shutil.which("powershell.exe") \
            else "PowerShell not found"
    if s == "Darwin":
        return None if shutil.which("say") else "the 'say' command is missing"
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        return None
    return "install espeak-ng (sudo apt install espeak-ng)"


def _pronto(m: dict, cfg: dict) -> str | None:
    """None se il motore si puo' usare, altrimenti cosa manca, in parole."""
    if m["chiave"] and not _chiave(m, cfg) and m["id"] == "elevenlabs":
        return "paste the ElevenLabs API key"
    if m["id"] == "openai" and not _chiave(m, cfg) and _indirizzo(m, cfg) == m["base"]:
        return "paste an OpenAI key, or set the address of a compatible local server"
    if m["id"] == "piper":
        if not _piper_cmd():
            return "piper is not installed: pip install piper-tts"
        voce = _voce(m, cfg)
        if not voce or not Path(voce).is_file():
            return "set the voice to the path of a Piper model (.onnx)"
    if m["id"] == "system":
        return _sistema_disponibile()
    return None


def _indirizzo(m: dict, cfg: dict) -> str:
    return cfg["indirizzi"].get(m["id"]) or m.get("base", "")


def _voce(m: dict, cfg: dict) -> str:
    return cfg["voci"].get(m["id"]) or m["voce"]


def _modello(m: dict, cfg: dict) -> str:
    return cfg["modelli"].get(m["id"]) or m["modello"]


def _piper_cmd() -> list[str] | None:
    if exe := shutil.which("piper"):
        return [exe]
    try:
        import importlib.util
        if importlib.util.find_spec("piper") is not None:
            import sys
            return [sys.executable, "-m", "piper"]
    except (ImportError, ValueError):
        pass
    return None


def stato() -> dict:
    """Motori con quello che serve a ognuno: e' quello che mostra la UI."""
    cfg = carica()
    out = []
    for m in MOTORI:
        k = _chiave(m, cfg)
        motivo = _pronto(m, cfg)
        out.append({"id": m["id"], "nome": m["nome"], "nota": m["nota"],
                    "vuole_chiave": m["chiave"], "chiave": f"…{k[-4:]}" if k else "",
                    "voce": _voce(m, cfg), "voci": m["voci"], "modello": _modello(m, cfg),
                    "indirizzo": _indirizzo(m, cfg), "indirizzo_modificabile": "base" in m,
                    "pronto": motivo is None, "motivo": motivo})
    return {"motore": predefinito(), "motori": out}


def predefinito() -> str:
    """Il motore scelto; senza scelta il primo pronto, e alla fine la voce di sistema."""
    cfg = carica()
    if cfg["motore"]:
        return cfg["motore"]
    for m in MOTORI:
        if _pronto(m, cfg) is None:
            return m["id"]
    return "system"


# --------------------------------------------------------------------------
# generazione
# --------------------------------------------------------------------------


def _post(url: str, headers: dict, body: dict, timeout: float = 180) -> bytes:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        dettaglio = exc.read().decode("utf-8", "replace")[:400]
        raise TtsError(f"the voice service answered {exc.code}: {dettaglio}") from exc
    except urllib.error.URLError as exc:
        raise TtsError(f"cannot reach the voice service at {url}: {exc.reason}") from exc


def _openai(m: dict, cfg: dict, testo: str, voce: str, velocita: float,
            istruzioni: str, out: Path) -> None:
    body = {"model": _modello(m, cfg), "voice": voce, "input": testo,
            "response_format": "wav", "speed": velocita}
    if istruzioni:
        body["instructions"] = istruzioni
    k = _chiave(m, cfg)
    out.write_bytes(_post(f"{_indirizzo(m, cfg)}/audio/speech",
                          {"Authorization": f"Bearer {k}"} if k else {}, body))


def _elevenlabs(m: dict, cfg: dict, testo: str, voce: str, velocita: float,
                istruzioni: str, out: Path) -> None:
    body = {"text": testo, "model_id": _modello(m, cfg),
            "voice_settings": {"speed": max(0.7, min(1.2, velocita))}}
    url = f"{_indirizzo(m, cfg)}/text-to-speech/{voce}?output_format=mp3_44100_128"
    out.write_bytes(_post(url, {"xi-api-key": _chiave(m, cfg)}, body))


def _esegui(cmd: list[str], **kw) -> None:
    r = subprocess.run(cmd, capture_output=True, timeout=600,
                       creationflags=ffmpeg._NO_WINDOW, **kw)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()[-400:]
        raise TtsError(f"{Path(cmd[0]).name} failed: {err or r.returncode}")


def _piper(m: dict, cfg: dict, testo: str, voce: str, velocita: float,
           istruzioni: str, out: Path) -> None:
    cmd = _piper_cmd()
    if not cmd:
        raise TtsError("piper is not installed: pip install piper-tts")
    if not voce or not Path(voce).is_file():
        raise TtsError("for Piper the voice is the path of a model .onnx")
    # length_scale e' la durata: piu' grande, piu' lento
    _esegui(cmd + ["--model", voce, "--output_file", str(out),
                   "--length_scale", f"{1.0 / max(0.25, velocita):.3f}"],
            input=testo.encode("utf-8"))


def _sistema(m: dict, cfg: dict, testo: str, voce: str, velocita: float,
             istruzioni: str, out: Path) -> None:
    s = platform.system()
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "testo.txt"
        src.write_text(testo, encoding="utf-8")
        if s == "Windows":
            # SAPI dal .NET di PowerShell: c'e' su ogni Windows. Testo e voce
            # passano per file e variabili d'ambiente, mai dentro lo script.
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "if ($env:VEDIT_TTS_VOCE) { $s.SelectVoice($env:VEDIT_TTS_VOCE) };"
                "$s.Rate = [int]$env:VEDIT_TTS_RATE;"
                "$s.SetOutputToWaveFile($env:VEDIT_TTS_OUT);"
                "$s.Speak([IO.File]::ReadAllText($env:VEDIT_TTS_IN, [Text.Encoding]::UTF8));"
                "$s.Dispose()")
            rate = max(-10, min(10, round((velocita - 1.0) * 10)))
            env = {**os.environ, "VEDIT_TTS_VOCE": voce or "", "VEDIT_TTS_RATE": str(rate),
                   "VEDIT_TTS_OUT": str(out), "VEDIT_TTS_IN": str(src)}
            _esegui(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env)
        elif s == "Darwin":
            aiff = Path(d) / "voce.aiff"
            cmd = ["say", "-f", str(src), "-o", str(aiff), "-r", str(round(175 * velocita))]
            if voce:
                cmd += ["-v", voce]
            _esegui(cmd)
            ffmpeg.run(ffmpeg.base_cmd() + ["-i", str(aiff), "-f", "wav", str(out)], timeout=600)
        else:
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if not exe:
                raise TtsError("install espeak-ng (sudo apt install espeak-ng)")
            cmd = [exe, "-f", str(src), "-w", str(out), "-s", str(round(170 * velocita))]
            if voce:
                cmd += ["-v", voce]
            _esegui(cmd)


_GENERATORI = {"openai": _openai, "elevenlabs": _elevenlabs, "piper": _piper, "system": _sistema}
_ESTENSIONE = {"elevenlabs": ".mp3"}


def voci_sistema() -> list[str]:
    """Le voci installate nel sistema (solo Windows e macOS sanno elencarle bene)."""
    try:
        if platform.system() == "Windows":
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -AssemblyName System.Speech;"
                 "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices()"
                 " | % { $_.VoiceInfo.Name }"], capture_output=True, text=True, timeout=30)
            return [v.strip() for v in r.stdout.splitlines() if v.strip()]
        if platform.system() == "Darwin":
            r = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=30)
            return [v.split("  ")[0].strip() for v in r.stdout.splitlines() if v.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def genera(testo: str, cartella: str | Path, motore_id: str | None = None,
           voce: str | None = None, velocita: float = 1.0, istruzioni: str = "") -> Path:
    """Scrive la voce di ``testo`` in ``cartella`` e restituisce il file.

    istruzioni: come dirlo (tono, ritmo, emozione), per i modelli che lo
    capiscono (gpt-4o-mini-tts); gli altri lo ignorano.
    """
    testo = (testo or "").strip()
    if not testo:
        raise TtsError("there is no text to say")
    if len(testo) > 4096:
        raise TtsError("at most 4096 characters per line: split the text into several lines")
    if not 0.25 <= float(velocita) <= 4.0:
        raise TtsError("speed must be between 0.25 and 4")
    cfg = carica()
    m = motore(motore_id or predefinito())
    if motivo := _pronto(m, cfg):
        raise TtsError(f"{m['nome']}: {motivo}")
    voce = voce or _voce(m, cfg)
    impronta = hashlib.sha1(json.dumps(
        [m["id"], _modello(m, cfg), _indirizzo(m, cfg), voce, round(float(velocita), 3),
         istruzioni, testo], ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    nome = "".join(c if c.isascii() and c.isalnum() else "_" for c in testo[:24]).strip("_") or "voce"
    out = cartella / f"{nome}_{impronta}{_ESTENSIONE.get(m['id'], '.wav')}"
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = out.with_name(f"~{out.name}")
    try:
        _GENERATORI[m["id"]](m, cfg, testo, voce, float(velocita), istruzioni, tmp)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise TtsError(f"{m['nome']} produced no audio")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def cartella_progetto(percorso_progetto: str | None) -> Path:
    """Dove mettere le voci: accanto al progetto, come il resto del materiale."""
    if percorso_progetto:
        p = Path(percorso_progetto)
        return p.parent / f"{p.stem}_voice"
    return _base() / "tts"


def battute(righe: list[dict], cartella: str | Path, motore_id: str | None = None,
            voce: str | None = None, velocita: float = 1.0, istruzioni: str = "",
            progresso=None) -> list[dict]:
    """Genera piu' battute; ognuna puo' cambiare voce, velocita' e istruzioni.

    Restituisce le voci pronte per ``Store.add_voiceover``. ``progresso(i, n)``
    a ogni battuta finita: con decine di battute un servizio lento tiene li'
    per minuti.
    """
    if not righe:
        raise TtsError("no lines to say")
    out = []
    for i, r in enumerate(righe):
        f = genera(r.get("text", ""), cartella, r.get("engine") or motore_id,
                   r.get("voice") or voce, float(r.get("speed") or velocita),
                   r.get("style") or istruzioni)
        out.append({"path": str(f), "start": r.get("start"), "text": r.get("text", "")})
        if progresso:
            progresso(i + 1, len(righe))
    return out
