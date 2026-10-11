"""Tracking di un oggetto qualsiasi ed evidenziazione.

Il tracker senza YOLO (vision.track_box) si prova su un video sintetico dove
si sa dov'e' l'oggetto a ogni istante; gli effetti di evidenziazione si
provano guardando i pixel del fotogramma renderizzato, non solo il fatto che
il render non fallisca.
"""

import subprocess

import numpy as np
import pytest
from PIL import Image

from vedit import effects as fx
from vedit import ffmpeg, render, vision
from vedit.store import EditError, Store


@pytest.fixture(scope="module")
def quadrato(tmp_path_factory) -> str:
    """Un riquadro con un motivo che scorre da x=40 a destra di 60 px/s, y fisso."""
    out = tmp_path_factory.mktemp("trk") / "quadrato.mp4"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x404040:s=640x360:r=25:d=3",
        "-f", "lavfi", "-i", "testsrc2=s=60x60:r=25:d=3",
        "-filter_complex", "[0][1]overlay=x='40+t*60':y=150",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    return str(out)


@pytest.fixture(scope="module")
def maschera(tmp_path_factory) -> str:
    """Maschera di scontorno finta: bianco a sinistra, nero a destra."""
    out = tmp_path_factory.mktemp("mat") / "matte.mkv"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=3",
        "-vf", "drawbox=x=0:y=0:w=320:h=360:color=white:t=fill,format=gray",
        "-c:v", "ffv1", str(out),
    ], check=True, capture_output=True)
    return str(out)


# --------------------------------------------------------------------------
# tracker
# --------------------------------------------------------------------------


def test_ncc_trova_il_modello():
    rng = np.random.default_rng(3)
    img = rng.random((80, 120)).astype(np.float32)
    mappa = vision.ncc(img, img[30:50, 70:95].copy())
    dy, dx = divmod(int(np.argmax(mappa)), mappa.shape[1])
    assert (dy, dx) == (30, 70)
    assert mappa.max() == pytest.approx(1.0, abs=1e-3)


def test_ncc_modello_piatto_non_si_cerca():
    assert vision.ncc(np.ones((40, 40), np.float32), np.ones((8, 8), np.float32)) is None


def test_box_in_frazioni_o_pixel():
    assert vision.box_in_pixel([0.25, 0.5, 0.1, 0.2], 1000, 500) == (250, 250, 100, 100)
    assert vision.box_in_pixel([300, 100, 50, 40], 1000, 500) == (300, 100, 50, 40)
    with pytest.raises(vision.VisionError):
        vision.box_in_pixel([0.1, 0.1, 0.2], 100, 100)


def test_track_box_segue_l_oggetto(quadrato):
    res = vision.track_box(quadrato, [40, 150, 60, 60], t=0.0)
    assert res["copertura"] > 0.9
    a_due = min(res["traccia"], key=lambda p: abs(p["t"] - 2.0))
    # al secondo 2 il riquadro sta a x = 40 + 120: centro 190, y fermo a 180
    assert a_due["cx"] == pytest.approx(190, abs=8)
    assert a_due["cy"] == pytest.approx(180, abs=6)


def test_track_box_parte_anche_da_meta(quadrato):
    """Indicato a t=1.5 deve seguire anche all'indietro, verso l'inizio."""
    res = vision.track_box(quadrato, [130 / 640, 150 / 360, 60 / 640, 60 / 360], t=1.5)
    inizio = res["traccia"][0]
    assert inizio["cx"] == pytest.approx(70, abs=8)


def test_to_canvas_contain_e_cover():
    p = [{"t": 0, "cx": 1920.0, "cy": 1080.0,
          "box": {"x": 1820.0, "y": 980.0, "w": 200.0, "h": 200.0}}]
    # 4K in un 1080p: tutto a meta'
    q = vision.to_canvas(p, "contain", 3840, 2160, 1920, 1080)[0]
    assert (q["cx"], q["cy"], q["box"]["w"]) == (960, 540, 100)
    # 4:3 in 16:9 con le bande: il centro resta al centro, x spostato dalle bande
    q = vision.to_canvas([{"t": 0, "cx": 0.0, "cy": 0.0, "box": None}],
                         "contain", 1440, 1080, 1920, 1080)[0]
    assert (q["cx"], q["cy"]) == (240, 0)


# --------------------------------------------------------------------------
# effetti di evidenziazione
# --------------------------------------------------------------------------


def test_tint_amount_zero_non_cambia_niente():
    assert fx.tint_matrix("#ff0000", 0.0) == [1, 0, 0, 0, 1, 0, 0, 0, 1]


def test_tint_colore_sbagliato_e_un_errore_chiaro():
    with pytest.raises(ValueError, match="colore"):
        fx.tint_matrix("fucsiaacceso", 0.5)


def test_nuove_maschere_nel_registro():
    for nome in ("mask_outline", "mask_spotlight", "tint"):
        assert nome in fx.EFFECTS


def _fotogramma(tmp_path, s: Store, t: float = 0.5) -> Image.Image:
    out = tmp_path / f"f{t}.png"
    render.render_frame(s.project, t, str(out), width=s.project.settings.width,
                        use_proxy=False)
    return Image.open(out).convert("RGB")


@pytest.mark.slow
def test_cornice_disegna_il_bordo_e_lascia_il_dentro(tmp_path):
    s = Store.create("c", "720p")
    s.set_settings(width=320, height=180)
    c = s.add_color("0x808080", duration=1)
    s.add_effect(c.id, "mask_outline", {"x": 100, "y": 50, "w": 100, "h": 80,
                                        "color": "#ff0000", "thickness": 6})
    img = _fotogramma(tmp_path, s)
    bordo, dentro = img.getpixel((102, 90)), img.getpixel((150, 90))
    assert bordo[0] > 200 and bordo[1] < 80, bordo
    assert abs(dentro[0] - dentro[2]) < 10, dentro


@pytest.mark.slow
def test_spotlight_scurisce_fuori_e_non_dentro(tmp_path):
    s = Store.create("c", "720p")
    s.set_settings(width=320, height=180)
    c = s.add_color("0x808080", duration=1)
    s.add_effect(c.id, "mask_spotlight", {"x": 100, "y": 50, "w": 100, "h": 80,
                                          "amount": 0.8})
    img = _fotogramma(tmp_path, s)
    fuori, dentro = sum(img.getpixel((20, 20))), sum(img.getpixel((150, 90)))
    assert dentro > fuori + 120, (dentro, fuori)


@pytest.mark.slow
def test_tinta_porta_il_grigio_verso_il_colore(tmp_path):
    s = Store.create("c", "720p")
    s.set_settings(width=320, height=180)
    c = s.add_color("0x808080", duration=1)
    s.add_effect(c.id, "tint", {"color": "#ff3000", "amount": 0.8})
    r, g, b = _fotogramma(tmp_path, s).getpixel((160, 90))
    assert r > b + 60, (r, g, b)


# --------------------------------------------------------------------------
# highlight_subject: doppione scontornato sopra la clip
# --------------------------------------------------------------------------


def _con_clip(assets) -> tuple[Store, str]:
    s = Store.create("h", "720p")
    m = s.import_media([assets["green"]])[0]
    return s, s.add_clip(m.id, duration=2.0).id


@pytest.mark.parametrize("mode", Store.HIGHLIGHT_MODES)
def test_highlight_crea_il_doppione_muto_sopra(assets, maschera, mode):
    s, cid = _con_clip(assets)
    out = s.highlight_subject(cid, maschera, 0.0, mode, "#00ccff")
    tracce = [t.id for t in s.project.tracks if t.kind == "video"]
    assert tracce.index(out["traccia"]) == tracce.index("V1") + 1
    _, dup = s.clip_or_die(out["doppione"])
    assert dup.audio.mute and dup.effects[0].type == "matte"
    assert dup.start == s.clip_or_die(cid)[1].start
    if mode == "glow":
        assert dup.blend == "screen"
    if mode == "spotlight":
        assert s.clip_or_die(cid)[1].effects[-1].type == "color"


def test_highlight_e_un_gesto_solo(assets, maschera):
    s, cid = _con_clip(assets)
    prima = s.project.to_dict()
    s.highlight_subject(cid, maschera, 0.0, "tint")
    s.undo()
    assert s.project.to_dict() == prima


def test_highlight_rifiuta_modi_e_colori_sbagliati(assets, maschera):
    s, cid = _con_clip(assets)
    with pytest.raises(EditError):
        s.highlight_subject(cid, maschera, 0.0, "arcobaleno")
    with pytest.raises(ValueError):
        s.highlight_subject(cid, maschera, 0.0, "tint", "nonuncolore")
    assert len(s.project.tracks) == 2   # niente tracce lasciate a meta'


@pytest.mark.slow
def test_highlight_tint_colora_solo_la_sagoma(assets, maschera, tmp_path):
    s = Store.create("h", "720p")
    s.set_settings(width=640, height=360)
    m = s.import_media([assets["green"]])[0]
    cid = s.add_clip(m.id, duration=2.0).id
    s.highlight_subject(cid, maschera, 0.0, "tint", "#ff0000", amount=1.0)
    img = _fotogramma(tmp_path, s, 1.0)
    sagoma, fondo = img.getpixel((100, 180)), img.getpixel((540, 180))
    # a sinistra (bianco nella maschera) il verde diventa rosso, a destra resta verde
    assert sagoma[0] > sagoma[1], sagoma
    assert fondo[1] > fondo[0] + 40, fondo
