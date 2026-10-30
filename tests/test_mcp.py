"""Il server MCP deve funzionare passando dal protocollo, non solo chiamando le
funzioni python: e' cosi' che lo usera' l'agente.
"""

import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from vedit import mcp_server as srv


def _out(result):
    """Contenuto della risposta: strutturato se c'e', altrimenti il JSON testuale."""
    data = result.structured_content
    if data is None:
        blocks = [json.loads(c.text) for c in result.content if getattr(c, "text", None)]
        return blocks[0] if len(blocks) == 1 else blocks
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


async def call(_tool: str, **args):
    return _out(await srv.mcp.call_tool(_tool, args))


@pytest.fixture(autouse=True)
def _reset():
    srv._stores.clear()
    srv._current[0] = None
    yield


@pytest.mark.anyio
async def test_elenco_strumenti():
    tools = await srv.mcp.list_tools()
    names = {t.name for t in tools}
    for atteso in ("project_create", "import_media", "add_clip", "split", "set_speed",
                   "add_effect", "render_video", "preview_frame", "normalize_audio"):
        assert atteso in names
    for t in tools:
        assert t.description, f"{t.name} senza descrizione"


@pytest.mark.anyio
async def test_flusso_completo(assets, tmp_path):
    """Monta un video passando solo dagli strumenti MCP."""
    p = str(tmp_path / "prog.json")
    await call("project_create", path=p, name="test", preset="720p")

    media = await call("import_media", paths=[assets["red"], assets["blue"], assets["music"]])
    assert len(media) == 3
    red, blue, music = [m["id"] for m in media]

    c1 = await call("add_clip", media=red, duration=3.0)
    c2 = await call("add_clip", media=blue, duration=3.0)
    assert c2["start"] == pytest.approx(3.0)

    parts = await call("split", clip=c1["id"], at=1.5)
    assert parts["dopo"]["start"] == pytest.approx(1.5)

    sped = await call("set_speed", clip=c2["id"], speed=2.0)
    assert sped["duration"] == pytest.approx(1.5)

    await call("add_effect", clip=c2["id"], type="color", params={"saturation": 1.4})
    await call("set_transform", clip=c2["id"],
               scale={"kf": [{"t": 0, "v": 1.0}, {"t": 1.5, "v": 1.3}]})
    await call("add_text", text="Titolo", start=0.0, duration=2.0, font_size=60, box=True)

    a2 = await call("add_track", kind="audio", name="musica")
    m2 = await call("add_clip", media=music, track=a2["id"], start=0.0, duration=4.0)
    await call("set_audio", clip=m2["id"], gain_db=-12)

    info = await call("project_info")
    assert info["duration"] > 0
    assert len(info["tracks"]) == 3
    assert c2["id"] in [c["id"] for c in info["tracks"][0]["clips"]]

    res = await call("render_video", output=str(tmp_path / "out.mp4"), preview=True)
    assert res["mb"] > 0


@pytest.mark.anyio
async def test_errori_sono_parlanti(tmp_path):
    with pytest.raises(ToolError, match="no project open"):
        await call("add_clip", media="x")

    await call("project_create", path=str(tmp_path / "p.json"))
    with pytest.raises(ToolError, match="does not exist"):
        await call("add_clip", media="fantasma")
    with pytest.raises(ToolError):
        await call("add_effect", type="nonesiste")
    with pytest.raises(ToolError, match="unknown"):
        await call("add_effect", type="blur", params={"raggio": 3})


@pytest.mark.anyio
async def test_catalogo_effetti():
    audio = await call("list_effects", kind="audio")
    assert audio and all(e["kind"] == "audio" for e in audio)
    assert any(e["name"] == "compressor" for e in audio)
    tutti = await call("list_effects")
    assert len(tutti) > len(audio)


@pytest.mark.anyio
async def test_undo_redo_via_mcp(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"))
    m = (await call("import_media", paths=[assets["red"]]))[0]
    await call("add_clip", media=m["id"])
    assert (await call("undo"))["undone"] is True
    assert len(_tracks(await call("project_info"))) == 0
    assert (await call("redo"))["redone"] is True
    assert len(_tracks(await call("project_info"))) == 1


def _tracks(info):
    return info["tracks"][0]["clips"]


@pytest.mark.anyio
@pytest.mark.slow
async def test_preview_frame_restituisce_immagine(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    m = (await call("import_media", paths=[assets["blue"]]))[0]
    await call("add_clip", media=m["id"])
    r = await srv.mcp.call_tool("preview_frame", {"t": 1.0, "width": 320,
                                                 "path": str(tmp_path / "f.jpg")})
    assert not r.is_error
    assert "image" in [getattr(c, "type", None) for c in r.content]


@pytest.mark.anyio
async def test_project_open_rilegge_da_disco(assets, tmp_path):
    """Il file puo' cambiare fuori (UI, altro processo): open deve rileggerlo."""
    p = str(tmp_path / "p.json")
    await call("project_create", path=p)
    m = (await call("import_media", paths=[assets["red"]]))[0]
    await call("add_clip", media=m["id"])
    assert len(_tracks(await call("project_info"))) == 1

    # modifica dall'esterno, come farebbe la UI su un altro processo
    doc = json.loads(Path(p).read_text(encoding="utf-8"))
    doc["tracks"][0]["clips"] = []
    Path(p).write_text(json.dumps(doc), encoding="utf-8")

    await call("project_open", path=p)
    assert _tracks(await call("project_info")) == []


@pytest.mark.anyio
async def test_add_clips_monta_in_una_chiamata(assets, tmp_path):
    """Un montaggio serrato deve entrare con una chiamata, non con una per taglio."""
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    red, blue = [m["id"] for m in await call(
        "import_media", paths=[assets["red"], assets["blue"]])]

    res = await call("add_clips", clips=[
        {"media": red, "start": 0.0, "in": 1.0, "duration": 0.5},
        {"media": blue, "start": 0.5, "in": 0.5, "duration": 0.75},
        {"media": red, "start": 1.25, "in": 3.0, "duration": 0.5},
    ])
    assert res["aggiunte"] == 3
    assert res["fine"] == pytest.approx(1.75)

    clips = _tracks(await call("project_info"))
    assert [c["in"] for c in clips] == [1.0, 0.5, 3.0]

    # tre tagli restano una modifica sola: un undo li toglie tutti
    await call("undo")
    assert _tracks(await call("project_info")) == []


@pytest.mark.anyio
async def test_add_clips_non_lascia_montaggi_a_meta(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    red = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    with pytest.raises(ToolError):
        await call("add_clips", clips=[
            {"media": red, "duration": 1.0},
            {"media": "fantasma", "duration": 1.0},
        ])
    assert _tracks(await call("project_info")) == []


@pytest.mark.anyio
async def test_move_effect_riordina(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    await call("add_effect", type="sharpen", params={"amount": 1.0})
    await call("add_effect", type="denoise", params={"strength": 3})
    res = await call("move_effect", index=1, to=0)
    assert res["catena"] == ["denoise", "sharpen"]


@pytest.mark.anyio
async def test_music_beats(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"))
    b = await call("music_beats", path=assets["music"], every=4, end=4.0)
    assert b["bpm"] > 0
    assert b["beat"] == pytest.approx(60.0 / b["bpm"], abs=1e-3)
    assert b["bar"] == pytest.approx(b["beat"] * 4, abs=1e-3)
    assert b["profilo"], "senza profilo non si trova lo stacco"
    assert b["griglia"] and all(t <= 4.0 for t in b["griglia"])


@pytest.mark.anyio
async def test_analisi_su_un_progetto_lo_dice(assets, tmp_path):
    """Passare il progetto dove va il girato e' l'errore naturale: va spiegato."""
    p = str(tmp_path / "p.json")
    await call("project_create", path=p)
    with pytest.raises(ToolError, match="is a project, not footage"):
        await call("inspect_footage", path=p)


@pytest.mark.anyio
async def test_inspect_footage_accetta_un_media(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"))
    m = (await call("import_media", paths=[assets["red"]]))[0]
    rep = await call("inspect_footage", media=m["id"])
    assert rep["verdict"] in ("keep", "trim", "drop")


@pytest.mark.anyio
async def test_sinonimi_degli_argomenti(assets, tmp_path):
    """files/paths e time/t sono lo stesso argomento: sbagliarlo non deve fermare."""
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    media = await call("import_media", files=[assets["red"]])
    await call("add_clip", media=media[0]["id"], duration=1.0)
    r = await srv.mcp.call_tool("preview_frame", {"time": 0.5, "width": 160})
    assert not r.is_error


def test_istruzioni_contengono_le_regole_di_montaggio():
    """Le istruzioni del server sono l'unica cosa che l'agente legge sempre.

    Dentro non c'e' solo come si chiamano gli strumenti: ci sono i difetti veri
    dei video che escono da qui — musica a volume fisso, solo stacchi secchi,
    inquadrature ripetute, un video che dopo dieci secondi non aggiunge piu'
    niente. Se sparisce quella parte, l'editor torna a produrli.
    """
    t = srv.ISTRUZIONI.lower()
    assert srv.mcp.instructions == srv.ISTRUZIONI
    for regola in ("musica", "stacchi", "due volte", "dieci secondi", "cinematografico"):
        assert regola in t, f"regola di montaggio persa: {regola}"
    # e devono restare agganciate a strumenti veri, non a buoni propositi
    for strumento in ("music_beats", "add_clips", "preview_grid", "set_transform",
                      "set_transition", "set_audio", "verify_edit"):
        assert strumento in srv.ISTRUZIONI, f"regola senza strumento: {strumento}"


@pytest.mark.anyio
async def test_gli_strumenti_citati_esistono_davvero():
    """Le istruzioni non devono promettere strumenti che non ci sono."""
    nomi = {t.name for t in await srv.mcp.list_tools()}
    citati = {p.strip(".,:;()") for p in srv.ISTRUZIONI.replace("\n", " ").split()
              if p.strip(".,:;()") in nomi or "_" in p}
    inventati = {c for c in citati if "_" in c and c.isidentifier() and c not in nomi}
    assert not inventati, f"strumenti citati ma inesistenti: {sorted(inventati)}"


@pytest.mark.anyio
async def test_effetti_speciali_da_mcp(tmp_path):
    """Fusioni, particelle ed effetti speciali raggiungibili dall'agente."""
    p = str(tmp_path / "fx.json")
    await call("project_create", path=p, preset="720p")
    c = await call("add_color", color="red", duration=2.0)
    v = await call("set_clip", clip=c["id"], blend="screen")
    assert v["blend"] == "screen"
    with pytest.raises(Exception):
        await call("set_clip", clip=c["id"], blend="fumo")
    for tipo in ("glitch", "warp", "tilt3d", "shake", "rgb_split", "lens", "sky_key",
                 "remove_object"):
        await call("add_effect", clip=c["id"], type=tipo)
    part = await call("add_particles", kind="sparks", duration=2.0)
    assert part["type"] == "html" and part["kind"] == "sparks"
    nomi = {t.name for t in await srv.mcp.list_tools()}
    assert {"remove_background", "pin_to_subject", "add_particles", "set_particles",
            "create_particles", "delete_particles"} <= nomi


@pytest.mark.anyio
async def test_particelle_su_misura_dall_agente(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    await call("project_create", path=str(tmp_path / "pp.json"), preset="720p")
    c = await call("add_particles", kind="custom", duration=2.0,
                   custom={"shape": "star", "motion": "rise", "colors": ["#ffd23b"]})
    assert c["parametri"]["custom"]["shape"] == "star"
    v = await call("set_particles", clip=c["id"], custom={"motion": "float"}, density=1.5)
    assert v["parametri"]["custom"]["motion"] == "float" and v["parametri"]["density"] == 1.5
    with pytest.raises(ToolError, match="shape"):
        await call("add_particles", kind="custom", custom={"shape": "drago"})
    salvate = await call("create_particles", name="Oro", custom={"shape": "star"})
    pid = salvate["particelle"]["id"]
    assert pid in salvate["prossimo_passo"]
    assert (await call("add_particles", kind=pid))["parametri"]["custom"]["shape"] == "star"
    await call("delete_particles", particles=pid)
    with pytest.raises(ToolError, match="do not exist"):
        await call("delete_particles", particles=pid)


@pytest.mark.anyio
async def test_preview_media_guarda_senza_timeline(assets, tmp_path):
    """Il girato si guarda prima di montarlo: la timeline resta vuota."""
    p = str(tmp_path / "pm.json")
    await call("project_create", path=p, preset="720p")
    m = (await call("import_media", paths=[assets["blue"]]))[0]["id"]
    for args in ({"media": m}, {"media": m, "t": 1.0, "width": 480, "guide": True},
                 {"path": assets["blue"], "count": 4, "start": 1.0, "end": 3.0}):
        r = await srv.mcp.call_tool("preview_media", args)
        assert any(getattr(c, "type", "") == "image" for c in r.content), args
    info = await call("project_info")
    assert all(not t["clips"] for t in info["tracks"])


@pytest.mark.anyio
async def test_apply_style_e_review_edit(assets, tmp_path):
    p = str(tmp_path / "st.json")
    await call("project_create", path=p, preset="720p")
    red, blue = [x["id"] for x in await call("import_media",
                                              paths=[assets["red"], assets["blue"]])]
    await call("add_clips", clips=[{"media": red if i % 2 else blue, "start": i * 1.0,
                                    "in": 0.0, "duration": 1.0} for i in range(6)])
    prima = await call("review_edit")
    assert prima["solo_tagli"]
    esito = await call("apply_style", style="cinematico")
    assert esito["applicato"]["look"] == "cinema_teal_orange"
    dopo = await call("review_edit", style="cinematico")
    assert not dopo["solo_tagli"]
    with pytest.raises(ToolError, match="unknown style"):
        await call("apply_style", style="barocco")


@pytest.mark.anyio
async def test_l_agente_crea_e_applica_uno_stile(assets, tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    elenco = await call("list_styles")
    assert "vhs" in elenco["looks"]
    assert any(s["id"] == "cinematico" and s["ricetta"]["movimento"] == "spinta"
               for s in elenco["stili_montaggio"])
    creato = await call("create_style", name="Sogno", guide="Lento e caldo",
                        base="cinematic", recipe={"look": "sogno", "musica": "crescendo"})
    sid = creato["stile"]["id"]
    assert creato["ricetta"]["look"] == "sogno" and sid in creato["prossimo_passo"]
    assert any(s["id"] == sid for s in (await call("list_styles"))["stili_montaggio"])

    p = str(tmp_path / "cs.json")
    await call("project_create", path=p, preset="720p")
    m = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    await call("add_clips", clips=[{"media": m, "start": i * 1.0, "in": 0.0,
                                    "duration": 1.0} for i in range(4)])
    assert (await call("apply_style", style=sid))["applicato"]["look"] == "sogno"
    with pytest.raises(ToolError, match="unknown look"):
        await call("create_style", name="Z", guide="g", recipe={"look": "marte"})
    await call("delete_style", style=sid)
    with pytest.raises(ToolError, match="does not exist"):
        await call("delete_style", style=sid)


@pytest.mark.anyio
async def test_track_mask_con_box_segue_un_oggetto_qualsiasi(tmp_path):
    """Un oggetto che YOLO non conosce, indicato col riquadro: la cornice lo segue."""
    import subprocess
    from vedit import ffmpeg

    src = tmp_path / "obj.mp4"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x404040:s=1280x720:r=25:d=3",
        "-f", "lavfi", "-i", "testsrc2=s=120x120:r=25:d=3",
        "-filter_complex", "[0][1]overlay=x='80+t*120':y=300",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src),
    ], check=True, capture_output=True)
    p = str(tmp_path / "tm.json")
    await call("project_create", path=p, preset="720p")
    m = (await call("import_media", paths=[str(src)]))[0]["id"]
    c = await call("add_clip", media=m, start=0.0, in_=1.0, duration=1.5)
    # al secondo 1 della sorgente (inizio clip) il riquadro sta a x=200
    r = await call("track_mask", clip=c["id"], kind="mask_outline",
                   box=[200 / 1280, 300 / 720, 120 / 1280, 120 / 720], box_t=0.0,
                   padding=1.0, params={"color": "#00ff00", "thickness": 4})
    assert r["copertura"] > 0.9
    info = await call("project_info", detail="full")
    fx_ = info["tracks"][0]["clips"][0]["effects"][-1]
    assert fx_["type"] == "mask_outline" and fx_["params"]["color"] == "#00ff00"
    punti = fx_["params"]["x"]["kf"]
    # canvas 1280 come la sorgente: in tempo di clip t=1 -> sorgente 2 s -> x=320
    a_uno = min(punti, key=lambda q: abs(q["t"] - 1.0))
    assert a_uno["v"] == pytest.approx(320, abs=12)
    with pytest.raises(ToolError):
        await call("track_mask", clip=c["id"], kind="mask_arcobaleno", box=[0, 0, 0.1, 0.1])


@pytest.mark.anyio
async def test_report_issue_scrive_il_registro(tmp_path, monkeypatch):
    from vedit import mcp_server as srv
    f = tmp_path / "SEGNALAZIONI.md"
    monkeypatch.setenv("VEDIT_SEGNALAZIONI", str(f))
    esito = await srv.report_issue("scomodo", "servono 40 chiamate per 40 titoli",
                                   compito="sottotitoli a mano", strumento="add_text")
    assert esito["file"] == str(f)
    await srv.report_issue("manca", "niente import di una cartella intera")
    testo = f.read_text(encoding="utf-8")
    assert testo.startswith("# Segnalazioni")
    assert "[scomodo] add_text" in testo and "sottotitoli a mano" in testo
    assert "[manca] generale" in testo
    with pytest.raises(ValueError):
        await srv.report_issue("boh", "x")
    assert "report_issue" in srv.ISTRUZIONI


@pytest.mark.anyio
async def test_trim_edit_dall_agente(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "te.json"), preset="720p")
    m = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    a = await call("add_clip", media=m, duration=2.0)
    b = await call("add_clip", media=m, duration=2.0, in_point=2.0)
    r = await call("trim_edit", clip=a["id"], mode="roll", delta=0.5)
    assert r["duration"] == 2.5 and r["dopo"]["start"] == 2.5
    assert (await call("trim_edit", clip=b["id"], mode="slip", delta=-0.5))["in"] == 2.0
    assert (await call("trim_edit", clip=a["id"], mode="ripple", edge="end",
                       delta=-1.0))["duration"] == 1.5
    assert (await call("trim_edit", clip=b["id"], mode="slide", delta=-0.5))["start"] == 1.0
    with pytest.raises(ToolError, match="mode"):
        await call("trim_edit", clip=a["id"], mode="zoom", delta=1)


# --------------------------------------------------------------------------
# economia: ogni risposta resta nel contesto dell'agente e viene riletta a ogni
# turno. Due minuti di video montati via MCP consumavano un abbonamento intero.
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_risposte_in_json_compatto(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    r = await srv.mcp.call_tool("import_media", {"paths": [assets["red"]]})
    assert r.structured_content is None, "la stessa risposta non va mandata due volte"
    testo = r.content[0].text
    assert "\n" not in testo and ", " not in testo and '": ' not in testo


@pytest.mark.anyio
async def test_risposte_senza_eco(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    m = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    res = await call("add_clips", clips=[{"media": m, "start": i * 1.0, "in": 0.0,
                                          "duration": 1.0} for i in range(3)])
    assert len(res["ids"]) == 3 and "clip" not in res
    kf = {"kf": [{"t": 0, "v": 1}, {"t": 1, "v": 1.2}]}
    t = await call("set_transform", clip=res["ids"][0], scale=kf)
    assert t["transform"]["scale"] == "kf x2"
    info = await call("project_info", track="V1")
    assert "media" not in info and [tr["id"] for tr in info["tracks"]] == ["V1"]
    assert all("end" not in c for c in info["tracks"][0]["clips"])


@pytest.mark.anyio
async def test_batch_una_chiamata_atomica(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    m = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    ids = (await call("add_clips", clips=[{"media": m, "start": i * 1.0, "in": 0.0,
                                           "duration": 1.0} for i in range(3)]))["ids"]
    res = await call("batch", ops=[
        {"tool": "set_transform", "args": {"clip": ids[0], "scale": 1.2}},
        {"tool": "add_effect", "args": {"clip": ids[1], "type": "sharpen"}},
        {"tool": "set_fades", "args": {"clip": ids[2], "fade_out": 0.5}},
    ])
    assert res["done"] == 3
    full = await call("project_info", detail="full")
    clips = full["tracks"][0]["clips"]
    assert clips[0]["transform"]["scale"] == 1.2 and clips[1]["effects"]
    # un solo undo disfa tutto il blocco
    await call("undo")
    clips = (await call("project_info", detail="full"))["tracks"][0]["clips"]
    assert clips[0]["transform"]["scale"] == 1.0 and not clips[1].get("effects")

    # un'operazione sbagliata: non resta applicato niente, e l'errore dice quale
    with pytest.raises(ToolError, match=r"op 1 \(set_transform\)"):
        await call("batch", ops=[
            {"tool": "set_transform", "args": {"clip": ids[0], "scale": 1.5}},
            {"tool": "set_transform", "args": {"clip": "fantasma", "scale": 1.5}},
        ])
    clips = (await call("project_info", detail="full"))["tracks"][0]["clips"]
    assert clips[0]["transform"]["scale"] == 1.0
    with pytest.raises(ToolError, match="cannot be used in batch"):
        await call("batch", ops=[{"tool": "render_video", "args": {"output": "x.mp4"}}])


@pytest.mark.anyio
async def test_transcribe_tutto_il_girato_in_una_chiamata(assets, tmp_path, monkeypatch):
    from vedit import analyze
    viste = []

    def finta(src, model, language):
        viste.append(src)
        return {"language": "it", "words_per_minute": 120.0, "speech_seconds": 1.0,
                "text": "ciao", "segments": [{"start": 0.123, "end": 1.0, "text": " ciao"}]}

    monkeypatch.setattr(analyze, "transcribe", finta)
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    ids = [x["id"] for x in await call("import_media", paths=[assets["red"], assets["blue"]])]
    res = await call("transcribe", media=["*"])
    assert set(res["files"]) == set(ids) and len(viste) == 2
    assert res["files"][ids[0]]["segments"] == [[0.12, 1.0, "ciao"]]


@pytest.mark.anyio
async def test_preview_media_tutto_il_girato(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    await call("import_media", paths=[assets["red"], assets["blue"]])
    r = await srv.mcp.call_tool("preview_media", {"media": ["*"]})
    assert [c.type for c in r.content] == ["image"]


@pytest.mark.anyio
async def test_list_effects_compatto_e_scheda():
    corto = await call("list_effects")
    assert all(isinstance(q, str) for e in corto for q in e["params"])
    scheda = await call("list_effects", name="sharpen")
    assert len(scheda) == 1 and isinstance(scheda[0]["params"][0], dict)


@pytest.mark.anyio
async def test_project_info_riassume_i_keyframe(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    m = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    c = (await call("add_clips", clips=[{"media": m, "duration": 2.0}]))["ids"][0]
    kf = {"kf": [{"t": 0, "v": 1}, {"t": 1, "v": 1.2}, {"t": 2, "v": 1.3}]}
    await call("batch", ops=[{"tool": "set_transform", "args": {"clip": c, "scale": kf}},
                             {"tool": "add_effect", "args": {"clip": c, "type": "shake",
                                                             "params": {"amount": kf}}}])
    clip = (await call("project_info"))["tracks"][0]["clips"][0]
    assert clip["transform"]["scale"] == "kf x3"
    assert clip["effects"][0]["params"]["amount"] == "kf x3"
    full = (await call("project_info", detail="full"))["tracks"][0]["clips"][0]
    assert full["transform"]["scale"] == kf


@pytest.mark.anyio
async def test_add_clips_crea_le_tracce_che_nomina(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    m = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    await call("add_clips", clips=[{"media": m, "duration": 1.0, "track": "V3"},
                                   {"media": m, "duration": 1.0, "track": "A2"}])
    ids = [t["id"] for t in (await call("project_info"))["tracks"]]
    assert {"V2", "V3", "A2"} <= set(ids)
    with pytest.raises(ToolError, match="does not exist"):
        await call("add_clips", clips=[{"media": m, "duration": 1.0, "track": "musica"}])
    # un solo undo toglie clip e tracce create
    await call("undo")
    assert "V3" not in [t["id"] for t in (await call("project_info"))["tracks"]]


@pytest.mark.anyio
async def test_piu_istanti_in_un_immagine(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    m = (await call("import_media", paths=[assets["blue"]]))[0]["id"]
    c = (await call("add_clips", clips=[{"media": m, "duration": 3.0}]))["ids"][0]
    r = await srv.mcp.call_tool("preview_frame", {"t": [0.5, 1.5, 2.5]})
    assert [x.type for x in r.content] == ["image"]
    r = await srv.mcp.call_tool("batch", {"ops": [
        {"tool": "set_transform", "args": {"clip": c, "scale": 1.3}}], "look": [1.0, 2.0]})
    assert [x.type for x in r.content] == ["text", "image"]
    assert json.loads(r.content[0].text)["done"] == 1


@pytest.mark.anyio
async def test_list_styles_senza_le_guide_lunghe(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    lunga = "Monta cosi'. " * 1000
    sid = (await call("create_style", name="Lungo", guide=lunga, base="vlog"))["stile"]["id"]
    elenco = await call("list_styles")
    mio = next(x for x in elenco["stili_montaggio"] if x["id"] == sid)
    assert sid in mio["guida"] and len(mio["guida"]) < 100
    assert (await call("list_styles", style=sid))["guida"] == lunga.strip()


@pytest.mark.anyio
async def test_make_captions_un_file_per_clip_e_solo_il_tratto(assets, tmp_path, monkeypatch):
    """Segnalato montando 53 clip: tutte mostravano i sottotitoli dell'ultima."""
    from vedit import analyze

    def parole(*voci):
        return [{"w": w, "t": t, "e": t + 0.4, "p": 0.9} for w, t in voci]

    finta = {"language": "it", "segments": [
        {"start": 0.0, "end": 0.9, "text": "uno", "words": parole(("uno", 0.2))},
        {"start": 2.0, "end": 2.9, "text": "due", "words": parole(("due", 2.2))},
        {"start": 4.0, "end": 4.9, "text": "tre", "words": parole(("tre", 4.2))},
    ]}
    monkeypatch.setattr(analyze, "transcribe", lambda *a, **k: finta)
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    m = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    a, b = (await call("add_clips", clips=[
        {"media": m, "start": 0.0, "in": 0.0, "duration": 1.0},
        {"media": m, "start": 1.0, "in": 2.0, "duration": 1.0}]))["ids"]
    res = await call("make_captions", clips=[a, b], format="srt")
    assert res["righe"] == {a: 1, b: 1}
    clips = (await call("project_info", detail="full"))["tracks"][0]["clips"]
    file = [c["effects"][0]["params"]["file"] for c in clips]
    assert file[0] != file[1]
    assert "uno" in Path(file[0]).read_text(encoding="utf-8")
    testo_b = Path(file[1]).read_text(encoding="utf-8")
    assert "due" in testo_b and "tre" not in testo_b


@pytest.mark.anyio
async def test_add_html_da_modello_con_vars(tmp_path):
    """Dieci cartelli = un modello e dieci vars, non dieci documenti interi."""
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    modello = tmp_path / "cartello.html"
    modello.write_text("<h1>{{titolo}}</h1><p>{{ sotto }}</p>", encoding="utf-8")
    res = await call("batch", ops=[
        {"tool": "add_html", "args": {"path": str(modello), "start": i * 2.0, "duration": 2.0,
                                      "vars": {"titolo": f"Capitolo {i}", "sotto": "x"}}}
        for i in range(3)])
    assert res["done"] == 3
    docs = sorted(c.html for t in srv._store().project.tracks for c in t.clips)
    assert docs == [f"<h1>Capitolo {i}</h1><p>x</p>" for i in range(3)]
    with pytest.raises(ToolError, match=r"placeholders without a value.*sotto"):
        await call("add_html", path=str(modello), vars={"titolo": "solo questo"})


@pytest.mark.anyio
async def test_lavori_lunghi_mandano_battiti_di_progresso(assets, tmp_path, monkeypatch):
    """Claude Code tronca una chiamata muta da 300 s: render e trascrizioni lunghe
    ripartivano da capo. Mentre il lavoro gira, il server manda progresso."""
    import time
    from mcp import Client
    from vedit import analyze

    def lenta(src, model, language):
        time.sleep(0.5)
        return {"language": "it", "words_per_minute": 1.0, "speech_seconds": 1.0,
                "text": "x", "segments": []}

    monkeypatch.setattr(analyze, "transcribe", lenta)
    monkeypatch.setattr(srv, "BATTITO_S", 0.1)
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    await call("import_media", paths=[assets["red"], assets["blue"]])
    visti = []

    async def progresso(fatto, totale, nota):
        visti.append((fatto, totale, nota))

    async with Client(srv.mcp) as client:
        r = await client.call_tool("transcribe", {"media": ["*"]}, progress_callback=progresso)
    assert not r.is_error
    assert len(visti) >= 3
    assert any(n and n.startswith("transcribing 2/2") for _, _, n in visti)


@pytest.mark.anyio
async def test_preview_grid_su_un_video_lo_guarda(assets, tmp_path):
    """Quattro volte l'agente ha passato il render .mp4 come path della griglia."""
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    r = await srv.mcp.call_tool("preview_grid", {"path": assets["blue"], "count": 4})
    assert [c.type for c in r.content] == ["image"]
    with pytest.raises(ToolError, match="preview_media"):
        await call("preview_grid", path=str(tmp_path / "manca.mp4"))


@pytest.mark.anyio
async def test_formato_video(tmp_path):
    """Formati per rapporto alla creazione e a progetto aperto."""
    p = str(tmp_path / "f.json")
    r = await call("project_create", path=p, preset="9:16")
    assert r["settings"]["resolution"] == "1080x1920" and r["settings"]["format"] == "9:16"
    r = await call("project_settings", format="4:5")
    assert (r["width"], r["height"], r["format"]) == (1080, 1350, "4:5")
    r = await call("project_settings", format="16:9", size=2160)
    assert (r["width"], r["height"]) == (3840, 2160)
    with pytest.raises(ToolError):
        await call("project_settings", format="boh")


@pytest.mark.anyio
async def test_skill_di_montaggio(tmp_path, monkeypatch):
    """L'agente crea, legge e toglie le skill; installarle vuole il si' dell'utente."""
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    s = await call("create_skill", name="podcast", description="Podcast con due camere",
                   instructions="Alterna le camere.", files={"esempio.md": "ciao"})
    assert s["name"] == "podcast"
    p = await call("project_create", path=str(tmp_path / "s.json"), preset="720p")
    assert p["skill"] == {"podcast": "Podcast con due camere"}
    assert (await call("list_skills"))["skill"] == {"podcast": "Podcast con due camere"}
    assert "Alterna" in (await call("use_skill", name="podcast"))["istruzioni"]
    assert (await call("use_skill", name="podcast", file="esempio.md"))["testo"] == "ciao"
    altra = tmp_path / "altra"
    altra.mkdir()
    (altra / "SKILL.md").write_text("---\nname: altra\ndescription: d\n---\ncorpo",
                                    encoding="utf-8")
    assert (await call("install_skill", source=str(altra)))["installate"] == []
    assert (await call("install_skill", source=str(altra), confirmed=True))["installate"]
    await call("delete_skill", name="podcast")
    assert set((await call("list_skills"))["skill"]) == {"altra"}


@pytest.mark.anyio
async def test_learn_style_da_mcp(tmp_path, monkeypatch, assets):
    """learn_style misura un video, salva lo stile e restituisce il foglio da guardare."""
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    await call("project_create", path=str(tmp_path / "ls.json"), preset="720p")
    media = await call("import_media", paths=[assets["blue"]])
    mid = media[0]["id"] if isinstance(media, list) else media["media"][0]["id"]
    res = await srv.mcp.call_tool("learn_style", {"media": mid, "name": "Dal blu"})
    tipi = [c.type for c in res.content]
    assert "image" in tipi
    dati = json.loads(next(c.text for c in res.content if c.type == "text"))
    assert dati["stile"]["nome"] == "Dal blu" and "guida" in dati
    with pytest.raises(ToolError):
        await call("learn_style")
