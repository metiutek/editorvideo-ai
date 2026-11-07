"""Cosa sta dentro una raccolta oltre ai video: file di informazioni e skill;
e il quaderno di ogni video, la memoria del progetto che l'AI scrive da se'."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import chat, estensioni, memoria, progetti, raccolte
from vedit import mcp_server as srv
from vedit.store import Store


@pytest.fixture(autouse=True)
def _isolati(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("VEDIT_MEMORIA", str(tmp_path / "MEMORIA.md"))
    monkeypatch.setattr(estensioni, "_vedit", lambda: tmp_path / "vedit")
    monkeypatch.setattr(estensioni, "_home", lambda: tmp_path / "claude")
    srv._stores.clear()
    srv._current[0] = None
    api_mod.S.store = None
    yield
    api_mod.S.store = None


def _raccolta(tmp_path, nome="Cliente"):
    c = raccolte.crea(nome, str(tmp_path / nome.lower()))["path"]
    p = raccolte.percorso_video(c, "Spot")
    Store.create("Spot", path=p)
    return c, p


def test_documenti(tmp_path):
    c, p = _raccolta(tmp_path)
    brief = tmp_path / "brief.md"
    brief.write_text("Il cliente vuole toni caldi e il logo alla fine.", encoding="utf-8")
    lungo = tmp_path / "trascrizione.txt"
    lungo.write_text("parola " * 5000, encoding="utf-8")
    (tmp_path / "listino.pdf").write_bytes(b"%PDF-1.4 finto")
    out = raccolte.aggiungi_documenti(c, [str(brief), str(lungo), str(tmp_path / "listino.pdf")])
    assert out["aggiunti"] == ["brief.md", "trascrizione.txt", "listino.pdf"]
    assert Path(c, "documenti", "brief.md").is_file()
    # stesso nome: non sovrascrive
    assert raccolte.aggiungi_documenti(c, [str(brief)])["aggiunti"] == ["brief_2.md"]
    with pytest.raises(raccolte.RaccoltaError, match="text or pdf"):
        raccolte.libero_doc(c, "video.mp4")

    ctx = raccolte.contesto(p)
    assert "toni caldi" in ctx                              # il testo breve entra intero
    assert "trascrizione.txt" in ctx and "parola parola parola" not in ctx   # quello lungo no
    assert "listino.pdf" in ctx and "collection_file" in ctx
    letto = raccolte.leggi_documento(None, "trascrizione.txt", p)
    assert letto["testo"].startswith("parola")
    assert raccolte.leggi_documento(c, "listino.pdf")["testo"] is None

    raccolte.scrivi_documento(c, "note di produzione", "## riprese\n- sabato mattina")
    assert "sabato" in raccolte.leggi_documento(c, "note di produzione.md")["testo"]
    with pytest.raises(raccolte.RaccoltaError, match="only text"):
        raccolte.scrivi_documento(c, "x.pdf", "no")
    raccolte.togli_documenti(c, ["brief_2.md"])
    assert [d["file"] for d in raccolte.info(c)["documenti"]] == [
        "brief.md", "listino.pdf", "note di produzione.md", "trascrizione.txt"]
    with pytest.raises(raccolte.RaccoltaError, match="no information file"):
        raccolte.leggi_documento(c, "../raccolta.json")
    # i documenti non sono video, neanche un .json che ne ha l'aria
    Path(c, "documenti", "dati.json").write_text(json.dumps({"tracks": [], "settings": {}}))
    assert [v["name"] for v in raccolte.video(c)] == ["Spot"]


def test_skill_della_raccolta(tmp_path):
    c, p = _raccolta(tmp_path)
    fuori = tmp_path / "fuori.json"
    Store.create("fuori", path=str(fuori))
    dove = raccolte.cartella_skill(c)
    estensioni.crea_skill("spot-cliente", "spot di 15 secondi del cliente", "- logo alla fine", dove=dove)
    assert (dove / "spot-cliente" / "SKILL.md").is_file()
    assert [s["name"] for s in raccolte.skill(c)] == ["spot-cliente"]

    # vale solo per i video della raccolta
    dentro = {s["name"]: s for s in estensioni.skill_vedit(p)}
    assert dentro["spot-cliente"]["origin"] == "collection"
    assert "spot-cliente" not in {s["name"] for s in estensioni.skill_vedit(str(fuori))}
    assert "logo alla fine" in estensioni.usa_skill("spot-cliente", p, solo_vedit=True)["istruzioni"]
    assert "spot-cliente" in raccolte.contesto(p)

    md = tmp_path / "tagli.md"
    md.write_text("---\nname: tagli\ndescription: tagli rapidi\n---\n\nTaglia sul battito.", encoding="utf-8")
    assert estensioni.installa_skill(str(md), dove=dove)["installate"][0]["name"] == "tagli"
    assert not (estensioni.cartella_vedit() / "tagli").exists()     # non e' finita fra quelle di tutti
    estensioni.elimina_skill("tagli", dove)
    assert [s["name"] for s in raccolte.skill(c)] == ["spot-cliente"]
    with pytest.raises(ValueError, match="no vedit skill"):
        estensioni.elimina_skill("spot-cliente")     # senza dove: cerca in ~/.vedit/skills


def test_memoria_del_progetto(tmp_path):
    c, p = _raccolta(tmp_path)
    f = memoria.file_progetto(p)
    assert f == Path(p).with_name("Spot.memoria.md")
    assert memoria.contesto_progetto(p) == ""
    memoria.ricorda("l'utente vuole chiudere sul logo", "requests", f, memoria.INTESTAZIONE_PROGETTO)
    assert memoria.leggi(f).startswith("# Memoria del progetto")
    ctx = memoria.contesto_progetto(p)
    assert "chiudere sul logo" in ctx and "# Memoria del progetto" not in ctx
    assert "logo" not in memoria.leggi()                    # non e' la memoria comune
    assert "logo" not in memoria.leggi(raccolte.file_memoria(c))   # ne' quella della raccolta

    # viaggia col progetto
    nuovo = progetti.rinomina(p, "Spot estate")["path"]
    assert "chiudere sul logo" in memoria.leggi(memoria.file_progetto(nuovo))
    assert "chiudere sul logo" not in memoria.leggi(memoria.file_progetto(progetti.duplica(nuovo)["path"]))


@pytest.mark.anyio
async def test_mcp(tmp_path):
    from test_mcp import call

    c, p = _raccolta(tmp_path)
    await call("project_open", path=p)
    await call("remember", note="manca la musica finale", section="todo", scope="project")
    assert "musica finale" in (await call("memory", scope="project"))["testo"]
    assert "musica finale" not in (await call("memory"))["testo"]
    r = await call("project_open", path=p)
    assert "musica finale" in r["memoria_progetto"]
    assert (await call("forget", match="musica", scope="project"))["tolte"] == 1

    brief = tmp_path / "brief.txt"
    brief.write_text("target: 25-35 anni", encoding="utf-8")
    r = await call("collection_update", add_files=[str(brief)], write_file={"tono.md": "ironico"})
    assert r["documenti"] == ["brief.txt", "tono.md"]
    assert (await call("collection_file", file="tono.md"))["testo"] == "ironico"
    assert "25-35" in (await call("project_open", path=p))["raccolta"]

    await call("create_skill", name="chiusura", description="chiusura degli spot",
               instructions="logo 2 secondi", collection=".")
    assert [s["name"] for s in raccolte.skill(c)] == ["chiusura"]
    assert "chiusura" in (await call("project_open", path=p))["skill"]
    await call("delete_skill", name="chiusura", collection=".")
    assert raccolte.skill(c) == []
    with pytest.raises(Exception, match="scope"):
        await call("remember", note="x", scope="video")


def test_chat(tmp_path):
    c, p = _raccolta(tmp_path)
    s = Store.open(p)
    chat.execute(s, "remember", {"note": "titolo: Estate 2026", "scope": "project"})
    assert "Estate 2026" in memoria.leggi(memoria.file_progetto(p))
    raccolte.scrivi_documento(c, "brief.md", "solo musica libera da diritti")
    assert json.loads(chat.execute(s, "collection_file", {"file": "brief.md"}))["testo"].startswith("solo")
    chat.execute(s, "create_skill", {"name": "brand", "description": "regole del brand",
                                     "instructions": "colori del logo", "collection": True})
    assert [x["name"] for x in raccolte.skill(c)] == ["brand"]
    chat.execute(s, "forget", {"match": "Estate", "scope": "project"})
    assert "Estate" not in memoria.leggi(memoria.file_progetto(p))
    nomi = {t["name"]: t for t in chat.build_tools()}
    assert "project" in nomi["remember"]["input_schema"]["properties"]["scope"]["enum"]
    assert "collection_file" in nomi


def test_api(tmp_path):
    c, p = _raccolta(tmp_path)
    with TestClient(api_mod.app) as client:
        client.post("/api/project/open", json={"path": p})
        r = client.put("/api/memoria", params={"scope": "project"}, json={"testo": "# x\n\n## todo\n- grafica finale\n"})
        assert r.status_code == 200, r.text
        assert "grafica finale" in client.get("/api/memoria", params={"scope": "project"}).json()["testo"]
        assert "grafica finale" not in client.get("/api/memoria").json()["testo"]

        r = client.put("/api/raccolta/documento", json={"path": c, "file": "brief", "testo": "toni caldi"})
        assert r.status_code == 200, r.text
        assert [d["file"] for d in r.json()["documenti"]] == ["brief.md"]
        assert client.get("/api/raccolta/documento", params={"path": c, "file": "brief.md"}).json()["testo"] == "toni caldi"
        r = client.post("/api/raccolta/documenti/carica", data={"path": c},
                        files=[("files", ("copione.txt", b"scena 1", "text/plain"))])
        assert [d["file"] for d in r.json()["documenti"]] == ["brief.md", "copione.txt"]
        r = client.post("/api/raccolta/documenti/carica", data={"path": c},
                        files=[("files", ("clip.mp4", b"x", "video/mp4"))])
        assert r.status_code == 400
        r = client.delete("/api/raccolta/documento", params={"path": c, "file": "copione.txt"})
        assert [d["file"] for d in r.json()["documenti"]] == ["brief.md"]

        r = client.post("/api/raccolta/skill", json={"path": c, "name": "Spot", "description": "gli spot",
                                                     "instructions": "15 secondi"})
        assert r.status_code == 200, r.text
        assert [x["name"] for x in r.json()["skill"]] == ["spot"]
        r = client.post("/api/raccolta/skill/carica", data={"path": c},
                        files=[("file", ("ritmo.md", b"---\nname: ritmo\ndescription: d\n---\n\nveloce", "text/markdown"))])
        assert [x["name"] for x in r.json()["skill"]] == ["ritmo", "spot"]
        r = client.delete("/api/raccolta/skill", params={"path": c, "nome": "ritmo"})
        assert [x["name"] for x in r.json()["skill"]] == ["spot"]
        assert client.delete("/api/raccolta/skill", params={"path": c, "nome": "no"}).status_code == 400
        client.post("/api/project/close")
        assert client.get("/api/memoria", params={"scope": "project"}).status_code == 400
