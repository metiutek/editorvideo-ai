"""Blocchi grafici pronti (blocchi.py, add_block): ogni blocco si compone, i parametri
sono controllati, un testo non diventa mai HTML, e in Chromium si vedono davvero."""

import pytest

from vedit import blocchi, htmlclip
from vedit import mcp_server as srv
from vedit.store import EditError, Store
from test_html import _browser_o_salta, _pixel
from test_mcp import call


@pytest.mark.parametrize("nome", list(blocchi.BLOCCHI))
def test_ogni_blocco_si_compone_coi_default(nome):
    doc, durata = blocchi.documento(nome, None)
    assert doc.startswith("<!doctype html>") and "{{" not in doc
    assert durata == blocchi.BLOCCHI[nome]["durata"]
    # misure relative: stesso aspetto in 16:9, 9:16 e 1:1
    assert "vw" in doc or "vh" in doc


def test_la_durata_scelta_entra_nell_uscita():
    doc, durata = blocchi.documento("lower_third", {"nome": "Ada"}, 7.5)
    assert durata == 7.5 and "calc(7.5s - .4s)" in doc


def test_un_testo_non_diventa_html():
    doc, _ = blocchi.documento("lower_third", {"nome": "<script>alert(1)</script>",
                                               "ruolo": "a & b \"c\""})
    assert "<script>" not in doc and "&lt;script&gt;" in doc
    assert "a &amp; b &quot;c&quot;" in doc


def test_errori_con_l_elenco_di_quelli_ammessi():
    with pytest.raises(ValueError, match="unknown block 'lampo'.*lower_third"):
        blocchi.documento("lampo", None)
    with pytest.raises(ValueError, match="unknown parameters for title: tinta.*allowed: font"):
        blocchi.documento("title", {"tinta": "red"})
    with pytest.raises(ValueError, match="must be a color"):
        blocchi.documento("title", {"colore": "red; background:url(x)"})
    with pytest.raises(ValueError, match="allowed: bottom, top"):
        blocchi.documento("caption_pill", {"posizione": "centro"})
    with pytest.raises(ValueError, match="out of range"):
        blocchi.documento("highlight_box", {"x": 140})
    with pytest.raises(ValueError, match="too long"):
        blocchi.documento("title", {"titolo": "x" * 500})
    with pytest.raises(ValueError, match="font cannot contain"):
        blocchi.documento("title", {"font": "a;} body{display:none"})
    with pytest.raises(ValueError, match="duration must be > 0"):
        blocchi.documento("title", None, 0)


def test_grafico_a_barre_e_parole():
    doc, _ = blocchi.documento("bar_chart", {"dati": "Mele:40, Pere: 75, Kiwi:20", "titolo": "Frutta"})
    assert doc.count('<div class="r"') == 3 and "width:100.0%" in doc and "width:53.3%" in doc
    for male in ("Mele", "A:b:c"):
        with pytest.raises(ValueError):
            blocchi.documento("bar_chart", {"dati": male})
    with pytest.raises(ValueError, match="between 1 and 10"):
        blocchi.documento("bar_chart", {"dati": ",".join(f"v{i}:1" for i in range(11))})
    k, _ = blocchi.documento("kinetic_words", {"testo": "Fallo *muovere* adesso"})
    assert k.count("<span") == 3 and 'class="h"' in k and ">muovere<" in k


def test_contatore_ha_lo_script_e_prefissi_innocui():
    doc, _ = blocchi.documento("counter", {"da": 0, "a": 1250, "prefisso": "$",
                                           "suffisso": "';alert(1)//"})
    script = doc.split("<script>")[1]
    assert "window.veditRender" in script and "A=1250.0" in script and "PRE='$'" in script
    assert "alert(1)" not in script and "SUF='alert1'" in script   # niente apici ne' parentesi


def test_elenco_dice_i_default():
    voci = {b["id"]: b for b in blocchi.elenco()}
    assert set(voci) == set(blocchi.BLOCCHI)
    assert voci["lower_third"]["parametri"]["nome"]["default"] == "Name Surname"
    assert all(b["descrizione"] and b["durata"] > 0 for b in voci.values())


def test_store_add_block_mette_una_clip_html():
    s = Store.create("t", "720p")
    v2 = s.add_track("video")
    c = s.add_block("lower_third", {"nome": "Anna Rossi", "ruolo": "Regista"}, track_id=v2.id, start=1.0)
    assert c.type == "html" and c.start == 1.0 and c.duration == 4.0 and c.name == "block lower_third"
    assert "Anna Rossi" in c.html and "Regista" in c.html
    assert s.add_block("title", None, duration=2.0).duration == 2.0
    with pytest.raises(EditError, match="unknown block"):
        s.add_block("nope")
    with pytest.raises(EditError, match="must be a color"):
        s.add_block("title", {"colore": "###"})
    s.undo()
    assert len([c for t in s.project.tracks for c in t.clips]) == 1   # un solo undo per blocco


@pytest.mark.anyio
async def test_mcp_list_blocks_e_add_block(tmp_path):
    nomi = {t.name for t in await srv.mcp.list_tools()}
    assert {"add_block", "list_blocks"} <= nomi
    elenco = await call("list_blocks")
    assert {b["id"] for b in elenco} >= {"lower_third", "counter", "chapter_card"}
    assert "default" in (await call("list_blocks", block="counter"))[0]["parametri"]["a"]
    with pytest.raises(Exception, match="unknown block"):
        await call("list_blocks", block="zzz")
    await call("project_create", path=str(tmp_path / "p.json"), name="t", preset="720p")
    c = await call("add_block", block="date_badge", vars={"testo": "YEAR 20"}, start=2.0)
    assert c["block"] == "date_badge" and c["start"] == 2.0 and c["duration"] == 3.0


def test_api_e_chat_conoscono_add_block():
    from vedit import api, chat

    assert "add_block" in api.OPS
    nomi = {t["name"] for t in chat.build_tools()}
    assert {"add_block", "list_blocks"} <= nomi
    s = Store.create("t", "720p")
    import json

    voci = json.loads(chat.execute(s, "list_blocks", {}))
    assert any(b["id"] == "quote" for b in voci)
    assert json.loads(chat.execute(s, "list_blocks", {"block": "x"}))[0]["errore"]


@pytest.mark.slow
@pytest.mark.parametrize("nome,t,vars", [
    ("lower_third", 1.5, {"nome": "Anna Rossi", "ruolo": "Regista"}),
    ("date_badge", 1.5, {"testo": "YEAR 20"}),
    ("caption_pill", 1.5, {"testo": "Minimum starting crew: 98"}),
    ("counter", 3.5, {"da": 0, "a": 98, "etichetta": "people"}),
    ("bar_chart", 3.5, {"dati": "A:40,B:75,C:20"}),
    ("kinetic_words", 3.0, {"testo": "Make it *move*"}),
    ("highlight_box", 1.5, {"x": 20, "y": 20, "larghezza": 30, "altezza": 30}),
])
def test_i_blocchi_si_vedono_davvero(nome, t, vars):
    """In Chromium: qualcosa e' disegnato a meta' clip, l'angolo resta trasparente, e
    a fine clip (uscita compiuta) non resta niente."""
    _browser_o_salta()
    doc, durata = blocchi.documento(nome, vars)
    try:
        mov, _ = htmlclip.rasterize(doc, base=None, duration=durata, width=640, height=360,
                                    fps=10, page_w=640, page_h=360)
    except htmlclip.HtmlNonDisponibile as exc:
        pytest.skip(str(exc))
    import subprocess

    from PIL import Image

    from vedit import ffmpeg

    def immagine(secondo):
        out = mov + f".{nome}.{secondo}.png"
        subprocess.run([ffmpeg.binary("ffmpeg"), "-loglevel", "error", "-y", "-ss", str(secondo),
                        "-i", mov, "-frames:v", "1", "-pix_fmt", "rgba", out], check=True)
        return Image.open(out).convert("RGBA")

    meta = immagine(t)
    coperti = sum(1 for a in meta.getchannel("A").getdata() if a > 100)
    assert coperti > 300, f"{nome}: a {t}s non c'e' niente disegnato"
    # highlight_box scurisce il resto: l'angolo non e' piu' trasparente, e va bene
    if nome != "highlight_box":
        assert meta.getpixel((2, 2))[3] == 0
    fine = immagine(round(durata - 0.1, 2))   # l'ultimo fotogramma a 10 fps
    assert sum(1 for a in fine.getchannel("A").getdata() if a > 100) < coperti * 0.1, \
        f"{nome}: l'uscita non spegne la grafica"
