"""Movimenti di camera (moves.py, camera_move): ricette a keyframe che non scoprono mai i
bordi, ripetibili, applicate in un solo undo da Store, MCP e chat."""

import json
import math

import pytest

from vedit import keyframes as kf
from vedit import moves
from vedit import mcp_server as srv
from vedit.store import EditError, Store
from test_mcp import call

DIMENSIONI = [(1920, 1080), (1080, 1920), (1080, 1080)]
DURATE = [0.5, 3.0, 20.0]


def _costruisci(nome, d, w, h, **kw):
    kw.setdefault("bpm", 120 if nome == "beat_pulse" else None)
    return moves.costruisci(nome, d, w, h, **kw)


def _scoperto(v, t, w, h):
    """Di quanto, in pixel, il canvas esce dall'immagine trasformata al tempo t (0 = coperto)."""
    s = kf.sample(v["scale"], t, 1.0)
    x, y = kf.sample(v["x"], t), kf.sample(v["y"], t)
    a = math.radians(kf.sample(v["rotation"], t))
    peggio = 0.0
    for sgn in (1, -1):                               # il verso della rotazione non conta: provo entrambi
        c, sn = math.cos(sgn * a), math.sin(sgn * a)
        sforo = 0.0
        for cx in (-w / 2, w / 2):
            for cy in (-h / 2, h / 2):
                px, py = (cx - x) / s, (cy - y) / s
                lx, ly = px * c + py * sn, -px * sn + py * c
                sforo = max(sforo, abs(lx) - w / 2, abs(ly) - h / 2)
        peggio = max(peggio, sforo)
    return peggio


@pytest.mark.parametrize("nome", list(moves.MOSSE))
@pytest.mark.parametrize("d", DURATE)
@pytest.mark.parametrize("w,h", DIMENSIONI)
def test_ogni_movimento_e_valido_e_non_scopre_i_bordi(nome, d, w, h):
    for k in (0.5, 1.0, 3.0):
        v = _costruisci(nome, d, w, h, intensita=k)
        assert set(v) == {"x", "y", "scale", "rotation"}
        for campo, val in v.items():
            kf.validate(val)
            if kf.is_kf(val):
                tempi = [p["t"] for p in val["kf"]]
                assert tempi == sorted(tempi) and 0 <= tempi[0] and tempi[-1] <= d + 1e-6, (nome, campo)
                assert len(tempi) <= moves.MAX_KEYFRAME
        for i in range(0, 41):
            t = d * i / 40
            assert _scoperto(v, t, w, h) <= 1.5, f"{nome} k={k} t={t:.2f}: il bordo si vede"


def test_la_scala_e_il_senso_dei_movimenti():
    w, h, d = 1920, 1080, 4.0
    push = _costruisci("push_in", d, w, h)
    assert kf.sample(push["scale"], 0) == 1.0 and kf.sample(push["scale"], d) == pytest.approx(1.12)
    pull = _costruisci("pull_out", d, w, h)
    assert kf.sample(pull["scale"], 0) > kf.sample(pull["scale"], d) == 1.0
    sx, dx = _costruisci("pan_left", d, w, h), _costruisci("pan_right", d, w, h)
    # la camera gira a sinistra: l'immagine scorre verso destra (x cresce)
    assert kf.sample(sx["x"], d) > kf.sample(sx["x"], 0) and kf.sample(dx["x"], d) < kf.sample(dx["x"], 0)
    su = _costruisci("tilt_up", d, w, h)
    assert kf.sample(su["y"], d) > kf.sample(su["y"], 0)       # alza lo sguardo: l'immagine scende
    assert kf.sample(_costruisci("dutch_tilt", d, w, h)["rotation"], d) == pytest.approx(-5.0)
    # il punch arriva in fretta e poi tiene
    p = _costruisci("punch_in", d, w, h)
    assert kf.sample(p["scale"], 0.28) == pytest.approx(1.18) == kf.sample(p["scale"], d)
    z = _costruisci("zoom_burst", d, w, h)
    assert kf.sample(z["scale"], d - 1.0) == 1.0 and kf.sample(z["scale"], d) == pytest.approx(1.4)


def test_l_intensita_cambia_l_ampiezza():
    w, h, d = 1920, 1080, 4.0
    piano = kf.sample(_costruisci("push_in", d, w, h, intensita=0.5)["scale"], d)
    forte = kf.sample(_costruisci("push_in", d, w, h, intensita=2.0)["scale"], d)
    assert 1.0 < piano < forte


def test_il_tremolio_e_ripetibile_e_dipende_dal_seme():
    a = _costruisci("handheld", 6.0, 1920, 1080, seme=5)
    assert a == _costruisci("handheld", 6.0, 1920, 1080, seme=5)
    assert a != _costruisci("handheld", 6.0, 1920, 1080, seme=6)
    # non e' un movimento fermo: cambia davvero nel tempo
    xs = {round(kf.sample(a["x"], t / 2), 3) for t in range(12)}
    assert len(xs) > 6
    # la scossa si smorza: all'inizio piu' ampia che alla fine
    s = _costruisci("impact_shake", 3.0, 1920, 1080)
    assert max(abs(p["v"]) for p in s["x"]["kf"][:4]) > max(abs(p["v"]) for p in s["x"]["kf"][-4:])
    assert s["x"]["kf"][-1]["t"] == pytest.approx(0.6)


def test_il_battito_segue_i_bpm():
    d = 4.0
    v = _costruisci("beat_pulse", d, 1920, 1080, bpm=120)       # un battito ogni 0,5 s
    picchi = [p["t"] for p in v["scale"]["kf"] if p["v"] > 1.01]
    assert picchi[:4] == [0.0, 0.5, 1.0, 1.5]
    assert kf.sample(v["scale"], 0.25) < kf.sample(v["scale"], 0.01)         # scende fra i battiti
    with pytest.raises(ValueError, match="needs bpm"):
        moves.costruisci("beat_pulse", d, 1920, 1080)
    with pytest.raises(ValueError, match="too long"):
        moves.costruisci("beat_pulse", 300.0, 1920, 1080, bpm=120)
    with pytest.raises(ValueError, match="bpm out of range"):
        moves.costruisci("push_in", d, 1920, 1080, bpm=900)


def test_errori_con_l_elenco_di_quelli_ammessi():
    with pytest.raises(ValueError, match="unknown move 'volo'.*push_in"):
        moves.costruisci("volo", 3, 1920, 1080)
    with pytest.raises(ValueError, match="intensity out of range"):
        moves.costruisci("push_in", 3, 1920, 1080, intensita=9)
    with pytest.raises(ValueError, match="too short"):
        moves.costruisci("push_in", 0.1, 1920, 1080)
    assert {m["gruppo"] for m in moves.elenco()} == {"push / pull", "pan / tilt", "impact", "rhythm", "organic"}
    assert all(m["descrizione"] for m in moves.elenco()) and len(moves.elenco()) == len(moves.MOSSE) == 16


def _clip(assets):
    s = Store.create("t", "720p")
    m = s.import_media([assets["blue"]])[0]
    return s, s.add_clip(m.id, duration=3.0)


def test_store_camera_move_sostituisce_e_si_annulla_in_un_colpo(assets):
    s, c = _clip(assets)
    s.set_transform(c.id, x=40, rotation=3, opacity=0.5)
    s.camera_move(c.id, "push_in", 1.5)
    t = s.clip_or_die(c.id)[1].transform
    assert kf.is_kf(t.scale) and t.x == 0.0 and t.rotation == 0.0     # il vecchio spostamento non resta
    assert t.opacity == 0.5                                           # l'opacita' non e' del movimento
    s.undo()
    t = s.clip_or_die(c.id)[1].transform
    assert t.x == 40 and t.rotation == 3 and not kf.is_kf(t.scale)    # un solo undo
    with pytest.raises(EditError, match="unknown move"):
        s.camera_move(c.id, "teletrasporto")
    with pytest.raises(EditError, match="needs bpm"):
        s.camera_move(c.id, "beat_pulse")


def test_non_si_muove_una_traccia_audio(assets):
    s = Store.create("t", "720p")
    m = s.import_media([assets["music"]])[0]
    traccia = s.add_track("audio")
    c = s.add_clip(m.id, track_id=traccia.id, duration=2.0)
    with pytest.raises(EditError, match="audio track"):
        s.camera_move(c.id, "push_in")


@pytest.mark.anyio
async def test_mcp_list_moves_e_camera_move(assets, tmp_path):
    nomi = {t.name for t in await srv.mcp.list_tools()}
    assert {"camera_move", "list_moves"} <= nomi
    assert {m["id"] for m in await call("list_moves")} == set(moves.MOSSE)
    await call("project_create", path=str(tmp_path / "p.json"), name="t", preset="720p")
    m = await call("import_media", paths=[assets["blue"]])
    cid = (await call("add_clip", media=m[0]["id"], duration=3.0))["id"]
    r = await call("camera_move", clip=cid, move="drift", intensity=1.2)
    assert r == {"id": cid, "move": "drift"}
    with pytest.raises(Exception, match="unknown move"):
        await call("camera_move", clip=cid, move="x")


def test_api_e_chat_conoscono_camera_move(assets):
    from vedit import api, chat

    assert "camera_move" in api.OPS
    assert {"camera_move", "list_moves"} <= {t["name"] for t in chat.build_tools()}
    s, c = _clip(assets)
    voci = json.loads(chat.execute(s, "list_moves", {}))
    assert any(m["id"] == "handheld" for m in voci)
    chat.execute(s, "camera_move", {"clip_id": c.id, "move": "tilt_up"})
    assert kf.is_kf(s.clip_or_die(c.id)[1].transform.y)


@pytest.mark.slow
@pytest.mark.parametrize("nome", ["pan_left", "tilt_down", "dutch_tilt", "handheld", "drift"])
def test_render_vero_senza_bordi_neri(assets, tmp_path, nome):
    """Il fotogramma reale, ai due estremi e a meta': l'immagine si muove e i quattro
    angoli restano pieni (lo sfondo del progetto e' nero: un bordo scoperto si vede)."""
    from PIL import Image

    from vedit import render

    s = Store.create("t", "720p")
    m = s.import_media([assets["red"]])[0]                 # tinta unita: un bordo nero non puo' nascondersi
    c = s.add_clip(m.id, duration=3.0)
    s.camera_move(c.id, nome, 2.0)
    for t in (0.05, 1.5, 2.95):
        out = render.render_frame(s.project, t, str(tmp_path / f"{nome}{t}.png"), width=320, use_proxy=False)
        im = Image.open(out).convert("RGB")
        w, h = im.size
        for p in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3)):
            r, g, b = im.getpixel(p)
            assert r > 150 and g < 60 and b < 60, f"{nome} a {t}s: l'angolo {p} e' {im.getpixel(p)}"


@pytest.mark.slow
def test_scala_animata_e_spostamento_vanno_dalla_stessa_parte(assets, tmp_path):
    """Con la scala animata lo spostamento sta dentro zoompan: deve dare (quasi) lo stesso
    fotogramma di scala fissa + overlay, dalla stessa parte e della stessa misura."""
    import numpy as np
    from PIL import Image

    from vedit import render

    lenta = {"kf": [{"t": 0, "v": 1.2}, {"t": 3, "v": 1.2001}]}     # animata, ma ferma di fatto

    def fotogramma(scala, x, y, nome):
        s = Store.create("t", "720p")
        m = s.import_media([assets["blue"]])[0]            # testsrc2: ha struttura, si vede lo scarto
        c = s.add_clip(m.id, duration=3.0)
        s.set_transform(c.id, scale=scala, x=x, y=y)
        out = render.render_frame(s.project, 1.0, str(tmp_path / f"{nome}.png"), width=320, use_proxy=False)
        return np.asarray(Image.open(out).convert("RGB"), dtype=float)

    def scarto(a, b):
        return float(np.abs(a - b).mean())

    fissa = fotogramma(1.2, 60, -30, "fissa")
    animata = fotogramma(lenta, 60, -30, "animata")
    opposta = fotogramma(lenta, -60, 30, "opposta")
    ferma = fotogramma(lenta, 0, 0, "ferma")
    # misurato: stesso verso ~8, nessuno spostamento ~38, verso opposto ~71
    assert scarto(fissa, animata) < 15.0
    assert scarto(fissa, ferma) > 25.0 and scarto(fissa, opposta) > 40.0
