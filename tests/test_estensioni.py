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
    # le versioni recenti di mcp nascondono il testo dell'eccezione del server:
    # conta che l'errore arrivi come errore, non come risultato
    with pytest.raises(RuntimeError, match="rotto apposta|rompe"):
        estensioni.esegui("mcp__prova__rompe", {})
    # spento dall'utente: sparisce dagli strumenti
    monkeypatch.setattr(estensioni, "_spenti", lambda: {"prova"})
    assert not any(t["name"].startswith("mcp__prova") for t in estensioni.strumenti())


def test_chat_usa_skill(casa):
    s = Store.create("c")
    try:
        llm.imposta_accesso("estensioni", [])
        out = json.loads(chat.execute(s, "use_skill", {"name": "sottotitoli"}))
        assert out["name"] == "sottotitoli"
        assert "karaoke" in chat.execute(s, "list_skills", {})
    finally:
        llm.imposta_accesso("editor", [])
    # al livello "editor" solo le skill di montaggio di vedit
    assert "karaoke" not in chat.execute(s, "list_skills", {})


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


# --------------------------------------------------------------------------
# skill di montaggio: quelle che si aggiungono a vedit
# --------------------------------------------------------------------------


@pytest.fixture
def vedit_skill(tmp_path, monkeypatch):
    """~/.vedit e ~/.claude finte e vuote."""
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "vedit"))
    monkeypatch.setenv("VEDIT_HOME_CLAUDE", str(tmp_path / "claude"))
    return tmp_path / "vedit" / "skills"


def test_crea_e_elimina_skill(vedit_skill):
    s = estensioni.crea_skill("Reel di Viaggio!", "reel verticali di viaggio",
                              "- 9:16\n- stacchi sul battito", {"modelli/titolo.html": "<h1>x</h1>"})
    assert s["name"] == "reel-di-viaggio" and not s["aggiornata"]
    assert (vedit_skill / "reel-di-viaggio" / "modelli" / "titolo.html").is_file()
    voci = estensioni.skill_vedit()
    assert [(v["name"], v["description"], v["origin"]) for v in voci] == [
        ("reel-di-viaggio", "reel verticali di viaggio", "vedit")]
    assert "stacchi sul battito" in estensioni.usa_skill("reel-di-viaggio")["istruzioni"]
    assert estensioni.crea_skill("reel-di-viaggio", "altro", "altro")["aggiornata"]
    with pytest.raises(ValueError):
        estensioni.crea_skill("x", "d", "i", {"../fuori.txt": "no"})
    with pytest.raises(ValueError):
        estensioni.crea_skill("x", "", "i")
    estensioni.elimina_skill("reel-di-viaggio")
    assert estensioni.skill_vedit() == []
    with pytest.raises(ValueError):
        estensioni.elimina_skill("reel-di-viaggio")


def test_installa_da_cartella_md_e_zip(vedit_skill, tmp_path):
    import zipfile

    raccolta = tmp_path / "repo"
    _skill(raccolta / "skills" / "podcast", "podcast", "Podcast con due camere")
    (raccolta / "skills" / "podcast" / "note.md").write_text("primo piano", encoding="utf-8")
    _skill(raccolta / "skills" / "trailer", "trailer", "Trailer in tre atti")
    out = estensioni.installa_skill(raccolta)
    assert sorted(s["name"] for s in out["installate"]) == ["podcast", "trailer"]
    assert (vedit_skill / "podcast" / "note.md").read_text(encoding="utf-8") == "primo piano"

    # un .md senza frontmatter: nome dal file, descrizione dalla prima riga
    md = tmp_path / "vlog-veloce.md"
    md.write_text("# Vlog veloce con zoom\n\nTaglia ogni 2 secondi.", encoding="utf-8")
    estensioni.installa_skill(md)
    v = next(s for s in estensioni.skill_vedit() if s["name"] == "vlog-veloce")
    assert v["description"] == "Vlog veloce con zoom"

    z = tmp_path / "pacchetto.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("cartella/intervista/SKILL.md",
                   "---\nname: intervista\ndescription: Interviste\n---\nTaglia le pause.")
    assert estensioni.installa_skill(z)["installate"][0]["name"] == "intervista"
    # lo stesso pacchetto caricato dalla UI
    assert estensioni.installa_skill("", "p.zip", z.read_bytes())["installate"][0]["aggiornata"]

    cattivo = tmp_path / "cattivo.zip"
    with zipfile.ZipFile(cattivo, "w") as f:
        f.writestr("../fuori/SKILL.md", "---\nname: x\ndescription: y\n---\nz")
    with pytest.raises(ValueError):
        estensioni.installa_skill(cattivo)
    with pytest.raises(ValueError):
        estensioni.installa_skill(tmp_path / "vuota")


def test_url_github():
    assert estensioni._url_github("https://github.com/a/b") == (
        "https://github.com/a/b/archive/HEAD.zip", "")
    assert estensioni._url_github("https://github.com/a/b/tree/main/skills/x") == (
        "https://github.com/a/b/archive/main.zip", "skills/x")
    assert estensioni._url_github("https://github.com/a/b/blob/main/x/SKILL.md")[0] == \
        "https://raw.githubusercontent.com/a/b/main/x/SKILL.md"


def test_installa_da_link(vedit_skill, monkeypatch):
    import http.server
    import threading

    monkeypatch.setenv("VEDIT_WEB_LOCALE", "1")

    class Sito(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("SKILL.md"):
                corpo, tipo = b"---\ndescription: Montaggio a tempo\n---\nUsa music_beats.", "text/markdown"
            else:
                corpo, tipo = b"<html>pagina</html>", "text/html"
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Sito)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        out = estensioni.installa_skill(f"{base}/skills/a-tempo/SKILL.md")
        assert out["installate"][0]["name"] == "a-tempo"
        with pytest.raises(ValueError, match="web page"):
            estensioni.installa_skill(f"{base}/una-pagina")
    finally:
        server.shutdown()


def test_skill_di_vedit_al_livello_editor(vedit_skill, tmp_path):
    """Al livello "editor" il modello vede le skill di montaggio, non le altre."""
    _skill(tmp_path / "claude" / "skills" / "altro", "altro", "Non di montaggio")
    estensioni.crea_skill("podcast", "Podcast con due camere", "Alterna le camere.")
    assert "altro" not in estensioni.indice_skill(solo_vedit=True)
    assert "podcast" in estensioni.indice_skill(solo_vedit=True)
    s = Store.create("c")
    llm.imposta_accesso("editor", [])
    assert json.loads(chat.execute(s, "use_skill", {"name": "podcast"}))["name"] == "podcast"
    with pytest.raises(ValueError):
        chat.execute(s, "use_skill", {"name": "altro"})
    out = json.loads(chat.execute(s, "create_skill", {
        "name": "reel", "description": "Reel", "instructions": "Corto."}))
    assert out["name"] == "reel"
    assert "con use_skill del server MCP vedit" in chat.comando_skill("/podcast", True)
    assert "con lo strumento Skill" in chat.comando_skill("/altro", True)
