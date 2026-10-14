"""Scope grafici: waveform, parade, vettorscopio, istogramma del fotogramma sotto la testina."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vedit import api as api_mod
from vedit import mcp_server as srv
from vedit import review
from vedit.store import Store


def _rosso() -> Store:
    s = Store.create("sc", "720p")
    s.add_color("#ff0000", duration=2)
    return s


@pytest.mark.parametrize("vista, misura", [
    ("waveform", (512, 256)), ("parade", (768, 256)),
    ("vectorscope", (360, 360)), ("histogram", (512, 200)),
])
def test_ogni_scope_esce_della_sua_misura(tmp_path, vista, misura):
    p = review.scope_immagine(_rosso().project, 1.0, vista, str(tmp_path / f"{vista}.png"))
    assert Image.open(p).size == misura


def test_parade_di_un_rosso_pieno(tmp_path):
    """Rosso puro: la colonna R sta in alto, la B in fondo."""
    p = review.scope_immagine(_rosso().project, 1.0, "parade", str(tmp_path / "p.png"))
    a = np.asarray(Image.open(p).convert("RGB")).astype(int)
    h, terzo = a.shape[0], a.shape[1] // 3
    r = a[:, :terzo]
    ys = np.nonzero((r[..., 0] > 150) & (r[..., 1] < 100))[0]
    assert ys.size and ys.mean() < h * 0.25
    b = a[:, 2 * terzo:]
    ys = np.nonzero((b[..., 2] > 150) & (b[..., 0] < 100))[0]
    assert ys.size and ys.mean() > h * 0.75


def test_istogramma_di_un_rosso_pieno(tmp_path):
    p = review.scope_immagine(_rosso().project, 1.0, "histogram", str(tmp_path / "h.png"))
    a = np.asarray(Image.open(p).convert("RGB")).astype(int)
    # la linea rossa tocca la cima solo all'estremo destro (livello 255)
    cima = a[:8]
    rossi = np.nonzero((cima[..., 0] > 200) & (cima[..., 1] < 120))[1]
    assert rossi.size and rossi.min() > a.shape[1] * 0.9


def test_scope_sconosciuto(tmp_path):
    with pytest.raises(ValueError, match="scope sconosciuto"):
        review.scope_immagine(_rosso().project, 1.0, "falsi colori", str(tmp_path / "x.png"))


def test_api_scope(tmp_path):
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
        assert c.get("/api/scope?t=0&view=waveform").status_code == 400   # timeline vuota
        c.post("/api/op/add_color", json={"color": "#336699", "duration": 2})
        r = c.get("/api/scope?t=1&view=vectorscope")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert c.get("/api/scope?t=1&view=boh").status_code == 400


@pytest.mark.anyio
async def test_scope_image_dall_agente():
    nomi = {t.name for t in await srv.mcp.list_tools()}
    assert {"scope_image", "color_scopes"} <= nomi
