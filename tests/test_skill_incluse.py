"""Le skill incluse nel pacchetto (backend/vedit/skills_incluse): animazione, montaggio
parlato, motori esterni. Devono caricarsi, dichiarare la fonte e la licenza, nominare
solo strumenti e blocchi che esistono, e poter essere sostituite dall'utente."""

import re
import tomllib
from pathlib import Path

import pytest

from vedit import blocchi, estensioni, moves
from vedit import mcp_server as srv

CARTELLA = Path(estensioni.__file__).resolve().parent / "skills_incluse"
ATTESE = {"motion-craft", "kinetic-typography", "data-animation", "short-form-video",
          "lower-thirds", "explainer-styles", "product-launch", "talking-head-edit",
          "external-engines"}


def _skill_dirs():
    return sorted(p.parent for p in CARTELLA.glob("*/SKILL.md"))


def test_ci_sono_tutte_e_nient_altro():
    assert {d.name for d in _skill_dirs()} == ATTESE


def test_si_scoprono_come_skill_di_vedit(tmp_path):
    nomi = {s["name"]: s for s in estensioni.skill_vedit(str(tmp_path / "p.json"))}
    assert ATTESE <= set(nomi)
    assert all(nomi[n]["origin"] == "incluse" for n in ATTESE)
    # arrivano anche all'agente MCP e alla chat, che ne ricevono l'indice
    indice = estensioni.indice_skill(str(tmp_path / "p.json"), solo_vedit=True)
    assert "motion-craft" in indice and "external-engines" in indice


@pytest.mark.parametrize("cartella", _skill_dirs(), ids=lambda d: d.name)
def test_ogni_skill_e_fatta_bene(cartella):
    testo = (cartella / "SKILL.md").read_text(encoding="utf-8")
    meta, corpo = estensioni._frontmatter(testo)
    assert meta["name"] == cartella.name
    assert 60 <= len(meta["description"]) <= 500 and "use when" in meta["description"].lower()
    # la fonte e la licenza sono dichiarate, e rimandano all'attribuzione
    assert meta["source"] and "NOTICE.md" in meta["source"]
    assert len(testo) < 9000 and len(testo) < estensioni.MAX_SKILL       # si legge tutta, ogni volta
    assert corpo.lstrip().startswith("# ")


def test_l_attribuzione_copre_ogni_skill_e_le_licenze_ci_sono():
    notice = (CARTELLA / "NOTICE.md").read_text(encoding="utf-8")
    for d in _skill_dirs():
        assert f"`{d.name}`" in notice, f"{d.name} non e' nell'attribuzione"
    assert "Copyright (c) 2026 iart.ai" in notice and "Copyright (c) 2026 Browser Use" in notice
    assert "MIT License" in notice and "LICENSE-Apache-2.0.txt" in notice
    apache = (CARTELLA / "LICENSE-Apache-2.0.txt").read_text(encoding="utf-8")
    assert "Apache License" in apache and "Version 2.0" in apache
    # cio' che non si puo' riusare e' dichiarato, non solo omesso
    assert "AGPL" in notice


def test_nominano_solo_strumenti_e_blocchi_veri():
    import anyio

    async def nomi():
        return {t.name for t in await srv.mcp.list_tools()}

    strumenti = anyio.run(nomi)
    non_strumenti = set(blocchi.BLOCCHI) | set(moves.MOSSE) | {
        # termini di altri motori, di CSS e di codice che stanno in backtick
        "font_weight", "font_variation_settings", "clip_path", "ease_out_cubic", "ease_in_cubic",
        "ease_in_out_cubic", "ease_in", "ease_out", "ease_in_out", "stroke_dasharray",
        "stroke_dashoffset", "title_safe", "font_variant_numeric", "letter_spacing",
        "line_height", "wall_clock", "margin_v", "min_silence"}
    chiamate = set()
    for d in _skill_dirs():
        corpo = (d / "SKILL.md").read_text(encoding="utf-8")
        chiamate |= set(re.findall(r"`([a-z]+(?:_[a-z]+)+)(?:\(|`)", corpo))
    sconosciuti = sorted(n for n in chiamate - non_strumenti if n not in strumenti)
    assert not sconosciuti, f"nominati nelle skill ma assenti dal server MCP: {sconosciuti}"
    # i nomi di blocchi nominati davvero esistono: nessuno e' rimasto dopo un rinomina
    for nome in ("lower_third", "kinetic_words", "caption_pill", "color_wipe", "flash_frame",
                 "stat_card", "end_card", "chapter_card", "section_label"):
        assert nome in blocchi.BLOCCHI


def test_l_utente_puo_sostituirne_una(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    estensioni.crea_skill("motion-craft", "Use when animating: my own rules", "# Mine\n\nUse 0.2 s.")
    s = next(x for x in estensioni.skill_vedit() if x["name"] == "motion-craft")
    assert s["origin"] == "vedit"                                  # la sua vince sulla inclusa
    assert "Use 0.2 s." in estensioni.usa_skill("motion-craft", solo_vedit=True)["istruzioni"]
    # togliere la sua riporta quella inclusa; quella inclusa non si cancella da qui
    estensioni.elimina_skill("motion-craft")
    assert next(x for x in estensioni.skill_vedit() if x["name"] == "motion-craft")["origin"] == "incluse"
    with pytest.raises(ValueError, match="no vedit skill named"):
        estensioni.elimina_skill("motion-craft")


def test_il_pacchetto_le_porta_con_se():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml")
                              .read_text(encoding="utf-8"))
    assert "skills_incluse/**/*" in pyproject["tool"]["setuptools"]["package-data"]["vedit"]


def test_le_istruzioni_dell_agente_le_nominano():
    assert "skills_incluse" not in srv.ISTRUZIONI
    for n in ("motion-craft", "list_skills", "external-engines"):
        assert n in srv.ISTRUZIONI
