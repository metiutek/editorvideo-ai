"""I file dei progetti: duplicare, rinominare, spostare, eliminare e ripristinare.

Un progetto viaggia coi suoi compagni (chat, piano, istantanee); i media
restano dove sono, tranne quando il video ha una cartella tutta sua: allora la
cartella si sposta intera e i percorsi nel documento la seguono.
"""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import mcp_server as srv
from vedit import progetti, raccolte, versions
from vedit.model import Media
from vedit.store import Store


@pytest.fixture(autouse=True)
def _isolati(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("VEDIT_MEMORIA", str(tmp_path / "MEMORIA.md"))
    srv._stores.clear()
    srv._current[0] = None
    api_mod.S.store = None
    yield
    api_mod.S.store = None


def _progetto(path: Path, nome: str, media: Path | None = None) -> Store:
    s = Store.create(nome, path=str(path))
    if media is not None:
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"x")
        s.project.media.append(Media(id="m1", path=str(media), kind="image"))
        s.save()
    return s


def _media(path: str) -> str:
    return json.loads(Path(path).read_text(encoding="utf-8"))["media"][0]["path"]


def test_duplica(tmp_path):
    girato = tmp_path / "girato" / "a.png"
    f = tmp_path / "lavori" / "Gita.json"
    _progetto(f, "Gita", girato)
    f.with_name("Gita.chat.json").write_text('{"vista": [1]}', encoding="utf-8")

    out = progetti.duplica(str(f))
    copia = Path(out["path"])
    assert copia == f.with_name("Gita copy.json") and out["name"] == "Gita copy"
    assert _media(str(copia)) == str(girato)          # stessi media, niente copie di girato
    assert not copia.with_name("Gita copy.chat.json").exists()   # la conversazione riparte
    assert Path(progetti.duplica(str(f))["path"]).name == "Gita copy 2.json"
    assert progetti.duplica(str(f), "Gita lunga")["name"] == "Gita lunga"

    # un video con la cartella sua: la copia ha la sua cartella accanto
    c = raccolte.crea("Famiglia", str(tmp_path / "famiglia"))
    v = Path(raccolte.percorso_video(c["path"], "Natale"))
    _progetto(v, "Natale")
    out = progetti.duplica(str(v))
    assert Path(out["path"]) == Path(c["path"]) / "Natale copy" / "Natale copy.json"
    assert out["raccolta"]["name"] == "Famiglia"
    # dentro una raccolta
    out = progetti.duplica(str(f), raccolta="Famiglia")
    assert Path(out["path"]).parent.parent == Path(c["path"])


def test_rinomina(tmp_path):
    f = tmp_path / "Bozza.json"
    s = _progetto(f, "Bozza")
    f.with_name("Bozza.chat.json").write_text("{}", encoding="utf-8")
    versions.snapshot(s, "prima")
    out = progetti.rinomina(str(f), "Vacanze 2026")
    nuovo = Path(out["path"])
    assert nuovo == tmp_path / "Vacanze 2026.json" and not f.exists()
    assert nuovo.with_name("Vacanze 2026.chat.json").is_file()
    assert (tmp_path / "Vacanze 2026.versioni" / "prima.json").is_file()
    assert Store.open(str(nuovo)).project.name == "Vacanze 2026"

    # video con la cartella sua: la cartella cambia nome e i media la seguono
    c = raccolte.crea("Viaggi", str(tmp_path / "viaggi"))
    v = Path(raccolte.percorso_video(c["path"], "Video 1"))
    sv = _progetto(v, "Video 1", v.parent / "media" / "foto.png")
    versions.snapshot(sv, "uno")
    out = progetti.rinomina(str(v), "Roma")
    r = Path(c["path"]) / "Roma" / "Roma.json"
    assert Path(out["path"]) == r and not v.parent.exists()
    assert _media(str(r)) == str(r.parent / "media" / "foto.png")
    assert Path(_media(str(r.parent / "Roma.versioni" / "uno.json"))) == r.parent / "media" / "foto.png"
    assert [x["name"] for x in raccolte.video(c["path"])] == ["Roma"]   # le istantanee non sono video

    # nome del file occupato: cambia solo il nome mostrato
    _progetto(tmp_path / "Occupato.json", "Occupato")
    out = progetti.rinomina(str(nuovo), "Occupato")
    assert Path(out["path"]) == nuovo and out["name"] == "Occupato"
    with pytest.raises(progetti.ProgettoError, match="empty"):
        progetti.rinomina(str(nuovo), "  ")


def test_rinomina_il_progetto_aperto(tmp_path):
    f = tmp_path / "Aperto.json"
    s = _progetto(f, "Aperto")
    out = progetti.rinomina(str(f), "Chiuso no", store=s)
    assert s.path == out["path"] and s.project.name == "Chiuso no"
    s.rename("ancora")          # lo Store aperto salva nel file nuovo, non ricrea il vecchio
    assert not f.exists() and Store.open(out["path"]).project.name == "ancora"


def test_sposta(tmp_path):
    girato = tmp_path / "girato" / "a.png"
    f = tmp_path / "sciolti" / "Matrimonio.json"
    _progetto(f, "Matrimonio", girato)
    f.with_name("Matrimonio.piano.json").write_text("{}", encoding="utf-8")
    a = raccolte.crea("Clienti", str(tmp_path / "clienti"))
    out = progetti.sposta(str(f), raccolta="Clienti")
    dest = Path(a["path"]) / "Matrimonio" / "Matrimonio.json"
    assert Path(out["path"]) == dest and out["raccolta"]["name"] == "Clienti"
    assert dest.with_name("Matrimonio.piano.json").is_file() and not f.exists()
    assert _media(str(dest)) == str(girato)            # i media fuori restano dove sono
    with pytest.raises(progetti.ProgettoError, match="already"):
        progetti.sposta(str(dest), raccolta="Clienti")

    # da una raccolta all'altra: la cartella intera, media compresi
    (dest.parent / "media").mkdir()
    (dest.parent / "media" / "b.png").write_bytes(b"y")
    b = raccolte.crea("Archivio", str(tmp_path / "archivio"))
    out = progetti.sposta(str(dest), raccolta="Archivio")
    finale = Path(b["path"]) / "Matrimonio" / "Matrimonio.json"
    assert Path(out["path"]) == finale and (finale.parent / "media" / "b.png").is_file()
    assert not dest.parent.exists()

    # in una cartella qualunque
    out = progetti.sposta(str(finale), cartella=str(tmp_path / "fuori"))
    assert Path(out["path"]) == tmp_path / "fuori" / "Matrimonio" / "Matrimonio.json"
    assert out["raccolta"] is None
    with pytest.raises(progetti.ProgettoError, match="collection= .* or folder="):
        progetti.sposta(out["path"])


def test_elimina_e_ripristina(tmp_path):
    c = raccolte.crea("Famiglia", str(tmp_path / "famiglia"))
    v = Path(raccolte.percorso_video(c["path"], "Compleanno"))
    _progetto(v, "Compleanno", v.parent / "media" / "torta.png")
    v.with_name("Compleanno.chat.json").write_text("{}", encoding="utf-8")

    out = progetti.elimina(str(v))
    assert not v.exists() and not v.with_name("Compleanno.chat.json").exists()
    assert out["restano"] == str(v.parent)               # i media non si toccano
    assert (v.parent / "media" / "torta.png").is_file()
    assert raccolte.video(c["path"]) == []
    voci = progetti.cestino()
    assert [(x["name"], x["raccolta"]) for x in voci] == [("Compleanno", "Famiglia")]

    out = progetti.ripristina(voci[0]["id"])
    assert Path(out["path"]) == v and v.with_name("Compleanno.chat.json").is_file()
    assert progetti.cestino() == []
    with pytest.raises(progetti.ProgettoError, match="trash"):
        progetti.ripristina(voci[0]["id"])

    # un progetto senza media: la cartella vuota se ne va
    w = Path(raccolte.percorso_video(c["path"], "Vuoto"))
    _progetto(w, "Vuoto")
    assert progetti.elimina(str(w))["restano"] is None and not w.parent.exists()
    # torna accanto se nel frattempo il posto e' preso
    _progetto(w, "Vuoto bis")
    out = progetti.ripristina(progetti.cestino()[0]["id"])
    assert Path(out["path"]) == w.with_name("Vuoto 2.json")

    # svuotare, e il cestino che si pulisce da solo
    x = tmp_path / "x.json"
    _progetto(x, "x")
    vid = progetti.elimina(str(x))["id"]
    assert progetti.svuota(vid) == {"cancellati": 1} and progetti.cestino() == []
    _progetto(x, "x")
    voce = progetti.elimina(str(x))
    f = progetti._cestino() / voce["id"] / "voce.json"
    vecchia = json.loads(f.read_text(encoding="utf-8"))
    vecchia["quando"] = time.time() - (progetti.GIORNI_CESTINO + 1) * 86400
    f.write_text(json.dumps(vecchia), encoding="utf-8")
    assert progetti.cestino() == [] and not f.exists()
    with pytest.raises(progetti.ProgettoError, match="not found"):
        progetti.elimina(str(x))


def test_video_nuovo_senza_titolo(tmp_path):
    c = raccolte.crea("TikTok", str(tmp_path / "tiktok"))
    assert raccolte.nome_nuovo(c["path"]) == "Video 1"
    _progetto(Path(raccolte.percorso_video(c["path"], "Video 1")), "Video 1")
    assert raccolte.nome_nuovo(c["path"]) == "Video 2"
    # una cartella rimasta con i media di un video eliminato non si riusa
    (Path(c["path"]) / "Video 2" / "media").mkdir(parents=True)
    assert raccolte.nome_nuovo(c["path"]) == "Video 3"
    raccolte.ricorda_formato(c["path"], "9:16", 1080)
    assert raccolte.info(c["path"])["formato"] == {"preset": "9:16", "size": 1080}

    out = srv.project_create(collection="TikTok")
    assert Path(out["path"]).name == "Video 3.json"


def test_api(tmp_path):
    with TestClient(api_mod.app) as client:
        c = client.post("/api/raccolte", json={"nome": "Corso", "cartella": str(tmp_path / "corso")}).json()
        r = client.post("/api/raccolta/video", json={"path": c["path"], "preset": "9:16"})
        assert r.status_code == 200, r.text
        aperto = r.json()["path"]
        assert Path(aperto).name == "Video 1.json"
        assert client.get("/api/raccolta", params={"path": c["path"]}).json()["formato"]["preset"] == "9:16"

        # rinominare il progetto aperto: l'editor lo segue
        r = client.post("/api/progetto/rinomina", json={"path": aperto, "nome": "Lezione 1"})
        assert r.status_code == 200, r.text
        nuovo = r.json()["path"]
        assert r.json()["aperto"] == nuovo and Path(nuovo).name == "Lezione 1.json"
        assert client.get("/api/project").json()["project"]["name"] == "Lezione 1"
        assert r.json()["recenti"][0] == {**r.json()["recenti"][0], "path": nuovo, "name": "Lezione 1"}

        r = client.post("/api/progetto/duplica", json={"path": nuovo})
        assert r.status_code == 200, r.text
        copia = r.json()["path"]
        assert r.json()["name"] == "Lezione 1 copy" and r.json()["aperto"] == nuovo

        r = client.post("/api/progetto/sposta", json={"path": copia, "cartella": str(tmp_path / "altrove")})
        assert r.status_code == 200, r.text
        assert r.json()["raccolta"] is None

        # eliminare quello aperto lo chiude
        r = client.delete("/api/progetto", params={"path": nuovo})
        assert r.status_code == 200, r.text
        assert r.json()["aperto"] is None and client.get("/api/project").json()["project"] is None
        assert nuovo not in [x["path"] for x in r.json()["recenti"]]
        voci = client.get("/api/progetti/cestino").json()
        assert [v["name"] for v in voci] == ["Lezione 1"]
        r = client.post("/api/progetti/cestino/ripristina", json={"id": voci[0]["id"]})
        assert r.status_code == 200 and r.json()["path"] == nuovo
        assert client.post("/api/progetti/cestino/ripristina", json={"id": "no"}).status_code == 400

        client.post("/api/project/open", json={"path": nuovo})
        assert client.post("/api/project/close").json()["project"] is None
        assert client.delete("/api/progetti/cestino").json()["cancellati"] == 0


def test_mcp(tmp_path):
    c = raccolte.crea("Serie", str(tmp_path / "serie"))
    out = srv.project_create(collection="Serie", name="Puntata 1")
    p = out["path"]
    r = srv.project_manage("rename", name="Pilota")
    assert Path(r["path"]).name == "Pilota.json"
    assert srv._percorso_corrente() == r["path"]        # il progetto corrente lo segue
    srv.add_text(text="ciao", start=0, duration=1)       # e si continua a montare
    assert Store.open(r["path"]).project.tracks
    d = srv.project_manage("duplicate")
    assert d["name"] == "Pilota copy" and srv._percorso_corrente() == r["path"]
    e = srv.project_manage("delete", project=d["path"])
    assert [v["id"] for v in srv.project_manage("trash")] == [e["id"]]
    assert srv.project_manage("restore", id=e["id"])["name"] == "Pilota copy"
    with pytest.raises(Exception, match="unknown action"):
        srv.project_manage("burn")
    srv.project_manage("delete")
    with pytest.raises(Exception, match="no project"):
        srv.project_manage("rename", name="x")
    assert not Path(p).exists() and Path(c["path"]).is_dir()
