"""Assistente di montaggio dentro l'editor.

Le stesse operazioni che usa la UI (i metodi di ``Store``) vengono esposte a
Claude come strumenti: l'assistente non ha una strada privata per modificare il
progetto, fa esattamente quello che faresti tu cliccando. Ogni turno ritorna un
flusso di eventi che la UI mostra mentre arrivano.

Il modello lo sceglie l'utente fra quelli di ``llm.py``: Claude, qualunque
servizio compatibile OpenAI, oppure il Claude Code installato sul computer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterator

from . import llm, presets

SYSTEM = """Sei l'assistente di montaggio dentro vedit, un editor video non lineare.

Lavori sul progetto aperto usando gli strumenti: sono le stesse operazioni dei
pulsanti dell'interfaccia, quindi l'utente vede il risultato comparire in
timeline e puo' annullarlo con Ctrl+Z.

Come lavorare:
- Lo stato del progetto (media, tracce, clip con i loro id e tempi) ti viene
  passato a ogni turno. Usa quegli id, non inventarli. Se ti serve lo stato
  aggiornato dopo una modifica, chiama project_info.
- Fai il lavoro richiesto e basta: non aggiungere effetti, titoli o tagli che
  non sono stati chiesti. Se una richiesta e' ambigua in modo che cambierebbe
  il risultato, chiedi; per le scelte di poco conto decidi tu e dillo.
- I tempi sono in secondi dall'inizio della timeline. La durata delle clip e'
  in timeline, non nella sorgente.
- Per un "look" o una catena audio preferisci apply_preset: sono combinazioni
  gia' tarate. add_effect serve quando serve un parametro preciso.
- Se un'operazione fallisce, leggi l'errore e correggi invece di ripeterla.

Rispondi in italiano, in modo breve. Dopo aver modificato la timeline di' in una
frase cosa hai fatto, senza rielencare ogni chiamata."""


# --------------------------------------------------------------------------
# strumenti
# --------------------------------------------------------------------------

def _tool(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": required}}


_NUM = {"type": "number"}
_STR = {"type": "string"}


def build_tools() -> list[dict]:
    look_ids = [p["id"] for p in presets.LOOKS + presets.AUDIO]
    tr_ids = [t["id"] for t in presets.transitions()]
    return [
        _tool("project_info",
              "Stato aggiornato della timeline: media, tracce, clip con id, tempi ed "
              "effetti. Chiamalo quando ti serve verificare il risultato di una modifica "
              "o quando non hai un id che ti serve.",
              {}, []),
        _tool("import_media",
              "Aggiunge file dal disco al progetto (non li mette in timeline). "
              "Usalo solo con percorsi che l'utente ha indicato.",
              {"paths": {"type": "array", "items": _STR}}, ["paths"]),
        _tool("add_clip",
              "Mette un media in timeline. start assente = accoda alla fine della traccia.",
              {"media_id": _STR, "track_id": _STR, "start": _NUM,
               "in_": {**_NUM, "description": "punto di attacco nella sorgente"},
               "duration": _NUM}, ["media_id"]),
        _tool("add_text",
              "Aggiunge un titolo in sovrimpressione sulla traccia video.",
              {"text": _STR, "start": _NUM, "duration": _NUM,
               "font_size": {"type": "integer"}, "color": _STR,
               "box": {"type": "boolean", "description": "riquadro dietro al testo"}},
              ["text"]),
        _tool("add_html",
              "Grafica animata in HTML/CSS/JS sopra il video, con sfondo trasparente: "
              "sottopancia, titoli animati, contatori, infografiche. La pagina e' grande "
              "quanto il progetto in pixel CSS; animazioni CSS, GSAP, requestAnimationFrame "
              "e setTimeout seguono il tempo della clip. Mettila su una traccia sopra la ripresa.",
              {"html": {**_STR, "description": "documento HTML completo"},
               "track_id": _STR, "start": _NUM, "duration": _NUM}, ["html"]),
        _tool("set_html",
              "Sostituisce il documento HTML di una clip html.",
              {"clip_id": _STR, "html": _STR}, ["clip_id", "html"]),
        _tool("split_clip",
              "Taglia una clip in due al tempo di timeline indicato.",
              {"clip_id": _STR, "at": _NUM}, ["clip_id", "at"]),
        _tool("remove_clip",
              "Elimina una clip. ripple=true chiude anche il buco che lascia.",
              {"clip_id": _STR, "ripple": {"type": "boolean"}}, ["clip_id"]),
        _tool("move_clip",
              "Sposta una clip nel tempo e/o su un'altra traccia.",
              {"clip_id": _STR, "start": _NUM, "track_id": _STR}, ["clip_id"]),
        _tool("trim_clip",
              "Cambia attacco e durata di una clip senza spostarla.",
              {"clip_id": _STR, "in_": _NUM, "duration": _NUM}, ["clip_id"]),
        _tool("set_speed",
              "Cambia la velocita' di una clip. 2 = doppia, 0.5 = slow motion.",
              {"clip_id": _STR, "speed": _NUM}, ["clip_id", "speed"]),
        _tool("set_fades",
              "Dissolvenza in entrata e/o in uscita, in secondi.",
              {"clip_id": _STR, "fade_in": _NUM, "fade_out": _NUM}, ["clip_id"]),
        _tool("crossfade",
              "Transizione tra due clip consecutive della stessa traccia: accosta B ad A "
              "e le sovrappone. E' il modo giusto quando le clip sono attaccate.",
              {"clip_a": _STR, "clip_b": _STR, "duration": _NUM,
               "type": {"type": "string", "enum": tr_ids}}, ["clip_a", "clip_b"]),
        _tool("set_transition",
              "Cambia la transizione in uscita di una clip senza spostare niente. "
              "Usalo quando le clip si sovrappongono gia'.",
              {"clip_id": _STR, "type": {"type": "string", "enum": tr_ids}, "duration": _NUM},
              ["clip_id"]),
        _tool("apply_preset",
              "Applica un look video o una catena audio gia' tarata. Preferiscilo a "
              "add_effect quando la richiesta e' di stile ('piu' cinematografico', "
              "'voce piu' pulita') invece che di un parametro preciso. "
              "clip_id assente = applica al master, cioe' a tutto il video.",
              {"preset_id": {"type": "string", "enum": look_ids}, "clip_id": _STR},
              ["preset_id"]),
        _tool("add_effect",
              "Applica un singolo effetto con parametri espliciti. clip_id assente = master.",
              {"effect": _STR, "params": {"type": "object"}, "clip_id": _STR}, ["effect"]),
        _tool("set_transform",
              "Posizione, scala, rotazione e opacita' della clip sul canvas. x/y in pixel "
              "dal centro, scale 1 = naturale. Ogni valore accetta anche keyframe: "
              "{\"kf\":[{\"t\":0,\"v\":1},{\"t\":3,\"v\":1.2}]} con t relativo all'inizio clip.",
              {"clip_id": _STR, "x": {}, "y": {}, "scale": {}, "rotation": {}, "opacity": {}},
              ["clip_id"]),
        _tool("set_audio",
              "Volume in dB, muto, pan e dissolvenze audio di una clip.",
              {"clip_id": _STR, "gain_db": {}, "mute": {"type": "boolean"},
               "pan": _NUM, "fade_in": _NUM, "fade_out": _NUM}, ["clip_id"]),
        _tool("set_text",
              "Cambia il testo o lo stile di una clip di tipo testo.",
              {"clip_id": _STR, "text": _STR, "font_size": {"type": "integer"},
               "color": _STR, "box": {"type": "boolean"}}, ["clip_id"]),
        _tool("add_track",
              "Aggiunge una traccia video o audio. Serve ogni volta che due cose devono "
              "stare insieme nello stesso istante: un titolo sopra una ripresa, un "
              "riquadro PiP, musica sotto il parlato, un secondo microfono. Le tracce "
              "video si sovrappongono: l'ultima della lista sta sopra tutte.",
              {"kind": {"type": "string", "enum": ["video", "audio"]}, "name": _STR},
              ["kind"]),
        _tool("set_track",
              "Stato di una traccia: name, hidden (nasconde il video), muted (silenzia), "
              "solo (isola: le altre tacciono), locked (protegge dalle modifiche), "
              "volume (1 = invariato). E' anche l'unico modo di sbloccare una traccia.",
              {"track_id": _STR, "name": _STR, "hidden": {"type": "boolean"},
               "muted": {"type": "boolean"}, "solo": {"type": "boolean"},
               "locked": {"type": "boolean"}, "volume": {}}, ["track_id"]),
        _tool("move_track",
              "Cambia l'ordine di una traccia tra quelle dello stesso tipo. Per il video "
              "l'ordine e' la sovrapposizione: indice 0 sta sotto, l'ultimo sta sopra. "
              "Usalo quando un titolo o un PiP finisce dietro invece che davanti.",
              {"track_id": _STR, "index": {"type": "integer"}}, ["track_id", "index"]),
        _tool("remove_track",
              "Elimina una traccia con tutte le sue clip. Chiedi conferma se non e' vuota.",
              {"track_id": _STR}, ["track_id"]),
        _tool("close_gaps",
              "Compatta una traccia eliminando i buchi tra le clip.",
              {"track_id": _STR}, ["track_id"]),
        _tool("undo", "Annulla l'ultima modifica.", {}, []),
    ]


# --------------------------------------------------------------------------
# esecuzione
# --------------------------------------------------------------------------

# strumenti che non sono metodi di Store
_SPECIAL = {"project_info", "apply_preset"}


def execute(store: Any, name: str, args: dict) -> str:
    """Esegue uno strumento sul progetto e descrive il risultato a parole."""
    from .model import to_dict

    if name == "project_info":
        return json.dumps(store.summary("full"), ensure_ascii=False)

    if name == "apply_preset":
        p = presets.find(args["preset_id"])
        if p is None:
            raise ValueError(f"preset sconosciuto: {args['preset_id']}")
        clip_id = args.get("clip_id")
        store.add_effects(clip_id, p["effects"])
        dove = f"clip {clip_id}" if clip_id else "master"
        return f"preset '{p['name']}' applicato a {dove} ({len(p['effects'])} effetti)"

    result = getattr(store, name)(**args)
    if result is None:
        return "fatto"
    if isinstance(result, (str, int, float, bool)):
        return str(result)
    if isinstance(result, (list, tuple)):
        return json.dumps([to_dict(r) if hasattr(r, "__dataclass_fields__") else r
                           for r in result], ensure_ascii=False, default=str)
    if hasattr(result, "__dataclass_fields__"):
        return json.dumps(to_dict(result), ensure_ascii=False, default=str)
    return json.dumps(result, ensure_ascii=False, default=str)


class ChatUnavailable(RuntimeError):
    """Manca la credenziale o il pacchetto: e' un problema di setup, non un bug."""


def available() -> dict:
    """Modello attivo e se si puo' usare: e' quello che la UI mostra nella chat."""
    return llm.stato()


def _state_block(store: Any) -> str:
    return ("Stato attuale del progetto (usa questi id):\n"
            + json.dumps(store.summary("full"), ensure_ascii=False))


# --------------------------------------------------------------------------
# riferimenti: i punti del video di cui l'utente sta parlando
# --------------------------------------------------------------------------


def _fmt(t: float) -> str:
    m, s = divmod(max(0.0, float(t)), 60)
    return f"{int(m)}:{s:05.2f}"


def _fotogramma(store: Any, t: float, area: dict | None = None) -> str | None:
    """PNG del fotogramma al tempo t, con il riquadro dell'area se c'e'."""
    import tempfile
    import uuid

    from . import render

    cartella = Path(tempfile.gettempdir()) / "vedit_riferimenti"
    cartella.mkdir(parents=True, exist_ok=True)
    out = cartella / f"rif_{uuid.uuid4().hex[:10]}.png"
    try:
        render.render_frame(store.project, max(0.0, t), str(out), width=960)
    except Exception:  # noqa: BLE001 - senza immagine il riferimento resta in parole
        return None
    if area:
        from PIL import Image, ImageDraw

        im = Image.open(out).convert("RGB")
        w, h = im.size
        x0, y0 = area["x"] * w, area["y"] * h
        x1, y1 = x0 + area["w"] * w, y0 + area["h"] * h
        d = ImageDraw.Draw(im)
        for k in range(4):
            d.rectangle([x0 - k, y0 - k, x1 + k, y1 + k], outline=(255, 70, 70))
        im.save(out)
    return str(out)


IMMAGINI_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TESTO_EXT = {".txt", ".md", ".html", ".htm", ".css", ".js", ".json", ".srt", ".vtt", ".ass",
             ".csv", ".xml", ".svg", ".py", ".cube", ".lrc"}
MEDIA_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mp3", ".wav", ".aac", ".m4a",
             ".flac", ".ogg", ".opus"}
MAX_TESTO = 60_000   # caratteri di un allegato di testo passati al modello


def tipo_allegato(path: str | Path) -> str:
    """image | pdf | testo | media | altro: decide come arriva al modello."""
    ext = Path(path).suffix.lower()
    if ext in IMMAGINI_EXT:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in TESTO_EXT:
        return "testo"
    if ext in MEDIA_EXT:
        return "media"
    return "altro"


def riferimenti(store: Any, refs: list[dict]) -> tuple[str, list[dict]]:
    """Testo che descrive i riferimenti, piu' le immagini dei fotogrammi indicati.

    Ogni riferimento ha un numero: l'utente scrive "il punto 2" e il modello sa
    di cosa parla, con l'immagine davanti quando serve guardare.
    """
    if not refs:
        return "", []
    p = store.project
    righe, immagini = [], []
    w, h = p.settings.width, p.settings.height
    for i, r in enumerate(refs, 1):
        k = r.get("kind")
        nota = f" — nota: {r['nota']}" if r.get("nota") else ""
        a = b = 0.0
        if k == "clip":
            found = p.find_clip(r.get("id", ""))
            if not found:
                righe.append(f"[{i}] clip {r.get('id')} (non esiste piu')")
                continue
            tr, c = found
            righe.append(f"[{i}] clip {c.id} \"{c.name}\" ({c.type}) sulla traccia {tr.id}, "
                         f"da {_fmt(c.start)} a {_fmt(c.end)}{nota}")
            t = c.start + c.duration / 2
        elif k == "time":
            t = float(r.get("t", 0))
            righe.append(f"[{i}] l'istante {_fmt(t)} ({t:.2f}s){nota}")
        elif k == "range":
            a, b = sorted((float(r.get("a", 0)), float(r.get("b", 0))))
            righe.append(f"[{i}] il tratto da {_fmt(a)} a {_fmt(b)} ({a:.2f}-{b:.2f}s){nota}")
            t = a
        elif k == "area":
            t = float(r.get("t", 0))
            x, y, aw, ah = (float(r.get(c, 0)) for c in ("x", "y", "w", "h"))
            righe.append(
                f"[{i}] un'area dell'inquadratura al tempo {_fmt(t)}: riquadro rosso nell'immagine; "
                f"in pixel di progetto x={round(x * w)} y={round(y * h)} "
                f"larghezza={round(aw * w)} altezza={round(ah * h)} "
                f"(set_transform usa x/y dal centro: centro dell'area = "
                f"{round((x + aw / 2 - .5) * w)}, {round((y + ah / 2 - .5) * h)}){nota}")
        elif k == "file":
            f = Path(r.get("path", ""))
            if not f.is_file():
                righe.append(f"[{i}] file allegato {r.get('name', '')} (non trovato){nota}")
                continue
            tipo = tipo_allegato(f)
            if tipo in ("image", "pdf"):
                cosa = "immagine" if tipo == "image" else "documento PDF"
                righe.append(f"[{i}] {cosa} allegato \"{f.name}\" (percorso: {f}){nota}")
                if len(immagini) < llm.MAX_IMMAGINI:
                    immagini.append({"etichetta": f"[{i}]", "path": str(f), "tipo": tipo})
            elif tipo == "testo":
                testo_file = f.read_text(encoding="utf-8", errors="replace")
                taglio = "\n[... tagliato ...]" if len(testo_file) > MAX_TESTO else ""
                righe.append(f"[{i}] file allegato \"{f.name}\" (percorso: {f}){nota}, contenuto:\n"
                             f"```\n{testo_file[:MAX_TESTO]}{taglio}\n```")
            elif tipo == "media":
                righe.append(f"[{i}] file multimediale allegato \"{f.name}\", percorso: {f}{nota}. "
                             "Per usarlo nel montaggio importalo con import_media.")
            else:
                righe.append(f"[{i}] file allegato \"{f.name}\", percorso: {f}{nota}")
            continue
        else:
            continue
        if len(immagini) < llm.MAX_IMMAGINI:
            png = _fotogramma(store, t, r if k == "area" else None)
            if png:
                immagini.append({"etichetta": f"[{i}]", "path": png})
            if k == "range" and len(immagini) < llm.MAX_IMMAGINI:
                png2 = _fotogramma(store, max(a, b - 0.05))
                if png2:
                    immagini.append({"etichetta": f"[{i}] fine", "path": png2})
    testo = ("L'utente indica questi riferimenti (fotogrammi e allegati seguono "
             "nello stesso ordine):\n" + "\n".join(righe))
    return testo, immagini


# --------------------------------------------------------------------------
# un turno
# --------------------------------------------------------------------------


def run(store: Any, stato_chat: dict, question: str, run_op: Callable[[str, dict], str],
        refs: list[dict] | None = None, mcp_url: str | None = None) -> Iterator[dict]:
    """Un turno di conversazione con il modello attivo, come flusso di eventi.

    ``stato_chat`` conserva la cronologia nel formato del motore che l'ha
    prodotta: cambiando modello si ricomincia, perche' i formati non sono
    intercambiabili.
    """
    try:
        p, cfg = llm.attivo()
    except (RuntimeError, ValueError) as exc:
        raise ChatUnavailable(str(exc)) from exc
    if stato_chat.get("provider") != p["id"]:
        stato_chat.clear()
        stato_chat.update({"provider": p["id"], "messaggi": [], "sessione": None})

    testo_rif, immagini = riferimenti(store, refs or [])
    contenuto: list[dict] = []
    if p["tipo"] != "claude_code":
        # lo stato va nel turno utente, non nel prompt di sistema: il prefisso
        # resta identico fra un turno e l'altro e la cache non si invalida
        contenuto.append({"type": "text", "text": _state_block(store)})
    if testo_rif:
        contenuto.append({"type": "text", "text": testo_rif})
    for im in immagini:
        pdf = im.get("tipo") == "pdf"
        if p["tipo"] == "claude_code":
            # Claude Code legge da se' immagini e PDF con Read
            cosa = "Documento" if pdf else "Immagine"
            contenuto.append({"type": "text", "text": f"{cosa} {im['etichetta']}: {im['path']}"})
        elif pdf and p["tipo"] != "anthropic":
            contenuto.append({"type": "text", "text": f"(il PDF {im['etichetta']} non si puo' "
                                                      "passare a questo modello: chiedi all'utente "
                                                      "di incollarne il testo se serve)"})
        else:
            contenuto.append(llm.documento(im["path"]) if pdf else llm.immagine(im["path"]))
    contenuto.append({"type": "text", "text": question})

    if p["tipo"] == "claude_code":
        if not mcp_url:
            yield {"type": "error", "message": "il server MCP dell'editor non e' attivo"}
            return
        cwd = str(Path(store.path).parent) if store.path else None
        yield from llm.run_claude_code(p, cfg, stato_chat, contenuto, mcp_url, cwd)
    elif p["tipo"] == "anthropic":
        yield from llm.run_anthropic(p, cfg, SYSTEM, build_tools(), stato_chat["messaggi"],
                                     contenuto, run_op)
    else:
        yield from llm.run_openai(p, cfg, SYSTEM, build_tools(), stato_chat["messaggi"],
                                  contenuto, run_op)
