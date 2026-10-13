"""Import di tanti file: a blocchi, per riferimento, a pezzi riprendibili."""

import os
import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod
from vedit import probe, proxy
from vedit.store import Store


@pytest.fixture
def client(tmp_path):
    api_mod.S.store = None
    api_mod.S.jobs.clear()
    with TestClient(api_mod.app) as c:
        c.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": "720p"})
        yield c


def test_probe_many_un_esito_per_file(assets, tmp_path):
    rotto = tmp_path / "rotto.mp4"
    rotto.write_bytes(b"non sono un video")
    esiti = probe.probe_many([assets["red"], str(rotto), assets["blue"], assets["red"]])
    assert len(esiti) == 3                                   # i doppioni una volta sola
    assert esiti[assets["red"]].kind == "video"
    assert isinstance(esiti[str(rotto)], Exception)


def test_store_import_con_cartella_e_un_solo_passo_di_undo(tmp_path, assets):
    s = Store.create(name="t", path=str(tmp_path / "p.json"))
    passi = len(s._undo)
    media = s.import_media([assets["red"], assets["blue"], assets["red"]], folder="giorno 1/")
    assert [m.name for m in media] == ["red.mp4", "blue.mp4"]
    assert all(m.folder == "giorno 1" for m in media)
    assert len(s._undo) == passi + 1


def test_import_scarta_i_file_rotti_senza_annullare_gli_altri(client, tmp_path, assets):
    rotto = tmp_path / "rotto.mp4"
    rotto.write_bytes(b"\x00" * 100)
    r = client.post("/api/import", json={"paths": [assets["red"], str(rotto)], "folder": "scheda"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["importati"]) == 1
    assert [x["path"] for x in body["scartati"]] == [str(rotto)]
    # il motivo, non la coda del JSON di ffprobe ne' il percorso ripetuto
    motivo = body["scartati"][0]["errore"]
    assert motivo.strip("{} ") and "rotto.mp4" not in motivo
    assert body["project"]["media"][0]["folder"] == "scheda"

    # rimandare lo stesso blocco non duplica niente
    again = client.post("/api/import", json={"paths": [assets["red"]]}).json()
    assert again["importati"] == body["importati"] and len(again["project"]["media"]) == 1


def test_scan_scende_nelle_sottocartelle(client, tmp_path, assets):
    base = tmp_path / "scheda"
    (base / "A001").mkdir(parents=True)
    (base / ".nascosta").mkdir()
    shutil.copy(assets["red"], base / "clip1.mp4")
    shutil.copy(assets["blue"], base / "A001" / "clip2.mp4")
    shutil.copy(assets["blue"], base / ".nascosta" / "no.mp4")
    (base / "note.txt").write_text("x")

    r = client.get("/api/scan", params={"path": str(base)}).json()
    assert r["nome"] == "scheda"
    assert [(Path(f["path"]).name, f["cartella"]) for f in r["files"]] == [
        ("clip1.mp4", ""), ("clip2.mp4", "A001")]
    assert r["byte"] == sum(f["size"] for f in r["files"])


def _pezzo(client, nome, dati, offset, mtime=123):
    return client.put("/api/upload/pezzo", content=dati,
                      params={"nome": nome, "size": TOT[nome], "offset": offset, "mtime": mtime})


TOT: dict = {}


def test_upload_a_pezzi_riprende_e_non_ricopia(client, tmp_path, assets):
    dati = Path(assets["green"]).read_bytes()
    TOT["green.mp4"] = len(dati)
    meta = len(dati) // 2
    q = {"nome": "green.mp4", "size": len(dati), "mtime": 123}

    assert client.get("/api/upload/stato", params=q).json()["ricevuti"] == 0
    assert _pezzo(client, "green.mp4", dati[:meta], 0).json() == {"ricevuti": meta, "completo": False}
    # interrotto qui: lo stato dice da dove riprendere
    assert client.get("/api/upload/stato", params=q).json()["ricevuti"] == meta
    # un pezzo che salta avanti non lascia buchi
    assert _pezzo(client, "green.mp4", dati[meta + 10:], meta + 10).status_code == 409

    fine = _pezzo(client, "green.mp4", dati[meta:], meta).json()
    assert fine["completo"]
    arrivato = Path(fine["path"])
    assert arrivato == tmp_path / "media" / "green.mp4" and arrivato.read_bytes() == dati
    assert not list((tmp_path / "media" / ".parti").glob("*.part"))

    # lo stesso file trascinato di nuovo: gia' arrivato, niente da mandare
    stato = client.get("/api/upload/stato", params=q).json()
    assert stato["completo"] and stato["path"] == str(arrivato)

    # un file diverso con lo stesso nome non sovrascrive il primo
    altro = Path(assets["red"]).read_bytes()
    TOT["green.mp4"] = len(altro)
    secondo = _pezzo(client, "green.mp4", altro, 0, mtime=999).json()
    assert Path(secondo["path"]).name == "green_1.mp4" and arrivato.read_bytes() == dati

    r = client.post("/api/import", json={"paths": [fine["path"], secondo["path"]]}).json()
    assert len(r["importati"]) == 2


def test_upload_rifiuta_pezzi_oltre_la_dimensione(client):
    TOT["x.mp4"] = 10
    assert _pezzo(client, "x.mp4", b"0" * 20, 0).status_code == 400


def test_upload_aspetta_il_file_bloccato_dall_antivirus(client, assets, monkeypatch):
    """Su Windows l'antivirus tiene il .part appena chiuso: si riprova, non si esplode."""
    monkeypatch.setattr(api_mod, "_ATTESE_BLOCCO", (0.01, 0.01, 0.01))
    vero = os.replace
    bloccati = [2]

    def replace_occupato(a, b):
        if str(a).endswith(".part") and bloccati[0]:
            bloccati[0] -= 1
            raise PermissionError(32, "Il file è utilizzato da un altro processo")
        return vero(a, b)

    monkeypatch.setattr(api_mod.os, "replace", replace_occupato)
    dati = Path(assets["red"]).read_bytes()
    TOT["bloccato.mp4"] = len(dati)
    r = _pezzo(client, "bloccato.mp4", dati, 0)
    assert r.status_code == 200 and r.json()["completo"] and bloccati[0] == 0


def test_upload_bloccato_per_sempre_da_503_non_500(client, monkeypatch):
    monkeypatch.setattr(api_mod, "_ATTESE_BLOCCO", (0.01,))
    vero_open = Path.open

    def open_occupato(self, *a, **k):
        if self.suffix == ".part":
            raise PermissionError(13, "Permission denied")
        return vero_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", open_occupato)
    TOT["sempre.mp4"] = 4
    r = _pezzo(client, "sempre.mp4", b"abcd", 0)
    assert r.status_code == 503        # il browser lo rimanda da solo


def test_due_upload_dello_stesso_file_non_si_pestano(client, assets):
    dati = Path(assets["blue"]).read_bytes()
    TOT["doppio.mp4"] = len(dati)
    esiti = []

    def manda():
        esiti.append(_pezzo(client, "doppio.mp4", dati, 0))

    fili = [threading.Thread(target=manda) for _ in range(3)]
    for t in fili:
        t.start()
    for t in fili:
        t.join()
    corpi = [r.json() for r in esiti if r.status_code == 200]
    assert corpi and all(c["completo"] for c in corpi)
    assert len({c["path"] for c in corpi}) == 1          # un file solo, non tre
    assert Path(corpi[0]["path"]).read_bytes() == dati


def test_nome_caricato_senza_percorsi_ne_caratteri_proibiti():
    assert api_mod._nome_sicuro("..\\..\\a:b?.mp4") == "a_b_.mp4"
    assert api_mod._nome_sicuro("../") == "file"


def test_lavori_pesanti_in_coda_e_uno_solo_per_risultato(monkeypatch):
    monkeypatch.setattr(proxy, "_PESANTI", threading.BoundedSemaphore(2))
    attivi, picco, fatti = [0], [0], []
    lock = threading.Lock()

    def lavoro(chiave):
        with proxy.lavoro_pesante(chiave):
            with lock:
                attivi[0] += 1
                picco[0] = max(picco[0], attivi[0])
            time.sleep(0.05)
            fatti.append(chiave)
            with lock:
                attivi[0] -= 1

    stessa = [threading.Thread(target=lavoro, args=("uguale",)) for _ in range(3)]
    altre = [threading.Thread(target=lavoro, args=(f"k{i}",)) for i in range(6)]
    for t in stessa + altre:
        t.start()
    for t in stessa + altre:
        t.join()
    assert picco[0] <= 2 and len(fatti) == 9


@pytest.mark.slow
def test_striscia_coi_soli_keyframe(tmp_path, assets):
    """Sui file lunghi la striscia legge solo i keyframe e deve uscire lo stesso."""
    from PIL import Image

    m = probe.probe(assets["blue"])
    dst = tmp_path / "s.jpg"
    proxy._genera_striscia(m.path, dst, 2.0, 40, 22, 3)
    assert Image.open(dst).size == (120, 22)
