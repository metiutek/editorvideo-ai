"""Imparare uno stile da un video gia' montato: le misure devono ritrovare
quello che il riferimento contiene davvero (tagli, dissolvenze, punch-in)."""

import subprocess

import pytest

from vedit import apprendi, ffmpeg, stili


def _riferimento(cartella) -> str:
    """Taglio netto a 2 s, dissolvenza di 1 s centrata a 4.5 s, 6 s in tutto."""
    out = cartella / "rif.mp4"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "smptehdbars=s=640x360:r=25:d=2",
        "-f", "lavfi", "-i", "testsrc=s=640x360:r=25:d=3",
        "-f", "lavfi", "-i", "rgbtestsrc=s=640x360:r=25:d=2",
        "-filter_complex",
        "[0][1]concat=n=2:v=1:a=0,settb=1/25,fps=25[ab];"
        "[2]settb=1/25,fps=25[c];[ab][c]xfade=transition=fade:duration=1:offset=4[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(out),
    ], check=True, capture_output=True)
    return str(out)


def test_misura_tagli_e_dissolvenze(tmp_path):
    m = apprendi.misura(_riferimento(tmp_path))
    assert m["tagli"]["numero"] == 2
    assert m["transizioni"]["dissolvenze"] == 1 and m["transizioni"]["sul_nero"] == 0
    assert abs(m["transizioni"]["dove"][0] - 4.5) <= 0.3
    assert 0.6 <= m["transizioni"]["durata_dissolvenza"] <= 1.4
    assert m["formato"] == "16:9" and m["bande_nere"] is None
    assert m["musica"] is None  # niente audio: niente BPM inventati


def test_impara_salva_uno_stile_applicabile(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    res = apprendi.impara(_riferimento(tmp_path), "Come il riferimento")
    sid = res["stile"]["id"]
    assert stili.trova(sid)["nome"] == "Come il riferimento"
    r = stili.ricetta(sid)
    assert r["transizioni"][0] == "dissolve"
    assert "dissolvenze" in res["guida"] and "tagli al minuto" in res["guida"]
    assert res["misure"]["foglio"] and res["misure"]["foglio"].endswith(".jpg")
    # rifarlo su quello stile lo aggiorna, non ne crea un altro
    n = len(stili.personali())
    apprendi.impara(_riferimento(tmp_path), stile_id=sid)
    assert len(stili.personali()) == n


def _misure(**sopra):
    base = {
        "formato": "9:16", "durata": 30, "bande_nere": None, "cartelli_su_nero": [],
        "apertura": 0.0, "chiusura": 0.0,
        "tagli": {"numero": 30, "al_minuto": 60, "inquadratura_mediana": 0.9,
                  "inquadratura_p10": 0.5, "inquadratura_p90": 1.6, "variazione": 0.7,
                  "prima_inquadratura": 0.4, "accelera": 1.0},
        "transizioni": {"dissolvenze": 0, "sul_nero": 0, "flash": 3, "durata_dissolvenza": 0},
        "movimento": {"inquadrature_con_zoom": 0.0, "zoom_medio": 0.15, "punch_in": 0.4,
                      "mosso": 0.01, "scosse": 0.3},
        "colore": {"luminosita": 0.5, "contrasto": 0.2, "saturazione": 0.5, "caldo": 0.1,
                   "ombre_blu": 0.0, "luci_calde": 0.1, "neri": 0.0,
                   "statistiche": {"mean": [0.6, 0.5, 0.4], "std": [0.2, 0.2, 0.2]}},
        "musica": {"bpm": 120, "battito": 0.5, "tagli_sul_battito": 0.8, "a_caso": 0.3,
                   "forma": "crescendo"},
    }
    base.update(sopra)
    return base


def test_dalle_misure_alla_ricetta():
    piano, r = apprendi.ricetta(_misure())
    assert piano == "shortform"
    # il colore vero del riferimento al posto del look, che resta nominato nella guida
    assert r["movimento"] == "punch" and r["look"] is None
    assert r["colore"] == {"mean": [0.6, 0.5, 0.4], "std": [0.2, 0.2, 0.2]}
    assert r["musica"] == "crescendo" and r["accenti"]["effetto"] == "shake"
    assert {"movimento", "colore", "musica_viva", "ritmo_vario", "effetti"} <= set(r["attese"])
    assert any("battito" in x for x in r["da_fare"])
    assert any("9:16" in x for x in r["da_fare"])
    stili.valida_ricetta(r)  # quello che esce si salva senza errori
    testo = apprendi.guida(_misure(), "rif", apprendi._look(_misure()["colore"]))
    assert "caldo_tramonto" in testo and "sul battito" in testo and "gancio" in testo and "punch-in" in testo


def test_ricetta_calma_e_cinema():
    piano, r = apprendi.ricetta(_misure(
        tagli={"numero": 6, "al_minuto": 8, "inquadratura_mediana": 6.0,
               "inquadratura_p10": 4, "inquadratura_p90": 9, "variazione": 0.3,
               "prima_inquadratura": 6, "accelera": 1.0},
        transizioni={"dissolvenze": 2, "sul_nero": 1, "flash": 0, "durata_dissolvenza": 1.2},
        movimento={"inquadrature_con_zoom": 0.6, "zoom_medio": 0.05, "punch_in": 0.0,
                   "mosso": 0.0, "scosse": 0.0},
        bande_nere=2.39, cartelli_su_nero=[3.0, 20.0], musica=None))
    assert piano == "cinematic" and r["movimento"] == "spinta"
    assert r["transizioni"] == {"tipo": "dissolve", "durata": 1.2, "ogni": 2}
    assert r["musica"] is None and "grafica" in r["attese"]
    assert any("bande nere" in x for x in r["da_fare"])


def test_fonte_che_non_esiste():
    with pytest.raises(ValueError):
        apprendi.procura("C:/non/esiste.mp4")


@pytest.mark.slow
def test_punch_in_da_un_montaggio_vero(tmp_path):
    """Un montaggio di vedit con punch-in sulla stessa ripresa: l'analisi lo ritrova."""
    from vedit import render
    from vedit.store import Store

    srcs = []
    for i, src in enumerate(["testsrc2", "smptehdbars"]):
        f = tmp_path / f"s{i}.mp4"
        subprocess.run([ffmpeg.binary("ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"{src}=s=1280x720:r=25", "-t", "8", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(f)], check=True)
        srcs.append(str(f))
    s = Store.create("p", preset="720p", path=str(tmp_path / "p.json"))
    a, b = s.import_media(srcs)
    items = []
    for k in range(4):
        m = a if k % 2 == 0 else b
        items += [{"media": m.id, "start": k * 3.0, "in": 2, "duration": 1.5},
                  {"media": m.id, "start": k * 3.0 + 1.5, "in": 2, "duration": 1.5}]
    ids = [c.id for c in s.add_clips(items)]
    for cid in ids[1::2]:
        s.set_transform(cid, scale=1.25)
    out = str(tmp_path / "p.mp4")
    render.render(s.project, render.RenderOptions(output=out))
    m = apprendi.misura(out)
    assert m["tagli"]["numero"] == 7
    assert m["movimento"]["punch_in"] >= 0.4
    assert apprendi.ricetta(m)[1]["movimento"] == "punch"


def test_la_chat_vede_il_foglio(tmp_path, monkeypatch):
    """Con un modello via API il foglio dei fotogrammi arriva come immagine:
    e' da li' che legge testi e grafica che le misure non vedono."""
    from vedit import chat, llm
    from vedit.store import Store

    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    rif = _riferimento(tmp_path)
    s = Store.create("t", "720p")
    out = chat.execute(s, "learn_style", {"source": rif, "name": "Dalla chat"})
    assert isinstance(out, llm.ConImmagine) and out.immagine.endswith(".jpg")

    args = '{"source": ' + __import__("json").dumps(rif) + '}'
    risposte = [
        [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {
            "name": "learn_style", "arguments": args}}]}, "finish_reason": "tool_calls"}]}],
        [{"choices": [{"delta": {"content": "Fatto."}, "finish_reason": "stop"}]}],
    ]
    mandati = []

    def finto(url, chiave, body):
        mandati.append(body)
        yield from risposte.pop(0)

    monkeypatch.setattr(llm, "_post_stream", finto)
    llm.imposta("openai", chiave="k", modello="gpt-5")
    list(chat.run(s, {}, "montalo come questo", lambda n, a: chat.execute(s, n, a)))
    ultimo = mandati[1]["messages"]
    assert ultimo[-2]["role"] == "tool"
    assert ultimo[-1]["role"] == "user" and ultimo[-1]["content"][1]["type"] == "image_url"


def _video(cartella, nome, sorgente, durata=3):
    out = cartella / nome
    subprocess.run([ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"{sorgente}:s=640x360:r=25:d={durata}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)],
                   check=True, capture_output=True)
    return str(out)


def test_lo_stile_porta_il_colore_del_riferimento(tmp_path, monkeypatch):
    """Non solo il look piu' vicino: apply_style porta le riprese verso le
    statistiche di colore misurate sul riferimento (colormatch)."""
    from vedit.store import Store

    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    rif = _video(tmp_path, "arancio.mp4", "color=c=0xE08030")
    res = apprendi.impara(rif, "Arancio")
    colore = res["ricetta"]["colore"]
    assert colore["mean"][0] > colore["mean"][2] + 0.3   # rosso ben sopra il blu
    s = Store.create("c", "720p", path=str(tmp_path / "c.json"))
    m = s.import_media([_video(tmp_path, "blu.mp4", "color=c=0x3050C0")])[0]
    s.add_clips([{"media": m.id, "start": 0, "in": 0, "duration": 2}])
    fatto = stili.applica(s, res["stile"]["id"])
    assert "1 clip" in fatto["applicato"]["colore"]
    fx = s.project.tracks[0].clips[0].effects
    p = next(e for e in fx if e.type == "colormatch").params
    assert p["r_off"] > 0 and p["b_off"] < 0
    # rilanciare non la rimette due volte
    stili.applica(s, res["stile"]["id"])
    assert sum(e.type == "colormatch" for e in s.project.tracks[0].clips[0].effects) == 1


@pytest.mark.slow
def test_scosse_sull_attacco(tmp_path):
    """Riprese con dettaglio, una scossa sull'attacco di una clip su due: l'analisi
    ne fa un accento ogni 2."""
    from vedit import render
    from vedit.store import Store

    sorgenti = ["mandelbrot=s=1280x720:r=25:maxiter=200", "testsrc2=s=1280x720:r=25",
                "cellauto=s=1280x720:r=25:rule=30", "smptehdbars=s=1280x720:r=25"]
    srcs = []
    for i, src in enumerate(sorgenti):
        f = tmp_path / f"s{i}.png"
        subprocess.run([ffmpeg.binary("ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", src, "-frames:v", "1", str(f)], check=True)
        srcs.append(str(f))
    s = Store.create("p", preset="720p", path=str(tmp_path / "p.json"))
    ms = s.import_media(srcs)
    ids = [c.id for c in s.add_clips([{"media": ms[k % 4].id, "start": k * 1.5, "in": 0,
                                       "duration": 1.5} for k in range(12)])]
    for cid in ids[1::2]:
        s.add_effect(cid, "shake", {"amount": {"kf": [{"t": 0, "v": 28},
                                                      {"t": 0.45, "v": 0, "ease": "ease_out"}]},
                                    "frequency": 9})
    out = str(tmp_path / "p.mp4")
    render.render(s.project, render.RenderOptions(output=out))
    m = apprendi.misura(out)
    assert m["tagli"]["numero"] == 11
    assert 0.35 <= m["movimento"]["scosse"] <= 0.65
    assert apprendi.ricetta(m)[1]["accenti"] == {"effetto": "shake", "ogni": 2}
