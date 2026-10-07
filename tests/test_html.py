"""Clip html: documento, orologio virtuale, rasterizzazione e anteprima dal vivo."""

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import htmlclip
from vedit import mcp_server as srv
from vedit.graph import CompileOptions, compile_project
from vedit.store import EditError, Store

PAGINA = "<!doctype html><html><head><title>x</title></head><body><p>ciao</p></body></html>"


# --------------------------------------------------------------------------
# documento
# --------------------------------------------------------------------------


def test_orologio_dentro_head_e_dopo_il_doctype():
    """Prima del doctype la pagina andrebbe in quirks mode e impaginerebbe diversa."""
    doc = htmlclip.compose(PAGINA, 25)
    assert doc.lower().startswith("<!doctype html>")
    testa = doc.index("<head>")
    assert testa < doc.index("window.__vedit") < doc.index("<title>")
    assert "const FPS = 25.0" in doc


def test_orologio_anche_su_un_frammento():
    doc = htmlclip.compose("<div>solo un pezzo</div>", 30)
    assert doc.startswith("<!doctype html><html><head>")
    assert "window.__vedit" in doc and "<div>solo un pezzo</div>" in doc


def test_base_href_per_i_percorsi_relativi():
    doc = htmlclip.compose(PAGINA, 30, '/api/html/c1/files/')
    assert '<base href="/api/html/c1/files/">' in doc


def test_frame_range():
    assert htmlclip.frame_range(2.0, 30) == (0, 60)
    # un solo fotogramma a meta' clip: si fotografa solo quel pezzetto
    da, a = htmlclip.frame_range(2.0, 30, 1.0, 1.05)
    assert da == 30 and 31 <= a <= 33
    assert htmlclip.frame_range(0.01, 30) == (0, 1)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


def test_add_html_di_esempio_e_da_file(tmp_path):
    s = Store.create("t", "720p")
    c = s.add_html(start=1, duration=3)
    assert c.type == "html" and "<body>" in c.html and c.html_base is None
    # il modello parte con le misure del progetto
    assert "1280px" in c.html

    f = tmp_path / "grafica" / "titolo.html"
    f.parent.mkdir()
    f.write_text(PAGINA, encoding="utf-8")
    d = s.add_html(path=str(f), duration=2)
    assert d.html == PAGINA
    assert d.html_base == str(f.parent.resolve())
    assert d.name == "titolo"


def test_add_html_rifiuta_l_impossibile(tmp_path):
    s = Store.create("t", "720p")
    with pytest.raises(EditError):
        s.add_html(html=PAGINA, path=str(tmp_path / "x.html"))
    with pytest.raises(EditError):
        s.add_html(path=str(tmp_path / "non-esiste.html"))
    with pytest.raises(EditError):
        s.add_html(html="   ")
    with pytest.raises(EditError):
        s.add_html(html=PAGINA, track_id="A1")
    # la velocita' di una grafica la decide la sua animazione
    c = s.add_html(html=PAGINA)
    with pytest.raises(EditError):
        s.set_speed(c.id, 2.0)


def test_set_html_e_undo():
    s = Store.create("t", "720p")
    c = s.add_html(html=PAGINA)
    s.set_html(c.id, html="<p>nuova</p>")
    assert s.project.clip(c.id).html == "<p>nuova</p>"
    s.undo()
    assert s.project.clip(c.id).html == PAGINA
    t = s.add_text("x")
    with pytest.raises(EditError):
        s.set_html(t.id, html=PAGINA)


def test_riepilogo_porta_il_documento_alla_ui():
    s = Store.create("t", "720p")
    c = s.add_html(html=PAGINA)
    full = s.summary("full")["tracks"][0]["clips"][0]
    assert full["type"] == "html" and full["html"] == PAGINA
    corto = s.summary()["tracks"][0]["clips"][0]
    assert "caratteri" in corto["html"]
    assert c.id == full["id"]


def test_salvato_e_riaperto(tmp_path):
    p = tmp_path / "p.json"
    s = Store.create("t", "720p", path=str(p))
    c = s.add_html(html=PAGINA, start=2)
    r = Store.open(str(p))
    assert r.project.clip(c.id).html == PAGINA
    assert r.project.clip(c.id).type == "html"


# --------------------------------------------------------------------------
# grafo
# --------------------------------------------------------------------------


def _progetto_con_html():
    s = Store.create("t", "720p")
    s.add_color("blue", duration=4)
    v2 = s.add_track("video")
    c = s.add_html(html=PAGINA, track_id=v2.id, start=1, duration=2)
    return s, c


def test_grafo_usa_il_file_rasterizzato():
    s, c = _progetto_con_html()
    comp = compile_project(s.project, CompileOptions(html_files={c.id: ("grafica.mov", 0.0)}))
    assert "grafica.mov" in comp.inputs
    # la grafica sta sopra e parte al suo istante
    assert "tpad=start_duration=1" in comp.filtergraph


def test_grafo_nei_segmenti_salta_solo_la_differenza():
    """Nel fotogramma singolo il file parte gia' a meta' clip."""
    s, c = _progetto_con_html()
    comp = compile_project(s.project, CompileOptions(
        start=2.0, end=2.1, html_files={c.id: ("pezzo.mov", 0.9)}))
    i = comp.inputs.index("pezzo.mov")
    assert comp.inputs[i - 5:i - 3] == ["-ss", "0.1"]


def test_grafo_senza_rasterizzazione_lo_dice():
    s, c = _progetto_con_html()
    comp = compile_project(s.project, CompileOptions())
    assert any("html non rasterizzato" in w for w in comp.warnings)


# --------------------------------------------------------------------------
# API dell'anteprima dal vivo
# --------------------------------------------------------------------------


@pytest.fixture
def client():
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        yield c


def test_api_documento_e_file(client, tmp_path):
    cartella = tmp_path / "grafica"
    cartella.mkdir()
    (cartella / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "segreto.txt").write_text("no", encoding="utf-8")
    pagina = cartella / "t.html"
    pagina.write_text(PAGINA, encoding="utf-8")

    client.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
    r = client.post("/api/op/add_html", json={"path": str(pagina), "duration": 2})
    assert r.status_code == 200, r.text
    cid = r.json()["result"]["id"]

    doc = client.get(f"/api/html/{cid}")
    assert doc.status_code == 200
    assert "window.__vedit" in doc.text
    assert f'<base href="/api/html/{cid}/files/">' in doc.text

    assert client.get(f"/api/html/{cid}/files/logo.svg").text == "<svg/>"
    # fuori dalla cartella della clip non si legge niente
    assert client.get(f"/api/html/{cid}/files/..%2Fsegreto.txt").status_code == 404
    assert client.get(f"/api/html/{cid}/files/../segreto.txt").status_code == 404
    assert client.get("/api/html/inesistente").status_code == 404


def test_api_origine_null_solo_in_lettura_html(tmp_path):
    """L'iframe in sandbox ha Origin "null": puo' leggere i suoi file e basta."""
    api_mod.S.store = None
    api_mod._consenti_host("127.0.0.1")
    try:
        with TestClient(api_mod.app, base_url="http://127.0.0.1:8760") as c:
            c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
            cid = c.post("/api/op/add_html", json={"html": PAGINA}).json()["result"]["id"]
            nulla = {"origin": "null"}
            assert c.get(f"/api/html/{cid}", headers=nulla).status_code == 200
            assert c.get("/api/recenti", headers=nulla).status_code == 403
            assert c.post("/api/op/undo", json={}, headers=nulla).status_code == 403
            # il nome host conta anche per l'iframe
            assert c.get(f"/api/html/{cid}", headers={**nulla, "host": "evil.example"}).status_code == 403
    finally:
        api_mod._host_consentiti.clear()
        api_mod.S.store = None


# --------------------------------------------------------------------------
# MCP
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_strumenti_mcp():
    nomi = {t.name for t in await srv.mcp.list_tools()}
    assert {"add_html", "set_html"} <= nomi
    assert "add_html" in srv.ISTRUZIONI


# --------------------------------------------------------------------------
# rasterizzazione vera (Chromium)
# --------------------------------------------------------------------------


def _browser_o_salta():
    pytest.importorskip("playwright")


ANIMATA = """<!doctype html><html><head><style>
body { width: 320px; height: 180px; }
#css { position: absolute; left: 0; top: 0; width: 20px; height: 20px; background: rgb(255,0,0);
       animation: va 1s linear forwards; }
@keyframes va { from { left: 0px } to { left: 200px } }
#js { position: absolute; left: 0; top: 100px; width: 20px; height: 20px; background: rgb(0,0,255); }
#tardi { display: none; position: absolute; left: 280px; top: 140px; width: 20px; height: 20px;
         background: rgb(0,255,0); }
</style></head><body>
<div id="css"></div><div id="js"></div><div id="tardi"></div>
<script>
  let n = 0;
  function giro() { n++; document.getElementById('js').style.left = n + 'px'; requestAnimationFrame(giro); }
  requestAnimationFrame(giro);
  setTimeout(() => { document.getElementById('tardi').style.display = 'block'; }, 500);
</script></body></html>"""


def _pixel(path, t, x, y):
    """Colore e alpha del fotogramma al tempo t del .mov rasterizzato."""
    import subprocess

    from PIL import Image

    from vedit import ffmpeg

    out = path + f".{t}.png"
    subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-y", "-ss", str(t), "-i", path,
                    "-frames:v", "1", "-pix_fmt", "rgba", out], check=True)
    return Image.open(out).convert("RGBA").getpixel((x, y))


@pytest.mark.slow
def test_rasterizza_con_tempo_virtuale():
    """CSS, rAF e setTimeout arrivano tutti allo stesso istante, sfondo trasparente."""
    _browser_o_salta()
    try:
        mov, t0 = htmlclip.rasterize(ANIMATA, base=None, duration=1.0, width=320, height=180,
                                     fps=10, page_w=320, page_h=180)
    except htmlclip.HtmlNonDisponibile as exc:
        pytest.skip(str(exc))
    assert t0 == 0.0
    # sfondo: trasparente
    assert _pixel(mov, 0.5, 160, 60)[3] == 0
    # a 0.5s l'animazione CSS e' a meta' strada: 100px
    assert _pixel(mov, 0.5, 110, 10)[:3] == pytest.approx((255, 0, 0), abs=8)
    assert _pixel(mov, 0.5, 60, 10)[3] == 0
    # rAF: un giro per fotogramma, 5 fotogrammi a 0.5s
    assert _pixel(mov, 0.5, 14, 110)[:3] == pytest.approx((0, 0, 255), abs=8)
    # setTimeout a 500ms: c'e' a 0.5s e non a 0.4s
    assert _pixel(mov, 0.4, 290, 150)[3] == 0
    assert _pixel(mov, 0.5, 290, 150)[:3] == pytest.approx((0, 255, 0), abs=8)

    # stessa grafica, stesso file: la cache non riapre il browser
    assert htmlclip.rasterize(ANIMATA, base=None, duration=1.0, width=320, height=180,
                              fps=10, page_w=320, page_h=180)[0] == mov


@pytest.mark.slow
def test_render_compone_la_grafica_sopra(tmp_path):
    _browser_o_salta()
    from PIL import Image

    from vedit import render

    s = Store.create("t", "720p")
    s.project.settings.width, s.project.settings.height = 320, 180
    s.add_color("blue", duration=1)
    v2 = s.add_track("video")
    s.add_html(html=ANIMATA, track_id=v2.id, duration=1)
    out = tmp_path / "f.png"
    try:
        render.render_frame(s.project, 0.5, str(out), width=320, use_proxy=False)
    except htmlclip.HtmlNonDisponibile as exc:
        pytest.skip(str(exc))
    im = Image.open(out).convert("RGB")
    r, g, b = im.getpixel((110, 10))
    assert r > 200 and b < 60          # la grafica
    r, g, b = im.getpixel((160, 60))
    assert b > 200 and r < 60          # il colore sotto, dove la pagina e' vuota
