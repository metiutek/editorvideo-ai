"""Modelli per l'assistente: quale usare, con che chiave, e come parlarci.

Tre famiglie di motori, stessa interfaccia verso la chat (un flusso di eventi
``text`` / ``tool`` / ``tool_done`` / ``tool_error`` / ``error`` / ``done``):

- ``anthropic``: Claude con l'SDK ufficiale;
- ``openai``: qualunque servizio che parla il protocollo chat/completions di
  OpenAI — OpenAI stesso, Google Gemini, OpenRouter, Groq, Mistral, DeepSeek,
  xAI, e i modelli locali di Ollama o LM Studio. Basta indirizzo e chiave;
- ``claude_code``: il Claude Code installato sul computer, guidato in modalita'
  non interattiva. Non vuole chiavi: usa l'abbonamento di chi l'ha installato,
  e lavora sul progetto attraverso il server MCP che l'editor stesso espone
  (``/mcp``), quindi tocca lo stesso progetto che si vede nel browser.

Le chiavi stanno in ``~/.vedit/llm.json``, solo su questa macchina, mai nel
file di progetto: un progetto si passa a qualcuno, una chiave no.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

# --------------------------------------------------------------------------
# catalogo
# --------------------------------------------------------------------------

PROVIDERS: list[dict] = [
    {"id": "claude_code", "nome": "Claude Code", "tipo": "claude_code", "chiave": False,
     "modello": "", "modelli": ["", "opus", "sonnet", "haiku"],
     "nota": "Usa il Claude Code installato su questo computer, con il tuo abbonamento. "
             "Nessuna chiave da incollare."},
    {"id": "anthropic", "nome": "Anthropic (Claude)", "tipo": "anthropic", "chiave": True,
     "env": "ANTHROPIC_API_KEY", "modello": "claude-opus-5-5",
     "modelli": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "claude-fable-5-1"],
     "nota": "Chiave da console.anthropic.com"},
    {"id": "openai", "nome": "OpenAI", "tipo": "openai", "chiave": True, "env": "OPENAI_API_KEY",
     "base": "https://api.openai.com/v1", "modello": "gpt-5", "modelli": ["gpt-5", "gpt-5-mini"],
     "nota": "Chiave da platform.openai.com"},
    {"id": "gemini", "nome": "Google Gemini", "tipo": "openai", "chiave": True, "env": "GEMINI_API_KEY",
     "base": "https://generativelanguage.googleapis.com/v1beta/openai", "modello": "gemini-2.5-pro",
     "modelli": ["gemini-2.5-pro", "gemini-2.5-flash"], "nota": "Chiave da aistudio.google.com"},
    {"id": "openrouter", "nome": "OpenRouter", "tipo": "openai", "chiave": True,
     "env": "OPENROUTER_API_KEY", "base": "https://openrouter.ai/api/v1",
     "modello": "anthropic/claude-opus-5-5", "modelli": [],
     "nota": "Una chiave sola per centinaia di modelli: openrouter.ai"},
    {"id": "groq", "nome": "Groq", "tipo": "openai", "chiave": True, "env": "GROQ_API_KEY",
     "base": "https://api.groq.com/openai/v1", "modello": "", "modelli": []},
    {"id": "mistral", "nome": "Mistral", "tipo": "openai", "chiave": True, "env": "MISTRAL_API_KEY",
     "base": "https://api.mistral.ai/v1", "modello": "mistral-large-latest", "modelli": []},
    {"id": "deepseek", "nome": "DeepSeek", "tipo": "openai", "chiave": True, "env": "DEEPSEEK_API_KEY",
     "base": "https://api.deepseek.com/v1", "modello": "deepseek-chat", "modelli": []},
    {"id": "xai", "nome": "xAI (Grok)", "tipo": "openai", "chiave": True, "env": "XAI_API_KEY",
     "base": "https://api.x.ai/v1", "modello": "", "modelli": []},
    {"id": "ollama", "nome": "Ollama (sul computer)", "tipo": "openai", "chiave": False,
     "base": "http://localhost:11434/v1", "modello": "", "modelli": [],
     "nota": "Modelli locali: serve un modello che sappia usare gli strumenti"},
    {"id": "lmstudio", "nome": "LM Studio (sul computer)", "tipo": "openai", "chiave": False,
     "base": "http://localhost:1234/v1", "modello": "", "modelli": []},
    {"id": "custom", "nome": "Altro (compatibile OpenAI)", "tipo": "openai", "chiave": True,
     "base": "", "modello": "", "modelli": [],
     "nota": "Qualunque servizio che espone /chat/completions: incolla indirizzo e chiave"},
]

MAX_TURNS = 16
MAX_IMMAGINI = 6


def provider(pid: str) -> dict:
    p = next((p for p in PROVIDERS if p["id"] == pid), None)
    if p is None:
        raise ValueError(f"provider sconosciuto: {pid}")
    return p


# --------------------------------------------------------------------------
# configurazione (solo su questa macchina)
# --------------------------------------------------------------------------


def _file() -> Path:
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "llm.json"


def carica() -> dict:
    try:
        cfg = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("provider", "")
    for k in ("chiavi", "modelli", "indirizzi"):
        cfg.setdefault(k, {})
    return cfg


def salva(cfg: dict) -> None:
    f = _file()
    tmp = f.with_name(f"~{f.name}")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def imposta(provider_id: str, chiave: str | None = None, modello: str | None = None,
            indirizzo: str | None = None, attiva: bool = True) -> dict:
    """Aggiorna la configurazione. ``chiave=""`` la cancella, ``None`` la lascia com'e'."""
    provider(provider_id)
    cfg = carica()
    if chiave is not None:
        if chiave.strip():
            cfg["chiavi"][provider_id] = chiave.strip()
        else:
            cfg["chiavi"].pop(provider_id, None)
    if modello is not None:
        cfg["modelli"][provider_id] = modello.strip()
    if indirizzo is not None:
        cfg["indirizzi"][provider_id] = indirizzo.strip().rstrip("/")
    if attiva:
        cfg["provider"] = provider_id
    salva(cfg)
    return stato()


def _chiave(p: dict, cfg: dict) -> str:
    return cfg["chiavi"].get(p["id"]) or (os.environ.get(p["env"], "") if p.get("env") else "")


def _modello(p: dict, cfg: dict) -> str:
    return cfg["modelli"].get(p["id"]) or p.get("modello", "")


def _indirizzo(p: dict, cfg: dict) -> str:
    return (cfg["indirizzi"].get(p["id"]) or p.get("base", "")).rstrip("/")


def claude_exe() -> str | None:
    return os.environ.get("VEDIT_CLAUDE") or shutil.which("claude")


def _pronto(p: dict, cfg: dict) -> str | None:
    """None se il provider si puo' usare, altrimenti il motivo in parole."""
    if p["tipo"] == "claude_code":
        return None if claude_exe() else (
            "Claude Code non e' installato su questo computer: "
            "npm install -g @anthropic-ai/claude-code, poi `claude` una volta per accedere")
    if p["tipo"] == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "manca il pacchetto anthropic: pip install anthropic"
        if not _chiave(p, cfg) and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return "incolla la chiave API di Anthropic"
        return None
    if p["chiave"] and not _chiave(p, cfg):
        return f"incolla la chiave API di {p['nome']}"
    if not _indirizzo(p, cfg):
        return "manca l'indirizzo del servizio"
    if not _modello(p, cfg):
        return "scrivi il nome del modello"
    return None


def _maschera(k: str) -> str:
    return "" if not k else (k[:4] + "…" + k[-4:] if len(k) > 12 else "••••")


def stato() -> dict:
    """Quello che vede la UI: mai le chiavi intere."""
    cfg = carica()
    elenco = []
    for p in PROVIDERS:
        k = _chiave(p, cfg)
        elenco.append({
            "id": p["id"], "nome": p["nome"], "tipo": p["tipo"], "vuole_chiave": p["chiave"],
            "nota": p.get("nota", ""), "modello": _modello(p, cfg), "modelli": p.get("modelli", []),
            "indirizzo": _indirizzo(p, cfg), "indirizzo_modificabile": p["tipo"] == "openai",
            "chiave": _maschera(k), "chiave_da_ambiente": bool(k) and p["id"] not in cfg["chiavi"],
            "pronto": _pronto(p, cfg) is None, "motivo": _pronto(p, cfg),
        })
    attivo = cfg["provider"] or _scelta_automatica(cfg)
    a = next((e for e in elenco if e["id"] == attivo), None)
    return {
        "provider": attivo, "providers": elenco,
        "ok": bool(a and a["pronto"]),
        "model": a["modello"] if a else "", "nome": a["nome"] if a else "",
        "motivo": (a["motivo"] if a else "scegli un modello nelle impostazioni dell'assistente"),
    }


def _scelta_automatica(cfg: dict) -> str:
    """Senza una scelta salvata: la prima cosa che funziona gia'."""
    for pid in ("anthropic", "openai", "gemini", "openrouter", "claude_code"):
        p = provider(pid)
        if _pronto(p, cfg) is None:
            return pid
    return ""


def attivo() -> tuple[dict, dict]:
    cfg = carica()
    pid = cfg["provider"] or _scelta_automatica(cfg)
    if not pid:
        raise RuntimeError("nessun modello configurato: apri le impostazioni dell'assistente")
    p = provider(pid)
    motivo = _pronto(p, cfg)
    if motivo:
        raise RuntimeError(motivo)
    return p, cfg


# --------------------------------------------------------------------------
# motore: Anthropic
# --------------------------------------------------------------------------


def _mai() -> bool:
    return False


def run_anthropic(p: dict, cfg: dict, system: str, tools: list[dict], history: list,
                  contenuto: list[dict], run_op: Callable[[str, dict], str],
                  fermo: Callable[[], bool] = _mai) -> Iterator[dict]:
    import anthropic

    kw: dict[str, Any] = {}
    k = cfg["chiavi"].get("anthropic")
    if k:
        kw["api_key"] = k
    cl = anthropic.Anthropic(**kw)
    model = _modello(p, cfg) or "claude-opus-5-5"
    strumenti = [{**t, "eager_input_streaming": True} for t in tools]

    blocchi = []
    for c in contenuto:
        if c["type"] == "image":
            blocchi.append({"type": "image", "source": {"type": "base64",
                                                        "media_type": c.get("mime", "image/png"),
                                                        "data": c["b64"]}})
        elif c["type"] == "document":
            blocchi.append({"type": "document", "source": {"type": "base64",
                                                           "media_type": "application/pdf",
                                                           "data": c["b64"]}})
        else:
            blocchi.append({"type": "text", "text": c["text"]})
    history.append({"role": "user", "content": blocchi})

    for _ in range(MAX_TURNS):
        try:
            with cl.beta.messages.stream(
                model=model,
                max_tokens=64000,
                system=system,
                tools=strumenti,
                messages=history,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            ) as stream:
                fermato = False
                for event in stream:
                    if fermo():
                        fermato = True
                        break
                    if event.type == "content_block_start" and event.content_block.type == "thinking":
                        yield {"type": "thinking"}
                    elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield {"type": "text", "text": event.delta.text}
                if not fermato:
                    message = stream.get_final_message()
            if fermato:
                # la risposta a meta' non entra nella cronologia: al suo posto una
                # nota, cosi' il turno dopo riparte da una conversazione valida
                history.append({"role": "assistant", "content": [{"type": "text", "text": "(interrotto dall'utente)"}]})
                yield {"type": "stopped"}
                return
        except anthropic.AuthenticationError:
            yield {"type": "error", "message": "chiave Anthropic non valida"}
            return
        except anthropic.RateLimitError:
            yield {"type": "error", "message": "troppe richieste: riprova fra poco"}
            return
        except anthropic.APIStatusError as exc:
            yield {"type": "error", "message": f"errore dal servizio ({exc.status_code}): {exc.message}"}
            return
        except anthropic.APIConnectionError:
            yield {"type": "error", "message": "non riesco a raggiungere Anthropic: controlla la rete"}
            return

        history.append({"role": "assistant", "content": message.content})
        if message.stop_reason == "refusal":
            yield {"type": "error", "message": "la richiesta e' stata rifiutata"}
            return
        if message.stop_reason == "max_tokens":
            yield {"type": "error", "message": "risposta troppo lunga, interrotta"}
            return
        if message.stop_reason != "tool_use":
            yield {"type": "done"}
            return

        risultati = []
        for b in message.content:
            if b.type != "tool_use":
                continue
            # ogni tool_use vuole il suo risultato, anche quando ci si ferma
            if fermo():
                risultati.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                  "content": "(interrotto dall'utente)"})
                continue
            # con eager_input_streaming l'input non e' validato dal servizio
            if not isinstance(b.input, dict):
                risultati.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                  "content": "INVALID_JSON: argomenti non leggibili, riprova"})
                continue
            yield {"type": "tool", "name": b.name, "input": b.input}
            try:
                out = run_op(b.name, dict(b.input))
                risultati.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
                yield {"type": "tool_done", "name": b.name}
            except Exception as exc:
                risultati.append({"type": "tool_result", "tool_use_id": b.id,
                                  "content": f"errore: {exc}", "is_error": True})
                yield {"type": "tool_error", "name": b.name, "message": str(exc)}
        history.append({"role": "user", "content": risultati})
        if fermo():
            history.append({"role": "assistant", "content": [{"type": "text", "text": "(interrotto dall'utente)"}]})
            yield {"type": "stopped"}
            return
    yield {"type": "error", "message": "troppi passaggi: mi fermo qui"}


# --------------------------------------------------------------------------
# motore: compatibile OpenAI (OpenAI, Gemini, OpenRouter, Ollama, ...)
# --------------------------------------------------------------------------


def strumenti_openai(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools]


def _post_stream(url: str, chiave: str, body: dict) -> Iterator[dict]:
    """POST in streaming: un dizionario per ogni riga ``data:`` del flusso SSE."""
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if chiave:
        headers["Authorization"] = f"Bearer {chiave}"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=300) as res:
        for raw in res:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except ValueError:
                continue


def _errore_http(exc: urllib.error.HTTPError) -> str:
    try:
        corpo = exc.read().decode("utf-8", "replace")
        d = json.loads(corpo)
        msg = (d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error")
        corpo = msg or corpo
    except Exception:  # noqa: BLE001
        corpo = ""
    if exc.code in (401, 403):
        return "chiave non valida o senza permessi"
    return f"errore dal servizio ({exc.code}): {str(corpo)[:300]}"


def run_openai(p: dict, cfg: dict, system: str, tools: list[dict], history: list,
               contenuto: list[dict], run_op: Callable[[str, dict], str],
               fermo: Callable[[], bool] = _mai) -> Iterator[dict]:
    url = _indirizzo(p, cfg) + "/chat/completions"
    chiave = _chiave(p, cfg)
    model = _modello(p, cfg)
    fn = strumenti_openai(tools)

    parti = []
    for c in contenuto:
        if c["type"] == "image":
            mime = c.get("mime", "image/png")
            parti.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64," + c["b64"]}})
        else:
            parti.append({"type": "text", "text": c["text"]})
    solo_testo = "\n\n".join(c["text"] for c in contenuto if c["type"] == "text")
    history.append({"role": "user", "content": parti})

    for _ in range(MAX_TURNS):
        testo, chiamate, fine, fermato = "", {}, None, False
        body = {"model": model, "stream": True, "tools": fn,
                "messages": [{"role": "system", "content": system}] + history}
        try:
            try:
                for ev in _post_stream(url, chiave, body):
                    if fermo():
                        fermato = True
                        break
                    for ch in ev.get("choices") or []:
                        d = ch.get("delta") or {}
                        if d.get("content"):
                            testo += d["content"]
                            yield {"type": "text", "text": d["content"]}
                        for tc in d.get("tool_calls") or []:
                            slot = chiamate.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                            slot["id"] = tc.get("id") or slot["id"]
                            f = tc.get("function") or {}
                            slot["name"] += f.get("name") or ""
                            slot["args"] += f.get("arguments") or ""
                        fine = ch.get("finish_reason") or fine
            except urllib.error.HTTPError as exc:
                # alcuni modelli non accettano immagini: si riprova solo col testo
                if exc.code == 400 and isinstance(history[-1].get("content"), list) and any(
                        x.get("type") == "image_url" for x in history[-1]["content"]):
                    history[-1] = {"role": "user", "content": solo_testo}
                    yield {"type": "note", "message": "questo modello non vede le immagini: "
                                                      "mando i riferimenti solo come testo"}
                    continue
                raise
        except urllib.error.HTTPError as exc:
            yield {"type": "error", "message": _errore_http(exc)}
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            yield {"type": "error", "message": f"non riesco a raggiungere {p['nome']}: {exc}"}
            return

        if fermato:
            history.append({"role": "assistant", "content": testo or "(interrotto dall'utente)"})
            yield {"type": "stopped"}
            return
        msg: dict[str, Any] = {"role": "assistant", "content": testo or None}
        if chiamate:
            msg["tool_calls"] = [{"id": c["id"] or f"call_{i}", "type": "function",
                                  "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                                 for i, c in sorted(chiamate.items())]
        history.append(msg)
        if not chiamate:
            yield {"type": "done"}
            return

        for tc in msg["tool_calls"]:
            nome = tc["function"]["name"]
            if fermo():
                history.append({"role": "tool", "tool_call_id": tc["id"], "content": "(interrotto dall'utente)"})
                continue
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
                if not isinstance(args, dict):
                    raise ValueError("gli argomenti devono essere un oggetto")
            except ValueError as exc:
                history.append({"role": "tool", "tool_call_id": tc["id"],
                                "content": f"INVALID_JSON: {exc}"})
                continue
            yield {"type": "tool", "name": nome, "input": args}
            try:
                out = run_op(nome, args)
                yield {"type": "tool_done", "name": nome}
            except Exception as exc:
                out = f"errore: {exc}"
                yield {"type": "tool_error", "name": nome, "message": str(exc)}
            history.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
        if fermo():
            yield {"type": "stopped"}
            return
    yield {"type": "error", "message": "troppi passaggi: mi fermo qui"}


# --------------------------------------------------------------------------
# motore: Claude Code installato sul computer
# --------------------------------------------------------------------------

PREFISSO_MCP = "mcp__vedit__"

SISTEMA_CLAUDE_CODE = """Stai lavorando dentro vedit, l'editor video che l'utente ha aperto nel browser.
Il progetto aperto e' quello che vedi con gli strumenti mcp__vedit__ (project_info per lo
stato): non passare il parametro project, lavori gia' su quello giusto. Ogni modifica
compare subito nella timeline dell'utente e si annulla con Ctrl+Z.

Usa gli strumenti di vedit per tutto: add_html per la grafica animata, preview_frame
per guardare il risultato prima di dire che e' fatto. Se l'utente ti indica dei
riferimenti (istanti, clip, aree dell'inquadratura) le immagini relative sono file
PNG che puoi aprire con Read. Rispondi in italiano, breve."""


def _comando_claude(exe: str) -> list[str]:
    if exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    return [exe]


def run_claude_code(p: dict, cfg: dict, stato_chat: dict, contenuto: list[dict], mcp_url: str,
                    cwd: str | None, fermo: Callable[[], bool] = _mai) -> Iterator[dict]:
    exe = claude_exe()
    if not exe:
        yield {"type": "error", "message": _pronto(p, cfg)}
        return
    config_mcp = json.dumps({"mcpServers": {"vedit": {"type": "http", "url": mcp_url}}})
    args = _comando_claude(exe) + [
        "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--mcp-config", config_mcp, "--strict-mcp-config",
        # solo lettura oltre a vedit: immagini e PDF allegati, cartelle indicate, link
        "--allowedTools", "mcp__vedit", "Read", "Glob", "WebFetch",
        "--append-system-prompt", SISTEMA_CLAUDE_CODE,
    ]
    modello = _modello(p, cfg)
    if modello:
        args += ["--model", modello]
    if stato_chat.get("sessione"):
        args += ["--resume", stato_chat["sessione"]]

    prompt = "\n\n".join(c["text"] if c["type"] == "text" else f"(immagine: {c['path']})"
                         for c in contenuto)
    env = {**os.environ}
    env.pop("CLAUDECODE", None)  # avviato da dentro un'altra sessione non deve credersi annidato
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd or None, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        yield {"type": "error", "message": f"non riesco ad avviare Claude Code: {exc}"}
        return
    # la lettura dell'uscita blocca: e' un filo a parte che ferma il processo
    # quando l'utente preme "ferma"
    import threading
    import time

    fermato = threading.Event()

    def sorveglia() -> None:
        while proc.poll() is None:
            if fermo():
                fermato.set()
                proc.kill()
                return
            time.sleep(0.2)

    threading.Thread(target=sorveglia, daemon=True).start()
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()
        aperti: dict[str, str] = {}
        for raw in proc.stdout:
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            tipo = ev.get("type")
            if ev.get("session_id"):
                stato_chat["sessione"] = ev["session_id"]
            if tipo == "stream_event":
                e = ev.get("event") or {}
                d = e.get("delta") or {}
                if e.get("type") == "content_block_delta" and d.get("type") == "text_delta":
                    yield {"type": "text", "text": d.get("text", "")}
                elif e.get("type") == "content_block_start" and (e.get("content_block") or {}).get("type") == "thinking":
                    yield {"type": "thinking"}
            elif tipo == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use":
                        grezzo = b.get("name", "")
                        # i passaggi interni di Claude Code (ricerca strumenti...)
                        # non dicono niente a chi monta: si mostrano solo vedit e Read
                        if not grezzo.startswith(PREFISSO_MCP) and grezzo not in ("Read", "Glob", "WebFetch"):
                            continue
                        nome = grezzo.removeprefix(PREFISSO_MCP)
                        aperti[b.get("id", "")] = nome
                        yield {"type": "tool", "name": nome, "input": b.get("input") or {}}
            elif tipo == "user":
                for b in (ev.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        if b.get("tool_use_id", "") not in aperti:
                            continue
                        nome = aperti.pop(b.get("tool_use_id", ""))
                        if b.get("is_error"):
                            testo = b.get("content")
                            if isinstance(testo, list):
                                testo = " ".join(x.get("text", "") for x in testo if isinstance(x, dict))
                            yield {"type": "tool_error", "name": nome, "message": str(testo)[:300]}
                        else:
                            yield {"type": "tool_done", "name": nome}
            elif tipo == "result":
                if ev.get("is_error"):
                    yield {"type": "error", "message": str(ev.get("result") or ev.get("subtype"))[:400]}
                else:
                    yield {"type": "done"}
        code = proc.wait()
        if fermato.is_set():
            yield {"type": "stopped"}
            return
        if code != 0:
            err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace").strip()
            if err:
                yield {"type": "error", "message": f"Claude Code: {err[-400:]}"}
    finally:
        if proc.poll() is None:
            proc.kill()


# --------------------------------------------------------------------------
# immagini dei riferimenti
# --------------------------------------------------------------------------


def immagine(path: str) -> dict:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    if mime == "image/jpg":
        mime = "image/jpeg"
    return {"type": "image", "path": path, "mime": mime,
            "b64": base64.b64encode(Path(path).read_bytes()).decode("ascii")}


def documento(path: str) -> dict:
    return {"type": "document", "path": path,
            "b64": base64.b64encode(Path(path).read_bytes()).decode("ascii")}
