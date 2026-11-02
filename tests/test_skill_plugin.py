"""La skill e il plugin per gli altri agenti (``.claude-plugin``, ``skills/vedit``): i
file devono restare veri. Una versione rimasta indietro o uno strumento nominato che
non esiste piu' si scoprono qui e non dopo che qualcuno li ha installati."""

import json
import re
import tomllib
from pathlib import Path

import pytest

from vedit import mcp_server as srv

RADICE = Path(__file__).resolve().parents[1]


def _json(rel):
    return json.loads((RADICE / rel).read_text(encoding="utf-8"))


def test_manifest_del_plugin_e_versione_allineata():
    plugin = _json(".claude-plugin/plugin.json")
    pyproject = tomllib.loads((RADICE / "pyproject.toml").read_text(encoding="utf-8"))
    assert plugin["name"] == "vedit" and plugin["license"] == "MIT"
    # chi cambia la versione del pacchetto cambia anche questa: e' nel controllo di release
    assert plugin["version"] == pyproject["project"]["version"]
    assert plugin["mcpServers"]["vedit"] == {"command": "uvx", "args": ["vedit-mcp"]}
    assert pyproject["project"]["scripts"].get("vedit-mcp")   # il comando che il plugin lancia


def test_marketplace_punta_al_plugin():
    m = _json(".claude-plugin/marketplace.json")
    assert m["name"] == "vedit" and m["owner"]["name"]
    assert [p["name"] for p in m["plugins"]] == ["vedit"] and m["plugins"][0]["source"] == "./"


def _skill():
    testo = (RADICE / "skills" / "vedit" / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", testo, re.S)
    assert m, "SKILL.md deve cominciare con il frontmatter"
    meta = dict(r.split(": ", 1) for r in m.group(1).splitlines() if ": " in r)
    return meta, m.group(2)


def test_skill_ha_nome_e_descrizione_utili():
    meta, corpo = _skill()
    assert meta["name"] == "vedit" and Path(RADICE / "skills" / "vedit").name == meta["name"]
    assert 80 <= len(meta["description"]) <= 1024
    assert "when" in meta["description"].lower()        # dice QUANDO usarla
    assert len(corpo.splitlines()) < 150                # una skill si legge tutta, ogni volta


@pytest.mark.anyio
async def test_ogni_strumento_nominato_dalla_skill_esiste():
    _, corpo = _skill()
    esistenti = {t.name for t in await srv.mcp.list_tools()}
    nominati = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)(?:\(|`)", corpo))
    # i nomi dei blocchi grafici sono in backtick ma non sono strumenti
    from vedit import blocchi
    non_strumenti = set(blocchi.BLOCCHI)
    termini = {"filter_complex"}                       # ffmpeg, non strumenti
    mancanti = sorted(n for n in nominati - non_strumenti - termini if n not in esistenti)
    assert not mancanti, f"strumenti nominati nella skill ma assenti dal server MCP: {mancanti}"
    # e i blocchi nominati sono veri: un nome sparito dalla libreria non resta nella skill
    nominati_blocchi = {n for n in nominati if n in non_strumenti}
    assert {"lower_third", "chapter_card", "color_wipe"} <= nominati_blocchi
    # quelli che la skill promette come passaggi obbligati ci sono
    for atteso in ("add_block", "list_blocks", "learn_style", "generate_media", "render_video"):
        assert atteso in esistenti and atteso in corpo
