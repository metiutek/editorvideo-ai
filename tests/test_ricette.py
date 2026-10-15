"""Stili come ricette eseguibili e controllo del montaggio piatto.

Il difetto da cui nascono: con uno stile scelto, l'assistente metteva le clip
in fila e si fermava. La guida dello stile era solo testo. Qui si verifica che
la ricetta lasci davvero qualcosa nella timeline e che review_edit riconosca un
montaggio fatto di soli tagli.
"""

import pytest

from vedit import keyframes as kf
from vedit import review, stili
from vedit.store import Store


@pytest.fixture
def montaggio(assets) -> Store:
    """Otto tagli in fila e una musica a volume fisso: il montaggio piatto tipico."""
    s = Store.create("r", "720p")
    red, blue, music = s.import_media([assets["red"], assets["blue"], assets["music"]])
    s.add_clips([{"media": (red if i % 2 else blue).id, "start": i * 1.0, "in": 0.0,
                  "duration": 1.0} for i in range(8)])
    a = s.add_track("audio")
    s.add_clip(music.id, track_id=a.id, start=0.0, duration=8.0)
    return s


def test_solo_tagli_e_riconosciuto(montaggio):
    r = review.ricchezza(montaggio.project)
    assert r["solo_tagli"] and not r["ok"]
    assert {"movimento", "colore", "musica_viva", "ritmo_vario"} <= set(r["mancano"])
    assert any("apply_style" in a for a in r["avvisi"])


@pytest.mark.parametrize("stile", list(stili.RICETTE))
def test_ogni_ricetta_lascia_un_montaggio_non_piatto(montaggio, stile):
    esito = stili.applica(montaggio, stile)
    assert esito["applicato"], esito
    assert not esito["controllo"]["solo_tagli"], esito["controllo"]
    musica = next(c for t in montaggio.project.tracks if t.kind == "audio" for c in t.clips)
    assert kf.is_kf(musica.audio.gain_db), "la musica deve muoversi in ogni stile"
    # quello che resta da fare e' detto, non taciuto
    assert esito["da_fare"]


def test_cinematico_mette_look_spinte_dissolvenze(montaggio):
    stili.applica(montaggio, "cinematico")
    p = montaggio.project
    assert p.master.effects, "il look va sul master"
    clips = sorted(p.tracks[0].clips, key=lambda c: c.start)
    assert all(kf.is_kf(c.transform.scale) for c in clips)
    assert clips[0].fade_in > 0 and clips[-1].fade_out > 0
    # ogni quattro tagli un cambio di sezione: dissolve senza sovrapposizione
    assert clips[3].fade_out > 0 and clips[1].fade_out == 0


def test_ricetta_e_un_undo_solo(montaggio):
    prima = montaggio.project.to_dict()
    stili.applica(montaggio, "dinamico")
    montaggio.undo()
    assert montaggio.project.to_dict() == prima


def test_rilanciare_non_raddoppia(montaggio):
    stili.applica(montaggio, "videoclip")
    dopo_uno = montaggio.project.to_dict()
    esito = stili.applica(montaggio, "videoclip")
    assert montaggio.project.to_dict()["master"] == dopo_uno["master"]
    assert any("look" in x for x in esito["saltati"])
    assert sum(len(c.effects) for c in montaggio.project.tracks[0].clips) == \
        sum(len(c["effects"]) for c in dopo_uno["tracks"][0]["clips"])


def test_non_tocca_quello_che_e_gia_deciso(montaggio):
    c = sorted(montaggio.project.tracks[0].clips, key=lambda c: c.start)[0]
    montaggio.set_transform(c.id, scale=1.5)
    stili.applica(montaggio, "cinematico")
    assert montaggio.clip_or_die(c.id)[1].transform.scale == 1.5


def test_senza_clip_lo_dice(assets):
    with pytest.raises(ValueError, match="no video clips"):
        stili.applica(Store.create("v", "720p"), "cinematico")


def test_spot_di_sola_grafica_html():
    """Segnalato: apply_style falliva e review_edit chiedeva movimento e colore
    che su uno spot fatto solo di add_html non si potevano dare."""
    s = Store.create("g", "720p")
    for i in range(6):
        s.add_html(html=f"<h1>scena {i}</h1>", start=i * 2.0, duration=2.0 + i * 0.3)
    esito = stili.applica(s, "dinamico")
    assert esito["applicato"]
    r = review.ricchezza(s.project, stili.ricetta("dinamico")["attese"])
    assert "movimento" not in r["mancano"] and "colore" not in r["mancano"]
    assert r["conti"]["clip_video"] == 6


def test_stile_sconosciuto(montaggio):
    with pytest.raises(ValueError, match="unknown style"):
        stili.applica(montaggio, "barocco")


def test_stile_personale_prende_la_ricetta_del_ritmo(montaggio, monkeypatch, tmp_path):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path))
    mio = stili.salva("Il mio", "Tagli secchi e colori accesi", piano="shortform")
    r = stili.ricetta(mio["id"])
    assert r["movimento"] == stili.RICETTE["dinamico"]["movimento"]
    assert r["look"] is None   # il colore lo decide la guida dell'utente
    stili.applica(montaggio, mio["id"])
    assert not montaggio.project.master.effects


def test_stile_creato_con_ricetta_propria(montaggio, monkeypatch, tmp_path):
    """Un agente crea lo stile da solo: la ricetta e' quella che apply_style esegue."""
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path))
    mio = stili.salva("Neon notturno", "Freddo, glitch sui colpi, stacchi secchi",
                      piano="shortform",
                      ricetta={"look": "freddo_notturno", "movimento": None,
                               "accenti": {"effetto": "glitch", "ogni": 2},
                               "transizioni": ["wipe_left", 0.4, 3],
                               "attese": ["colore", "effetti"],
                               "da_fare": "scritte al neon"})
    r = stili.ricetta(mio["id"])
    assert r["look"] == "freddo_notturno" and r["movimento"] is None
    assert r["accenti"] == ("glitch", 2) and r["transizioni"] == ("wipe_left", 0.4, 3)
    assert r["da_fare"][0] == "scritte al neon"
    # le voci non nominate vengono dal ritmo di base
    assert r["musica"] == stili.RICETTE["dinamico"]["musica"]

    esito = stili.applica(montaggio, mio["id"])
    p = montaggio.project
    assert p.master.effects
    clips = sorted(p.tracks[0].clips, key=lambda c: c.start)
    assert sum(any(e.type == "glitch" for e in c.effects) for c in clips) >= 3
    assert not any(kf.is_kf(c.transform.scale) for c in clips)
    assert clips[2].transition_out.type == "wipe_left" or clips[2].fade_out > 0
    assert esito["controllo"]["ok"], esito["controllo"]


def test_aggiornare_lo_stile_tiene_la_ricetta(monkeypatch, tmp_path):
    """La UI salva solo nome e guida: non deve cancellare la ricetta dell'agente."""
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path))
    mio = stili.salva("X", "guida", ricetta={"musica": "crescendo"})
    stili.salva("X", "guida nuova", stile_id=mio["id"])
    assert stili.ricetta(mio["id"])["musica"] == "crescendo"
    assert stili.trova(mio["id"])["guida"] == "guida nuova"


@pytest.mark.parametrize("ricetta, errore", [
    ({"colore": "blu"}, "unknown recipe entries"),
    ({"look": "barocco"}, "unknown look"),
    ({"movimento": "volo"}, "unknown movimento"),
    ({"zoom": 3}, "zoom out of range"),
    ({"transizioni": ["esplosione", 1, 2]}, "unknown transition"),
    ({"transizioni": "dissolve"}, "transizioni"),
    ({"accenti": ["blur", 2]}, "accenti"),
    ({"attese": ["bellezza"]}, "unknown expectations"),
    ("punch", "object"),
])
def test_ricetta_sbagliata_dice_cosa_e_ammesso(ricetta, errore, monkeypatch, tmp_path):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path))
    with pytest.raises(ValueError, match=errore):
        stili.salva("Y", "guida", ricetta=ricetta)
    assert stili.personali() == []


def test_curva_musica_tiene_i_tempi_in_ordine():
    for forma in ("arco", "crescendo", "sotto_voce"):
        punti = stili.curva_musica(forma, 30.0, -6.0)["kf"]
        tempi = [p["t"] for p in punti]
        assert tempi == sorted(tempi) and len(set(tempi)) == len(tempi)
        assert tempi[-1] == 30.0 and punti[-1]["v"] < -30   # chiude in dissolvenza
        kf.validate({"kf": punti})


def test_lo_stile_della_chat_chiede_apply_style():
    assert "apply_style(style='trailer')" in stili.blocco("trailer")
    assert "review_edit" in stili.blocco("trailer")


@pytest.mark.slow
@pytest.mark.parametrize("stile", list(stili.RICETTE))
def test_ogni_ricetta_si_renderizza(montaggio, stile, tmp_path):
    """Keyframe di scala, shake, glitch, look e volume devono compilare davvero."""
    from vedit import render

    stili.applica(montaggio, stile)
    out = tmp_path / f"{stile}.mp4"
    res = render.render(montaggio.project, render.RenderOptions(
        output=str(out), quality="draft", width=320, height=180))
    assert out.exists() and res.duration == pytest.approx(8.0, abs=0.3)


def test_guida_lunga_fino_a_ventimila(monkeypatch, tmp_path):
    """Una guida di montaggio dettagliata e' lunga: 4000 caratteri non bastavano."""
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path))
    assert stili.MAX_GUIDA >= 20000
    lunga = "Taglia sul battito. " * 750          # 15000 caratteri
    mio = stili.salva("Lungo", lunga)
    assert stili.trova(mio["id"])["guida"] == lunga.strip()
    with pytest.raises(ValueError, match="too long"):
        stili.salva("Troppo", "x" * (stili.MAX_GUIDA + 1))
