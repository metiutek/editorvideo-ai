"""Scambio della timeline con gli altri montaggi: EDL, FCPXML, OpenTimelineIO.

Il progetto di vedit e' un JSON suo; chi finisce il lavoro in Premiere,
Resolve, Avid o Final Cut vuole la *timeline* nel formato che il suo programma
legge, con i file originali al loro posto. Tre formati, tre pubblici:

- **EDL CMX3600** (``.edl``): il piu' vecchio e il piu' letto, una traccia per
  file, niente percorsi (solo il nome della clip in commento);
- **FCPXML 1.9** (``.fcpxml``): Final Cut e Resolve, tutte le tracce, percorsi
  veri dei file;
- **OTIO** (``.otio``): OpenTimelineIO, il formato aperto che Resolve, Premiere
  (con plugin), Avid e la pipeline degli studi leggono; tutte le tracce.

Esce solo il *montaggio*: quali tratti di quali file, dove, a che velocita',
con le dissolvenze fra clip. Effetti, colore, testi, grafica html e mix audio
sono di vedit e restano qui: ``esporta`` restituisce gli avvisi su cio' che non
e' uscito, invece di perderlo in silenzio.

In vedit una transizione e' una sovrapposizione fra due clip. Negli altri
formati la transizione sta *sul taglio* e prende materiale dalle maniglie:
il taglio cade a meta' della sovrapposizione, e la transizione ne copre la
durata intera.

L'import passa da ``Store`` in un ``batch``: o entra tutta la timeline o niente,
un solo passo di undo.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .model import Clip, Project, Track

FORMATI = {".edl": "edl", ".fcpxml": "fcpxml", ".otio": "otio"}


def formato(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext not in FORMATI:
        raise ValueError(f"unknown timeline format {ext or '(no extension)'}; "
                         f"allowed: {', '.join(FORMATI)}")
    return FORMATI[ext]


# --------------------------------------------------------------------------
# tempo: tutto in fotogrammi interi, come lo contano gli altri montaggi
# --------------------------------------------------------------------------

def _rate(fps: float) -> Fraction:
    """23.976 e 29.97 sono 24000/1001 e 30000/1001, non numeri decimali."""
    for nominale in (24, 30, 48, 60, 120):
        if abs(fps - nominale * 1000 / 1001) < 0.01:
            return Fraction(nominale * 1000, 1001)
    return Fraction(fps).limit_denominator(1000)


def _fotogrammi(t: float, rate: Fraction) -> int:
    return int(round(t * float(rate)))


def _tc(frames: int, rate: Fraction) -> str:
    """Timecode non-drop HH:MM:SS:FF sui fotogrammi nominali (30 per 29.97)."""
    n = int(round(float(rate)))
    frames = max(0, frames)
    f = frames % n
    s = frames // n
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def _da_tc(tc: str, rate: Fraction) -> int:
    hh, mm, ss, ff = (int(x) for x in re.split(r"[:;.]", tc.strip()))
    n = int(round(float(rate)))
    return ((hh * 60 + mm) * 60 + ss) * n + ff


def _url(path: str) -> str:
    return Path(path).resolve().as_uri()


def _percorso(url: str) -> str:
    if not url:
        return ""
    p = urllib.parse.urlparse(url)
    if p.scheme in ("", "file"):
        return urllib.request.url2pathname(p.path) if p.scheme else url
    return ""


# --------------------------------------------------------------------------
# la timeline vista come pezzi in fila, senza sovrapposizioni
# --------------------------------------------------------------------------

@dataclass
class Pezzo:
    clip: Clip
    media_path: str
    rec: int           # inizio in timeline (fotogrammi)
    dur: int           # durata in timeline
    src: int           # attacco nella sorgente
    speed: float
    entra: int = 0     # fotogrammi di transizione che entrano in questo pezzo (sul suo attacco)
    tipo_entra: str = ""


def _pezzi(project: Project, track: Track, rate: Fraction, avvisi: list[str]) -> list[Pezzo]:
    """Clip media della traccia, con le sovrapposizioni risolte in transizioni sul taglio."""
    media = {m.id: m for m in project.media}
    out: list[Pezzo] = []
    saltate: dict[str, int] = {}
    for c in sorted(track.clips, key=lambda x: x.start):
        if not c.enabled:
            continue
        m = media.get(c.media) if c.type == "media" else None
        if m is None or m.kind == "image":
            tipo = "image" if m is not None else {"text": "text", "color": "colour",
                                                   "html": "html graphics"}.get(c.type, c.type)
            saltate[tipo] = saltate.get(tipo, 0) + 1
            continue
        k = c.speed if not c.reverse else -abs(c.speed)
        p = Pezzo(c, m.path, _fotogrammi(c.start, rate), max(1, _fotogrammi(c.duration, rate)),
                  _fotogrammi(c.in_ if not c.reverse else c.in_ + c.duration * abs(c.speed), rate),
                  k)
        if out:
            prima = out[-1]
            fine = prima.rec + prima.dur
            if p.rec < fine:
                # sovrapposizione: il taglio a meta', la transizione su tutta la durata
                d = fine - p.rec
                meta = d // 2
                prima.dur -= d - meta
                p.rec += meta
                p.dur -= meta
                p.src += int(round(meta * p.speed))
                p.entra = d
                p.tipo_entra = prima.clip.transition_out.type or "dissolve"
                if prima.clip.transition_out.duration > 0 and p.tipo_entra != "dissolve":
                    avvisi.append(f"transition {p.tipo_entra} goes out as a dissolve: "
                                  "wipes are vedit's own")
                if p.dur <= 0 or prima.dur <= 0:
                    avvisi.append(f"clip {c.id}: almost entirely overlapping the previous one, skipped")
                    continue
        out.append(p)
    for tipo, n in saltate.items():
        avvisi.append(f"track {track.id}: {n} {tipo} clips do not go out (they stay in vedit)")
    return out


def _avvisi_comuni(project: Project, avvisi: list[str]) -> None:
    effetti = sum(len(c.effects) for t in project.tracks for c in t.clips) + len(project.master.effects)
    if effetti:
        avvisi.append(f"{effetti} effects do not go out: colour and filters are vedit's own")
    mossi = sum(1 for t in project.tracks for c in t.clips
                if any(isinstance(v, dict) for v in (c.transform.x, c.transform.y,
                                                    c.transform.scale, c.transform.rotation)))
    if mossi:
        avvisi.append(f"{mossi} clips with keyframed motion: the motion does not go out")


# --------------------------------------------------------------------------
# esporta
# --------------------------------------------------------------------------

def esporta(project: Project, path: str, track: str | None = None) -> dict:
    """Scrive la timeline in ``path``; il formato lo dice l'estensione.

    ``track`` vale per l'EDL, che porta una traccia sola (predefinita: la
    prima traccia video con clip). Restituisce file, formato, clip uscite e
    avvisi su quello che non e' potuto uscire.
    """
    fmt = formato(path)
    avvisi: list[str] = []
    rate = _rate(project.settings.fps)
    if fmt == "edl":
        testo, n = _edl(project, rate, track, avvisi)
    elif fmt == "fcpxml":
        testo, n = _fcpxml(project, rate, avvisi)
    else:
        testo, n = _otio(project, rate, avvisi)
    _avvisi_comuni(project, avvisi)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(testo, encoding="utf-8", newline="\n" if fmt != "edl" else "\r\n")
    return {"file": str(out), "formato": fmt, "clip": n, "avvisi": avvisi}


def _traccia_edl(project: Project, track: str | None) -> Track:
    if track:
        t = next((x for x in project.tracks if x.id == track), None)
        if t is None:
            raise ValueError(f"unknown track {track!r}")
        return t
    for t in project.tracks:
        if t.kind == "video" and t.clips:
            return t
    for t in project.tracks:
        if t.clips:
            return t
    raise ValueError("empty timeline: nothing to export")


def _edl(project: Project, rate: Fraction, track: str | None, avvisi: list[str]) -> tuple[str, int]:
    t = _traccia_edl(project, track)
    altre = [x.id for x in project.tracks if x is not t and x.clips]
    if altre:
        avvisi.append(f"an EDL carries one track only ({t.id}): left out {', '.join(altre)}; "
                      "for all of them use .fcpxml or .otio")
    pezzi = _pezzi(project, t, rate, avvisi)
    if any(p.entra for p in pezzi):
        avvisi.append("in the EDL transitions become cuts halfway through the overlap")
    # come Premiere e Resolve: la registrazione parte da un'ora
    ora = int(round(float(rate))) * 3600
    canale = "V" if t.kind == "video" else "AA"
    titolo = re.sub(r"[^\w .-]", "", project.name or "vedit")[:60] or "vedit"
    righe = [f"TITLE: {titolo}", "FCM: NON-DROP FRAME", ""]
    for i, p in enumerate(pezzi, 1):
        k = abs(p.speed) or 1.0
        src_in = p.src if p.speed > 0 else p.src - int(round(p.dur * k))
        src_out = src_in + int(round(p.dur * k))
        if p.speed < 0:
            src_in, src_out = src_out, src_in
        righe.append(f"{i:03d}  AX       {canale:<5} C        {_tc(src_in, rate)} {_tc(src_out, rate)} "
                     f"{_tc(ora + p.rec, rate)} {_tc(ora + p.rec + p.dur, rate)}")
        if abs(p.speed - 1.0) > 1e-6:
            righe.append(f"M2   AX       {float(rate) * p.speed:05.1f}    {_tc(src_in, rate)}")
        righe.append(f"* FROM CLIP NAME: {Path(p.media_path).name}")
        righe.append(f"* SOURCE FILE: {p.media_path}")
        righe.append("")
    return "\n".join(righe), len(pezzi)


def _fcpxml(project: Project, rate: Fraction, avvisi: list[str]) -> tuple[str, int]:
    fd = Fraction(1) / rate                   # durata di un fotogramma

    def tempo(frames: int) -> str:
        v = fd * frames
        return f"{v.numerator}/{v.denominator}s" if v.denominator != 1 else f"{v.numerator}s"

    st = project.settings
    root = ET.Element("fcpxml", version="1.9")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", frameDuration=tempo(1),
                  width=str(st.width), height=str(st.height))
    asset_di: dict[str, str] = {}
    for m in project.media:
        if m.kind == "image" or not any(c.media == m.id for t in project.tracks for c in t.clips):
            continue
        aid = f"r{len(asset_di) + 2}"
        asset_di[m.id] = aid
        a = ET.SubElement(res, "asset", id=aid, name=Path(m.path).stem, start="0s",
                          duration=tempo(_fotogrammi(m.duration, rate)),
                          hasVideo="1" if m.has_video else "0",
                          hasAudio="1" if m.has_audio else "0", format="r1")
        if m.has_audio:
            a.set("audioSources", "1")
            a.set("audioChannels", str(m.channels or 2))
            a.set("audioRate", str(m.sample_rate or st.sample_rate))
        ET.SubElement(a, "media-rep", kind="original-media", src=_url(m.path))

    totale = _fotogrammi(project.duration(), rate)
    lib = ET.SubElement(root, "library")
    ev = ET.SubElement(lib, "event", name="vedit")
    pr = ET.SubElement(ev, "project", name=project.name or "vedit")
    seq = ET.SubElement(pr, "sequence", format="r1", duration=tempo(totale), tcStart="0s",
                        tcFormat="NDF", audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(seq, "spine")

    video = [t for t in project.tracks if t.kind == "video"]
    audio = [t for t in project.tracks if t.kind == "audio"]
    principale = video[0] if video else None
    collegati = {c.link for t in video for c in t.clips if c.link}
    n = 0

    def asset_clip(parent, p: Pezzo, offset: int, lane: int | None = None, solo_audio=False):
        e = ET.SubElement(parent, "asset-clip", ref=asset_di[p.clip.media], offset=tempo(offset),
                          name=p.clip.name or Path(p.media_path).stem, start=tempo(p.src),
                          duration=tempo(p.dur), tcFormat="NDF")
        if lane is not None:
            e.set("lane", str(lane))
        if solo_audio:
            e.set("srcEnable", "audio")
        if p.clip.audio.mute and not solo_audio:
            e.set("srcEnable", "video")
        if abs(p.speed - 1.0) > 1e-6:
            avvisi.append(f"clip {p.clip.id}: the {p.speed}x speed does not go out in FCPXML "
                          "(use .otio)")
        return e

    # trama principale: la prima traccia video, con i buchi riempiti da gap
    elementi: list[tuple[int, int, int, ET.Element]] = []   # (offset, dur, start locale, elemento)
    pos = 0
    if principale is not None:
        for p in _pezzi(project, principale, rate, avvisi):
            if p.rec > pos:
                g = ET.SubElement(spine, "gap", name="Gap", offset=tempo(pos), start="0s",
                                  duration=tempo(p.rec - pos))
                elementi.append((pos, p.rec - pos, 0, g))
            if p.entra:
                ET.SubElement(spine, "transition", name="Cross Dissolve",
                              offset=tempo(p.rec - p.entra // 2), duration=tempo(p.entra))
            e = asset_clip(spine, p, p.rec)
            elementi.append((p.rec, p.dur, p.src, e))
            pos = p.rec + p.dur
            n += 1
    if totale > pos:
        g = ET.SubElement(spine, "gap", name="Gap", offset=tempo(pos), start="0s",
                          duration=tempo(totale - pos))
        elementi.append((pos, totale - pos, 0, g))

    def aggancia(p: Pezzo, lane: int, solo_audio: bool) -> None:
        nonlocal n
        for off, dur, start, el in elementi:
            if off <= p.rec < off + dur:
                asset_clip(el, p, start + (p.rec - off), lane, solo_audio)
                n += 1
                return
        avvisi.append(f"clip {p.clip.id}: outside the sequence duration, skipped")

    # le altre tracce: clip agganciate su corsie sopra (video) e sotto (audio)
    for lane, t in enumerate(video[1:], 1):
        for p in _pezzi(project, t, rate, avvisi):
            aggancia(p, lane, False)
    for i, t in enumerate(audio, 1):
        for p in _pezzi(project, t, rate, avvisi):
            # l'audio collegato a un video esce gia' con il video
            if p.clip.link and p.clip.link in collegati:
                continue
            aggancia(p, -i, True)

    ET.indent(root, "  ")
    corpo = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + corpo + "\n", n


def _otio(project: Project, rate: Fraction, avvisi: list[str]) -> tuple[str, int]:
    r = float(rate)

    def rt(v: int) -> dict:
        return {"OTIO_SCHEMA": "RationalTime.1", "rate": r, "value": float(v)}

    def rango(start: int, dur: int) -> dict:
        return {"OTIO_SCHEMA": "TimeRange.1", "start_time": rt(start), "duration": rt(dur)}

    def base(schema: str, name: str = "") -> dict:
        return {"OTIO_SCHEMA": schema, "name": name, "metadata": {}}

    media = {m.id: m for m in project.media}
    tracce = []
    n = 0
    for t in project.tracks:
        figli = []
        pos = 0
        for p in _pezzi(project, t, rate, avvisi):
            if p.rec > pos:
                figli.append({**base("Gap.1"), "source_range": rango(0, p.rec - pos),
                              "effects": [], "markers": []})
            if p.entra and figli and figli[-1]["OTIO_SCHEMA"] == "Clip.1":
                meta = p.entra // 2
                figli.append({**base("Transition.1", "Cross Dissolve"),
                              "transition_type": "SMPTE_Dissolve",
                              "in_offset": rt(meta), "out_offset": rt(p.entra - meta)})
            m = media[p.clip.media]
            effetti = []
            if abs(p.speed - 1.0) > 1e-6:
                effetti.append({**base("LinearTimeWarp.1", "speed"), "effect_name": "LinearTimeWarp",
                                "time_scalar": p.speed})
            figli.append({
                **base("Clip.1", p.clip.name or Path(m.path).stem),
                "source_range": rango(p.src, p.dur),
                "media_reference": {**base("ExternalReference.1"), "target_url": _url(m.path),
                                    "available_range": rango(0, _fotogrammi(m.duration, rate))},
                "effects": effetti, "markers": [],
                "metadata": {"vedit": {"clip": p.clip.id, "track": t.id}},
            })
            pos = p.rec + p.dur
            n += 1
        tracce.append({**base("Track.1", t.id), "kind": "Video" if t.kind == "video" else "Audio",
                       "children": figli, "source_range": None, "effects": [], "markers": []})
    doc = {**base("Timeline.1", project.name or "vedit"), "global_start_time": None,
           "tracks": {**base("Stack.1", "tracks"), "children": tracce, "source_range": None,
                      "effects": [], "markers": []}}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n", n


# --------------------------------------------------------------------------
# importa
# --------------------------------------------------------------------------

@dataclass
class Voce:
    """Una clip da mettere in timeline, letta da un file di un altro montaggio."""
    path: str
    kind: str          # video | audio: su che tipo di traccia
    corsia: int        # 0, 1, 2... dal basso fra le tracce di quel tipo
    start: float
    in_: float
    duration: float
    speed: float = 1.0
    nome: str = ""


@dataclass
class Dissolvenza:
    """Transizione sul taglio: ``prima`` secondi prima, ``dopo`` secondi dopo."""
    kind: str
    corsia: int
    taglio: float
    prima: float
    dopo: float


def importa(store, path: str, cartella: str | None = None, testo: str | None = None) -> dict:
    """Legge una timeline (.edl, .fcpxml, .otio) e la mette in coda a quella del progetto.

    ``cartella`` serve all'EDL, che non porta percorsi: i file si cercano per
    nome li' e fra i media gia' importati. ``testo`` e' il contenuto gia' letto
    (un file trascinato nel browser non ha percorso): allora ``path`` serve solo
    per l'estensione. Tutto in un ``batch``: un solo undo, e se un file manca
    non entra niente.
    """
    fmt = formato(path)
    if testo is None:
        testo = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        cartella = cartella or str(Path(path).parent)
    testo = testo.lstrip("\ufeff")
    avvisi: list[str] = []
    dissolvenze: list[Dissolvenza] = []
    rate = _rate(store.project.settings.fps)
    if fmt == "otio":
        voci = _leggi_otio(testo, avvisi, dissolvenze)
    elif fmt == "fcpxml":
        voci = _leggi_fcpxml(testo, avvisi, dissolvenze)
    else:
        voci = _leggi_edl(testo, rate, store, cartella, avvisi)
    if not voci:
        raise ValueError("no clips to import in this file")
    mancanti = sorted({v.path for v in voci if not Path(v.path).is_file()})
    if mancanti:
        elenco = ", ".join(mancanti[:5]) + (" e altri" if len(mancanti) > 5 else "")
        raise ValueError(f"files not found: {elenco}")

    # si accoda: niente di quello che c'e' gia' viene toccato
    coda = store.project.duration()
    with store.batch():
        gia = {str(Path(m.path).resolve()).lower(): m for m in store.project.media}
        nuovi = [p for p in dict.fromkeys(v.path for v in voci)
                 if str(Path(p).resolve()).lower() not in gia]
        for m in store.import_media(nuovi) if nuovi else []:
            gia[str(Path(m.path).resolve()).lower()] = m
        tracce = {"video": [t for t in store.project.tracks if t.kind == "video"],
                  "audio": [t for t in store.project.tracks if t.kind == "audio"]}
        for kind in ("video", "audio"):
            serve = max((v.corsia for v in voci if v.kind == kind), default=-1) + 1
            while len(tracce[kind]) < serve:
                tracce[kind].append(store.add_track(kind))
        voci_clip = []
        for v in sorted(voci, key=lambda x: x.start):
            m = gia[str(Path(v.path).resolve()).lower()]
            if v.kind == "video" and not m.has_video:
                avvisi.append(f"{Path(v.path).name}: no video, put on an audio track")
                v.kind, v.corsia = "audio", 0
                if not tracce["audio"]:
                    tracce["audio"].append(store.add_track("audio"))
            voci_clip.append((v, store.add_clip(m.id, tracce[v.kind][v.corsia].id,
                                                coda + v.start, max(0.0, v.in_), v.duration,
                                                name=v.nome or None)))
        for v, c in voci_clip:
            if abs(v.speed - 1.0) > 1e-6:
                store.set_speed(c.id, abs(v.speed), keep_duration=True)
                if v.speed < 0:
                    store.set_reverse(c.id, True)
        fatte = sum(_rimetti(store, tracce[d.kind][d.corsia], coda + d.taglio, d, avvisi)
                    for d in dissolvenze if d.corsia < len(tracce[d.kind]))
    return {"formato": fmt, "clip": len(voci_clip), "transizioni": fatte, "da": round(coda, 3),
            "media_nuovi": len(nuovi), "avvisi": list(dict.fromkeys(avvisi))}


def _rimetti(store, track, taglio: float, d: Dissolvenza, avvisi: list[str]) -> int:
    """Ritorna alla sovrapposizione di vedit: le due clip si allungano nelle maniglie."""
    a = next((c for c in track.clips if abs(c.end - taglio) < 1e-3), None)
    b = next((c for c in track.clips if abs(c.start - taglio) < 1e-3), None)
    if a is None or b is None:
        return 0
    media = {m.id: m for m in store.project.media}
    ma, mb = media.get(a.media), media.get(b.media)
    ka, kb = abs(a.speed or 1.0), abs(b.speed or 1.0)
    if (ma and ma.duration and a.in_ + (a.duration + d.dopo) * ka > ma.duration + 1e-3)             or b.in_ - d.prima * kb < -1e-3 or a.reverse or b.reverse:
        avvisi.append(f"transition at {round(taglio, 2)}s: not enough material past the "
                      "cut, it stays a hard cut")
        return 0
    store.set_clip(a.id, duration=a.duration + d.dopo)
    store.set_clip(b.id, start=b.start - d.prima, in_=max(0.0, b.in_ - d.prima * kb),
                   duration=b.duration + d.prima)
    store.set_transition(a.id, "dissolve", d.prima + d.dopo)
    return 1


def _leggi_otio(testo: str, avvisi: list[str], dissolvenze: list[Dissolvenza]) -> list[Voce]:
    doc = json.loads(testo)
    if not str(doc.get("OTIO_SCHEMA", "")).startswith("Timeline"):
        raise ValueError("not an OTIO timeline")

    def secondi(t: dict | None) -> float:
        return float(t["value"]) / float(t["rate"]) if t and t.get("rate") else 0.0

    voci: list[Voce] = []
    corsie = {"Video": 0, "Audio": 0}
    for tr in doc["tracks"].get("children", []):
        kind = tr.get("kind", "Video")
        if kind not in corsie:
            continue
        corsia = corsie[kind]
        corsie[kind] += 1
        pos = 0.0
        for el in tr.get("children", []):
            schema = str(el.get("OTIO_SCHEMA", ""))
            sr = el.get("source_range") or {}
            dur = secondi(sr.get("duration"))
            if schema.startswith("Gap"):
                pos += dur
            elif schema.startswith("Clip"):
                ref = el.get("media_reference") or {}
                if not ref and el.get("media_references"):
                    ref = el["media_references"].get(el.get("active_media_reference_key")
                                                     or "DEFAULT_MEDIA", {})
                p = _percorso(ref.get("target_url", ""))
                speed = 1.0
                for fx in el.get("effects", []):
                    if "time_scalar" in fx:
                        speed = float(fx["time_scalar"]) or 1.0
                if p:
                    voci.append(Voce(p, kind.lower(), corsia, pos, secondi(sr.get("start_time")),
                                     dur, speed, el.get("name", "")))
                else:
                    avvisi.append(f"clip {el.get('name', '')!r} without a file: skipped")
                pos += dur
            elif schema.startswith("Transition"):
                dissolvenze.append(Dissolvenza(kind.lower(), corsia, pos,
                                               secondi(el.get("in_offset")),
                                               secondi(el.get("out_offset"))))
            elif schema.startswith("Stack"):
                avvisi.append("nested OTIO clips: skipped")
                pos += dur
    return voci


def _leggi_fcpxml(testo: str, avvisi: list[str], dissolvenze: list[Dissolvenza]) -> list[Voce]:
    root = ET.fromstring(testo)
    if root.tag != "fcpxml":
        raise ValueError("not an FCPXML")

    def secondi(v: str | None) -> float:
        if not v:
            return 0.0
        v = v.rstrip("s")
        return float(Fraction(v)) if "/" in v else float(v)

    file_di = {}
    for a in root.iter("asset"):
        rep = a.find("media-rep")
        src = rep.get("src") if rep is not None else a.get("src", "")
        file_di[a.get("id")] = _percorso(src)
    seq = next(root.iter("sequence"), None)
    if seq is None:
        raise ValueError("FCPXML without a sequence")
    spine = seq.find("spine")
    voci: list[Voce] = []
    corsie_video: dict[int, int] = {}
    corsie_audio: dict[int, int] = {}

    def corsia(lane: int) -> tuple[str, int]:
        if lane >= 0:
            return "video", corsie_video.setdefault(lane, len(corsie_video))
        return "audio", corsie_audio.setdefault(lane, len(corsie_audio))

    def clip(el, lane: int, assoluto: float) -> None:
        ref = el.get("ref")
        if el.tag == "clip":         # contenitore di Final Cut: dentro c'e' video o asset-clip
            # un Element senza figli vale falso: niente catene di "or"
            dentro = next((x for x in (el.find("video"), el.find("asset-clip"), el.find("audio"))
                           if x is not None), None)
            ref = dentro.get("ref") if dentro is not None else None
        p = file_di.get(ref or "", "")
        if not p:
            avvisi.append(f"{el.tag} {el.get('name', '')!r} without a file: skipped")
            return
        kind, n = corsia(lane)
        if el.get("srcEnable") == "audio" and kind == "video":
            kind, n = "audio", corsia(-1)[1]
        voci.append(Voce(p, kind, n, assoluto, secondi(el.get("start")),
                         secondi(el.get("duration")), 1.0, el.get("name", "")))
        if el.find("timeMap") is not None:
            avvisi.append(f"{el.get('name', '')!r}: FCPXML speed change not read")

    def visita(contenitore, base_assoluta: float, start_locale: float) -> None:
        for el in contenitore:
            if el.tag not in ("asset-clip", "clip", "gap", "video", "audio", "ref-clip",
                              "transition", "title"):
                continue
            lane = int(el.get("lane", "0"))
            assoluto = base_assoluta + secondi(el.get("offset")) - start_locale
            if el.tag == "transition":
                # la transizione e' centrata sul taglio fra la clip prima e quella dopo
                dur = secondi(el.get("duration"))
                prossima = next((x for x in list(contenitore)[list(contenitore).index(el) + 1:]
                                 if x.tag in ("asset-clip", "clip", "gap")), None)
                if prossima is not None and lane == 0:
                    taglio = base_assoluta + secondi(prossima.get("offset")) - start_locale
                    meta = taglio - assoluto
                    dissolvenze.append(Dissolvenza("video", 0, taglio, meta, dur - meta))
                continue
            if el.tag in ("ref-clip", "title"):
                avvisi.append(f"{el.tag} {el.get('name', '')!r}: not imported")
            elif el.tag != "gap":
                clip(el, lane, assoluto)
            # le agganciate contano il tempo dall'attacco di chi le porta
            visita(el, assoluto, secondi(el.get("start")))

    if spine is not None:
        visita(spine, 0.0, 0.0)
    return voci


_EVENTO = re.compile(
    r"^\s*(\d{1,6})\s+(\S+)\s+(\S+)\s+(C|D|W\d+|K\s*B?)\s*(\d*)\s+"
    r"(\d\d[:;.]\d\d[:;.]\d\d[:;.]\d\d)\s+(\d\d[:;.]\d\d[:;.]\d\d[:;.]\d\d)\s+"
    r"(\d\d[:;.]\d\d[:;.]\d\d[:;.]\d\d)\s+(\d\d[:;.]\d\d[:;.]\d\d[:;.]\d\d)")


def _leggi_edl(testo: str, rate: Fraction, store, cartella: str | None,
               avvisi: list[str]) -> list[Voce]:
    eventi: list[dict] = []
    for riga in testo.splitlines():
        m = _EVENTO.match(riga)
        if m:
            eventi.append({"canale": m.group(3).upper(), "tipo": m.group(4),
                           "src": [_da_tc(m.group(6), rate), _da_tc(m.group(7), rate)],
                           "rec": [_da_tc(m.group(8), rate), _da_tc(m.group(9), rate)],
                           "nome": "", "file": "", "speed": 1.0})
            continue
        if not eventi:
            continue
        e = eventi[-1]
        if riga.startswith("* FROM CLIP NAME:"):
            e["nome"] = riga.split(":", 1)[1].strip()
        elif riga.startswith("* SOURCE FILE:"):
            e["file"] = riga.split(":", 1)[1].strip()
        elif riga.startswith("M2"):
            parti = riga.split()
            try:
                e["speed"] = float(parti[2]) / float(rate)
            except (IndexError, ValueError):
                pass
    if not eventi:
        raise ValueError("no events in this EDL")

    # la registrazione di solito parte da un'ora (01:00:00:00): si riporta a zero
    ora = int(round(float(rate))) * 3600
    zero = (min(e["rec"][0] for e in eventi) // ora) * ora
    noti = {Path(m.path).name.lower(): m.path for m in store.project.media}
    voci = []
    for e in eventi:
        if e["tipo"] != "C":
            avvisi.append("EDL transitions: they come in as cuts")
        p = e["file"] if e["file"] and Path(e["file"]).is_file() else ""
        if not p and e["nome"]:
            p = noti.get(e["nome"].lower(), "")
            if not p and cartella and (Path(cartella) / e["nome"]).is_file():
                p = str(Path(cartella) / e["nome"])
        if not p:
            raise ValueError(f"EDL: cannot find the file for {e['nome'] or 'an unnamed event'}; "
                             "put it next to the EDL or import it into the project first")
        kind = "video" if "V" in e["canale"] else "audio"
        speed = e["speed"] or 1.0
        src_in = min(e["src"]) / float(rate)
        dur = (e["rec"][1] - e["rec"][0]) / float(rate)
        if dur <= 0:
            continue
        voci.append(Voce(p, kind, 0, (e["rec"][0] - zero) / float(rate), src_in, dur,
                         speed if e["src"][1] >= e["src"][0] else -abs(speed), e["nome"]))
    return voci

