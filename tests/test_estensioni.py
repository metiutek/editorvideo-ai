"""Skill e server MCP dell'utente per l'assistente, e livelli di accesso."""

import json
import sys

import pytest

from vedit import chat, estensioni, llm
from vedit.store import Store

_SERVER = """
from mcp.server.mcpserver import MCPServer
m = MCPServer("prova")

@m.tool()
def somma(a: int, b: int) -> str:
    '''Somma due numeri.'''
    return str(a + b)

@m.tool()
def rompe() -> str:
    '''Fallisce sempre.'''
    raise ValueError("rotto apposta")

m.run()
"""


def _skill(cartella, nome, descrizione, corpo="Fai cosi'."):
    cartella.mkdir(parents=True, exist_ok=True)
    (cartella / "SKILL.md").write_text(
        f"---\nname: {nome}\ndescription: {descrizione}\n---\n{corpo}\n", encoding="utf-8")
    return cartella


@pytest.fixture
def casa(tmp_path, monkeypatch):
    """Una ~/.claude finta, con skill in tutti i posti dove le mette Claude Code."""
    home = tmp_path / "claude"
    monkeypatch.setenv("VEDIT_HOME_CLAUDE", str(home))
    monkeypatch.setenv("VEDIT_CLAUDE_JSON", str(tmp_path / "claude.json"))
    s = _skill(home / "skills" / "sottotitoli", "sottotitoli", "Sottotitoli in stile karaoke")
    (s / "riferimenti").mkdir()
    (s / "riferimenti" / "colori.md").write_text("giallo e nero", encoding="utf-8")
    _skill(home / "skills" / "synced" / "acc" / "computer-use", "computer-use",
           "Usare il computer")
    plug = home / "plugins" / "synced" / "acc" / "1234-uuid"
    (plug / ".claude-plugin").mkdir(parents=True)
    (plug / ".claude-plugin" / "plugin.json").write_text('{"name": "cowork"}', encoding="utf-8")
    _skill(plug / "skills" / "crea", "crea", "Crea un plugin")
    _skill(home / "plugins" / ".trash" / "x" / "skills" / "vecchia", "vecchia", "cancellata")
    yield home
    estensioni.GESTORE.chiudi()


def test_trova_le_skill(casa):
    nomi = {s["name"]: s["origin"] for s in estensioni.skill()}
    assert nomi == {"sottotitoli": "user", "computer-use": "account", "cowork:crea": "plugin:cowork"}
    indice = estensioni.indice_skill()
    assert "computer-use: Usare il computer" in indice and "use_skill" in indice
    u = estensioni.usa_skill("sottotitoli")
    assert u["istruzioni"].strip() == "Fai cosi'." and u["file"] == ["riferimenti/colori.md"]
    assert estensioni.usa_skill("crea")["name"] == "cowork:crea"   # anche senza il plugin davanti
    assert estensioni.leggi_file_skill("sottotitoli", "riferimenti/colori.md") == "giallo e nero"
    with pytest.raises(ValueError):
        estensioni.leggi_file_skill("sottotitoli", "../../../claude.json")
    with pytest.raises(ValueError):
        estensioni.usa_skill("non-esiste")


def test_server_configurati(casa, tmp_path):
    (tmp_path / "claude.json").write_text(json.dumps({
        "mcpServers": {"gimp": {"command": "gimp-mcp"}, "vedit": {"command": "vedit-mcp"}},
        "projects": {"/altrove": {"mcpServers": {"segreto": {"command": "x"}}}},
    }), encoding="utf-8")
    server = estensioni.server_configurati()
    assert set(server) == {"gimp"}               # vedit no, progetti di altre cartelle no
    assert server["gimp"]["_origine"] == "claude-code"


def test_server_mcp_vero(casa, tmp_path, monkeypatch):
    script = tmp_path / "server.py"
    script.write_text(_SERVER, encoding="utf-8")
    (tmp_path / "claude.json").write_text(json.dumps({"mcpServers": {
        "prova": {"command": sys.executable, "args": [str(script)]},
        "morto": {"command": str(tmp_path / "non-esiste.exe")},
    }}), encoding="utf-8")
    nomi = {t["name"] for t in estensioni.strumenti()}
    assert {"mcp__prova__somma", "mcp__prova__rompe", "use_skill"} <= nomi
    st = estensioni.GESTORE.stato
    assert st["prova"] == {"ok": True, "strumenti": 2} and st["morto"]["ok"] is False
    assert estensioni.esegui("mcp__prova__somma", {"a": 2, "b": 40}) == "42"
    with pytest.raises(RuntimeError, match="rotto apposta"):
        estensioni.esegui("mcp__prova__rompe", {})
    # spento dall'utente: sparisce dagli strumenti
    monkeypatch.setattr(estensioni, "_spenti", lambda: {"prova"})
    assert not any(t["name"].startswith("mcp__prova") for t in estensioni.strumenti())


def test_chat_usa_skill(casa):
    s = Store.create("c")
    out = json.loads(chat.execute(s, "use_skill", {"name": "sottotitoli"}))
    assert out["name"] == "sottotitoli"
    assert "karaoke" in chat.execute(s, "list_skills", {})


def test_livelli_di_accesso():
    assert "--strict-mcp-config" in llm.argomenti_accesso({"accesso": "editor"})
    est = llm.argomenti_accesso({"accesso": "estensioni", "server_spenti": ["gmail"]})
    assert "--strict-mcp-config" not in est and "--chrome" in est and "Skill" in est
    assert est[est.index("--permission-mode") + 1] == "auto"
    assert est[est.index("--disallowedTools") + 1] == "mcp__gmail"
    tutto = llm.argomenti_accesso({"accesso": "completo"})
    assert tutto[tutto.index("--permission-mode") + 1] == "bypassPermissions"
    try:
        llm.imposta_accesso("estensioni", ["gmail"])
        assert llm.carica()["accesso"] == "estensioni" and llm.stato()["accesso"] == "estensioni"
        with pytest.raises(ValueError):
            llm.imposta_accesso("tutto-tutto")
    finally:
        llm.imposta_accesso("editor", [])
