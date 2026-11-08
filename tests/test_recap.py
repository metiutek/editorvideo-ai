"""Invarianti del piano e integrazione con l'editor, senza chiamate a pagamento."""
import copy
import json
from pathlib import Path

import pytest

from vedit import recap
from vedit.model import Media
from vedit.store import EditError, Store


def progetto(tmp_path):
    s = Store.create(path=str(tmp_path/"recap.json"), width=320, height=180)
    s.project.media = [Media(id="a", path=str(tmp_path/"one.mp4"), duration=12),
                       Media(id="b", path=str(tmp_path/"two.mp4"), duration=12),
                       Media(id="song", kind="audio", duration=20)]
    return s


def eventi():
    return [{"id": "first", "name": "Arrival", "media": ["a"], "weight": 1},
            {"id": "second", "name": "Celebration", "media": ["b"], "weight": 2}]


def analisi_finta(m, *args):
    return [{"media": m.id, "in": i*3, "end": i*3+3, "hash": str((2**(i*12)-1)),
             "subject": f"subject {i}", "score": .9-i*.1} for i in range(4)]


@pytest.fixture
def analisi(monkeypatch):
    monkeypatch.setattr(recap, "analizza", analisi_finta)
    monkeypatch.setattr(recap.analyze, "beats", lambda p: {"profilo": [{"t": 0, "energia": .5}, {"t": 4, "energia": 1}]})
    monkeypatch.setattr(recap.analyze, "beat_grid", lambda *a, **k: [i*.5 for i in range(41)])


def test_quote():
    assert recap.assegna(120, [100, 100], [1, 3], [None, None], 15) == [38, 82]
    assert recap.assegna(120, [30, 150], [1, 1], [None, None], 15) == [30, 90]
    assert recap.assegna(120, [100, 100], [1, 1], [40, None], 15) == [40, 80]
    for args in [(20, [100, 100], [1, 1], [None, None], 15),
                 (120, [30, 30], [1, 1], [None, None], 15),
                 (120, [100, 100], [1, 1], [40, 40], 15)]:
        with pytest.raises(recap.RecapError):
            recap.assegna(*args)


def test_ordine_intervalli_salvataggio_undo(tmp_path, analisi):
    s = progetto(tmp_path)
    prima = s.project.to_dict()
    plan = recap.pianifica(s.project, eventi(), "song", 9, consenso=True)
    indices = [next(i for i, e in enumerate(eventi()) if e["id"] == c["activity"]) for c in plan["clips"]]
    assert indices == sorted(indices) and set(indices) == {0, 1}
    assert sum(c["duration"] for c in plan["clips"]) == pytest.approx(9)
    for i, a in enumerate(plan["clips"]):
        assert 0 <= a["in"] < a["in"]+a["duration"] <= 12
        for b in plan["clips"][i+1:]:
            if a["media"] == b["media"]:
                assert a["in"]+a["duration"] <= b["in"] or b["in"]+b["duration"] <= a["in"]
    result = s.apply_recap(plan)
    assert len(result["clips"]) > 2
    assert s.undo() and s.project.to_dict() == prima
    assert s.redo()
    c = next(c for tr in s.project.tracks for c in tr.clips if c.id == result["clips"][0])
    s.trim_clip(c.id, duration=c.duration/2)
    s.move_clip(c.id, start=.1)
    s.set_transform(c.id, opacity={"kf": [{"t": 0, "v": 0}, {"t": .2, "v": 1}]})
    s.save()
    reopened = Store.open(s.path)
    assert reopened.project.to_dict() == s.project.to_dict()
    assert any(c.get("provenance") for t in s.summary("full")["tracks"] for c in t["clips"])
    assert any(t.kind == "audio" and t.clips for t in reopened.project.tracks)


@pytest.mark.parametrize("damage", ["order", "range", "overlap", "missing", "membership", "music"])
def test_rifiuto_atomico(tmp_path, analisi, damage):
    s = progetto(tmp_path)
    p = recap.pianifica(s.project, eventi(), "song", 9, consenso=True)
    if damage == "order":
        p["clips"].reverse()
    elif damage == "range":
        p["clips"][0]["in"] = 100
    elif damage == "overlap":
        same = [c for c in p["clips"] if c["media"] == "b"]
        same[1]["in"] = same[0]["in"]
    elif damage == "missing":
        p["clips"] = [c for c in p["clips"] if c["activity"] != "first"]
    elif damage == "membership":
        p["clips"][0]["media"] = "b"
    else:
        s.project.media[-1].duration = .1
    prima = copy.deepcopy(s.project.to_dict())
    with pytest.raises(EditError):
        s.apply_recap(p)
    assert s.project.to_dict() == prima and not s._undo


def test_cancellazione_e_materiale_insufficiente(tmp_path, analisi, monkeypatch):
    s = progetto(tmp_path)
    with pytest.raises(recap.RecapError, match="cancelled"):
        recap.pianifica(s.project, eventi(), "song", 9, fermo=lambda: True)
    with pytest.raises(recap.RecapError, match="too short"):
        recap.pianifica(s.project, eventi(), "song", .5)
    monkeypatch.setattr(recap, "analizza", lambda *a: [])
    with pytest.raises(recap.RecapError, match="Arrival"):
        recap.pianifica(s.project, eventi(), "song", 9)


def test_consenso():
    with pytest.raises(recap.RecapError, match="Allow visual analysis"):
        recap.analizza(Media(), False)


def test_target_e_peso_prima_del_modello(tmp_path, analisi, monkeypatch):
    s = progetto(tmp_path)
    def vietata(*args):
        pytest.fail("Invalid settings must not trigger paid analysis")
    monkeypatch.setattr(recap, "analizza", vietata)
    gruppi = eventi()
    gruppi[1]["weight"] = 0
    with pytest.raises(recap.RecapError, match="positive"):
        recap.pianifica(s.project, gruppi, "song", 9)
    gruppi = eventi()
    gruppi[0]["target"] = 12
    with pytest.raises(recap.RecapError, match="targets exceed"):
        recap.pianifica(s.project, gruppi, "song", 9)


def test_target_esatti_e_battiti(tmp_path, analisi):
    s = progetto(tmp_path)
    gruppi = eventi()
    gruppi[0]["target"] = 3.3
    piano = recap.pianifica(s.project, gruppi, "song", 9, consenso=True)
    primo = [c for c in piano["clips"] if c["activity"] == "first"]
    assert sum(c["duration"] for c in primo) == pytest.approx(3.3)
    # Il primo taglio interno usa un battito; il confine dell'attivita' mantiene il target.
    assert (primo[0]["start"]+primo[0]["duration"])*2 == pytest.approx(round((primo[0]["start"]+primo[0]["duration"])*2))
    assert any(c["start"] == pytest.approx(3.3) for c in piano["clips"])


def test_stessa_sorgente_in_due_attivita(tmp_path, analisi):
    s = progetto(tmp_path)
    gruppi = eventi()
    gruppi[1]["media"] = ["a"]
    with pytest.raises(recap.RecapError, match="only one activity"):
        recap.pianifica(s.project, gruppi, "song", 9, consenso=True)


@pytest.mark.parametrize("azione", ["cancel", "edit", "success", "failure"])
def test_lavoro_api(tmp_path, analisi, monkeypatch, azione):
    import threading
    import time
    from vedit import api
    s = progetto(tmp_path)
    monkeypatch.setattr(api.S, "store", s)
    monkeypatch.setattr(api.S, "jobs", {})
    monkeypatch.setattr(recap, "identita", lambda: {"model": "test"})
    piano = recap.pianifica(s.project, eventi(), "song", 9, consenso=True)
    iniziato, continua = threading.Event(), threading.Event()
    def lavora(*args):
        iniziato.set()
        assert continua.wait(5)
        if azione == "failure":
            raise RuntimeError("model unavailable")
        return piano
    monkeypatch.setattr(recap, "pianifica", lavora)
    with pytest.raises(api.HTTPException):
        api.recap_start({"consent": False})
    job = api.recap_start({"consent": True, "activities": eventi(), "music": "song", "duration": 9})
    assert iniziato.wait(5)
    if azione == "cancel":
        api.recap_cancel(job["id"])
    elif azione == "edit":
        s.rename("changed")
    continua.set()
    fine = time.monotonic()+5
    while api.recap_status(job["id"])["state"] == "running" and time.monotonic() < fine:
        time.sleep(.01)
    stato = api.recap_status(job["id"])["state"]
    assert stato == {"success": "done", "cancel": "cancelled", "edit": "error", "failure": "error"}[azione]
    assert bool(any(t.clips for t in s.project.tracks)) == (azione == "success")


def test_contatti_cache_modello_e_id(assets, monkeypatch):
    m = Media(id="first-id", path=assets["blue"], duration=4)
    monkeypatch.setattr(recap, "identita", lambda: {"model": "test-vision"})
    chiamate = []
    def visione(prompt, paths, **kw):
        assert Path(paths[0]).is_file()
        chiamate.append(paths)
        return json.dumps([{"index": 0, "usable": True, "clarity": .9, "stability": .8,
                            "representative": .9, "subject": "synthetic test scene"}])
    monkeypatch.setattr(recap.llm, "chiedi_con_immagini", visione)
    monkeypatch.setattr(recap.analyze, "scenes", lambda p: [0])
    a = recap.analizza(m, True)
    m.id = "new-project-id"
    b = recap.analizza(m, True)
    assert len(chiamate) == 1 and a[0]["media"] == "first-id" and b[0]["media"] == m.id
    monkeypatch.setattr(recap, "identita", lambda: {"model": "different-vision"})
    recap.analizza(m, True)
    assert len(chiamate) == 2


@pytest.mark.slow
def test_cartelle_musica_edit_export(tmp_path, assets, monkeypatch):
    """Video/analisi locale/export veri; soltanto le valutazioni LLM sono simulate."""
    import shutil
    from vedit.render import RenderOptions, render
    from vedit.probe import probe
    s = Store.create(path=str(tmp_path/"event-recap.json"), width=320, height=180)
    groups = []
    for i in range(2):
        folder = tmp_path/f"Activity-{i}"
        folder.mkdir()
        paths = []
        for j, key in enumerate(("blue", "green")):
            dst = folder/f"source-{j}.mp4"
            shutil.copyfile(assets[key], dst)
            paths.append(str(dst))
        imported = s.import_media(paths, folder=folder.name)
        groups.append({"id": folder.name, "name": folder.name, "media": [m.id for m in imported]})
    music = s.import_media([assets["music"]])[0]
    monkeypatch.setattr(recap, "identita", lambda: {"model": "test-e2e"})
    def vision(prompt, paths, **kw):
        from PIL import Image
        with Image.open(paths[0]) as im:
            n = im.height//166
        return json.dumps([{"index": i, "usable": True, "clarity": .9, "stability": .9,
                            "representative": .9, "subject": "test action"} for i in range(n)])
    monkeypatch.setattr(recap.llm, "chiedi_con_immagini", vision)
    plan = recap.pianifica(s.project, groups, music.id, 4, consenso=True)
    ids = s.apply_recap(plan)["clips"]
    s.trim_clip(ids[0], duration=plan["clips"][0]["duration"]-.1)
    s.move_clip(ids[0], start=.1)
    s.set_transform(ids[0], scale={"kf": [{"t": 0, "v": 1}, {"t": .5, "v": 1.1}]})
    s.save()
    reopened = Store.open(s.path)
    assert reopened.project.to_dict() == s.project.to_dict()
    dst = str(tmp_path/"recap.mp4")
    render(reopened.project, RenderOptions(output=dst, prefer_hw=False, quality="draft", jobs=1))
    assert probe(dst).duration == pytest.approx(4, abs=.15)
