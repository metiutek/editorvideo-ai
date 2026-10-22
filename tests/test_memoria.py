"""Memoria comune a tutti i progetti: MEMORIA.md, strumenti MCP e chat."""

import pytest

from vedit import chat, memoria
from vedit import mcp_server as srv
from vedit.store import Store


@pytest.fixture(autouse=True)
def _memoria_isolata(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_MEMORIA", str(tmp_path / "MEMORIA.md"))


def test_ricorda_sezioni_e_doppioni():
    assert memoria.contesto() == ""
    memoria.ricorda("i video sono 9:16 per i Reels", "preferences")
    memoria.ricorda("niente musica epica", "audio")
    memoria.ricorda("sottotitoli sempre gialli", "preferences")
    assert memoria.ricorda("niente musica epica", "audio")["salvata"] is False
    testo = memoria.leggi()
    # la seconda preferenza resta sotto il suo titolo, non in fondo al file
    pref = testo.index("## preferences")
    assert pref < testo.index("sottotitoli sempre gialli") < testo.index("## audio")
    assert len(memoria.voci()) == 3
    ctx = memoria.contesto()
    assert "9:16" in ctx and "# Memoria di vedit" not in ctx


def test_dimentica_e_sostituisci():
    memoria.ricorda("voce maschile", "voice")
    memoria.ricorda("canale: Montagne", "channel")
    assert memoria.dimentica("VOCE")["tolte"] == 1
    assert memoria.voci()[0].startswith("canale: Montagne")
    memoria.sostituisci("## a mano\r\n- scritta dall'utente\r\n")
    assert memoria.voci() == ["scritta dall'utente"]


def test_contesto_lungo_tiene_le_ultime():
    for i in range(200):
        memoria.ricorda(f"preferenza numero {i:03d} con un po' di testo intorno", "tante")
    ctx = memoria.contesto()
    assert "numero 199" in ctx and "numero 000" not in ctx
    assert len(ctx) < memoria.MAX_CONTESTO + 300


def test_voce_vuota_rifiutata():
    with pytest.raises(ValueError):
        memoria.ricorda("   ")


@pytest.mark.anyio
async def test_strumenti_mcp_e_apertura_progetto(tmp_path):
    from test_mcp import call

    srv._stores.clear()
    p = str(tmp_path / "a.json")
    r = await call("project_create", path=p)
    assert "memoria" not in r
    await call("remember", note="formato abituale 4:5", section="preferences")
    r = await call("project_open", path=p)
    assert "4:5" in r["memoria"]
    r = await call("project_create", path=str(tmp_path / "b.json"))
    assert "4:5" in r["memoria"]
    assert "formato abituale" in (await call("memory"))["testo"]
    assert (await call("forget", match="abituale"))["tolte"] == 1


def test_chat_ricorda():
    s = Store.create("c")
    chat.execute(s, "remember", {"note": "titoli in maiuscolo"})
    assert "titoli in maiuscolo" in memoria.leggi()
    nomi = {t["name"] for t in chat.build_tools()}
    assert {"remember", "forget", "generate_voice", "set_format"} <= nomi
