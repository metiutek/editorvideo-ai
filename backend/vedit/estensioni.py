"""Le skill e i server MCP dell'utente, per l'assistente dentro l'editor.

Con Claude Code come motore basta non isolarlo (``llm.run_claude_code``): carica
da se' server MCP, skill, plugin e Chrome della configurazione dell'utente.
Questo modulo serve ai modelli via API (Claude con chiave, OpenAI e
compatibili), che da soli non hanno niente di tutto questo:

- **server MCP**: vedit fa da client verso gli stessi server che l'utente ha
  configurato in Claude Code (``~/.claude.json``), in Claude Desktop e in
  ``~/.vedit/mcp.json``. I loro strumenti arrivano al modello come
  ``mcp__<server>__<strumento>``. I connettori di claude.ai (Gmail, Drive...)
  vivono nell'account Claude e non si raggiungono da qui: per quelli serve
  Claude Code come motore;
- **skill**: le cartelle con ``SKILL.md`` (``~/.claude/skills``, le skill dei
  plugin di Claude Code, ``~/.vedit/skills``, ``.claude/skills`` del
  progetto). Il modello vede nome e descrizione di ognuna e ne carica le
  istruzioni con ``use_skill`` quando servono, come fa Claude Code.

I server partono in un ciclo asincrono a parte e restano aperti finche'
l'editor gira: avviarli a ogni messaggio costerebbe secondi.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

MAX_SKILL = 60_000          # caratteri di un SKILL.md passati al modello
MAX_INDICE = 12_000         # caratteri dell'elenco delle skill nel contesto
TIMEOUT_AVVIO = 30.0        # secondi per collegarsi a un server
TIMEOUT_CHIAMATA = 600.0
_NOME = re.compile(r"[^a-zA-Z0-9_-]+")


# --------------------------------------------------------------------------
# skill
# --------------------------------------------------------------------------


def _home() -> Path:
    return Path(os.environ.get("VEDIT_HOME_CLAUDE") or (Path.home() / ".claude"))


def _vedit() -> Path:
    return Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))


def _frontmatter(testo: str) -> tuple[dict, str]:
    """Il blocco ``---`` in testa a SKILL.md: name e description, il resto e' corpo."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?", testo, re.S)
    if not m:
        return {}, testo
    meta: dict = {}
    chiave = None
    for riga in m.group(1).splitlines():
        k = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", riga)
        if k:
            chiave, valore = k.group(1), k.group(2).strip()
            meta[chiave] = valore.strip("\"'") if valore not in ("|", ">", "|-", ">-") else ""
        elif chiave and riga.startswith((" ", "\t")):
            meta[chiave] = (meta[chiave] + " " + riga.strip()).strip()
    return meta, testo[m.end():]


def _nome_plugin(radice: Path) -> str:
    """Il nome di un plugin dal suo plugin.json: le cartelle sincronizzate hanno un uuid."""
    meta = radice / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("name") or radice.name
    except (OSError, ValueError):
        return radice.name


def _cartelle_plugin(base: Path, profondita: int = 4) -> list[Path]:
    """Le cartelle ``skills`` dei plugin, senza cestino ne' copie per altri editor."""
    out = []
    if not base.is_dir():
        return out
    for radice, dirs, _ in os.walk(base):
        livello = len(Path(radice).relative_to(base).parts)
        dirs[:] = [d for d in dirs if not d.startswith(".") and livello < profondita]
        if "skills" in dirs:
            out.append(Path(radice) / "skills")
    # piu' versioni dello stesso plugin: la piu' recente per prima
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def _cartelle_skill(progetto: str | None) -> list[tuple[str, Path]]:
    """(origine, cartella che contiene le skill), dalla piu' vicina alla piu' lontana."""
    out = []
    if progetto:
        out.append(("project", Path(progetto).parent / ".claude" / "skills"))
    out.append(("vedit", _vedit() / "skills"))
    out.append(("user", _home() / "skills"))
    # quelle sincronizzate dall'account Claude: skills/synced/<account>/<skill>
    for d in sorted((_home() / "skills" / "synced").glob("*")):
        if d.is_dir():
            out.append(("account", d))
    for gruppo in ("synced", "cache"):
        for d in _cartelle_plugin(_home() / "plugins" / gruppo):
            out.append((f"plugin:{_nome_plugin(d.parent)}", d))
    return out


def skill(progetto: str | None = None) -> list[dict]:
    """Le skill disponibili: nome, descrizione, origine, cartella."""
    viste: dict[str, dict] = {}
    for origine, base in _cartelle_skill(progetto):
        if not base.is_dir():
            continue
        for f in sorted(base.glob("*/SKILL.md")):
            try:
                meta, _ = _frontmatter(f.read_text(encoding="utf-8", errors="replace")[:8000])
            except OSError:
                continue
            nome = meta.get("name") or f.parent.name
            if origine.startswith("plugin:"):
                nome = f"{origine[7:]}:{nome}"
            if nome in viste:
                continue  # la prima trovata vince: progetto, vedit, utente, plugin piu' recente
            viste[nome] = {"name": nome, "description": meta.get("description", "")[:500],
                           "origin": origine, "dir": str(f.parent)}
    return sorted(viste.values(), key=lambda s: s["name"].lower())


def indice_skill(progetto: str | None = None) -> str:
    """L'elenco per il contesto del modello, o "" se non ce ne sono."""
    voci = skill(progetto)
    if not voci:
        return ""
    righe = [f"- {s['name']}: {s['description']}" for s in voci]
    testo = "\n".join(righe)
    if len(testo) > MAX_INDICE:
        testo = testo[:MAX_INDICE] + "\n[...altre skill: list_skills per l'elenco intero]"
    return ("Skill dell'utente (istruzioni specializzate). Quando una richiesta corrisponde "
            "a una descrizione, chiama use_skill con il suo nome PRIMA di procedere e segui "
            "le istruzioni che ricevi:\n" + testo)


def usa_skill(nome: str, progetto: str | None = None) -> dict:
    s = next((x for x in skill(progetto) if x["name"] == nome), None)
    if s is None:
        s = next((x for x in skill(progetto) if x["name"].split(":")[-1] == nome), None)
    if s is None:
        raise ValueError(f"no skill named {nome!r}: list_skills shows the available ones")
    cartella = Path(s["dir"])
    _, corpo = _frontmatter((cartella / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
    file = sorted(str(p.relative_to(cartella)).replace("\\", "/")
                  for p in cartella.rglob("*") if p.is_file() and p.name != "SKILL.md")[:200]
    return {"name": s["name"], "dir": str(cartella), "istruzioni": corpo[:MAX_SKILL],
            "file": file,
            "nota": "read the other files with read_skill_file when the instructions point to "
                    "them. Scripts cannot be run from here: do their job with the tools you have."}


def leggi_file_skill(nome: str, percorso: str, progetto: str | None = None) -> str:
    cartella = Path(usa_skill(nome, progetto)["dir"]).resolve()
    f = (cartella / percorso).resolve()
    if cartella not in f.parents or not f.is_file():
        raise ValueError(f"{percorso} is not a file of the skill {nome}")
    return f.read_text(encoding="utf-8", errors="replace")[:MAX_SKILL]


# --------------------------------------------------------------------------
# server MCP: configurazione
# --------------------------------------------------------------------------


def _leggi_json(f: Path) -> dict:
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _desktop() -> Path | None:
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    mac = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if mac.parent.is_dir():
        return mac
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def server_configurati(progetto: str | None = None) -> dict[str, dict]:
    """Tutti i server MCP che l'utente ha configurato, per nome. vedit escluso:
    i suoi strumenti l'assistente li ha gia'."""
    out: dict[str, dict] = {}

    def aggiungi(servers: dict | None, origine: str) -> None:
        for nome, conf in (servers or {}).items():
            if nome == "vedit" or not isinstance(conf, dict) or nome in out:
                continue
            if conf.get("disabled"):
                continue
            out[nome] = {**conf, "_origine": origine}

    aggiungi(_leggi_json(_vedit() / "mcp.json").get("mcpServers"), "vedit")
    if progetto:
        aggiungi(_leggi_json(Path(progetto).parent / ".mcp.json").get("mcpServers"), "project")
    cc = _leggi_json(Path(os.environ.get("VEDIT_CLAUDE_JSON") or (Path.home() / ".claude.json")))
    aggiungi(cc.get("mcpServers"), "claude-code")
    home = str(Path.home()).replace("\\", "/")
    for chiave, prog in (cc.get("projects") or {}).items():
        if chiave.replace("\\", "/").rstrip("/") == home.rstrip("/"):
            aggiungi(prog.get("mcpServers"), "claude-code")
    if (d := _desktop()) is not None:
        aggiungi(_leggi_json(d).get("mcpServers"), "claude-desktop")
    return out


def _nome_strumento(server: str, tool: str) -> str:
    # 64 caratteri al massimo e niente punti: e' il limite comune a Anthropic e OpenAI
    nome = f"mcp__{_NOME.sub('_', server)}__{_NOME.sub('_', tool)}"
    return nome[:64]


# --------------------------------------------------------------------------
# server MCP: collegamento
# --------------------------------------------------------------------------


class Gestore:
    """Sessioni MCP aperte in un ciclo asincrono tutto loro."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._sessioni: dict[str, Any] = {}
        self._uscite: dict[str, contextlib.AsyncExitStack] = {}
        self.strumenti: dict[str, dict] = {}       # nome per il modello -> {server, tool, schema}
        self.stato: dict[str, dict] = {}           # server -> {ok, errore, strumenti}

    def _ciclo(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, daemon=True,
                                 name="vedit-mcp-client").start()
            return self._loop

    def _esegui(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._ciclo()).result(timeout)

    async def _apri(self, nome: str, conf: dict) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        pila = contextlib.AsyncExitStack()
        try:
            tipo = conf.get("type") or ("stdio" if conf.get("command") else "http")
            if tipo == "stdio":
                env = {**os.environ, **{k: str(v) for k, v in (conf.get("env") or {}).items()}}
                params = StdioServerParameters(command=conf["command"],
                                               args=[str(a) for a in conf.get("args") or []],
                                               env=env, cwd=conf.get("cwd"))
                with open(os.devnull, "w") as nulla:
                    lettura, scrittura = await pila.enter_async_context(
                        stdio_client(params, errlog=nulla))
            elif tipo == "sse":
                from mcp.client.sse import sse_client
                lettura, scrittura = await pila.enter_async_context(
                    sse_client(conf["url"], headers=conf.get("headers")))
            else:
                # il client HTTP lo crea mcp: e' lui a sapere quale libreria usa
                from mcp.client.streamable_http import (create_mcp_http_client,
                                                        streamable_http_client)
                cliente = await pila.enter_async_context(create_mcp_http_client(
                    headers={k: str(v) for k, v in (conf.get("headers") or {}).items()}))
                flussi = await pila.enter_async_context(
                    streamable_http_client(conf["url"], http_client=cliente))
                lettura, scrittura = flussi[0], flussi[1]
            sessione = await pila.enter_async_context(ClientSession(lettura, scrittura))
            await asyncio.wait_for(sessione.initialize(), TIMEOUT_AVVIO)
            elenco = await asyncio.wait_for(sessione.list_tools(), TIMEOUT_AVVIO)
        except BaseException:
            await pila.aclose()
            raise
        self._sessioni[nome] = sessione
        self._uscite[nome] = pila
        n = 0
        for t in elenco.tools:
            chiave = _nome_strumento(nome, t.name)
            self.strumenti[chiave] = {
                "server": nome, "tool": t.name,
                "description": f"[{nome}] {(t.description or '').strip()}"[:1024],
                "schema": (getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)
                           or {"type": "object", "properties": {}}),
            }
            n += 1
        self.stato[nome] = {"ok": True, "strumenti": n}

    def collega(self, server: dict[str, dict], riprova: bool = False) -> dict[str, dict]:
        """Apre i server che non sono gia' aperti; chi non risponde resta fuori.

        Un server che non ha risposto non si ritenta a ogni messaggio (ogni
        tentativo puo' costare mezzo minuto): solo con ``riprova``.
        """
        for nome, conf in server.items():
            if nome in self._sessioni or (nome in self.stato and not riprova):
                continue
            if conf.get("type") == "http" and conf.get("oauth") or conf.get("_origine") == "claude.ai":
                continue
            try:
                self._esegui(asyncio.wait_for(self._apri(nome, conf), TIMEOUT_AVVIO + 5),
                             TIMEOUT_AVVIO + 10)
            except BaseException as exc:  # noqa: BLE001 - un server rotto non ferma gli altri
                msg = str(exc) or type(exc).__name__
                if "401" in msg or "Unauthorized" in msg:
                    msg = "needs sign-in (OAuth): use Claude Code as the model for this server"
                self.stato[nome] = {"ok": False, "errore": msg[:300]}
        return self.stato

    def chiama(self, nome: str, argomenti: dict) -> str:
        s = self.strumenti.get(nome)
        if s is None:
            raise ValueError(f"unknown MCP tool {nome}")
        sessione = self._sessioni[s["server"]]
        res = self._esegui(sessione.call_tool(s["tool"], argomenti or {}), TIMEOUT_CHIAMATA)
        parti = []
        for c in getattr(res, "content", None) or []:
            if getattr(c, "type", "") == "text":
                parti.append(c.text)
            elif getattr(c, "type", "") == "image":
                parti.append("[image returned by the tool: not shown here]")
            elif getattr(c, "type", "") == "resource":
                r = getattr(c, "resource", None)
                parti.append(getattr(r, "text", None) or f"[resource {getattr(r, 'uri', '')}]")
        strutturato = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
        if strutturato and not parti:
            parti.append(json.dumps(strutturato, ensure_ascii=False, default=str))
        testo = "\n".join(parti) or "done"
        if getattr(res, "is_error", None) or getattr(res, "isError", False):
            raise RuntimeError(testo[:2000])
        return testo[:100_000]

    def chiudi(self) -> None:
        for nome in list(self._uscite):
            pila = self._uscite.pop(nome)
            try:
                self._esegui(pila.aclose(), 10)
            except BaseException:  # noqa: BLE001
                pass
        self._sessioni.clear()
        self.strumenti.clear()
        self.stato.clear()


GESTORE = Gestore()


# --------------------------------------------------------------------------
# per la chat
# --------------------------------------------------------------------------

STRUMENTI_SKILL = [
    {"name": "use_skill",
     "description": "Carica le istruzioni di una skill dell'utente (vedi l'elenco nel "
                    "contesto) e i nomi dei suoi file. Usala prima di fare il compito.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "read_skill_file",
     "description": "Legge un file di una skill (riferimenti, modelli, esempi).",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"},
                                                        "path": {"type": "string"}},
                      "required": ["name", "path"]}},
    {"name": "list_skills",
     "description": "Tutte le skill dell'utente con la descrizione.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _spenti() -> set[str]:
    from . import llm
    return set(llm.carica().get("server_spenti") or [])


def server_attivi(progetto: str | None = None) -> dict[str, dict]:
    spenti = _spenti()
    return {n: c for n, c in server_configurati(progetto).items() if n not in spenti}


def strumenti(progetto: str | None = None) -> list[dict]:
    """Gli strumenti in piu' per il modello: skill e server MCP collegati."""
    attivi = server_attivi(progetto)
    GESTORE.collega(attivi)
    # un server spento dall'utente dopo il collegamento non deve piu' comparire
    out = list(STRUMENTI_SKILL)
    for nome, s in GESTORE.strumenti.items():
        if s["server"] in attivi:
            out.append({"name": nome, "description": s["description"], "input_schema": s["schema"]})
    return out


def esegui(nome: str, args: dict, progetto: str | None = None) -> str | None:
    """Esegue uno strumento di questo modulo; None se il nome non e' suo."""
    if nome == "use_skill":
        return json.dumps(usa_skill(args["name"], progetto), ensure_ascii=False)
    if nome == "read_skill_file":
        return leggi_file_skill(args["name"], args["path"], progetto)
    if nome == "list_skills":
        return json.dumps([{k: s[k] for k in ("name", "description")} for s in skill(progetto)],
                          ensure_ascii=False)
    if nome.startswith("mcp__"):
        return GESTORE.chiama(nome, args)
    return None


def stato(progetto: str | None = None) -> dict:
    """Cosa c'e': per la UI. Non apre i server, dice solo quelli configurati."""
    server = server_configurati(progetto)
    spenti = _spenti()
    return {
        "skill": [{k: s[k] for k in ("name", "description", "origin")} for s in skill(progetto)],
        "server": [{"name": n, "origin": c.get("_origine"),
                    "type": c.get("type") or ("stdio" if c.get("command") else "http"),
                    "on": n not in spenti, **GESTORE.stato.get(n, {})}
                   for n, c in server.items()],
    }
