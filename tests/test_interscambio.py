"""Timeline per e da altri montaggi: EDL, FCPXML, OTIO.

Andata e ritorno: quello che esce deve rientrare uguale (tratti, posizioni,
tracce, dissolvenze), e quello che non puo' uscire va detto negli avvisi.
"""

import json
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import interscambio as ix
from vedit import mcp_server as srv
from vedit.store import Store


def _montaggio(assets) -> Store:
    """V1: due clip con audio collegato e una dissolvenza; V2: una clip a 2x; un titolo."""
    s = Store.create("scambio", "720p")
    s.set_settings(fps=25)
    rosso = s.import_media([assets["red"]])[0]
    blu = s.import_media([assets["blue"]])[0]
    # tempi a fotogramma pieno (25 fps): i formati contano in fotogrammi interi
    a = s.add_clip(rosso.id, duration=3, in_=0.4, audio_collegato=True)
    b = s.add_clip(blu.id, duration=3, in_=1.0, audio_collegato=True)
    s.crossfade(a.id, b.id, 1.0)
    v2 = s.add_track("video")
    c = s.add_clip(rosso.id, v2.id, start=1.0, in_=1.0, duration=1.0)
    s.set_speed(c.id, 2.0, keep_duration=True)
    s.add_text("titolo", duration=1)
    return s


def _vista(s: Store) -> list:
    return [(t.kind, [(round(c.start, 2), round(c.duration, 2), round(c.in_, 2), c.speed,
                       round(c.fade_out, 2)) for c in t.clips if c.type == "media"])
            for t in s.project.tracks if any(c.type == "media" for c in t.clips)]


@pytest.mark.parametrize("ext", [".otio", ".fcpxml"])
def test_andata_e_ritorno(tmp_path, assets, ext):
    s = _montaggio(assets)
    r = ix.esporta(s.project, str(tmp_path / f"t{ext}"))
    assert any("testo" in w for w in r["avvisi"])        # il titolo non esce, e lo dice
    n = Store.create("n", "720p")
    n.set_settings(fps=25)
    ri = ix.importa(n, r["file"])
    assert ri["transizioni"] >= 1 and len(n._undo) == 2   # set_settings + un solo import
    orig = _vista(s)
    rientrato = _vista(n)
    # la prima traccia video torna identica, dissolvenza compresa
    assert rientrato[0] == orig[0]
    v2 = next(v for k, v in rientrato[1:] if k == "video")
    if ext == ".otio":
        assert v2 == [(1.0, 1.0, 1.0, 2.0, 0.0)]          # la velocita' viaggia in OTIO
    else:
        assert [x[:3] for x in v2] == [(1.0, 1.0, 1.0)]
        assert any("velocita'" in w for w in r["avvisi"])


def test_edl_cmx3600(tmp_path, assets):
    s = _montaggio(assets)
    r = ix.esporta(s.project, str(tmp_path / "t.edl"))
    testo = (tmp_path / "t.edl").read_text(encoding="utf-8")
    assert testo.startswith("TITLE: scambio")
    righe = [x for x in testo.splitlines() if x[:3].isdigit()]
    # taglio a meta' della dissolvenza di un secondo: 2.5 s = 2 s e 12 fotogrammi a 25 fps
    # A: attacco 0.4 s (10 fotogrammi), accorciata di 13 fino al taglio
    assert righe[0].split()[-4:] == ["00:00:00:10", "00:00:02:22", "01:00:00:00", "01:00:02:12"]
    assert righe[1].split()[-2:] == ["01:00:02:12", "01:00:05:00"]
    assert "* FROM CLIP NAME: red.mp4" in testo
    assert any("una traccia sola" in w for w in r["avvisi"])
    n = Store.create("n", "720p")
    n.set_settings(fps=25)
    ix.importa(n, r["file"])
    assert _vista(n)[0][1] == [(0.0, 2.48, 0.4, 1.0, 0.0), (2.48, 2.52, 1.48, 1.0, 0.0)]


def test_edl_velocita_e_file_per_nome(tmp_path, assets):
    s = Store.create("v", "720p")
    s.set_settings(fps=25)
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, duration=1, in_=1)
    s.set_speed(c.id, 2.0, keep_duration=True)
    ix.esporta(s.project, str(tmp_path / "v.edl"))
    testo = (tmp_path / "v.edl").read_text(encoding="utf-8")
    assert "M2   AX       050.0" in testo
    # senza SOURCE FILE il file si ritrova per nome fra i media del progetto
    testo = "\n".join(x for x in testo.splitlines() if not x.startswith("* SOURCE FILE"))
    n = Store.create("n", "720p")
    n.set_settings(fps=25)
    n.import_media([assets["red"]])
    ix.importa(n, "v.edl", testo=testo)
    c = n.project.tracks[0].clips[0]
    assert (round(c.in_, 2), round(c.duration, 2), c.speed) == (1.0, 1.0, 2.0)


def test_fcpxml_corsie_e_risorse(tmp_path, assets):
    s = _montaggio(assets)
    ix.esporta(s.project, str(tmp_path / "t.fcpxml"))
    root = ET.parse(tmp_path / "t.fcpxml").getroot()
    assert root.get("version") == "1.9"
    assert {a.find("media-rep").get("src").split("/")[-1] for a in root.iter("asset")} == \
        {"red.mp4", "blue.mp4"}
    spine = next(root.iter("spine"))
    assert [e.tag for e in spine] == ["asset-clip", "transition", "asset-clip", "gap"] or \
        [e.tag for e in spine][:3] == ["asset-clip", "transition", "asset-clip"]
    # V2 sta su una corsia sopra; l'audio collegato non si duplica
    lanes = [e.get("lane") for e in root.iter("asset-clip") if e.get("lane")]
    assert lanes == ["1"]


def test_otio_struttura(tmp_path, assets):
    s = _montaggio(assets)
    ix.esporta(s.project, str(tmp_path / "t.otio"))
    doc = json.loads((tmp_path / "t.otio").read_text(encoding="utf-8"))
    assert doc["OTIO_SCHEMA"] == "Timeline.1"
    tracce = doc["tracks"]["children"]
    assert [t["kind"] for t in tracce] == ["Video", "Audio", "Video"]
    v1 = [c["OTIO_SCHEMA"] for c in tracce[0]["children"]]
    assert v1 == ["Clip.1", "Transition.1", "Clip.1"]
    otio = pytest.importorskip("opentimelineio")
    t = otio.adapters.read_from_file(str(tmp_path / "t.otio"))
    assert len(list(t.find_clips())) == 5


def test_import_atomico_e_formato(tmp_path, assets):
    s = _montaggio(assets)
    ix.esporta(s.project, str(tmp_path / "t.otio"))
    testo = (tmp_path / "t.otio").read_text(encoding="utf-8").replace("red.mp4", "manca.mp4")
    n = Store.create("n", "720p")
    with pytest.raises(ValueError, match="non trovati"):
        ix.importa(n, "t.otio", testo=testo)
    assert n.project.media == [] and len(n._undo) == 0
    with pytest.raises(ValueError, match="sconosciuto"):
        ix.esporta(s.project, str(tmp_path / "t.aaf"))


def test_import_si_accoda(tmp_path, assets):
    s = _montaggio(assets)
    ix.esporta(s.project, str(tmp_path / "t.otio"))
    fine = s.project.duration()
    r = ix.importa(s, str(tmp_path / "t.otio"))
    assert r["da"] == round(fine, 3) and r["media_nuovi"] == 0
    assert round(s.project.duration(), 2) == round(2 * fine, 2)


def test_api_timeline(tmp_path, assets):
    api_mod.S.store = None
    with TestClient(api_mod.app) as c:
        c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
        m = c.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]
        c.post("/api/op/add_clip", json={"media_id": m, "duration": 2})
        r = c.post("/api/timeline/export", json={"path": str(tmp_path / "x.fcpxml")})
        assert r.status_code == 200 and r.json()["clip"] == 1
        testo = (tmp_path / "x.fcpxml").read_text(encoding="utf-8")
        r = c.post("/api/timeline/import", json={"path": "x.fcpxml", "testo": testo})
        assert r.status_code == 200 and r.json()["clip"] == 1
        assert c.post("/api/timeline/export", json={"path": str(tmp_path / "x.aaf")}).status_code == 400


@pytest.mark.anyio
async def test_strumenti_mcp():
    nomi = {t.name for t in await srv.mcp.list_tools()}
    assert {"export_timeline", "import_timeline"} <= nomi
