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
     "nota": "Uses the Claude Code installed on this computer, with your subscription. "
             "No key to paste."},
    {"id": "anthropic", "nome": "Anthropic (Claude)", "tipo": "anthropic", "chiave": True,
     "env": "ANTHROPIC_API_KEY", "modello": "claude-opus-5-5",
     "modelli": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "claude-fable-5-1"],
     "nota": "Key from console.anthropic.com"},
    {"id": "openai", "nome": "OpenAI", "tipo": "openai", "chiave": True, "env": "OPENAI_API_KEY",
     "base": "https://api.openai.com/v1", "modello": "gpt-5", "modelli": ["gpt-5", "gpt-5-mini"],
     "nota": "Key from platform.openai.com"},
    {"id": "gemini", "nome": "Google Gemini", "tipo": "openai", "chiave": True, "env": "GEMINI_API_KEY",
     "base": "https://generativelanguage.googleapis.com/v1beta/openai", "modello": "gemini-2.5-pro",
     "modelli": ["gemini-2.5-pro", "gemini-2.5-flash"], "nota": "Key from aistudio.google.com"},
    {"id": "openrouter", "nome": "OpenRouter", "tipo": "openai", "chiave": True,
     "env": "OPENROUTER_API_KEY", "base": "https://openrouter.ai/api/v1",
     "modello": "anthropic/claude-opus-5-5", "modelli": [],
     "nota": "One key for hundreds of models: openrouter.ai"},
    {"id": "groq", "nome": "Groq", "tipo": "openai", "chiave": True, "env": "GROQ_API_KEY",
     "base": "https://api.groq.com/openai/v1", "modello": "", "modelli": []},
    {"id": "mistral", "nome": "Mistral", "tipo": "openai", "chiave": True, "env": "MISTRAL_API_KEY",
     "base": "https://api.mistral.ai/v1", "modello": "mistral-large-latest", "modelli": []},
    {"id": "deepseek", "nome": "DeepSeek", "tipo": "openai", "chiave": True, "env": "DEEPSEEK_API_KEY",
     "base": "https://api.deepseek.com/v1", "modello": "deepseek-chat", "modelli": []},
    {"id": "xai", "nome": "xAI (Grok)", "tipo": "openai", "chiave": True, "env": "XAI_API_KEY",
     "base": "https://api.x.ai/v1", "modello": "", "modelli": []},
    {"id": "ollama", "nome": "Ollama (on this computer)", "tipo": "openai", "chiave": False,
     "base": "http://localhost:11434/v1", "modello": "", "modelli": [],
     "nota": "Local models: you need a model that can use tools"},
    {"id": "lmstudio", "nome": "LM Studio (on this computer)", "tipo": "openai", "chiave": False,
     "base": "http://localhost:1234/v1", "modello": "", "modelli": []},
    {"id": "custom", "nome": "Other (OpenAI compatible)", "tipo": "openai", "chiave": True,
     "base": "", "modello": "", "modelli": [],
     "nota": "Any service exposing /chat/completions: paste the address and key"},
]

# A cosa puo' arrivare l'assistente della chat, oltre all'editor:
# - editor: solo vedit (piu' lettura di file, pagine e ricerca web)
# - estensioni: anche skill, server MCP, plugin e Chrome dell'utente; con
#   Claude Code le azioni le approva la sua modalita' auto (le sicure passano,
#   le rischiose no); con i modelli via API arrivano skill e server MCP locali
# - completo: Claude Code senza nessuna richiesta di permesso (comandi, file,
#   computer). Solo se l'utente lo sceglie, sapendo cosa vuol dire.
ACCESSI = ("editor", "estensioni", "completo")

MAX_TURNS = 16
MAX_IMMAGINI = 6


def provider(pid: str) -> dict:
    p = next((p for p in PROVIDERS if p["id"] == pid), None)
    if p is None:
        raise ValueError(f"unknown provider: {pid}")
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
    if cfg.get("accesso") not in ACCESSI:
        cfg["accesso"] = "editor"
    cfg.setdefault("server_spenti", [])
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


def imposta_accesso(accesso: str | None = None, server_spenti: list[str] | None = None) -> dict:
    """Livello di accesso dell'assistente e server MCP da lasciare fuori."""
    cfg = carica()
    if accesso is not None:
        if accesso not in ACCESSI:
            raise ValueError(f"access must be one of {', '.join(ACCESSI)}")
        cfg["accesso"] = accesso
    if server_spenti is not None:
        cfg["server_spenti"] = sorted({str(x) for x in server_spenti})
    salva(cfg)
    return stato()


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
            "Claude Code is not installed on this computer: "
            "npm install -g @anthropic-ai/claude-code, then run `claude` once to sign in")
    if p["tipo"] == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "the anthropic package is missing: pip install anthropic"
        if not _chiave(p, cfg) and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return "paste the Anthropic API key"
        return None
    if p["chiave"] and not _chiave(p, cfg):
        return f"paste the {p['nome']} API key"
    if not _indirizzo(p, cfg):
        return "the service address is missing"
    if not _modello(p, cfg):
        return "type the model name"
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
        "provider": attivo, "providers": elenco, "accesso": cfg["accesso"],
        "ok": bool(a and a["pronto"]),
        "model": a["modello"] if a else "", "nome": a["nome"] if a else "",
        "motivo": (a["motivo"] if a else "choose a model in the assistant settings"),
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
        raise RuntimeError("no model configured: open the assistant settings")
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
                # l'API e' senza stato: sistema, strumenti e cronologia viaggiano
                # a ogni richiesta, ma dalla cache costano un decimo
                cache_control={"type": "ephemeral"},
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
            yield {"type": "error", "message": "invalid Anthropic key"}
            return
        except anthropic.RateLimitError:
            yield {"type": "error", "message": "too many requests: try again shortly"}
            return
        except anthropic.APIStatusError as exc:
            yield {"type": "error", "message": f"service error ({exc.status_code}): {exc.message}"}
            return
        except anthropic.APIConnectionError:
            yield {"type": "error", "message": "cannot reach Anthropic: check the network"}
            return

        history.append({"role": "assistant", "content": message.content})
        if message.stop_reason == "refusal":
            yield {"type": "error", "message": "the request was refused"}
            return
        if message.stop_reason == "max_tokens":
            yield {"type": "error", "message": "answer too long, cut off"}
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
    yield {"type": "error", "message": "too many steps: stopping here"}


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
        return "invalid key or missing permissions"
    return f"service error ({exc.code}): {str(corpo)[:300]}"


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
                    yield {"type": "note", "message": "this model cannot see images: "
                                                      "sending the references as text only"}
                    continue
                raise
        except urllib.error.HTTPError as exc:
            yield {"type": "error", "message": _errore_http(exc)}
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            yield {"type": "error", "message": f"cannot reach {p['nome']}: {exc}"}
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
                    raise ValueError("the arguments must be an object")
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
    yield {"type": "error", "message": "too many steps: stopping here"}


# --------------------------------------------------------------------------
# motore: Claude Code installato sul computer
# --------------------------------------------------------------------------

PREFISSO_MCP = "mcp__vedit__"
# passaggi interni di Claude Code che non dicono niente a chi monta
_INTERNI = {"ToolSearch", "TodoWrite", "Task", "Agent", "ExitPlanMode", "EnterPlanMode"}

SISTEMA_CLAUDE_CODE = """Stai lavorando dentro vedit, l'editor video che l'utente ha aperto nel browser.
Il progetto aperto e' quello che vedi con gli strumenti mcp__vedit__ (project_info per lo
stato): non passare il parametro project, lavori gia' su quello giusto. Ogni modifica
compare subito nella timeline dell'utente e si annulla con Ctrl+Z.

Usa gli strumenti di vedit per tutto: add_html per la grafica animata, preview_frame
per guardare il risultato prima di dire che e' fatto, preview_media per guardare un
media importato senza metterlo in timeline.

Quando ti chiedono di montare, le clip in fila sono solo meta' del lavoro: dopo
chiama apply_style (con lo stile scelto), aggiungi testi, grafica e accenti sui
momenti forti, e non dire che hai finito finche' review_edit da' avvisi.
Se l'utente vuole uno stile che non esiste, crealo con create_style (guida piu'
ricetta) e poi applicalo con apply_style.

Scrivi sempre nella lingua in cui ti scrive l'utente (l'interfaccia e' in inglese), anche
le brevi note fra un passaggio e l'altro.

Non esportare mai di tua iniziativa: render_video solo se l'utente lo chiede, e
l'editor gli chiede comunque conferma. Per le scelte che spettano all'utente
(stile, durata, formato, se esportare) usa mcp__vedit__ask_user, che gli mostra
le domande con le opzioni nell'editor: AskUserQuestion qui non funziona. Se l'utente ti indica dei
riferimenti (istanti, clip, aree dell'inquadratura) le immagini relative sono file
PNG che puoi aprire con Read. Rispondi nella lingua dell'utente, breve."""


_NOTA_ACCESSO = {
    "editor": "",
    "estensioni": """

Oltre a vedit hai le skill, i server MCP, i plugin e il browser (Chrome) che l'utente
ha configurato in Claude Code: usali quando servono al lavoro (una skill per un compito
specializzato, un server MCP per un programma esterno, il browser per cercare e
scaricare materiale). Le azioni rischiose vengono rifiutate: se ne serve una, chiedila
all'utente con mcp__vedit__ask_user.""",
    "completo": """

L'utente ti ha dato accesso completo al computer: oltre a vedit hai skill, server MCP,
plugin, browser, comandi e file, senza richieste di permesso. Usalo per il lavoro che ti
chiede e niente di piu'. Prima di cancellare, sovrascrivere, inviare o pubblicare
qualcosa fuori dal progetto chiedi conferma con mcp__vedit__ask_user.""",
}


def argomenti_accesso(cfg: dict) -> list[str]:
    """Le opzioni di Claude Code per il livello di accesso scelto.

    editor: solo il server MCP di vedit (``--strict-mcp-config``) e strumenti in
    sola lettura. Negli altri due livelli Claude Code carica la configurazione
    dell'utente: server MCP, skill, plugin; ``--chrome`` accende il browser.
    """
    accesso = cfg.get("accesso", "editor")
    if accesso == "editor":
        return ["--strict-mcp-config",
                # solo lettura oltre a vedit: immagini e PDF allegati, cartelle, link, ricerche
                "--allowedTools", "mcp__vedit", "Read", "Glob", "WebFetch", "WebSearch"]
    spenti = [f"mcp__{n}" for n in cfg.get("server_spenti") or []]
    out = ["--chrome", "--allowedTools", "mcp__vedit", "Read", "Glob", "Grep", "WebFetch",
           "WebSearch", "Skill"]
    if spenti:
        out += ["--disallowedTools", *spenti]
    if accesso == "completo":
        return out + ["--permission-mode", "bypassPermissions"]
    # le azioni sicure le approva il classificatore di Claude Code, le altre no
    return out + ["--permission-mode", "auto"]


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
        "--mcp-config", config_mcp] + argomenti_accesso(cfg) + [
        "--append-system-prompt", SISTEMA_CLAUDE_CODE + _NOTA_ACCESSO[cfg["accesso"]],
    ]
    modello = _modello(p, cfg)
    if modello:
        args += ["--model", modello]
    if stato_chat.get("sessione"):
        args += ["--resume", stato_chat["sessione"]]

    prompt = "\n\n".join(c["text"] if c["type"] == "text" else f"(immagine: {c['path']})"
                         for c in contenuto)
    env = {**os.environ}
    env.pop("CLAUDECODE", None)
    # ask_user aspetta che l'utente risponda nell'editor: puo' volerci un po'
    env.setdefault("MCP_TOOL_TIMEOUT", "1800000")  # avviato da dentro un'altra sessione non deve credersi annidato
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd or None, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        yield {"type": "error", "message": f"cannot start Claude Code: {exc}"}
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
        scritto = False   # c'e' gia' del testo: un blocco nuovo va staccato dal precedente
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
                    scritto = True
                    yield {"type": "text", "text": d.get("text", "")}
                elif e.get("type") == "content_block_start" and scritto and \
                        (e.get("content_block") or {}).get("type") == "text":
                    yield {"type": "text", "text": "\n\n"}
                elif e.get("type") == "content_block_start" and (e.get("content_block") or {}).get("type") == "thinking":
                    yield {"type": "thinking"}
            elif tipo == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use":
                        grezzo = b.get("name", "")
                        # i passaggi interni di Claude Code (ricerca strumenti...)
                        # non dicono niente a chi monta: si mostrano solo vedit e Read
                        if grezzo in _INTERNI or (cfg["accesso"] == "editor" and not grezzo.startswith(
                                PREFISSO_MCP) and grezzo not in ("Read", "Glob", "WebFetch",
                                                                 "WebSearch")):
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
