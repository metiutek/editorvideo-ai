"""Immagini e video generati da un modello, per metterli in timeline come qualunque media.

Un montaggio senza materiale non si monta: quando le riprese non ci sono (uno
spiegone, un trailer, uno sfondo, una scena da inventare) l'agente le genera.
Come la voce (``tts.py``), il servizio e' una scelta dell'utente e le chiavi
stanno solo su questa macchina, in ``~/.vedit/gen.json``, mai nel progetto.

Servizi:

- ``openai``: ``/images/generations`` di OpenAI e di qualunque servizio con la
  stessa forma (anche in locale: basta cambiare l'indirizzo). Solo immagini;
- ``fal``: fal.ai, che ospita FLUX per le immagini e Kling, Veo, Seedance, MiniMax
  per i video, testo-in-video e immagine-in-video. Si usa la coda
  (``queue.fal.run``): si consegna il lavoro e si aspetta, perche' un video puo'
  volere minuti.

I modelli non sono fissi: ogni servizio ha un modello predefinito per immagini e
uno per video, e si cambiano nelle impostazioni o a ogni chiamata (``model``).
``opzioni`` passa al servizio campi suoi (``duration``, ``negative_prompt``...)
senza che vedit li debba conoscere tutti.

Il file ha nome dall'impronta di servizio, modello, prompt e parametri: la stessa
richiesta non si paga due volte.

Generare costa: l'agente non lo decide da solo. Con l'editor aperto serve il si'
dell'utente (``domande.conferma_genera``); da MCP senza editor, ``confirmed=True``
dopo il suo si'.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

TIPI = ("image", "video")

MOTORI: list[dict] = [
    {"id": "openai", "nome": "OpenAI (or compatible)", "chiave": True, "env": "OPENAI_API_KEY",
     "base": "https://api.openai.com/v1", "tipi": ["image"],
     "modelli": {"image": "gpt-image-1"},
     "nota": "OpenAI key, or any /images/generations service: change the address for a "
             "local server."},
    {"id": "fal", "nome": "fal.ai", "chiave": True, "env": "FAL_KEY",
     "base": "https://queue.fal.run", "tipi": ["image", "video"],
     "modelli": {"image": "fal-ai/flux/dev",
                 "video": "fal-ai/kling-video/v2.1/master/text-to-video"},
     "modelli_img2video": "fal-ai/kling-video/v2.1/master/image-to-video",
     "nota": "Key from fal.ai. Models change often: set the one you want per kind "
             "(images, video) in the settings, or pass model on each call."},
]

ATTESA_MAX = {"image": 300.0, "video": 1500.0}   # secondi


class GenError(RuntimeError):
    """Configurazione mancante o servizio che rifiuta: il messaggio dice cosa fare."""


def motore(mid: str) -> dict:
    m = next((m for m in MOTORI if m["id"] == mid), None)
    if m is None:
        raise GenError(f"unknown generation service {mid!r}; available: "
                       f"{', '.join(x['id'] for x in MOTORI)}")
    return m


# --------------------------------------------------------------------------
# configurazione (solo su questa macchina)
# --------------------------------------------------------------------------


def _file() -> Path:
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    return base / "gen.json"


def carica() -> dict:
    try:
        cfg = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("motore", "")
    for k in ("chiavi", "modelli", "indirizzi"):
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


def imposta(motore_id: str, chiave: str | None = None, modello_immagini: str | None = None,
            modello_video: str | None = None, indirizzo: str | None = None,
            predefinito: bool = True) -> dict:
    """Aggiorna la configurazione. ``chiave=""`` la cancella, ``None`` la lascia."""
    motore(motore_id)
    cfg = carica()
    if chiave is not None:
        if chiave.strip():
            cfg["chiavi"][motore_id] = chiave.strip()
        else:
            cfg["chiavi"].pop(motore_id, None)
    for tipo, v in (("image", modello_immagini), ("video", modello_video)):
        if v is not None:
            cfg["modelli"][f"{motore_id}:{tipo}"] = v.strip()
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
        # la stessa chiave gia' data all'assistente della chat o alla voce
        from . import llm, tts
        if k := llm.carica()["chiavi"].get("openai") or tts.carica()["chiavi"].get("openai"):
            return k
    return os.environ.get(m.get("env") or "", "")


def _indirizzo(m: dict, cfg: dict) -> str:
    return (cfg["indirizzi"].get(m["id"]) or m["base"]).rstrip("/")


def _modello(m: dict, cfg: dict, tipo: str, da_immagine: bool = False) -> str:
    if da_immagine and tipo == "video" and m.get("modelli_img2video"):
        scelto = cfg["modelli"].get(f"{m['id']}:video")
        # un modello scelto dall'utente vale per entrambi i modi, salvo non lo si sappia:
        # i nomi dei modelli fal portano "text-to-video" / "image-to-video"
        if scelto:
            return scelto.replace("text-to-video", "image-to-video")
        return m["modelli_img2video"]
    return cfg["modelli"].get(f"{m['id']}:{tipo}") or m["modelli"].get(tipo, "")


def _pronto(m: dict, cfg: dict, tipo: str) -> str | None:
    if tipo not in m["tipi"]:
        capaci = [x["id"] for x in MOTORI if tipo in x["tipi"]]
        return f"{m['nome']} cannot make {tipo}s; use {' or '.join(capaci)}"
    if m["id"] == "openai":
        if not _chiave(m, cfg) and _indirizzo(m, cfg) == m["base"]:
            return "paste an OpenAI key, or set the address of a compatible local server"
        return None
    if not _chiave(m, cfg):
        return f"paste the {m['nome']} API key"
    return None


def scelto(motore_id: str | None, tipo: str) -> dict:
    """Il servizio da usare per ``tipo``: quello chiesto, o il predefinito, o il primo
    pronto. Solleva ``GenError`` con cosa fare se non ce n'e' nessuno."""
    cfg = carica()
    if motore_id:
        m = motore(motore_id)
        if (errore := _pronto(m, cfg, tipo)):
            raise GenError(errore)
        return m
    candidati = [cfg["motore"], *(x["id"] for x in MOTORI)]
    motivi = []
    for mid in candidati:
        if not mid:
            continue
        m = motore(mid)
        errore = _pronto(m, cfg, tipo)
        if errore is None:
            return m
        motivi.append(f"{m['nome']}: {errore}")
    raise GenError(f"no service ready to make {tipo}s: " + "; ".join(dict.fromkeys(motivi))
                   + ". Set one up in the generation settings (or `vedit gen-setup`).")


def stato() -> dict:
    cfg = carica()
    return {
        "motore": cfg["motore"],
        "motori": [{
            "id": m["id"], "nome": m["nome"], "nota": m.get("nota", ""), "tipi": m["tipi"],
            "chiave": m["chiave"], "ha_chiave": bool(_chiave(m, cfg)),
            "indirizzo": _indirizzo(m, cfg),
            "modelli": {t: _modello(m, cfg, t) for t in m["tipi"]},
            "pronto": {t: _pronto(m, cfg, t) is None for t in m["tipi"]},
            "motivo": {t: _pronto(m, cfg, t) for t in m["tipi"]},
        } for m in MOTORI],
    }


# --------------------------------------------------------------------------
# generare
# --------------------------------------------------------------------------

_FORMATI_OPENAI = {"16:9": "1536x1024", "9:16": "1024x1536", "1:1": "1024x1024"}
_FORMATI_DALLE3 = {"16:9": "1792x1024", "9:16": "1024x1792", "1:1": "1024x1024"}
_FORMATI_FAL = {"16:9": "landscape_16_9", "9:16": "portrait_16_9", "1:1": "square_hd",
                "4:3": "landscape_4_3", "3:4": "portrait_4_3"}


def cartella_progetto(progetto: str | None) -> Path:
    """Dove vanno i file generati: accanto al progetto, come ``_voice`` e ``_web``."""
    if progetto:
        p = Path(progetto)
        d = p.with_name(f"{p.stem}_gen")
    else:
        d = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")) / "gen"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _impronta(*parti) -> str:
    h = hashlib.sha256(json.dumps(parti, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()[:16]


def _richiesta(url: str, chiave: str, corpo: dict | None = None, metodo: str | None = None,
               schema: str = "Bearer", timeout: float = 120.0) -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if corpo is not None:
        data = json.dumps(corpo).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if chiave:
        headers["Authorization"] = f"{schema} {chiave}"
    req = urllib.request.Request(url, data=data, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        raise GenError(_errore_http(exc)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GenError(f"cannot reach the service: {exc}") from exc


def _errore_http(exc: urllib.error.HTTPError) -> str:
    try:
        d = json.loads(exc.read().decode("utf-8", "replace"))
        msg = d.get("detail") or d.get("error") or d.get("message") or ""
        if isinstance(msg, dict):
            msg = msg.get("message") or json.dumps(msg)
        if isinstance(msg, list):
            msg = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in msg)
    except Exception:  # noqa: BLE001
        msg = ""
    if exc.code in (401, 403):
        return "invalid key or missing permissions" + (f" ({msg})" if msg else "")
    if exc.code == 402:
        return "the service says there is no credit left"
    return f"service error ({exc.code}): {str(msg)[:300]}"


def _scarica(url: str, dest_senza_estensione: Path, timeout: float = 300.0) -> Path:
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise GenError(f"the service returned an unusable address: {url[:80]}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as res:
            tipo = (res.headers.get_content_type() or "").lower()
            dati = res.read()
    except (urllib.error.URLError, OSError) as exc:
        raise GenError(f"cannot download the result: {exc}") from exc
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"):
        ext = mimetypes.guess_extension(tipo) or (".mp4" if tipo.startswith("video") else ".png")
        ext = {".jpe": ".jpg"}.get(ext, ext)
    dest = dest_senza_estensione.with_suffix(ext)
    dest.write_bytes(dati)
    return dest


def _trova_media(r: dict, tipo: str) -> str | None:
    """L'indirizzo del file nel risultato di fal: la forma cambia da modello a modello."""
    chiavi = ("video", "videos") if tipo == "video" else ("images", "image")
    for k in chiavi:
        v = r.get(k)
        if isinstance(v, list) and v:
            v = v[0]
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
        if isinstance(v, str) and v.startswith("http"):
            return v
    return None


def _dati_immagine(img: str) -> str:
    """Un file locale diventa un data URI (fal lo accetta come image_url)."""
    p = Path(img)
    if p.is_file():
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    if img.startswith(("http://", "https://", "data:")):
        return img
    raise GenError(f"image not found: {img}")


def genera(tipo: str, prompt: str, cartella: Path, servizio: str | None = None,
           modello: str | None = None, formato: str = "16:9", durata: float | None = None,
           immagine: str | None = None, seed: int | None = None, opzioni: dict | None = None,
           avanza: Callable[[float, str], None] | None = None) -> dict:
    """Genera un'immagine o un video e lo salva in ``cartella``.

    ``immagine``: file o indirizzo da cui partire (immagine-in-video: il primo
    fotogramma). ``formato``: 16:9, 9:16, 1:1 (4:3 e 3:4 per fal). Restituisce
    ``{"path", "tipo", "servizio", "modello", "cache"}``; se la stessa richiesta e'
    gia' stata fatta il file c'e' e il servizio non viene chiamato.
    """
    if tipo not in TIPI:
        raise GenError(f"kind must be one of {', '.join(TIPI)}")
    prompt = (prompt or "").strip()
    if not prompt:
        raise GenError("write what to generate (prompt)")
    if len(prompt) > 4000:
        raise GenError("the prompt is too long (at most 4000 characters)")
    if opzioni is not None and not isinstance(opzioni, dict):
        raise GenError("options must be an object of extra fields for the service")
    m = scelto(servizio, tipo)
    cfg = carica()
    mod = modello or _modello(m, cfg, tipo, da_immagine=bool(immagine))
    if not mod:
        raise GenError(f"no {tipo} model set for {m['nome']}: pass model or set one in the settings")
    sig_img = ""
    if immagine and Path(immagine).is_file():
        sig_img = hashlib.sha256(Path(immagine).read_bytes()).hexdigest()[:16]
    elif immagine:
        sig_img = immagine
    nome = f"{tipo}-{_impronta(m['id'], mod, prompt, formato, durata, sig_img, seed, opzioni)}"
    for esistente in cartella.glob(nome + ".*"):
        return {"path": str(esistente), "tipo": tipo, "servizio": m["id"], "modello": mod,
                "cache": True}
    if avanza:
        avanza(0.02, f"asking {m['nome']}")
    chiave = _chiave(m, cfg)
    base = _indirizzo(m, cfg)
    cartella.mkdir(parents=True, exist_ok=True)
    dest = cartella / nome
    if m["id"] == "openai":
        percorso = _genera_openai(base, chiave, mod, prompt, formato, dest, opzioni)
    else:
        percorso = _genera_fal(base, chiave, mod, tipo, prompt, formato, durata, immagine, seed,
                               opzioni, dest, avanza)
    return {"path": str(percorso), "tipo": tipo, "servizio": m["id"], "modello": mod,
            "cache": False}


def _genera_openai(base: str, chiave: str, modello: str, prompt: str, formato: str,
                   dest: Path, opzioni: dict | None) -> Path:
    tabella = _FORMATI_DALLE3 if "dall-e-3" in modello else _FORMATI_OPENAI
    if formato not in tabella:
        raise GenError(f"format {formato} is not available here: use {', '.join(tabella)}")
    corpo = {"model": modello, "prompt": prompt, "n": 1, "size": tabella[formato], **(opzioni or {})}
    r = _richiesta(base + "/images/generations", chiave, corpo, timeout=300.0)
    voce = (r.get("data") or [{}])[0]
    if voce.get("b64_json"):
        try:
            dati = base64.b64decode(voce["b64_json"])
        except ValueError as exc:
            raise GenError("the service returned an image that cannot be decoded") from exc
        f = dest.with_suffix(".png")
        f.write_bytes(dati)
        return f
    if voce.get("url"):
        return _scarica(voce["url"], dest)
    raise GenError("the service answered without an image")


def _genera_fal(base: str, chiave: str, modello: str, tipo: str, prompt: str, formato: str,
                durata: float | None, immagine: str | None, seed: int | None,
                opzioni: dict | None, dest: Path,
                avanza: Callable[[float, str], None] | None) -> Path:
    corpo: dict = {"prompt": prompt}
    if tipo == "image":
        corpo["image_size"] = _FORMATI_FAL.get(formato, "landscape_16_9")
    else:
        corpo["aspect_ratio"] = formato
        if durata:
            corpo["duration"] = str(int(round(float(durata))))
    if immagine:
        corpo["image_url"] = _dati_immagine(immagine)
    if seed is not None:
        corpo["seed"] = int(seed)
    corpo.update(opzioni or {})
    coda = _richiesta(f"{base}/{modello.strip('/')}", chiave, corpo, schema="Key", timeout=120.0)
    if not (stato_url := coda.get("status_url")) or not (risultato_url := coda.get("response_url")):
        # alcuni modelli rispondono subito col risultato
        if url := _trova_media(coda, tipo):
            return _scarica(url, dest)
        raise GenError("the service did not accept the job: " + json.dumps(coda)[:200])
    limite = time.monotonic() + ATTESA_MAX[tipo]
    pausa = 1.0
    while True:
        st = _richiesta(stato_url, chiave, schema="Key", timeout=60.0)
        s = str(st.get("status") or "").upper()
        if s == "COMPLETED":
            break
        if s in ("FAILED", "ERROR", "CANCELLED", "CANCELED"):
            raise GenError(f"the service could not make it: {st.get('error') or s.lower()}")
        if time.monotonic() > limite:
            raise GenError(f"the service is taking too long (over {int(ATTESA_MAX[tipo])} s): "
                           "try again later")
        if avanza:
            pos = st.get("queue_position")
            avanza(0.1, f"in queue ({pos})" if s == "IN_QUEUE" and pos is not None
                   else "generating")
        time.sleep(pausa)
        pausa = min(5.0, pausa * 1.5)
    r = _richiesta(risultato_url, chiave, schema="Key", timeout=120.0)
    url = _trova_media(r, tipo) or _trova_media(r.get("data") or {}, tipo) \
        if isinstance(r, dict) else None
    if not url:
        raise GenError(f"the service finished but returned no {tipo}")
    if avanza:
        avanza(0.9, "downloading")
    return _scarica(url, dest)
