"""Effetti speciali: fusioni, distorsioni, 3D, scontorno, tracking, particelle.

test_effects verifica che ogni filtro renda; qui si guarda che faccia quello
che promette: lo screen schiarisce, il tremolio non scopre mai i bordi, fuori
dalla carta 3D si vede la traccia sotto, la maschera toglie davvero lo sfondo,
l'aggancio porta la grafica dove sta il soggetto.
"""

import subprocess

import pytest
from PIL import Image

from vedit import effects as fx
from vedit import ffmpeg, particelle, render
from vedit.model import BLEND_MODES
from vedit.store import EditError, Store

SFONDO = (0, 0, 255)


def _pixel(s: Store, t: float, xy: tuple[int, int], tmp_path) -> tuple[int, int, int]:
    out = tmp_path / "f.png"
    render.render_frame(s.project, t, str(out), width=320, use_proxy=False)
    return Image.open(out).convert("RGB").getpixel(xy)


def _progetto(tmp_path) -> Store:
    s = Store.create("fx", "720p", path=str(tmp_path / "p.json"))
    s.set_settings(width=320, height=180, background="#0000ff")
    return s


def _vicino(a, b, tol=24):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# --------------------------------------------------------------------------
# senza render
# --------------------------------------------------------------------------


def test_glitch_ripetibile_e_seed_diverso_cambia():
    c = fx.Ctx(width=320, height=180)
    uno = fx._f_glitch({"intensity": 0.5, "seed": 3}, c)
    assert uno == fx._f_glitch({"intensity": 0.5, "seed": 3}, fx.Ctx(width=320, height=180))
    assert uno != fx._f_glitch({"intensity": 0.5, "seed": 4}, c)
    assert "random" not in "".join(uno), "il render deve essere una funzione pura del progetto"
    assert fx._f_glitch({"intensity": 0}, c) == []


def test_blend_validato(tmp_path):
    s = _progetto(tmp_path)
    c = s.add_color("red", duration=1)
    for modo in BLEND_MODES:
        assert s.set_clip(c.id, blend=modo).blend == modo
    with pytest.raises(EditError):
        s.set_clip(c.id, blend="fumo")
    # la UI e l'agente leggono il progetto dal riassunto: la fusione deve esserci
    s.set_clip(c.id, blend="screen")
    for detail in ("normal", "full"):
        clip = s.summary(detail)["tracks"][0]["clips"][0]
        assert clip["blend"] == "screen", detail


def test_matte_in_testa_e_sostituito(tmp_path, assets):
    s = _progetto(tmp_path)
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, duration=1)
    s.add_effect(c.id, "blur", {})
    f1, f2 = tmp_path / "a.mkv", tmp_path / "b.mkv"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")
    s.set_matte(c.id, str(f1))
    s.set_matte(c.id, str(f2), feather=0)
    tipi = [e.type for e in c.effects]
    assert tipi == ["matte", "blur"]
    assert c.effects[0].params["file"] == str(f2)
    with pytest.raises(EditError):
        s.set_matte(c.id, str(tmp_path / "manca.mkv"))


def test_aggancio_segue_il_soggetto_nel_tempo_della_clip(tmp_path, assets):
    """Sorgente 640x360 in un 1920x1080: ogni pixel vale 3, e il tempo trasla."""
    s = Store.create("pin", "1080p", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["blue"]])[0]
    ripresa = s.add_clip(m.id, start=1.0, in_=2.0, duration=2.0)
    t2 = s.add_track("video")
    titolo = s.add_text("ciao", track_id=t2.id, start=1.0, duration=2.0)
    traccia = [
        {"t": 1.0, "cx": 999, "cy": 999},   # prima dell'attacco: scartato
        {"t": 2.0, "cx": 320, "cy": 180},   # centro -> 0, 0
        {"t": 3.0, "cx": 420, "cy": 130},   # +100, -50 sorgente -> +300, -150
    ]
    s.pin_to_subject(titolo.id, ripresa.id, traccia, 640, 360, offset_y=-40)
    kx, ky = titolo.transform.x["kf"], titolo.transform.y["kf"]
    assert [p["t"] for p in kx] == [0.0, 1.0]
    assert [p["v"] for p in kx] == [0.0, 300.0]
    assert [p["v"] for p in ky] == [-40.0, -190.0]


def test_particelle_deterministiche_e_validate(tmp_path):
    a = particelle.html("snow", 1920, 1080, seed=7)
    assert a == particelle.html("snow", 1920, 1080, seed=7)
    assert "Math.random" not in a
    for kind in particelle.KINDS:
        assert f'"kind": "{kind}"' in particelle.html(kind, 640, 360)
    s = _progetto(tmp_path)
    c = s.add_particles("confetti", duration=2)
    assert c.type == "html" and "confetti" in c.html
    with pytest.raises(EditError):
        s.add_particles("lava")
    with pytest.raises(EditError):
        s.add_particles("snow", density=0)


# --------------------------------------------------------------------------
# render veri
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_screen_schiarisce_multiply_scurisce(tmp_path):
    def fuso(modo):
        s = _progetto(tmp_path)
        s.add_color("#ff0000", duration=1)
        t2 = s.add_track("video")
        c = s.add_color("#808080", duration=1, track_id=t2.id)
        s.set_clip(c.id, blend=modo)
        return _pixel(s, 0.5, (160, 90), tmp_path)

    normale, screen, multiply = fuso("normal"), fuso("screen"), fuso("multiply")
    assert _vicino(normale, (128, 128, 128)), normale
    assert screen[0] > 230 and 100 < screen[1] < 160, screen      # rosso resta, grigio schiarisce
    assert 100 < multiply[0] < 160 and multiply[1] < 30, multiply  # rosso dimezzato, niente verde


@pytest.mark.slow
def test_blend_rispetta_posizione_e_dimensione(tmp_path):
    """Fuori dal riquadro della clip la base non deve cambiare."""
    s = _progetto(tmp_path)
    s.add_color("#ff0000", duration=1)
    t2 = s.add_track("video")
    c = s.add_color("#808080", duration=1, track_id=t2.id)
    s.set_transform(c.id, scale=0.5)
    s.set_clip(c.id, blend="screen")
    assert _vicino(_pixel(s, 0.5, (10, 10), tmp_path), (255, 0, 0))
    assert _pixel(s, 0.5, (160, 90), tmp_path)[1] > 100


@pytest.mark.slow
def test_tremolio_non_scopre_i_bordi(tmp_path):
    s = _progetto(tmp_path)
    c = s.add_color("#ff0000", duration=2)
    s.add_effect(c.id, "shake", {"amount": 40, "frequency": 9})
    for t in (0.13, 0.41, 0.77, 1.3):
        for xy in ((1, 1), (318, 1), (1, 178), (318, 178)):
            assert _vicino(_pixel(s, t, xy, tmp_path), (255, 0, 0)), (t, xy)


@pytest.mark.slow
def test_tilt3d_scopre_la_traccia_sotto(tmp_path):
    s = _progetto(tmp_path)
    c = s.add_color("#ff0000", duration=1)
    s.set_transform(c.id, scale=0.8)
    s.add_effect(c.id, "tilt3d", {"yaw": 50, "pitch": 0, "depth": 2})
    assert _vicino(_pixel(s, 0.5, (160, 90), tmp_path), (255, 0, 0))
    # il lato che si allontana si accorcia: l'angolo di quel lato e' vuoto
    angoli = [_pixel(s, 0.5, xy, tmp_path) for xy in ((40, 25), (280, 25))]
    assert any(_vicino(p, SFONDO, 40) for p in angoli), angoli


@pytest.mark.slow
def test_matte_toglie_lo_sfondo(tmp_path, assets):
    """Maschera bianca a destra e nera a sinistra: a sinistra si vede il fondo."""
    maschera = tmp_path / "m.mkv"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=black:s=320x180:r=25:d=5", "-vf",
        "drawbox=x=160:y=0:w=160:h=180:color=white:t=fill,format=gray",
        "-c:v", "ffv1", str(maschera)], check=True)
    s = _progetto(tmp_path)
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, in_=1.0, duration=2)
    s.set_matte(c.id, str(maschera), t0=0.0, feather=0)
    assert _vicino(_pixel(s, 1.0, (60, 90), tmp_path), SFONDO, 40)
    assert _vicino(_pixel(s, 1.0, (260, 90), tmp_path), (255, 0, 0), 40)
    s.update_effect(c.id, 0, params={"invert": True})
    assert _vicino(_pixel(s, 1.0, (60, 90), tmp_path), (255, 0, 0), 40)


@pytest.mark.slow
def test_rimuovi_oggetto_cancella_il_riquadro(tmp_path):
    s = _progetto(tmp_path)
    s.add_color("#00ff00", duration=1)
    t2 = s.add_track("video")
    q = s.add_color("#ff00ff", duration=1, track_id=t2.id)
    s.set_transform(q.id, scale=0.2)
    s.add_effect(None, "remove_object", {"x": 120, "y": 60, "w": 80, "h": 60})
    assert _vicino(_pixel(s, 0.5, (160, 90), tmp_path), (0, 255, 0), 60)
