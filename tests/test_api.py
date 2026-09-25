"""API della UI. Le stesse operazioni del server MCP, esposte via HTTP."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod


@pytest.fixture
def client(tmp_path):
    api_mod.S.store = None
    api_mod.S.jobs.clear()
    with TestClient(api_mod.app) as c:
        yield c


def _create(client, tmp_path, preset="720p"):
    r = client.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": preset})
    assert r.status_code == 200
    return r.json()


def test_stato_iniziale(client):
    s = client.get("/api/state").json()
    assert s["project"] is None
    assert any(e["name"] == "chromakey" for e in s["effects"])
    assert "1080p" in s["presets"]
    assert s["system"]["ffmpeg"]


def test_operazioni_e_revisione(client, tmp_path, assets):
    _create(client, tmp_path)
    rev0 = client.get("/api/state").json()["revision"]

    r = client.post("/api/op/import_media", json={"paths": [assets["red"]]})
    assert r.status_code == 200
    media_id = r.json()["result"][0]["id"]

    r = client.post("/api/op/add_clip", json={"media_id": media_id, "duration": 2.0})
    body = r.json()
    assert body["project"]["duration"] == pytest.approx(2.0)
    assert body["revision"] != rev0  # la revisione invalida le anteprime in cache

    clip_id = body["result"]["id"]
    r = client.post("/api/op/split_clip", json={"clip_id": clip_id, "at": 1.0})
    assert r.status_code == 200
    assert len(r.json()["project"]["tracks"][0]["clips"]) == 2

    # undo/redo passano dallo stesso canale
    assert client.post("/api/op/undo", json={}).json()["project"]["tracks"][0]["clips"].__len__() == 1
    assert client.post("/api/op/redo", json={}).json()["project"]["tracks"][0]["clips"].__len__() == 2


def test_errori_http(client, tmp_path):
    assert client.post("/api/op/add_clip", json={"media_id": "x"}).status_code == 400
    _create(client, tmp_path)
    r = client.post("/api/op/add_clip", json={"media_id": "fantasma"})
    assert r.status_code == 400 and "inesistente" in r.json()["detail"]

    assert client.post("/api/op/formatta_il_disco", json={}).status_code == 404
    r = client.post("/api/op/add_clip", json={"parametro_sbagliato": 1})
    assert r.status_code == 400


def test_browse(client, tmp_path, assets):
    r = client.get("/api/browse", params={"path": str(Path(assets["red"]).parent)})
    data = r.json()
    assert any(f["name"] == "red.mp4" for f in data["files"])
    assert data["parent"]
    assert client.get("/api/browse", params={"path": str(tmp_path / "nope")}).status_code == 404


@pytest.mark.slow
def test_frame_e_anteprima(client, tmp_path, assets):
    _create(client, tmp_path)
    # sorgente con dettaglio (testsrc2): un colore piatto comprimerebbe a poche centinaia di byte
    mid = client.post("/api/op/import_media", json={"paths": [assets["blue"]]}).json()["result"][0]["id"]
    client.post("/api/op/add_clip", json={"media_id": mid, "duration": 2.0})

    r = client.get("/api/frame", params={"t": 1.0, "width": 320})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 1000

    r = client.get("/api/preview", params={"start": 0.0, "duration": 1.0, "height": 180})
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert len(r.content) > 1000


def test_cartelle_del_bin(client, tmp_path, assets):
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]

    r = client.post("/api/op/set_media", json={"media_id": mid, "folder": "b-roll/citta"})
    assert r.json()["project"]["media"][0]["folder"] == "b-roll/citta"

    r = client.post("/api/op/rename_folder", json={"old": "b-roll", "new": "riprese"})
    assert r.json()["result"] == 1
    assert client.get("/api/state").json()["project"]["media"][0]["folder"] == "riprese/citta"

    # un media in uso non sparisce per sbaglio
    client.post("/api/op/add_clip", json={"media_id": mid, "duration": 1.0})
    r = client.post("/api/op/remove_media", json={"media_id": mid})
    assert r.status_code == 400 and "force" in r.json()["detail"]
    r = client.post("/api/op/remove_media", json={"media_id": mid, "force": True})
    assert r.json()["result"]["clip_eliminate"] == 1


def test_transizione_via_api(client, tmp_path, assets):
    _create(client, tmp_path)
    ids = [m["id"] for m in client.post(
        "/api/op/import_media", json={"paths": [assets["red"], assets["green"]]}).json()["result"]]
    a = client.post("/api/op/add_clip", json={"media_id": ids[0], "duration": 2.0}).json()["result"]
    b = client.post("/api/op/add_clip", json={"media_id": ids[1], "duration": 2.0}).json()["result"]

    r = client.post("/api/op/crossfade",
                    json={"clip_a": a["id"], "clip_b": b["id"], "duration": 0.5, "type": "iris"})
    assert r.json()["result"]["type"] == "iris"
    clip = r.json()["project"]["tracks"][0]["clips"][0]
    assert clip["transition"]["type"] == "iris"

    r = client.post("/api/op/crossfade",
                    json={"clip_a": a["id"], "clip_b": b["id"], "type": "tenda"})
    assert r.status_code == 400 and "sconosciuta" in r.json()["detail"]


@pytest.mark.slow
def test_filmstrip_e_stream(client, tmp_path, assets):
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["blue"]]}).json()["result"][0]["id"]

    info = client.get(f"/api/media/{mid}/strip", params={"height": 40}).json()
    assert info["tiles"] >= 1 and info["tile_height"] == 40
    assert client.get(info["url"].replace("/api/file?path=", "/api/file?path=")).status_code == 200

    r = client.get(f"/api/media/{mid}/stream")
    assert r.status_code == 200 and len(r.content) > 1000

    wf = client.get(f"/api/media/{mid}/waveform").json()
    assert len(wf["peaks"]) > 5 and max(wf["peaks"]) <= 1.0


@pytest.mark.slow
def test_upload_da_drag_and_drop(client, tmp_path, assets):
    _create(client, tmp_path)
    with open(assets["green"], "rb") as fh:
        r = client.post("/api/upload", files={"files": ("green.mp4", fh, "video/mp4")},
                        data={"folder": "trascinati"})
    body = r.json()
    assert len(body["importati"]) == 1
    m = body["project"]["media"][0]
    assert m["folder"] == "trascinati"
    assert (tmp_path / "media" / "green.mp4").exists()


@pytest.mark.slow
def test_prefetch_segmento(client, tmp_path, assets):
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]
    client.post("/api/op/add_clip", json={"media_id": mid, "duration": 3.0})

    assert client.post("/api/preview/prefetch",
                       params={"start": 1.0, "duration": 1.0, "height": 90}).json()["avviato"]
    # oltre la fine non c'e' niente da preparare
    assert client.post("/api/preview/prefetch", params={"start": 99.0}).json().get("skip")

    for _ in range(60):
        r = client.get("/api/preview", params={"start": 1.0, "duration": 1.0, "height": 90})
        if r.status_code == 200:
            break
        time.sleep(0.5)
    assert r.status_code == 200


@pytest.mark.slow
def test_render_in_background(client, tmp_path, assets):
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]
    client.post("/api/op/add_clip", json={"media_id": mid, "duration": 1.0})

    out = str(tmp_path / "out.mp4")
    job = client.post("/api/render", json={"output": out, "quality": "draft"}).json()
    assert job["state"] == "running"

    for _ in range(120):
        job = client.get(f"/api/render/{job['id']}").json()
        if job["state"] != "running":
            break
        time.sleep(0.5)
    assert job["state"] == "done", job.get("error")
    assert Path(out).stat().st_size > 0


@pytest.mark.slow
def test_frame_prova_effetto_non_tocca_il_progetto(client, tmp_path, assets):
    """L'anteprima al passaggio del mouse mostra l'effetto senza applicarlo."""
    _create(client, tmp_path)
    m = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()
    media_id = m["result"][0]["id"]
    clip = client.post("/api/op/add_clip", json={"media_id": media_id}).json()["result"]["id"]

    prima = client.get("/api/state").json()["revision"]
    normale = client.get("/api/frame", params={"t": 1.0, "width": 240})
    provato = client.get("/api/frame",
                         params={"t": 1.0, "width": 240, "effect": "pixelate", "clip": clip})
    assert normale.status_code == 200 and provato.status_code == 200
    assert normale.content != provato.content        # l'effetto si vede
    # la revisione e' l'impronta dell'intero progetto: se non cambia, l'effetto
    # non e' finito da nessuna parte
    stato = client.get("/api/state").json()
    assert stato["revision"] == prima
    # la revisione e' in cache sul contatore delle modifiche: il controllo vero
    # e' che la clip non abbia preso l'effetto
    assert not stato["project"]["tracks"][0]["clips"][0].get("effects")

    assert client.get("/api/frame", params={"t": 1.0, "effect": "inesistente"}).status_code == 400


def test_ordine_effetti_via_api(client, tmp_path, assets):
    """L'ordine della catena si cambia dalla UI, non solo da MCP.

    Denoise prima di sharpen pulisce e poi incide; l'ordine opposto incide
    anche il rumore. Se ``move_effect`` non e' fra le operazioni esposte, chi
    monta dall'interfaccia quella scelta non ce l'ha.
    """
    _create(client, tmp_path)
    media_id = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]
    clip = client.post("/api/op/add_clip", json={"media_id": media_id, "duration": 2.0}).json()["result"]["id"]

    for effetto in ("denoise", "sharpen"):
        assert client.post("/api/op/add_effect", json={"clip_id": clip, "effect": effetto}).status_code == 200

    def ordine():
        stato = client.get("/api/state").json()
        c = stato["project"]["tracks"][0]["clips"][0]
        # l'indice serve alla UI per indirizzare l'effetto: dev'esserci ed essere progressivo
        assert [e["i"] for e in c["effects"]] == list(range(len(c["effects"])))
        return [e["type"] for e in c["effects"]]

    assert ordine() == ["denoise", "sharpen"]

    r = client.post("/api/op/move_effect", json={"clip_id": clip, "index": 1, "to": 0})
    assert r.status_code == 200, r.text
    assert ordine() == ["sharpen", "denoise"]

    client.post("/api/op/undo", json={})
    assert ordine() == ["denoise", "sharpen"]


def test_stato_progetto_e_sequenza(client, tmp_path, assets):
    """Ogni risposta porta revisione e numero di modifica: la UI applica solo lo stato piu' nuovo."""
    r = _create(client, tmp_path)
    assert r["revision"] != "0" and r["seq"] >= 1 and r["path"].endswith("p.json")

    # /api/project e' quello che la UI chiede a ogni evento "project"
    p = client.get("/api/project").json()
    assert p["revision"] == r["revision"] and p["seq"] == r["seq"]

    mid = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()
    assert mid["seq"] > r["seq"]
    dopo = client.post("/api/op/add_clip", json={"media_id": mid["result"][0]["id"]}).json()
    assert dopo["seq"] > mid["seq"] and dopo["revision"] != mid["revision"]
    assert client.get("/api/project").json()["seq"] == dopo["seq"]

    # aprire un altro progetto cambia la revisione: le anteprime in cache non valgono piu'
    r2 = client.post("/api/project/create", json={"path": str(tmp_path / "q.json")}).json()
    assert r2["revision"] != dopo["revision"]


def test_progetti_recenti(client, tmp_path):
    _create(client, tmp_path)
    client.post("/api/project/create", json={"path": str(tmp_path / "secondo.json"), "name": "due"})
    rec = client.get("/api/recenti").json()
    assert [r["name"] for r in rec][:2] == ["due", "untitled"]
    assert rec[0]["path"].endswith("secondo.json")
    assert client.get("/api/state").json()["recenti"][0]["name"] == "due"

    # un progetto sparito dal disco non viene proposto
    (tmp_path / "secondo.json").unlink()
    assert all(not r["path"].endswith("secondo.json") for r in client.get("/api/recenti").json())

    # riaprire un progetto lo rimette in cima
    r = client.post("/api/project/open", json={"path": str(tmp_path / "p.json")})
    assert r.status_code == 200 and r.json()["recenti"][0]["path"].endswith("p.json")
    assert client.post("/api/project/open", json={"path": str(tmp_path / "manca.json")}).status_code == 400


def test_set_clip_resta_dentro_la_sorgente(client, tmp_path, assets):
    """Dal pannello proprieta' si scrive la durata a mano: oltre il file si vedrebbe nero."""
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]
    cid = client.post("/api/op/add_clip", json={"media_id": mid, "duration": 2.0}).json()["result"]["id"]

    r = client.post("/api/op/set_clip", json={"clip_id": cid, "duration": 100.0}).json()
    assert r["result"]["duration"] == pytest.approx(5.0, abs=0.05)
    r = client.post("/api/op/set_clip", json={"clip_id": cid, "in_": 4.0}).json()
    assert r["result"]["in"] == pytest.approx(4.0) and r["result"]["duration"] == pytest.approx(1.0, abs=0.05)
    assert client.post("/api/op/set_clip", json={"clip_id": cid, "duration": -1}).status_code == 400
    assert client.post("/api/op/set_clip", json={"clip_id": cid, "start": -3}).status_code == 400
