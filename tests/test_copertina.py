"""Copertina fatta a parte: si imposta, si misura, si salva, non entra nel render."""

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
