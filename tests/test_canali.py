"""Canali: tanti video sotto una cartella con memoria e riferimenti comuni.

Il contesto del canale deve arrivare a chi monta qualunque video del canale:
agente MCP all'apertura del progetto, assistente della chat una volta per
conversazione, interfaccia dalla schermata iniziale e dalla testata.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vedit import api as api_mod
from vedit import canali, chat, memoria
from vedit import mcp_server as srv
from vedit.store import Store


@pytest.fixture(autouse=True)
def _isolati(tmp_path, monkeypatch):
    # registro dei canali e memoria comune fuori dalla cartella dell'utente
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("VEDIT_MEMORIA", str(tmp_path / "MEMORIA.md"))
    srv._stores.clear()
    srv._current[0] = None


def _png(path: Path, colore=(200, 30, 30), alfa=False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA" if alfa else "RGB", (64, 40), colore + ((128,) if alfa else ())).save(path)
    return str(path)


def test_crea_trova_e_progetti_dentro(tmp_path):
    c = canali.crea("Montagne & Co", str(tmp_path / "montagne"), "trekking in Dolomiti")
    assert c["name"] == "Montagne & Co" and c["video"] == [] and c["riferimenti"] == []
    cartella = Path(c["path"])
    assert (cartella / "canale.json").is_file() and (cartella / "riferimenti").is_dir()
    # per nome (maiuscole indifferenti) e per cartella
    assert canali.trova("montagne & co") == cartella
    assert canali.trova(str(cartella)) == cartella
    with pytest.raises(canali.CanaleError, match="Montagne & Co"):
        canali.trova("altro")

    p = canali.percorso_video(str(cartella), "Lago di Braies")
    assert Path(p) == cartella / "Lago di Braies" / "Lago di Braies.json"
    Store.create("Lago di Braies", path=p)
    # i file che vedit mette accanto al progetto non sono video
    Path(p).with_name("Lago di Braies.chat.json").write_text('{"vista": []}', encoding="utf-8")
    Path(p).with_name("Lago di Braies.piano.json").write_text('{"scene": []}', encoding="utf-8")
    # stesso nome: cartella nuova, il primo video non si tocca
    assert Path(canali.percorso_video(str(cartella), "Lago di Braies")).parent.name == "Lago di Braies 2"

    assert canali.di_progetto(p) == cartella
    assert canali.di_progetto(str(tmp_path / "fuori.json")) is None
    v = canali.video(cartella)
    assert [x["name"] for x in v] == ["Lago di Braies"]

    # un canale non sta dentro un altro
    with pytest.raises(canali.CanaleError, match="do not nest"):
        canali.crea("dentro", str(cartella / "sotto"))
    with pytest.raises(canali.CanaleError, match="outside"):
        canali.dentro(cartella, str(tmp_path / "x.json"))


def test_cartella_esistente_adotta_i_progetti(tmp_path):
    d = tmp_path / "vecchi"
    Store.create("uno", path=str(d / "uno.json"))
    Store.create("due", path=str(d / "serie" / "due.json"))
    c = canali.crea("Vecchi", str(d))
    assert sorted(x["name"] for x in c["video"]) == ["due", "uno"]
    # riaprirlo non lo riscrive
    canali.modifica(str(d), descrizione="descrizione mia")
    assert canali.crea("altro nome", str(d))["description"] == "descrizione mia"
    assert [x["name"] for x in canali.elenco()] == ["Vecchi"]
    canali.dimentica_canale(str(d))
    assert canali.elenco() == [] and (d / "canale.json").is_file()


def test_riferimenti_note_e_foglio(tmp_path):
    c = canali.crea("C", str(tmp_path / "c"))["path"]
    logo = _png(tmp_path / "src" / "logo.png", alfa=True)
    mini = _png(tmp_path / "src" / "mini.jpg", (20, 200, 40))
    out = canali.aggiungi(c, [logo, mini, logo], nota="grafica del canale")
    # copiati, con un nome nuovo per il doppione
    assert out["aggiunti"] == ["logo.png", "mini.jpg", "logo_2.png"]
    assert all(Path(r["path"]).parent == Path(c) / "riferimenti" for r in out["riferimenti"])
    canali.annota(c, {"logo.png": "logo: sempre in alto a destra", "mini.jpg": ""})
    note = {r["file"]: r["nota"] for r in canali.riferimenti(c)}
    assert note == {"logo.png": "logo: sempre in alto a destra", "logo_2.png": "grafica del canale",
                    "mini.jpg": ""}
    with pytest.raises(canali.CanaleError, match="no reference"):
        canali.annota(c, {"nonce.png": "x"})
    with pytest.raises(canali.CanaleError, match="images"):
        canali.libero(c, "testo.txt")
    canali.togli(c, ["logo_2.png"])
    assert [r["file"] for r in canali.riferimenti(c)] == ["logo.png", "mini.jpg"]
    # immagine() non esce dalla cartella dei riferimenti
    with pytest.raises(canali.CanaleError):
        canali.immagine(c, "../canale.json")

    f = canali.foglio(c)
    with Image.open(f) as im:
        assert im.width == 2 * 360
    assert canali.foglio(c) == f   # stessa impronta, stesso file


def test_memoria_e_contesto(tmp_path):
    c = canali.crea("Cucina", str(tmp_path / "cucina"), "ricette veloci per studenti")["path"]
    p = canali.percorso_video(c, "pasta")
    Store.create("pasta", path=p)
    canali.ricorda(None, "sempre 9:16 e sottotitoli gialli", "format", progetto=p)
    canali.aggiungi(c, [_png(tmp_path / "logo.png")], nota="logo del canale")
    ctx = canali.contesto(p)
    assert "Cucina" in ctx and "ricette veloci" in ctx and "sottotitoli gialli" in ctx
    assert "logo del canale" in ctx and "# Memoria del canale" not in ctx
    # la memoria del canale non e' quella comune
    assert "gialli" not in memoria.leggi()
    assert canali.contesto(str(tmp_path / "altro.json")) == ""
    assert canali.dimentica(c, "GIALLI")["tolte"] == 1
    with pytest.raises(canali.CanaleError, match="not in a channel"):
        canali.ricorda(None, "x", progetto=str(tmp_path / "altro.json"))


@pytest.mark.anyio
async def test_strumenti_mcp(tmp_path):
    from test_mcp import call

    r = await call("channel_create", name="Viaggi", folder=str(tmp_path / "viaggi"),
                   description="vlog di viaggio")
    cartella = Path(r["path"])
    r = await call("project_create", channel="Viaggi", name="Islanda", preset="9:16")
    assert Path(r["path"]) == cartella / "Islanda" / "Islanda.json"
    assert "vlog di viaggio" in r["canale"]

    await call("remember", note="musica acustica, mai elettronica", scope="channel")
    assert "acustica" in (await call("memory", scope="channel"))["testo"]
    assert "acustica" not in (await call("memory"))["testo"]
    logo = _png(tmp_path / "logo.png")
    r = await call("channel_update", add_references=[logo], notes={"logo.png": "logo"},
                   description="vlog di viaggio a piedi")
    assert r["riferimenti"] == ["logo.png"]

    r = await call("project_open", path=str(cartella / "Islanda" / "Islanda.json"))
    assert "acustica" in r["canale"] and "a piedi" in r["canale"] and "logo.png" in r["canale"]
    # channel_info: dati e foglio dei riferimenti come immagine
    res = await srv.mcp.call_tool("channel_info", {})
    assert any(getattr(b, "type", "") == "image" for b in res.content)
    testo = json.loads(next(b.text for b in res.content if getattr(b, "text", None)))
    assert testo["video"][0]["name"] == "Islanda"
    assert [c["name"] for c in await call("channel_list")] == ["Viaggi"]
    assert (await call("forget", match="acustica", scope="channel"))["tolte"] == 1

    # path relativo: dentro il canale; fuori: rifiutato
    r = await call("project_create", channel=str(cartella), path="extra/x.json")
    assert Path(r["path"]) == cartella / "extra" / "x.json"
    with pytest.raises(Exception, match="outside"):
        await call("project_create", channel="Viaggi", path=str(tmp_path / "fuori.json"))
    with pytest.raises(Exception, match="path"):
        await call("project_create", name="senza percorso")


def test_chat_contesto_e_ricorda(tmp_path):
    c = canali.crea("Tech", str(tmp_path / "tech"), "recensioni di telefoni")["path"]
    canali.aggiungi(c, [_png(tmp_path / "logo.png")])
    s = Store.create("rec", path=canali.percorso_video(c, "rec"))
    stato: dict = {}
    blocchi = chat.blocco_canale(s.path, stato, claude_code=False)
    assert "recensioni di telefoni" in blocchi[0]["text"]
    assert any(b["type"] == "image" for b in blocchi)
    # una volta per conversazione, di nuovo se cambia
    assert chat.blocco_canale(s.path, stato, claude_code=False) == []
    canali.modifica(c, descrizione="recensioni di telefoni e tablet")
    assert "tablet" in chat.blocco_canale(s.path, stato, claude_code=False)[0]["text"]
    # Claude Code legge le immagini da se': solo testo, con i percorsi
    cc = chat.blocco_canale(s.path, {}, claude_code=True)
    assert len(cc) == 1 and "logo.png" in cc[0]["text"]

    chat.execute(s, "remember", {"note": "voce fuori campo ironica", "scope": "channel"})
    assert "ironica" in memoria.leggi(canali.file_memoria(c))
    assert "ironica" not in memoria.leggi()
    chat.execute(s, "forget", {"match": "ironica", "scope": "channel"})
    assert "ironica" not in memoria.leggi(canali.file_memoria(c))
    nomi = {t["name"]: t for t in chat.build_tools()}
    assert "scope" in nomi["remember"]["input_schema"]["properties"]


def test_api(tmp_path):
    api_mod.S.store = None
    with TestClient(api_mod.app) as client:
        r = client.post("/api/canali", json={"nome": "Gatti", "cartella": str(tmp_path / "gatti")})
        assert r.status_code == 200, r.text
        cartella = r.json()["path"]
        assert [c["name"] for c in client.get("/api/canali").json()["canali"]] == ["Gatti"]

        r = client.post("/api/canale/video", json={"path": cartella, "nome": "Micio", "preset": "9:16"})
        assert r.status_code == 200, r.text
        assert r.json()["canale"]["name"] == "Gatti"
        assert client.get("/api/project").json()["canale"]["path"] == cartella

        r = client.put("/api/canale", json={"path": cartella, "descrizione": "gatti buffi"})
        assert r.json()["description"] == "gatti buffi"
        r = client.put("/api/canale/memoria", json={"path": cartella, "testo": "## tono\n- leggero\n"})
        assert "leggero" in r.json()["memoria"]

        logo = _png(tmp_path / "logo.png")
        r = client.post("/api/canale/riferimenti", json={"path": cartella, "files": [logo]})
        assert [x["file"] for x in r.json()["riferimenti"]] == ["logo.png"]
        with open(logo, "rb") as f:
            r = client.post("/api/canale/riferimenti/carica", data={"path": cartella},
                            files=[("files", ("trascinata.png", f, "image/png"))])
        assert r.status_code == 200, r.text
        assert len(r.json()["riferimenti"]) == 2
        r = client.put("/api/canale/riferimento", json={"path": cartella, "file": "logo.png",
                                                        "nota": "in alto a destra"})
        assert r.json()["riferimenti"][0]["nota"] == "in alto a destra"
        r = client.get("/api/canale/immagine", params={"path": cartella, "file": "logo.png"})
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert client.get("/api/canale/immagine",
                          params={"path": cartella, "file": "../canale.json"}).status_code == 400
        r = client.delete("/api/canale/riferimento", params={"path": cartella, "file": "logo.png"})
        assert [x["file"] for x in r.json()["riferimenti"]] == ["trascinata.png"]

        info = client.get("/api/canale", params={"path": cartella}).json()
        assert [v["name"] for v in info["video"]] == ["Micio"]
        # un file rifiutato non e' un errore del server
        with open(tmp_path / "nota.txt", "w") as f:
            f.write("x")
        with open(tmp_path / "nota.txt", "rb") as f:
            r = client.post("/api/canale/riferimenti/carica", data={"path": cartella},
                            files=[("files", ("nota.txt", f, "text/plain"))])
        assert r.status_code == 400
        assert client.delete("/api/canali", params={"path": cartella}).json()["canali"] == []
    api_mod.S.store = None
