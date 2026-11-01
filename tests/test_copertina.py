"""Copertina fatta a parte: si imposta, si misura, si salva, non entra nel render."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vedit import api as api_mod
from vedit import mcp_server as srv
from vedit.store import EditError, Store


def _immagine(path, w, h):
    Image.new("RGB", (w, h), (200, 40, 40)).save(path)
    return str(path)


def test_copertina_impostata_salvata_e_tolta(tmp_path):
    s = Store.create(preset="1080p", path=str(tmp_path / "p.json"))
    info = s.set_cover(_immagine(tmp_path / "c.png", 1280, 720))
    assert info["width"] == 1280 and info["format"] == "16:9"
    assert "warnings" not in info
    assert s.summary()["cover"] == info["cover"]

    s.save()
    assert Store.open(str(tmp_path / "p.json")).project.cover == info["cover"]

    s.undo()
    assert not s.project.cover
    s.redo()
    s.set_cover("")
    assert "cover" not in s.summary()


def test_copertina_avvisi(tmp_path):
    s = Store.create(preset="1080p", path=str(tmp_path / "p.json"))
    info = s.set_cover(_immagine(tmp_path / "q.png", 400, 400))
    testo = " ".join(info["warnings"])
    assert "1:1" in testo and "16:9" in testo   # proporzione diversa dal video
    assert "640" in testo                       # troppo piccola per YouTube


def test_copertina_rifiutata(tmp_path):
    s = Store.create(preset="1080p", path=str(tmp_path / "p.json"))
    with pytest.raises(EditError, match="not found"):
        s.set_cover(str(tmp_path / "manca.png"))
    (tmp_path / "x.txt").write_text("no")
    with pytest.raises(EditError, match="image"):
        s.set_cover(str(tmp_path / "x.txt"))
    assert not s.project.cover


@pytest.mark.anyio
async def test_copertina_da_mcp(tmp_path):
    assert "set_cover" in {t.name for t in await srv.mcp.list_tools()}
    p = str(tmp_path / "p.json")
    srv.project_create(p, preset="vertical")
    info = srv.set_cover(_immagine(tmp_path / "v.png", 1080, 1920), project=p)
    assert info["format"] == "9:16" and "warnings" not in info


def test_copertina_da_api(tmp_path):
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "1080p"})
        assert c.get("/api/cover").json() == {}
        img = _immagine(tmp_path / "c.jpg", 1280, 720)
        r = c.post("/api/op/set_cover", json={"path": img})
        assert r.status_code == 200 and r.json()["project"]["cover"]
        info = c.get("/api/cover").json()
        assert info["width"] == 1280 and info["mtime"] > 0


def test_opzioni_di_copertina(tmp_path):
    s = Store.create(preset="1080p", path=str(tmp_path / "p.json"))
    a, b = _immagine(tmp_path / "a.png", 1280, 720), _immagine(tmp_path / "b.png", 1280, 720)
    with pytest.raises(EditError, match="not found"):
        s.add_covers([a, str(tmp_path / "manca.png")])
    assert s.project.covers == []                # tutte o nessuna

    s.add_covers([a, b])
    assert not s.project.cover and len(s.project.covers) == 2
    s.set_cover(b)
    assert s.project.cover.endswith("b.png") and len(s.project.covers) == 2
    s.set_cover("")
    assert len(s.project.covers) == 2            # togliere la scelta non toglie le opzioni

    s.set_cover(a)
    s.remove_cover(a)
    assert not s.project.cover and [x.endswith("b.png") for x in s.project.covers] == [True]
    s.undo()
    assert s.project.cover.endswith("a.png")
    assert Store.open(str(tmp_path / "p.json")).project.covers == s.project.covers


def test_titolo_e_punteggio():
    from vedit import copertine
    nero = Image.new("RGB", (640, 360), (0, 0, 0))
    righe = Image.new("RGB", (640, 360), (40, 120, 200))
    for x in range(0, 640, 16):
        Image.Image.paste(righe, (240, 200, 40), (x, 0, x + 8, 360))
    assert copertine.punteggio(nero) == 0
    assert copertine.punteggio(righe) > copertine.punteggio(Image.new("RGB", (640, 360), (40, 120, 200)))

    for dove in copertine.POSIZIONI:
        img = copertine.con_titolo(righe, "A long title that has to wrap on two lines", dove)
        assert img.size == righe.size and img.tobytes() != righe.tobytes()

    tratti = copertine.istanti(60, 6)
    assert len(tratti) == 6 and all(len(t) == copertine.PROVE for t in tratti)
    piatti = [t for tr in tratti for t in tr]
    assert piatti == sorted(piatti) and 0 < piatti[0] and piatti[-1] < 60


def test_download_della_copertina(tmp_path):
    img = _immagine(tmp_path / "c.png", 64, 36)
    with TestClient(api_mod.app) as c:
        r = c.get("/api/file", params={"path": img, "download": "true"})
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        assert "c.png" in r.headers["content-disposition"]
        assert "attachment" not in c.get("/api/file", params={"path": img}).headers.get(
            "content-disposition", "")


@pytest.mark.slow
def test_copertine_dal_montaggio(assets, tmp_path):
    s = Store.create(preset="1080p", path=str(tmp_path / "p.json"))
    with pytest.raises(EditError, match="empty"):
        s.make_covers(3)
    m = s.import_media([assets["red"], assets["blue"]])
    s.add_clip(m[0].id, start=0, duration=3)
    s.add_clip(m[1].id, start=3, duration=3)

    fatte = s.make_covers(3, title="Hello covers", choose=True)
    assert len(fatte) == 3 and s.project.cover == fatte[0]["path"]
    assert [f["path"] for f in fatte] == s.project.covers
    assert Path(fatte[0]["path"]).parent.name == "p_covers"
    for f in fatte:
        with Image.open(f["path"]) as im:
            assert im.size == (1920, 1080)
    # il tratto del testsrc vince sul rosso pieno: piu' dettaglio
    assert fatte[-1]["t"] > 3

    # di nuovo: file nuovi, non sovrascritti
    altre = s.make_covers(1)
    assert altre[0]["path"] not in [f["path"] for f in fatte]


@pytest.mark.anyio
async def test_copertine_da_mcp(tmp_path):
    names = {t.name for t in await srv.mcp.list_tools()}
    assert {"make_covers", "add_covers"} <= names
    p = str(tmp_path / "p.json")
    srv.project_create(p, preset="1080p")
    a = _immagine(tmp_path / "a.png", 1280, 720)
    assert srv.add_covers([a], choose=True, project=p)["cover"] == str(Path(a).resolve())
    out = srv.add_covers([a], remove=True, project=p)
    assert out == {"covers": [], "cover": ""}
