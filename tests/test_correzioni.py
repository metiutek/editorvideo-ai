"""Difetti corretti: ognuno qui ha rotto un montaggio vero prima di essere preso.

Niente render: sono tutti controlli sul documento o sul filtergraph compilato,
quindi girano nella parte veloce della suite.
"""

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import cleanup, ops
from vedit import keyframes as kf
from vedit.graph import compile_project, slice_project
from vedit.store import EditError, Store


@pytest.fixture
def s(tmp_path, assets):
    st = Store.create("fix", "720p", path=str(tmp_path / "p.json"))
    st.red = st.import_media([assets["red"]])[0]      # 5s con audio
    return st


# ---------------------------------------------------------------- split
def test_split_lascia_uscita_e_transizione_alla_seconda_meta(s):
    c = s.add_clip(s.red.id, duration=5.0)
    s.set_fades(c.id, 1.0, 1.0)
    s.set_transition(c.id, "wipe_left", 1.0)
    a, b = s.split_clip(c.id, 2.0)
    # sul punto di taglio non deve succedere niente
    assert a.fade_out == 0 and a.audio.fade_out == 0
    assert a.transition_out.duration == 0
    # l'uscita resta dov'era, alla fine della clip originale
    assert b.transition_out.type == "wipe_left" and b.transition_out.duration == 1.0
    assert b.audio.fade_out == 1.0
    assert a.fade_in == 1.0 and b.fade_in == 0


def test_split_di_clip_invertita(s):
    c = s.add_clip(s.red.id, duration=5.0)
    s.set_reverse(c.id)
    a, b = s.split_clip(c.id, 2.0)
    # all'indietro la testa in timeline e' la fine del tratto sorgente
    assert a.in_ == pytest.approx(3.0) and a.duration == pytest.approx(2.0)
    assert b.in_ == pytest.approx(0.0) and b.duration == pytest.approx(3.0)


def test_slice_di_clip_invertita(s):
    c = s.add_clip(s.red.id, duration=5.0)
    s.set_reverse(c.id)
    fetta = slice_project(s.project, 1.0, 3.0).tracks[0].clips[0]
    # timeline 1..3 all'indietro = sorgente 2..4
    assert fetta.in_ == pytest.approx(2.0)


def test_audio_segue_il_video_invertito(s):
    c = s.add_clip(s.red.id, duration=2.0)
    assert "areverse" not in compile_project(s.project).filtergraph
    s.set_reverse(c.id)
    assert "areverse" in compile_project(s.project).filtergraph


def test_dissolvenza_audio_prima_del_trim_nei_segmenti(s):
    """Un segmento preso a meta' clip non deve ripartire con una dissolvenza."""
    c = s.add_clip(s.red.id, duration=5.0)
    s.set_fades(c.id, 1.0, 1.0)
    g = compile_project(s.project, _opts(start=2.0, end=4.0)).filtergraph
    catena = next(r for r in g.split(";\n") if "afade=t=in" in r)
    assert catena.index("afade=t=in") < catena.index("atrim=")
    assert "asetpts=PTS-STARTPTS+2/TB" in catena


def _opts(**kw):
    from vedit.graph import CompileOptions
    return CompileOptions(**kw)


# ---------------------------------------------------------------- atomicita'
def test_transform_non_valido_non_scrive_niente(s):
    c = s.add_clip(s.red.id, duration=2.0)
    passi = len(s._undo)
    with pytest.raises(EditError):
        s.set_transform(c.id, x=50, y={"kf": [{"t": 0, "v": "boh"}]})
    assert c.transform.x == 0.0 and len(s._undo) == passi


def test_spostamento_rifiutato_non_sposta(s):
    c = s.add_clip(s.red.id, duration=2.0)
    passi = len(s._undo)
    with pytest.raises(EditError):
        s.move_clip(c.id, start=9.0, track_id="A1")
    assert c.start == 0.0 and len(s._undo) == passi


def test_trim_oltre_la_fine_rifiutato(s):
    c = s.add_clip(s.red.id, duration=2.0)
    passi = len(s._undo)
    with pytest.raises(EditError):
        s.trim_clip(c.id, in_=99.0)
    assert c.in_ == 0.0 and len(s._undo) == passi


def test_import_parziale_non_resta(s, tmp_path):
    passi = len(s._undo)
    with pytest.raises(Exception):
        s.import_media([str(tmp_path / "non_esiste.mp4")])
    assert len(s.project.media) == 1 and len(s._undo) == passi


def test_keyframe_con_numeri_illeggibili():
    with pytest.raises(ValueError):
        kf.validate({"kf": [{"t": "zero", "v": 1}]})
    with pytest.raises(ValueError):
        kf.validate("tanto")
    kf.validate({"kf": [{"t": "0", "v": "1.5"}]})     # stringhe numeriche: ok


# ---------------------------------------------------------------- montaggio
def test_crossfade_al_contrario_rifiutato(s):
    a = s.add_clip(s.red.id, duration=2.0)
    b = s.add_clip(s.red.id, duration=2.0)
    with pytest.raises(EditError):
        s.crossfade(b.id, a.id)


def test_close_gaps_tiene_le_transizioni(s):
    a = s.add_clip(s.red.id, duration=2.0)
    b = s.add_clip(s.red.id, start=4.0, duration=2.0)
    s.crossfade(a.id, b.id, 0.5)                 # b sovrapposta ad a di 0.5
    c = s.add_clip(s.red.id, start=8.0, duration=1.0)
    s.close_gaps("V1")
    assert b.start == pytest.approx(1.5)          # sovrapposizione intatta
    assert c.start == pytest.approx(3.5)          # buco chiuso
    passi = len(s._undo)
    assert s.close_gaps("V1") == 0 and len(s._undo) == passi


def test_velocita_a_durata_tenuta_non_supera_la_sorgente(s):
    c = s.add_clip(s.red.id, in_=3.0, duration=2.0)
    s.set_speed(c.id, 3.0, keep_duration=True)
    assert c.duration <= (5.0 - 3.0) / 3.0 + 1e-6


# ---------------------------------------------------------------- ops
def test_insert_e_un_gesto_solo(s, assets):
    logo = s.import_media([assets["logo"]])[0]
    s.add_clip(s.red.id, duration=4.0)
    passi = len(s._undo)
    r = ops.insert_clip(s, logo.id, at=2.0)
    assert r["durata"] == pytest.approx(5.0)       # immagine: 5s, non 0.1
    assert len(s._undo) == passi + 1
    s.undo()
    assert len(s.project.tracks[0].clips) == 1


def test_detach_mantiene_velocita(s):
    c = s.add_clip(s.red.id, duration=4.0)
    s.set_speed(c.id, 2.0)
    d = ops.detach_audio(s, c.id)
    _, audio = s.clip_or_die(d["audio_clip"])
    assert audio.speed == 2.0 and audio.duration == pytest.approx(c.duration)


def test_taglio_in_testa_senza_ripple_resta_a_sincrono(s):
    c = s.add_clip(s.red.id, duration=4.0)
    s.set_speed(c.id, 0.5)                         # 8s in timeline
    passi = len(s._undo)
    cleanup.cut_ranges(s, c.id, [(0.0, 2.0)], ripple=False)
    _, c = s.clip_or_die(c.id)
    assert c.start == pytest.approx(2.0)
    assert c.in_ == pytest.approx(1.0)             # 2s di timeline a 0.5x = 1s di sorgente
    assert len(s._undo) == passi + 1


# ---------------------------------------------------------------- api
def test_revisione_in_cache_ma_aggiornata(s):
    api_mod.S.store = s
    try:
        r1 = api_mod.S.revision()
        assert api_mod.S.revision() == r1
        s.add_clip(s.red.id, duration=1.0)
        assert api_mod.S.revision() != r1
    finally:
        api_mod.S.store = None


def test_richieste_da_altri_siti_rifiutate():
    """DNS rebinding e form di altri siti non devono arrivare all'API."""
    api_mod._consenti_host("127.0.0.1")
    try:
        with TestClient(api_mod.app, base_url="http://127.0.0.1:8760") as c:
            assert c.get("/api/recenti").status_code == 200
            assert c.get("/api/recenti", headers={"host": "evil.example"}).status_code == 403
            assert c.post("/api/chat/reset",
                          headers={"origin": "https://evil.example"}).status_code == 403
            assert c.post("/api/chat/reset", headers={"origin": "null"}).status_code == 403
            assert c.post("/api/chat/reset",
                          headers={"origin": "http://localhost:5173"}).status_code == 200
    finally:
        api_mod._host_consentiti.clear()
