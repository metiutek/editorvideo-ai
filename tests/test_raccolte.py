"""Raccolte: tanti video sotto una cartella con memoria e riferimenti comuni.

Una raccolta e' un canale, i video di famiglia, un cliente, una serie. Il suo
contesto deve arrivare a chi monta qualunque suo video:
agente MCP all'apertura del progetto, assistente della chat una volta per
conversazione, interfaccia dalla schermata iniziale e dalla testata.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vedit import api as api_mod
from vedit import chat, memoria, raccolte
from vedit import mcp_server as srv
from vedit.store import Store


@pytest.fixture(autouse=True)
def _isolati(tmp_path, monkeypatch):
    # registro delle raccolte e memoria comune fuori dalla cartella dell'utente
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("VEDIT_MEMORIA", str(tmp_path / "MEMORIA.md"))
    srv._stores.clear()
    srv._current[0] = None


def _png(path: Path, colore=(200, 30, 30), alfa=False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA" if alfa else "RGB", (64, 40), colore + ((128,) if alfa else ())).save(path)
    return str(path)


def test_crea_trova_e_progetti_dentro(tmp_path):
    c = raccolte.crea("Montagne & Co", str(tmp_path / "montagne"), "trekking in Dolomiti")
    assert c["name"] == "Montagne & Co" and c["video"] == [] and c["riferimenti"] == []
    cartella = Path(c["path"])
    assert (cartella / "raccolta.json").is_file() and (cartella / "riferimenti").is_dir()
    # per nome (maiuscole indifferenti) e per cartella
    assert raccolte.trova("montagne & co") == cartella
    assert raccolte.trova(str(cartella)) == cartella
    with pytest.raises(raccolte.RaccoltaError, match="Montagne & Co"):
        raccolte.trova("altro")

    p = raccolte.percorso_video(str(cartella), "Lago di Braies")
    assert Path(p) == cartella / "Lago di Braies" / "Lago di Braies.json"
    Store.create("Lago di Braies", path=p)
    # i file che vedit mette accanto al progetto non sono video
    Path(p).with_name("Lago di Braies.chat.json").write_text('{"vista": []}', encoding="utf-8")
    Path(p).with_name("Lago di Braies.piano.json").write_text('{"scene": []}', encoding="utf-8")
    # stesso nome: cartella nuova, il primo video non si tocca
    assert Path(raccolte.percorso_video(str(cartella), "Lago di Braies")).parent.name == "Lago di Braies 2"

    assert raccolte.di_progetto(p) == cartella
    assert raccolte.di_progetto(str(tmp_path / "fuori.json")) is None
    v = raccolte.video(cartella)
    assert [x["name"] for x in v] == ["Lago di Braies"]

    # una raccolta non sta dentro un'altra
    with pytest.raises(raccolte.RaccoltaError, match="do not nest"):
        raccolte.crea("dentro", str(cartella / "sotto"))
    with pytest.raises(raccolte.RaccoltaError, match="outside"):
        raccolte.dentro(cartella, str(tmp_path / "x.json"))


def test_cartella_esistente_adotta_i_progetti(tmp_path):
    d = tmp_path / "vecchi"
    Store.create("uno", path=str(d / "uno.json"))
    Store.create("due", path=str(d / "serie" / "due.json"))
    c = raccolte.crea("Vecchi", str(d))
    assert sorted(x["name"] for x in c["video"]) == ["due", "uno"]
    # riaprirlo non lo riscrive
    raccolte.modifica(str(d), descrizione="descrizione mia")
    assert raccolte.crea("altro nome", str(d))["description"] == "descrizione mia"
    assert [x["name"] for x in raccolte.elenco()] == ["Vecchi"]
    raccolte.dimentica_raccolta(str(d))
    assert raccolte.elenco() == [] and (d / "raccolta.json").is_file()


def test_riferimenti_note_e_foglio(tmp_path):
    c = raccolte.crea("C", str(tmp_path / "c"))["path"]
    logo = _png(tmp_path / "src" / "logo.png", alfa=True)
    mini = _png(tmp_path / "src" / "mini.jpg", (20, 200, 40))
    out = raccolte.aggiungi(c, [logo, mini, logo], nota="grafica del canale")
    # copiati, con un nome nuovo per il doppione
    assert out["aggiunti"] == ["logo.png", "mini.jpg", "logo_2.png"]
    assert all(Path(r["path"]).parent == Path(c) / "riferimenti" for r in out["riferimenti"])
    raccolte.annota(c, {"logo.png": "logo: sempre in alto a destra", "mini.jpg": ""})
    note = {r["file"]: r["nota"] for r in raccolte.riferimenti(c)}
    assert note == {"logo.png": "logo: sempre in alto a destra", "logo_2.png": "grafica del canale",
                    "mini.jpg": ""}
    with pytest.raises(raccolte.RaccoltaError, match="no reference"):
        raccolte.annota(c, {"nonce.png": "x"})
    with pytest.raises(raccolte.RaccoltaError, match="images"):
        raccolte.libero(c, "testo.txt")
    raccolte.togli(c, ["logo_2.png"])
    assert [r["file"] for r in raccolte.riferimenti(c)] == ["logo.png", "mini.jpg"]
    # immagine() non esce dalla cartella dei riferimenti
    with pytest.raises(raccolte.RaccoltaError):
        raccolte.immagine(c, "../raccolta.json")

    f = raccolte.foglio(c)
    with Image.open(f) as im:
        assert im.width == 2 * 360
    assert raccolte.foglio(c) == f   # stessa impronta, stesso file


def test_temporanei_di_salvataggio_non_sono_video(tmp_path):
    # un salvataggio interrotto lascia "~xxxxxxxx_<nome>.json" con il progetto
    # intero: la raccolta lo mostrava come una copia del video
    cartella = Path(raccolte.crea("Next", str(tmp_path / "next"))["path"])
    p = Path(raccolte.percorso_video(str(cartella), "Video 1"))
    s = Store.create("Video 1", path=str(p))
    rimasto = p.with_name(f"~3008629d_{p.name}")
    rimasto.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    assert [x["name"] for x in raccolte.video(cartella)] == ["Video 1"]

    # il salvataggio dopo li spazza, ma non quelli appena scritti (un altro
    # processo potrebbe star salvando proprio ora)
    import os
    import time
    fresco = p.with_name(f"~a0008d24_{p.name}")
    fresco.write_text("{}", encoding="utf-8")
    vecchio = time.time() - 3600
    os.utime(rimasto, (vecchio, vecchio))
    altro = p.with_name("~deadbeef_Altro.json")      # di un altro progetto: non si tocca
    altro.write_text("{}", encoding="utf-8")
    os.utime(altro, (vecchio, vecchio))
    s.save()
    assert not rimasto.exists() and fresco.exists() and altro.exists()


def test_memoria_e_contesto(tmp_path):
    c = raccolte.crea("Famiglia", str(tmp_path / "famiglia"), "i video di famiglia: Anna e Luca")["path"]
    p = raccolte.percorso_video(c, "Natale 2026")
    Store.create("Natale 2026", path=p)
    raccolte.ricorda(None, "sempre 9:16 e sottotitoli gialli", "format", progetto=p)
    raccolte.aggiungi(c, [_png(tmp_path / "logo.png")], nota="logo del canale")
    ctx = raccolte.contesto(p)
    assert "Famiglia" in ctx and "Anna e Luca" in ctx and "sottotitoli gialli" in ctx
    assert "logo del canale" in ctx and "# Memoria della raccolta" not in ctx
    # la memoria della raccolta non e' quella comune
    assert "gialli" not in memoria.leggi()
    assert raccolte.contesto(str(tmp_path / "altro.json")) == ""
    assert raccolte.dimentica(c, "GIALLI")["tolte"] == 1
    with pytest.raises(raccolte.RaccoltaError, match="not in a collection"):
        raccolte.ricorda(None, "x", progetto=str(tmp_path / "altro.json"))


@pytest.mark.anyio
async def test_strumenti_mcp(tmp_path):
    from test_mcp import call

    r = await call("collection_create", name="Viaggi", folder=str(tmp_path / "viaggi"),
                   description="vlog di viaggio")
    cartella = Path(r["path"])
    r = await call("project_create", collection="Viaggi", name="Islanda", preset="9:16")
    assert Path(r["path"]) == cartella / "Islanda" / "Islanda.json"
    assert "vlog di viaggio" in r["raccolta"]

    await call("remember", note="musica acustica, mai elettronica", scope="collection")
    assert "acustica" in (await call("memory", scope="collection"))["testo"]
    assert "acustica" not in (await call("memory"))["testo"]
    logo = _png(tmp_path / "logo.png")
    r = await call("collection_update", add_references=[logo], notes={"logo.png": "logo"},
                   description="vlog di viaggio a piedi")
    assert r["riferimenti"] == ["logo.png"]

    r = await call("project_open", path=str(cartella / "Islanda" / "Islanda.json"))
    assert "acustica" in r["raccolta"] and "a piedi" in r["raccolta"] and "logo.png" in r["raccolta"]
    # collection_info: dati e foglio dei riferimenti come immagine
    res = await srv.mcp.call_tool("collection_info", {})
    assert any(getattr(b, "type", "") == "image" for b in res.content)
    testo = json.loads(next(b.text for b in res.content if getattr(b, "text", None)))
    assert testo["video"][0]["name"] == "Islanda"
    assert [c["name"] for c in await call("collection_list")] == ["Viaggi"]
    assert (await call("forget", match="acustica", scope="collection"))["tolte"] == 1

    # path relativo: dentro la raccolta; fuori: rifiutato
    r = await call("project_create", collection=str(cartella), path="extra/x.json")
    assert Path(r["path"]) == cartella / "extra" / "x.json"
    with pytest.raises(Exception, match="outside"):
        await call("project_create", collection="Viaggi", path=str(tmp_path / "fuori.json"))
    with pytest.raises(Exception, match="path"):
        await call("project_create", name="senza percorso")


def test_chat_contesto_e_ricorda(tmp_path):
    c = raccolte.crea("Tech", str(tmp_path / "tech"), "recensioni di telefoni")["path"]
    raccolte.aggiungi(c, [_png(tmp_path / "logo.png")])
    s = Store.create("rec", path=raccolte.percorso_video(c, "rec"))
    stato: dict = {}
    blocchi = chat.blocco_raccolta(s.path, stato, claude_code=False)
    assert "recensioni di telefoni" in blocchi[0]["text"]
    assert any(b["type"] == "image" for b in blocchi)
    # una volta per conversazione, di nuovo se cambia
    assert chat.blocco_raccolta(s.path, stato, claude_code=False) == []
    raccolte.modifica(c, descrizione="recensioni di telefoni e tablet")
    assert "tablet" in chat.blocco_raccolta(s.path, stato, claude_code=False)[0]["text"]
    # Claude Code legge le immagini da se': solo testo, con i percorsi
    cc = chat.blocco_raccolta(s.path, {}, claude_code=True)
    assert len(cc) == 1 and "logo.png" in cc[0]["text"]

    chat.execute(s, "remember", {"note": "voce fuori campo ironica", "scope": "collection"})
    assert "ironica" in memoria.leggi(raccolte.file_memoria(c))
    assert "ironica" not in memoria.leggi()
    chat.execute(s, "forget", {"match": "ironica", "scope": "collection"})
    assert "ironica" not in memoria.leggi(raccolte.file_memoria(c))
    nomi = {t["name"]: t for t in chat.build_tools()}
    assert "scope" in nomi["remember"]["input_schema"]["properties"]


def test_api(tmp_path):
    api_mod.S.store = None
    with TestClient(api_mod.app) as client:
        r = client.post("/api/raccolte", json={"nome": "Gatti", "cartella": str(tmp_path / "gatti")})
        assert r.status_code == 200, r.text
        cartella = r.json()["path"]
        assert [c["name"] for c in client.get("/api/raccolte").json()["raccolte"]] == ["Gatti"]

        r = client.post("/api/raccolta/video", json={"path": cartella, "nome": "Micio", "preset": "9:16"})
        assert r.status_code == 200, r.text
        assert r.json()["raccolta"]["name"] == "Gatti"
        assert client.get("/api/project").json()["raccolta"]["path"] == cartella

        r = client.put("/api/raccolta", json={"path": cartella, "descrizione": "gatti buffi"})
        assert r.json()["description"] == "gatti buffi"
        r = client.put("/api/raccolta/memoria", json={"path": cartella, "testo": "## tono\n- leggero\n"})
        assert "leggero" in r.json()["memoria"]

        logo = _png(tmp_path / "logo.png")
        r = client.post("/api/raccolta/riferimenti", json={"path": cartella, "files": [logo]})
        assert [x["file"] for x in r.json()["riferimenti"]] == ["logo.png"]
        with open(logo, "rb") as f:
            r = client.post("/api/raccolta/riferimenti/carica", data={"path": cartella},
                            files=[("files", ("trascinata.png", f, "image/png"))])
        assert r.status_code == 200, r.text
        assert len(r.json()["riferimenti"]) == 2
        r = client.put("/api/raccolta/riferimento", json={"path": cartella, "file": "logo.png",
                                                        "nota": "in alto a destra"})
        assert r.json()["riferimenti"][0]["nota"] == "in alto a destra"
        r = client.get("/api/raccolta/immagine", params={"path": cartella, "file": "logo.png"})
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert client.get("/api/raccolta/immagine",
                          params={"path": cartella, "file": "../raccolta.json"}).status_code == 400
        r = client.delete("/api/raccolta/riferimento", params={"path": cartella, "file": "logo.png"})
        assert [x["file"] for x in r.json()["riferimenti"]] == ["trascinata.png"]

        info = client.get("/api/raccolta", params={"path": cartella}).json()
        assert [v["name"] for v in info["video"]] == ["Micio"]
        # un file rifiutato non e' un errore del server
        with open(tmp_path / "nota.txt", "w") as f:
            f.write("x")
        with open(tmp_path / "nota.txt", "rb") as f:
            r = client.post("/api/raccolta/riferimenti/carica", data={"path": cartella},
                            files=[("files", ("nota.txt", f, "text/plain"))])
        assert r.status_code == 400
        assert client.delete("/api/raccolte", params={"path": cartella}).json()["raccolte"] == []
    api_mod.S.store = None
