"""Piano da approvare prima di montare (piano.py, propose_plan): forma delle scene, totali,
domanda nell'editor, file accanto al progetto, e il no dell'utente che ferma tutto."""

import json

import pytest

from vedit import api as api_mod
from vedit import chat, domande, piano
from vedit import mcp_server as srv
from vedit.store import EditError, Store
from test_mcp import call

SCENE = [
    {"what": "Drone shot of the coast at sunrise", "duration": 4, "source": "generated_video", "cost": 1.5},
    {"what": "Interview, host speaks to camera", "duration": 20, "source": "footage"},
    {"what": "Chart of visitors per year", "duration": 6, "source": "graphic", "note": "line_chart"},
    {"what": "Closing shot", "duration": 5, "source": "generated_image"},
]


def test_scene_valide_e_totali():
    sc = piano.valida(SCENE)
    assert sc[0] == {"what": "Drone shot of the coast at sunrise", "duration": 4.0,
                     "source": "generated_video", "cost": 1.5}
    assert sc[3]["cost"] is None                       # genera e costa: segnato anche senza stima
    assert "cost" not in sc[1] and sc[2]["note"] == "line_chart"
    t = piano.totali(sc)
    assert t == {"scene": 4, "durata": 35.0, "generazioni": 2, "senza_stima": 1, "costo_stimato": 1.5}
    assert piano.totali(piano.valida(SCENE[1:3]))["costo_stimato"] is None


def test_errori_con_l_elenco_di_quelli_ammessi():
    with pytest.raises(ValueError, match="non-empty list"):
        piano.valida([])
    with pytest.raises(ValueError, match="scene 1 needs the 'what'"):
        piano.valida([{"duration": 3}])
    with pytest.raises(ValueError, match="scene 1 needs 'duration'"):
        piano.valida([{"what": "x"}])
    with pytest.raises(ValueError, match="out of range"):
        piano.valida([{"what": "x", "duration": 9999}])
    with pytest.raises(ValueError, match="unknown source 'telepatia'.*footage"):
        piano.valida([{"what": "x", "duration": 3, "source": "telepatia"}])
    with pytest.raises(ValueError, match="cost cannot be negative"):
        piano.valida([{"what": "x", "duration": 3, "cost": -1}])
    with pytest.raises(ValueError, match="cost must be a number"):
        piano.valida([{"what": "x", "duration": 3, "cost": "tanto"}])
    with pytest.raises(ValueError, match="at most 40 scenes"):
        piano.valida([{"what": "x", "duration": 1}] * 41)


def test_il_testo_dice_tempi_e_costi():
    t = piano.testo("Coast film", piano.valida(SCENE), "Music: calm piano")
    assert t.startswith("Coast film\n1. 0:00-0:04  [generated_video]")
    assert "2. 0:04-0:24  [footage] Interview" in t and "(line_chart)" in t
    assert "generated, ~1.5" in t and "generated, cost unknown" in t
    assert "2 generated (these cost credits, estimated 1.5 by the assistant, 1 without an estimate)" in t
    assert t.endswith("Music: calm piano") and "4 scenes, 0:35 long" in t
    senza = piano.testo("", piano.valida(SCENE[1:3]))
    assert "credits" not in senza and "2 scenes" in senza


def test_la_domanda_e_valida_e_avvisa_che_costa():
    sc = piano.valida(SCENE)
    d = domande.valida(piano.domanda("Coast film", sc))
    assert d[0]["opzioni"][0]["etichetta"] == "Yes, build it" and "credits" in d[0]["opzioni"][0]["descrizione"]
    assert "Coast film" in d[0]["domanda"] and "Interview" in d[0]["domanda"]
    quieta = piano.domanda("", piano.valida(SCENE[1:3]))
    assert "credits" not in quieta[0]["opzioni"][0]["descrizione"]
    assert domande.approvato({"risposte": {"0": "Yes, build it"}})
    assert not domande.approvato({"risposte": {"0": "No, change it"}})
    assert piano.feedback({"risposte": {"0": "Make it shorter"}}) == "Make it shorter"
    assert piano.feedback({"risposte": {"0": "No, change it"}}) == "" and piano.feedback({}) == ""


def test_si_salva_accanto_al_progetto(tmp_path):
    p = str(tmp_path / "film.json")
    assert piano.percorso(p).name == "film.piano.json" and piano.percorso(None) is None
    assert piano.carica(p) is None
    sc = piano.valida(SCENE)
    assert piano.salva(p, "Coast film", sc, "calm") is True
    dati = piano.carica(p)
    assert dati["titolo"] == "Coast film" and dati["approvato"] is True and dati["totali"]["durata"] == 35.0
    assert not list(tmp_path.glob("*.tmp"))                         # scrittura atomica, niente avanzi
    assert piano.salva(None, "x", sc) is False                      # progetto senza file: non si salva
    piano.percorso(p).write_text("{rotto", encoding="utf-8")
    assert piano.carica(p) is None                                  # un file rovinato non rompe niente


@pytest.mark.anyio
async def test_mcp_senza_editor_non_approva_da_solo(tmp_path):
    nomi = {t.name for t in await srv.mcp.list_tools()}
    assert "propose_plan" in nomi and "propose_plan" in srv._FUORI_BATCH
    p = str(tmp_path / "p.json")
    await call("project_create", path=p, name="t", preset="720p")
    assert (await call("propose_plan"))["plan"] is None
    r = await call("propose_plan", title="Coast film", scenes=SCENE)
    assert r["approved"] is False and "1. 0:00-0:04" in r["plan_text"] and "confirmed=True" in r["motivo"]
    assert piano.carica(p) is None                                  # senza si' non si scrive niente
    with pytest.raises(Exception, match="unknown source"):
        await call("propose_plan", scenes=[{"what": "x", "duration": 3, "source": "boh"}])
    ok = await call("propose_plan", title="Coast film", scenes=SCENE, confirmed=True)
    assert ok["approved"] is True and ok["saved"] is True and ok["totals"]["generazioni"] == 2
    assert (await call("propose_plan"))["plan"]["titolo"] == "Coast film"


@pytest.mark.anyio
async def test_mcp_con_editor_aperto_chiede_e_rispetta_il_no(tmp_path, monkeypatch):
    p = str(tmp_path / "p.json")
    await call("project_create", path=p, name="t", preset="720p")
    risposte = iter([{"risposte": {"0": "Make scene 2 shorter"}}, {"risposte": {"0": "Yes, build it"}}])
    viste = []
    monkeypatch.setattr(api_mod, "chiedi", lambda d: (viste.append(d), next(risposte))[1])
    monkeypatch.setattr(api_mod, "MCP_ATTIVO", True)
    api_mod.S.store = Store.create("x", "720p")
    try:
        no = await call("propose_plan", title="Coast film", scenes=SCENE)
        assert no["approved"] is False and no["feedback"] == "Make scene 2 shorter"
        assert piano.carica(p) is None
        si = await call("propose_plan", title="Coast film", scenes=SCENE)
        assert si["approved"] is True and len(viste) == 2 and "Coast film" in viste[0][0]["domanda"]
    finally:
        api_mod.S.store = None


def test_chat_chiede_prima_e_salva_solo_se_approva(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    api_mod.S.store = None
    esiti = []

    def finto_run(store, stato, domanda, run_op, **k):
        esiti.append(json.loads(run_op("propose_plan", {"title": "Coast film", "scenes": SCENE})))
        yield {"type": "text", "text": "ok"}
        yield {"type": "done"}

    monkeypatch.setattr(chat, "run", finto_run)
    risposte = iter([{"risposte": {"0": "No, change it"}}, {"risposte": {"0": "Yes, build it"}}])
    monkeypatch.setattr(api_mod, "chiedi", lambda d: next(risposte))
    try:
        with TestClient(api_mod.app) as c:
            c.post("/api/project/create", json={"path": str(tmp_path / "a.json"), "preset": "720p"})
            c.post("/api/chat", json={"message": "plan it"})
            assert esiti[0]["approved"] is False and piano.carica(str(tmp_path / "a.json")) is None
            c.post("/api/chat", json={"message": "plan it"})
            assert esiti[1]["approved"] is True and esiti[1]["saved"] is True
            assert piano.carica(str(tmp_path / "a.json"))["totali"]["scene"] == 4
    finally:
        api_mod.S.store = None


def test_la_chat_conosce_lo_strumento(tmp_path):
    assert "propose_plan" in {t["name"] for t in chat.build_tools()}
    s = Store.create("t", "720p", path=str(tmp_path / "c.json"))
    assert json.loads(chat.execute(s, "propose_plan", {}))["plan"] is None
    assert "errore" in json.loads(chat.execute(s, "propose_plan", {"scenes": [{"what": "x"}]}))
    assert isinstance(EditError("x"), Exception)
