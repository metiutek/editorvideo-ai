"""Davanti e dietro: dove va un titolo, come si porta avanti una clip, stili personali."""

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import stili
from vedit.store import EditError, Store


@pytest.fixture(autouse=True)
def cache_isolata(tmp_path, monkeypatch):
    # gli stili personali vivono in VEDIT_CACHE: ogni test parte da zero
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))


@pytest.fixture
def s(tmp_path):
    st = Store.create("livelli", "720p", path=str(tmp_path / "p.json"))
    st.add_track("video")          # V1 in fondo, V2 sopra
    return st


def _traccia(st, clip_id):
    return next(t for t in st.project.tracks if any(c.id == clip_id for c in t.clips))


def _video_ids(st):
    return [t.id for t in st.project.video_tracks()]


# --------------------------------------------------------------------------
# titoli: sulla traccia piu' in alto, altrimenti una ripresa sopra li copre


def test_titolo_va_sulla_traccia_in_cima(s):
    t = s.add_text("Ciao", start=0, duration=2)
    assert _traccia(s, t.id).id == _video_ids(s)[-1]
    h = s.add_html(start=0, duration=2)
    assert _traccia(s, h.id).id == _video_ids(s)[-1]


def test_titolo_salta_la_traccia_bloccata(s):
    s.set_track(_video_ids(s)[-1], locked=True)
    t = s.add_text("Ciao")
    assert _traccia(s, t.id).id == _video_ids(s)[0]


def test_titolo_con_traccia_indicata_resta_li(s):
    t = s.add_text("Ciao", track_id="V1")
    assert _traccia(s, t.id).id == "V1"


# --------------------------------------------------------------------------
# move_layer


def test_porta_avanti_su_traccia_libera(s):
    c = s.add_color("red", track_id="V1", start=0, duration=2)
    s.move_layer(c.id, "up")
    assert _traccia(s, c.id).id == "V2"
    assert len(s.project.video_tracks()) == 2


def test_porta_avanti_su_traccia_occupata_ne_inserisce_una(s):
    sopra = s.add_color("blue", track_id="V2", start=1, duration=2)
    c = s.add_color("red", track_id="V1", start=0, duration=2)
    s.move_layer(c.id, "up")
    ids = _video_ids(s)
    # nuova traccia fra V1 e V2: la clip sale di un livello senza coprire V2
    assert len(ids) == 3
    assert ids.index(_traccia(s, c.id).id) == 1
    assert _traccia(s, sopra.id).id == ids[-1]


def test_porta_avanti_dalla_cima_crea_traccia_sopra(s):
    c = s.add_color("red", track_id="V2", start=0, duration=2)
    s.move_layer(c.id, "up")
    assert _traccia(s, c.id).id == _video_ids(s)[-1]
    assert len(_video_ids(s)) == 3


def test_manda_dietro_e_limiti(s):
    c = s.add_color("red", track_id="V2", start=0, duration=2)
    s.move_layer(c.id, "down")
    assert _traccia(s, c.id).id == "V1"
    with pytest.raises(EditError):
        s.move_layer(c.id, "down")
    with pytest.raises(EditError):
        s.move_layer(c.id, "di lato")


def test_manda_dietro_su_traccia_occupata_inserisce_sotto(s):
    s.add_color("blue", track_id="V1", start=0, duration=4)
    c = s.add_color("red", track_id="V2", start=1, duration=1)
    s.move_layer(c.id, "down")
    ids = _video_ids(s)
    assert len(ids) == 3 and ids.index(_traccia(s, c.id).id) == 1


def test_davanti_a_tutto_e_un_solo_undo(s):
    s.add_color("blue", track_id="V2", start=0, duration=2)
    c = s.add_color("red", track_id="V1", start=0, duration=2)
    prima = s.project.to_dict()
    s.move_layer(c.id, "top")
    assert _traccia(s, c.id).id == _video_ids(s)[-1]
    s.undo()
    assert s.project.to_dict() == prima


# --------------------------------------------------------------------------
# stili personali


def test_stile_personale_arriva_al_modello():
    nuovo = stili.salva("Il mio canale", "Tagli di 1-2 s, sottotitoli gialli.", piano="shortform")
    assert nuovo["id"].startswith("mio-")
    blocco = stili.blocco(nuovo["id"])
    assert "Tagli di 1-2 s" in blocco and "shortform" in blocco and "scritto dall'utente" in blocco
    voce = next(x for x in stili.descrivi() if x["id"] == nuovo["id"])
    assert voce["personale"] and voce["guida"].startswith("Tagli")
    # i predefiniti restano e non espongono la guida
    assert all("guida" not in x for x in stili.descrivi() if not x.get("personale"))


def test_stile_personale_modifica_e_elimina():
    a = stili.salva("Uno", "prima")
    b = stili.salva("Uno", "doppione")          # stesso nome, id diverso
    assert a["id"] != b["id"]
    stili.salva("Uno rinominato", "dopo", stile_id=a["id"])
    assert stili.trova(a["id"])["guida"] == "dopo"
    stili.elimina(a["id"])
    assert stili.trova(a["id"]) is None and stili.trova(b["id"])


@pytest.mark.parametrize("kw", [
    {"nome": "", "guida": "x"},
    {"nome": "x", "guida": "  "},
    {"nome": "x", "guida": "x", "piano": "boh"},
    {"nome": "x", "guida": "x" * (stili.MAX_GUIDA + 1)},
    {"nome": "x", "guida": "x", "stile_id": "inesistente"},
])
def test_stile_personale_rifiuti(kw):
    with pytest.raises(ValueError):
        stili.salva(**kw)


def test_stili_via_api(tmp_path):
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        r = c.post("/api/stili", json={"nome": "Vlog mio", "guida": "jump cut ovunque"})
        assert r.status_code == 200
        sid = r.json()["stile"]
        assert any(x["id"] == sid for x in c.get("/api/state").json()["stili"])
        assert c.post("/api/stili", json={"nome": "", "guida": "x"}).status_code == 400
        assert c.delete(f"/api/stili/{sid}").status_code == 200
        assert c.delete(f"/api/stili/{sid}").status_code == 404


def test_move_layer_via_api(tmp_path):
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
        clip = c.post("/api/op/add_color", json={"color": "red"}).json()["result"]
        r = c.post("/api/op/move_layer", json={"clip_id": clip["id"], "direction": "up"})
        assert r.status_code == 200
        video = [t for t in r.json()["project"]["tracks"] if t["kind"] == "video"]
        assert any(x["id"] == clip["id"] for x in video[-1]["clips"])
