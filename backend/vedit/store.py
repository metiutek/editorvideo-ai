"""Operazioni di editing sul progetto + persistenza.

Questo modulo e' l'unica superficie di modifica: il server MCP e l'API REST
chiamano gli stessi metodi, quindi UI e agente non possono divergere.
Ogni mutazione crea uno snapshot per undo/redo e (se il progetto ha un file)
salva su disco.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import effects as fx
from . import captions, htmlclip
from . import particelle
from . import keyframes as kf
from . import probe as probe_mod
from .model import (
    AUDIO_LAYOUTS,
    BLEND_MODES,
    SURROUND,
    TRANSITIONS,
    Clip,
    ClipAudio,
    Effect,
    Master,
    Media,
    Project,
    Settings,
    TextStyle,
    Track,
    Transform,
    Transition,
    new_id,
)

MAX_HISTORY = 100

PRESETS = {
    "1080p": (1920, 1080, 30.0),
    "1080p60": (1920, 1080, 60.0),
    "4k": (3840, 2160, 30.0),
    "720p": (1280, 720, 30.0),
    "vertical": (1080, 1920, 30.0),  # reel / short / tiktok
    "vertical60": (1080, 1920, 60.0),
    "square": (1080, 1080, 30.0),
}

# Rapporti d'aspetto. Il lato corto e' la qualita' (720, 1080, 2160): 9:16 a
# 1080 e' 1080x1920, 4:5 e' 1080x1350, 21:9 e' 2520x1080.
FORMATI = {
    "16:9": (16, 9),     # YouTube, TV
    "9:16": (9, 16),     # reel, short, TikTok, storie
    "1:1": (1, 1),       # feed quadrato
    "4:5": (4, 5),       # feed verticale Instagram / Facebook
    "4:3": (4, 3),
    "3:4": (3, 4),
    "21:9": (21, 9),     # cinemascope
    "2:3": (2, 3),       # Pinterest
}


def risoluzione(formato: str, lato: int = 1080) -> tuple[int, int]:
    """Larghezza e altezza per un formato: "9:16", "4:5" o "WxH" esplicito.

    Le dimensioni escono pari: gli encoder in yuv420p rifiutano le dispari.
    """
    f = str(formato).strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d+)x(\d+)", f)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)[:/](\d+(?:\.\d+)?)", f)
        if not m or float(m.group(1)) <= 0 or float(m.group(2)) <= 0:
            raise EditError(f"unknown format {formato!r}; use a ratio like "
                            f"{', '.join(FORMATI)} or WIDTHxHEIGHT")
        a, b = float(m.group(1)), float(m.group(2))
        lato = int(lato)
        if not 144 <= lato <= 4320:
            raise EditError("size (the short side) must be between 144 and 4320")
        w, h = (lato * a / b, lato) if a >= b else (lato, lato * b / a)
    w, h = 2 * round(w / 2), 2 * round(h / 2)
    if not (16 <= w <= 8192 and 16 <= h <= 8192):
        raise EditError(f"resolution {w}x{h} out of range (16-8192 per side)")
    return w, h


def rapporto(w: int, h: int) -> str:
    """Il formato con cui chiamare una risoluzione: "16:9", "9:16"... o "WxH"."""
    for nome, (a, b) in FORMATI.items():
        if abs(w * b - h * a) <= max(a, b) * 2:
            return nome
    return f"{w}x{h}"


class EditError(ValueError):
    """Errore di editing con messaggio comprensibile all'utente."""


class Store:
    def __init__(self, project: Project, path: str | None = None, autosave: bool = True):
        self.project = project
        self.path = str(Path(path).resolve()) if path else None
        self.autosave = autosave
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._batch = 0
        # Contatore delle modifiche concluse. Chi deve sapere se il progetto e'
        # cambiato (la revisione delle anteprime nella UI) lo confronta invece
        # di serializzare e confrontare l'intero documento a ogni richiesta.
        self.version = 0
        # chiamata dopo ogni modifica conclusa. La usa l'interfaccia web per
        # aggiornarsi quando a montare e' l'agente: stesso Store, un solo
        # scrittore, niente due processi che si sovrascrivono il file.
        self.on_change = None

    # ---- ciclo di vita -------------------------------------------------
    @classmethod
    def create(cls, name: str = "untitled", preset: str = "1080p", path: str | None = None,
               width: int | None = None, height: int | None = None, fps: float | None = None,
               size: int | None = None) -> "Store":
        """preset: un nome di PRESETS oppure un formato ("9:16", "4:5", "1280x720");
        size e' il lato corto per i formati a rapporto (1080 di norma)."""
        if preset in PRESETS:
            w, h, f = PRESETS[preset]
        else:
            try:
                w, h = risoluzione(preset, size or 1080)
            except EditError:
                raise EditError(f"unknown preset {preset!r}; available: {', '.join(PRESETS)}, "
                                f"or a format: {', '.join(FORMATI)}, WIDTHxHEIGHT") from None
            f = 30.0
        settings = Settings(width=width or w, height=height or h, fps=fps or f)
        p = Project(name=name, settings=settings, master=Master())
        p.tracks = [
            Track(id="V1", kind="video", name="V1"),
            Track(id="A1", kind="audio", name="A1"),
        ]
        s = cls(p, path)
        if path:
            s.save()
        return s

    @classmethod
    def open(cls, path: str) -> "Store":
        f = Path(path)
        if not f.exists():
            raise EditError(f"project not found: {path}")
        data = json.loads(f.read_text(encoding="utf-8"))
        return cls(Project.from_obj(data), str(f.resolve()))

    def save(self, path: str | None = None) -> str:
        """Salva il progetto sostituendo il file, non riscrivendolo sul posto.

        Il salvataggio e' automatico dopo ogni modifica, quindi capita spesso e
        anche da piu' processi (interfaccia e server MCP sullo stesso file). Con
        una scrittura diretta un'interruzione a meta' lascia un progetto
        troncato, e su Windows basta che qualcun altro tenga aperto il file in
        quell'istante per far fallire l'operazione a modifica gia' avvenuta.
        ``os.replace`` e' atomico: o c'e' la versione vecchia o quella nuova.
        """
        target = Path(path or self.path or "")
        if not str(target):
            raise EditError("no save path: pass path=")
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(self.project.to_dict(), indent=2, ensure_ascii=False)

        def write_once() -> None:
            tmp = target.with_name(f"~{uuid.uuid4().hex[:8]}_{target.name}")
            try:
                tmp.write_text(blob, encoding="utf-8")
                os.replace(tmp, target)
            except OSError:
                tmp.unlink(missing_ok=True)
                raise

        # Su Windows sia la scrittura del temporaneo sia la sostituzione possono
        # fallire mentre qualcun altro tiene aperto il file (l'altro processo,
        # l'antivirus): sono attese brevissime, si riprova per circa un secondo.
        last: OSError | None = None
        for attempt in range(10):
            try:
                write_once()
                break
            except OSError as exc:
                last = exc
                time.sleep(0.02 * (attempt + 1))
        else:
            raise EditError(f"saving to {target} failed: {last}")

        self.path = str(target.resolve())
        return self.path

    # ---- undo/redo -----------------------------------------------------
    def _touch(self) -> None:
        """Da chiamare *prima* di ogni mutazione."""
        if self._batch:
            return          # dentro un blocco lo snapshot e' gia' stato preso
        self._undo.append(self.project.to_dict())
        if len(self._undo) > MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()

    def _done(self) -> None:
        if self._batch:
            return          # si salva una volta sola, alla chiusura del blocco
        self.version += 1
        if self.autosave and self.path:
            self.save()
        if self.on_change:
            # un osservatore rotto non deve far fallire una modifica gia' fatta
            try:
                self.on_change()
            except Exception:
                pass

    @contextmanager
    def batch(self):
        """Piu' operazioni come una sola modifica: un undo, un salvataggio.

        Costruire un montaggio serrato vuol dire centinaia di chiamate. Una per
        una diventano centinaia di snapshot dell'intero progetto e altrettanti
        salvataggi su disco — lento — e soprattutto centinaia di passi di undo
        per disfare quello che per chi monta e' un gesto solo.

        Il blocco e' anche atomico: se una chiamata a meta' fallisce si torna
        com'era, invece di lasciare in timeline mezzo montaggio da ripulire a
        mano.
        """
        if self._batch:
            self._batch += 1
            try:
                yield self
            finally:
                self._batch -= 1
            return

        self._undo.append(self.project.to_dict())
        if len(self._undo) > MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()
        self._batch = 1
        try:
            yield self
        except Exception:
            self.project = Project.from_obj(self._undo.pop())
            self.version += 1   # chi ha letto lo stato a meta' blocco lo rilegge
            raise
        finally:
            self._batch = 0
        self._done()

    @contextmanager
    def _edit(self):
        """Una modifica singola che, se fallisce a meta', non lascia traccia.

        Diverse operazioni validano mentre scrivono (keyframe, stili, durate):
        un errore dopo il primo campo lasciava il progetto modificato a meta' e
        una voce di undo che non annullava niente di sensato. Dentro un blocco
        ``batch`` esterno e' quello a rimettere tutto a posto.
        """
        with self.batch():
            yield self

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.project.to_dict())
        self.project = Project.from_obj(self._undo.pop())
        self._done()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.project.to_dict())
        self.project = Project.from_obj(self._redo.pop())
        self._done()
        return True

    # ---- media ---------------------------------------------------------
    def import_media(self, paths: list[str], folder: str | None = None,
                     probed: dict[str, Media] | None = None) -> list[Media]:
        """Importa i file; ``folder`` e' la cartella del bin dei media nuovi.

        I metadati si leggono in parallelo: uno alla volta, cinquecento file
        tenevano fermo l'editor per minuti. ``probed`` sono metadati gia' letti
        da chi chiama (l'API li legge fuori dal lock, cosi' la UI non si ferma
        mentre ffprobe lavora). Atomico: un file illeggibile non lascia
        importati gli altri.
        """
        nuovi = [p for p in dict.fromkeys(paths)
                 if not self.project.media_by_path(str(Path(p).resolve()))
                 and not (probed and p in probed)]
        letti = dict(probed or {})
        for p, esito in probe_mod.probe_many(nuovi).items():
            if isinstance(esito, Exception):
                raise esito
            letti[p] = esito
        cartella = (folder or "").strip().strip("/")
        with self._edit():
            out = []
            for p in paths:
                existing = self.project.media_by_path(str(Path(p).resolve()))
                if existing:
                    if existing not in out:
                        out.append(existing)
                    continue
                m = letti[p]
                if cartella:
                    m.folder = cartella
                self.project.media.append(m)
                out.append(m)
        return out

    def set_media(self, media_id: str, folder: str | None = None, name: str | None = None) -> Media:
        """Rinomina un media o lo sposta in una cartella del bin ('' = radice)."""
        m = self.media_or_die(media_id)
        self._touch()
        if folder is not None:
            m.folder = folder.strip().strip("/")
        if name:
            m.name = name
        self._done()
        return m

    def remove_media(self, media_id: str, force: bool = False) -> dict:
        """Toglie un media dal progetto. Con force elimina anche le sue clip."""
        m = self.media_or_die(media_id)
        used = [c.id for t in self.project.tracks for c in t.clips if c.media == m.id]
        if used and not force:
            raise EditError(
                f"{m.name} is used by {len(used)} clips ({', '.join(used[:4])}"
                f"{'...' if len(used) > 4 else ''}); use force=true to delete them"
            )
        self._touch()
        for t in self.project.tracks:
            t.clips = [c for c in t.clips if c.media != m.id]
        self.project.media.remove(m)
        self._done()
        return {"rimosso": m.id, "clip_eliminate": len(used)}

    def rename_folder(self, old: str, new: str) -> int:
        """Rinomina/sposta una cartella del bin, sottocartelle comprese."""
        old = old.strip("/")
        new = new.strip().strip("/")
        self._touch()
        n = 0
        for m in self.project.media:
            if m.folder == old or m.folder.startswith(old + "/"):
                m.folder = new + m.folder[len(old):] if new else m.folder[len(old):].lstrip("/")
                n += 1
        self._done()
        return n

    def media_or_die(self, media_id: str) -> Media:
        m = self.project.media_by_id(media_id)
        if m is None:
            known = ", ".join(f"{x.id}({x.name})" for x in self.project.media) or "nessuno"
            raise EditError(f"media {media_id!r} does not exist; imported: {known}")
        return m

    # ---- tracce --------------------------------------------------------
    def add_track(self, kind: str = "video", name: str | None = None, index: int | None = None) -> Track:
        if kind not in ("video", "audio"):
            raise EditError("kind must be 'video' or 'audio'")
        self._touch()
        same = [t for t in self.project.tracks if t.kind == kind]
        tid = f"{'V' if kind == 'video' else 'A'}{len(same) + 1}"
        while self.project.track_by_id(tid):
            tid = new_id("t")
        t = Track(id=tid, kind=kind, name=name or tid)
        if index is None:
            self.project.tracks.append(t)
        else:
            self.project.tracks.insert(index, t)
        self._done()
        return t

    def _crea_traccia(self, track_id: str) -> None:
        """``V3``/``A2`` che non esiste ancora: crea le tracce che mancano fino a lei.

        Chi costruisce un montaggio a piu' tracce con add_clips sa gia' dove
        vuole le cose; fermarlo per un add_track per traccia e' solo un giro in
        piu'. Un nome che non ha la forma V<n>/A<n> resta un errore.
        """
        m = re.fullmatch(r"([VA])(\d+)", track_id or "")
        if not m or self.project.track_by_id(track_id) or int(m.group(2)) > 16:
            return
        kind = "video" if m.group(1) == "V" else "audio"
        for _ in range(int(m.group(2))):
            if self.add_track(kind).id == track_id:
                return

    def track_or_die(self, track_id: str) -> Track:
        t = self.project.track_by_id(track_id)
        if t is None:
            known = ", ".join(x.id for x in self.project.tracks)
            raise EditError(f"track {track_id!r} does not exist; available: {known}")
        return t

    def track_for_edit(self, track_id: str) -> Track:
        """Come ``track_or_die``, ma rifiuta le tracce bloccate."""
        t = self.track_or_die(track_id)
        if t.locked:
            raise EditError(f"track {t.id} is locked: unlock it to edit it")
        return t

    def remove_track(self, track_id: str) -> None:
        t = self.track_for_edit(track_id)
        self._touch()
        self.project.tracks.remove(t)
        self._done()

    def move_track(self, track_id: str, index: int) -> list[str]:
        """Sposta una traccia nell'ordine, tra quelle dello stesso tipo.

        Per il video l'ordine e' la sovrapposizione: indice 0 sta sotto, l'ultimo
        sta sopra tutti. Le posizioni occupate dalle tracce dell'altro tipo non
        vengono toccate, cosi' l'ordine del file resta stabile.
        """
        t = self.track_or_die(track_id)
        same = [x for x in self.project.tracks if x.kind == t.kind]
        slots = [i for i, x in enumerate(self.project.tracks) if x.kind == t.kind]
        index = max(0, min(int(index), len(same) - 1))
        if same.index(t) == index:
            return [x.id for x in same]
        self._touch()
        same.remove(t)
        same.insert(index, t)
        for slot, track in zip(slots, same):
            self.project.tracks[slot] = track
        self._done()
        return [x.id for x in same]

    def set_track(self, track_id: str, *, hidden: bool | None = None, muted: bool | None = None,
                  volume: Any = None, name: str | None = None, locked: bool | None = None,
                  solo: bool | None = None, surround: str | None = None) -> Track:
        # volutamente non passa da track_for_edit: e' anche il modo di sbloccare
        t = self.track_or_die(track_id)
        if volume is not None:
            kf.validate(volume)
            volume = kf.coerce(volume)
        if surround is not None and surround not in SURROUND:
            raise EditError(f"unknown routing {surround!r}; allowed: {', '.join(SURROUND)}")
        self._touch()
        if surround is not None:
            t.surround = surround
        if hidden is not None:
            t.hidden = bool(hidden)
        if muted is not None:
            t.muted = bool(muted)
        if volume is not None:
            t.volume = volume
        if name is not None:
            t.name = name
        if locked is not None:
            t.locked = bool(locked)
        if solo is not None:
            t.solo = bool(solo)
        self._done()
        return t

    SIDECHAIN_DEFAULT = {"threshold": -30.0, "ratio": 6.0, "attack": 20.0,
                         "release": 400.0, "makeup": 1.0}
    _SIDECHAIN_LIMITI = {"threshold": (-60.0, 0.0), "ratio": (1.0, 20.0), "attack": (0.01, 2000.0),
                         "release": (0.01, 9000.0), "makeup": (1.0, 64.0)}

    def set_sidechain(self, track_id: str, source: str | None = None, **valori: Any) -> Track:
        """La traccia si abbassa da sola quando suona ``source``; source=None lo spegne.

        E' un compressore vero, che ascolta l'altra traccia mentre suona: a
        differenza di duck_music non scrive keyframe, quindi segue anche le
        modifiche fatte dopo.
        """
        t = self.track_or_die(track_id)
        if source in (None, "", False):
            self._touch()
            t.sidechain = None
            self._done()
            return t
        src = self.track_or_die(str(source))
        if src.id == t.id:
            raise EditError("a track cannot duck by listening to itself")
        ignoti = set(valori) - set(self.SIDECHAIN_DEFAULT)
        if ignoti:
            raise EditError(f"unknown sidechain parameters {sorted(ignoti)}; "
                            f"allowed: {sorted(self.SIDECHAIN_DEFAULT)}")
        conf = {**self.SIDECHAIN_DEFAULT, **(t.sidechain or {})}
        for k, v in valori.items():
            if v is None:
                continue
            lo, hi = self._SIDECHAIN_LIMITI[k]
            if not lo <= float(v) <= hi:
                raise EditError(f"sidechain {k}={v} outside {lo}..{hi}")
            conf[k] = float(v)
        conf["source"] = src.id
        self._touch()
        t.sidechain = conf
        self._done()
        return t

    # ---- clip ----------------------------------------------------------
    def clip_or_die(self, clip_id: str) -> tuple[Track, Clip]:
        found = self.project.find_clip(clip_id)
        if not found:
            ids = [c.id for t in self.project.tracks for c in t.clips]
            raise EditError(f"clip {clip_id!r} does not exist; present: {', '.join(ids) or 'none'}")
        return found

    def clip_for_edit(self, clip_id: str) -> tuple[Track, Clip]:
        """Accesso a una clip per modificarla: la traccia bloccata dice di no.

        Il blocco serve a proteggere il montaggio gia' fatto mentre si lavora
        sulle altre tracce, quindi va controllato qui, dove passano tutte le
        modifiche, e non in ogni singola operazione.
        """
        track, clip = self.clip_or_die(clip_id)
        if track.locked:
            raise EditError(
                f"clip {clip_id} is on the locked track {track.id}: unlock it first"
            )
        return track, clip

    def track_end(self, track: Track) -> float:
        return max((c.end for c in track.clips), default=0.0)

    def add_clip(self, media_id: str, track_id: str | None = None, start: float | None = None,
                 in_: float = 0.0, duration: float | None = None, name: str | None = None,
                 audio_collegato: bool = False) -> Clip:
        """Mette un media in timeline.

        Con ``audio_collegato`` una ripresa con audio entra come negli editor
        desktop: il video sulla traccia video, il suo audio su una traccia audio
        come clip a parte, collegate. Senza, l'audio resta dentro la clip video.
        """
        m = self.media_or_die(media_id)
        if audio_collegato and m.kind == "video" and m.has_audio:
            if track_id is None or self.track_or_die(track_id).kind == "video":
                with self.batch():
                    v = self.add_clip(media_id, track_id, start, in_, duration, name)
                    a = self.add_clip(media_id, self._audio_libera(v.start, v.end),
                                      v.start, v.in_, v.duration, name)
                    v.link = a.link = new_id("l")
                    v.audio.mute = True     # suona la clip audio, non tutte e due
                    return v
        if track_id is None:
            track_id = self._default_track("audio" if m.kind == "audio" else "video")
        track = self.track_for_edit(track_id)
        if m.kind == "audio" and track.kind != "audio":
            raise EditError(f"{m.name} is audio only: put it on an audio track")

        if duration is None:
            duration = m.duration - in_ if m.duration > 0 else 5.0  # immagini: 5s
        if duration <= 0:
            raise EditError(f"invalid duration ({duration}s): in_={in_} is past the end of the media ({m.duration}s)")
        if m.duration > 0 and in_ + duration > m.duration + 1e-3:
            duration = max(0.0, m.duration - in_)
            if duration <= 0:
                raise EditError(f"in_={in_}s is past the media duration ({m.duration}s)")

        self._touch()
        c = Clip(
            type="media", media=m.id,
            start=self.track_end(track) if start is None else max(0.0, float(start)),
            in_=max(0.0, float(in_)), duration=float(duration),
            name=name or m.name,
        )
        track.clips.append(c)
        track.clips.sort(key=lambda x: x.start)
        self._done()
        return c

    def add_text(self, text: str, track_id: str | None = None, start: float = 0.0, duration: float = 3.0,
                 **style: Any) -> Clip:
        st = TextStyle(text=text)
        for k, v in style.items():
            if not hasattr(st, k):
                raise EditError(f"unknown text style {k!r}; allowed: {', '.join(vars(st))}")
            setattr(st, k, v)
        if float(duration) <= 0:
            raise EditError("the duration must be > 0")
        track = self.track_for_edit(track_id or self._traccia_in_cima())
        self._touch()
        c = Clip(type="text", start=float(start), duration=float(duration), text=st,
                 name=(text[:24] or "testo"))
        track.clips.append(c)
        track.clips.sort(key=lambda x: x.start)
        self._done()
        return c

    def import_subtitles(self, path: str | None = None, testo: str | None = None,
                         fmt: str | None = None, offset: float = 0.0,
                         font_size: int | None = None) -> dict:
        """Un file .srt, .vtt o .ass diventa una traccia di testi, uno per sottotitolo.

        Sono clip di testo come le altre: si correggono, si spostano e si
        tagliano in timeline, e al render escono impressi o come traccia di
        sottotitoli nel file (``render`` con ``subtitle_track``). Traccia nuova
        in cima, chiamata "sottotitoli"; un solo passo di undo.
        """
        if testo is None:
            if not path:
                raise EditError("the subtitle file is needed")
            testo = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        fmt = (fmt or Path(path or "").suffix.lstrip(".")).lower()
        if fmt not in ("srt", "vtt", "ass", "ssa"):
            raise EditError(f".{fmt or '?'} subtitles not read: use .srt, .vtt or .ass")
        try:
            righe = captions.leggi(testo, "ass" if fmt == "ssa" else fmt)
        except ValueError as e:
            raise EditError(str(e)) from None
        st = self.project.settings
        # sopra il bordo basso, leggibili su qualunque ripresa: testo bianco su riquadro
        dimensione = int(font_size or max(24, round(st.height * 0.05)))
        y = round(st.height * 0.5 - dimensione * 2.2)
        with self.batch():
            track = self.add_track("video", name="subtitles")
            for r in righe:
                c = self.add_text(r["text"], track.id, max(0.0, r["start"] + float(offset)),
                                  r["end"] - r["start"], font_size=dimensione, box=True,
                                  box_opacity=0.55, box_padding=max(8, dimensione // 3))
                c.transform.y = y
        return {"track": track.id, "righe": len(righe),
                "da": round(righe[0]["start"] + offset, 3), "a": round(righe[-1]["end"] + offset, 3)}

    def add_color(self, color: str = "black", track_id: str | None = None, start: float = 0.0,
                  duration: float = 2.0) -> Clip:
        track = self.track_for_edit(track_id or self._default_track("video"))
        self._touch()
        c = Clip(type="color", color=color, start=float(start), duration=float(duration), name=color)
        track.clips.append(c)
        track.clips.sort(key=lambda x: x.start)
        self._done()
        return c

    @staticmethod
    def _sorgente_html(html: str | None, path: str | None,
                       vars: dict | None = None) -> tuple[str, str | None]:
        """Documento e cartella base da ``html`` (testo) o ``path`` (file .html).

        Il documento entra *nel progetto*: il render resta funzione del solo
        JSON anche se il file viene cambiato o spostato. La cartella serve ai
        percorsi relativi (immagini, font) e resta quella del file.

        ``vars`` riempie i segnaposto ``{{nome}}``: un solo modello per dieci
        cartelli diversi, invece di dieci documenti quasi uguali scritti per
        intero (e riletti, a ogni giro, nel contesto di chi li scrive).
        """
        if (html is None) == (path is None):
            raise EditError("pass html (the document) or path (an .html file), one of the two")
        base = None
        if path is not None:
            f = Path(path)
            if not f.is_file():
                raise EditError(f"html file not found: {path}")
            html = f.read_text(encoding="utf-8", errors="replace")
            base = str(f.resolve().parent)
        assert html is not None
        if vars:
            html = re.sub(r"\{\{\s*(\w+)\s*\}\}",
                          lambda m: str(vars[m.group(1)]) if m.group(1) in vars else m.group(0),
                          html)
            restano = sorted(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", html)))
            if restano:
                raise EditError(f"placeholders without a value in vars: {restano}")
        if not html.strip():
            raise EditError("the html document is empty")
        if len(html) > htmlclip.MAX_HTML:
            raise EditError(f"html document too large ({len(html)} characters)")
        return html, base

    def add_html(self, html: str | None = None, path: str | None = None, track_id: str | None = None,
                 start: float = 0.0, duration: float = 4.0, name: str | None = None,
                 base: str | None = None, vars: dict | None = None) -> Clip:
        """Grafica animata in HTML/CSS/JS sopra il video (vedi htmlclip.py).

        Senza ``html`` ne' ``path`` parte da un sottopancia di esempio.
        """
        if html is None and path is None:
            html = htmlclip.template(self.project.settings.width, self.project.settings.height)
        doc, cartella = self._sorgente_html(html, path, vars)
        if base is not None:
            if not Path(base).is_dir():
                raise EditError(f"base folder does not exist: {base}")
            cartella = str(Path(base).resolve())
        if float(duration) <= 0:
            raise EditError("the duration must be > 0")
        track = self.track_for_edit(track_id or self._traccia_in_cima())
        if track.kind != "video":
            raise EditError("an html clip goes on a video track")
        self._touch()
        c = Clip(type="html", html=doc, html_base=cartella, start=max(0.0, float(start)),
                 duration=float(duration), name=name or (Path(path).stem if path else "html"))
        track.clips.append(c)
        track.clips.sort(key=lambda x: x.start)
        self._done()
        return c

    def add_particles(self, kind: str = "snow", track_id: str | None = None, start: float = 0.0,
                      duration: float = 5.0, color: str | None = None, density: float = 1.0,
                      speed: float = 1.0, size: float = 1.0, seed: int = 1,
                      custom: dict | None = None) -> Clip:
        """Particelle (neve, scintille, coriandoli...) come clip html trasparente.

        ``kind`` e' un tipo integrato, ``custom`` con la ricetta in ``custom``
        (vedi ``particelle.valida``) o l'id di particelle personali salvate.
        """
        kind, custom, nome = self._particelle(kind, custom)
        doc = self._doc_particelle(kind, color, density, speed, size, seed, custom)
        return self.add_html(html=doc, track_id=track_id, start=start, duration=duration,
                             name=f"particelle {nome}")

    def set_particles(self, clip_id: str, kind: str | None = None, color: str | None = None,
                      density: float | None = None, speed: float | None = None,
                      size: float | None = None, seed: int | None = None,
                      custom: dict | None = None) -> Clip:
        """Cambia le particelle di una clip creata da ``add_particles``.

        Le voci assenti restano come sono; ``custom`` corregge solo le voci
        della ricetta che nomina. ``color=""`` toglie il colore imposto.
        """
        _, clip = self.clip_for_edit(clip_id)
        par = particelle.parametri(clip.html) if clip.type == "html" else None
        if par is None:
            raise EditError(f"clip {clip_id} is not made of particles")
        if kind is not None and kind != par["kind"]:
            kind, ricetta, nome = self._particelle(kind, custom)
        else:
            kind, nome = par["kind"], None
            ricetta = {**(par.get("custom") or {}), **(custom or {})} if kind == particelle.CUSTOM else None
            if kind == particelle.CUSTOM:
                try:
                    ricetta = particelle.valida(ricetta)
                except ValueError as e:
                    raise EditError(str(e)) from None
        val = lambda nuovo, vecchio: vecchio if nuovo is None else nuovo  # noqa: E731
        doc = self._doc_particelle(
            kind, val(color, par.get("color")) or None, val(density, par.get("density", 1.0)),
            val(speed, par.get("speed", 1.0)), val(size, par.get("size", 1.0)),
            val(seed, par.get("seed", 1)), ricetta)
        self._touch()
        clip.html = doc
        if nome:
            clip.name = f"particelle {nome}"
        self._done()
        return clip

    def _particelle(self, kind: str, custom: dict | None) -> tuple[str, dict | None, str]:
        """(tipo, ricetta, nome) da un tipo integrato, ``custom`` o un id personale."""
        if kind in particelle.KINDS:
            return kind, None, kind
        if kind == particelle.CUSTOM:
            try:
                return kind, particelle.valida(custom or {}), "personalizzate"
            except ValueError as e:
                raise EditError(str(e)) from None
        mie = particelle.trova(kind)
        if mie is None:
            nomi = [*particelle.KINDS, particelle.CUSTOM, *(p["id"] for p in particelle.personali())]
            raise EditError(f"unknown particles {kind!r}; choose from {', '.join(nomi)}")
        try:
            ricetta = particelle.valida({**mie["spec"], **(custom or {})})
        except ValueError as e:
            raise EditError(str(e)) from None
        return particelle.CUSTOM, ricetta, mie["nome"]

    def _doc_particelle(self, kind, color, density, speed, size, seed, custom) -> str:
        for nome, v in (("density", density), ("speed", speed), ("size", size)):
            if not 0 < float(v) <= 20:
                raise EditError(f"{nome} must be between 0 and 20")
        st = self.project.settings
        try:
            return particelle.html(kind, st.width, st.height, color, density, speed, size,
                                   seed, custom)
        except ValueError as e:
            raise EditError(str(e)) from None

    def set_html(self, clip_id: str, html: str | None = None, path: str | None = None,
                 base: str | None = None, vars: dict | None = None) -> Clip:
        """Sostituisce il documento di una clip html (o solo la cartella base)."""
        track, clip = self.clip_for_edit(clip_id)
        if clip.type != "html":
            raise EditError(f"clip {clip_id} is not an html clip")
        doc, cartella = (None, None)
        if html is not None or path is not None:
            doc, cartella = self._sorgente_html(html, path, vars)
        if base is not None and base != "" and not Path(base).is_dir():
            raise EditError(f"base folder does not exist: {base}")
        self._touch()
        if doc is not None:
            clip.html = doc
            if path is not None:
                clip.html_base = cartella
        if base is not None:
            clip.html_base = str(Path(base).resolve()) if base else None
        self._done()
        return clip

    def _traccia_in_cima(self) -> str:
        """Traccia video piu' in alto: dove va un titolo senza traccia indicata.

        Sulla prima traccia (quella in fondo) un titolo finiva sotto qualunque
        ripresa delle tracce sopra e nel file non si vedeva. In cima si vede
        sempre: dentro una traccia testi e grafica stanno gia' sopra i media.
        """
        libere = [t for t in self.project.video_tracks() if not t.locked]
        return libere[-1].id if libere else self._default_track("video")

    def _default_track(self, kind: str) -> str:
        t = next((t for t in self.project.tracks if t.kind == kind), None)
        if t is None:
            t = self.add_track(kind)
        return t.id

    def _audio_libera(self, start: float, end: float) -> str:
        """Prima traccia audio sbloccata e libera in quel tratto; se non c'e', una nuova."""
        for t in self.project.tracks:
            if t.kind == "audio" and not t.locked and all(
                    c.end <= start + 1e-6 or c.start >= end - 1e-6 for c in t.clips):
                return t.id
        return self.add_track("audio").id

    def collegate(self, clip: Clip) -> list[tuple[Track, Clip]]:
        """Le altre clip dello stesso gruppo (l'audio di un video, il video di un audio)."""
        if not clip.link:
            return []
        return [(t, c) for t in self.project.tracks for c in t.clips
                if c.link == clip.link and c is not clip]

    def _allinea(self, clip: Clip) -> None:
        """Porta le collegate sugli stessi tempi della clip appena modificata."""
        for t, c in self.collegate(clip):
            c.start, c.in_, c.duration = clip.start, clip.in_, clip.duration
            c.speed, c.reverse = clip.speed, clip.reverse
            t.clips.sort(key=lambda x: x.start)

    def unlink_clip(self, clip_id: str) -> list[str]:
        """Scollega video e audio: da qui si muovono da soli (J/L cut, musica sotto)."""
        _, clip = self.clip_or_die(clip_id)
        gruppo = [clip, *(c for _, c in self.collegate(clip))]
        if len(gruppo) < 2:
            return []
        self._touch()
        for c in gruppo:
            c.link = ""
        self._done()
        return [c.id for c in gruppo]

    def remove_clip(self, clip_id: str, ripple: bool = False) -> None:
        track, clip = self.clip_for_edit(clip_id)
        self._touch()
        for t, c in [(track, clip), *self.collegate(clip)]:
            gap = c.duration
            t.clips.remove(c)
            if ripple:
                for altra in t.clips:
                    if altra.start >= c.start:
                        altra.start = max(0.0, altra.start - gap)
        self._done()

    def move_clip(self, clip_id: str, start: float | None = None, track_id: str | None = None) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        dst = None
        if track_id and track_id != track.id:
            # controlli prima di toccare qualcosa: un rifiuto non deve lasciare
            # la clip spostata nel tempo ma sulla traccia di prima
            dst = self.track_for_edit(track_id)
            if dst.kind != track.kind:
                raise EditError(f"cannot move a {track.kind} clip onto a {dst.kind} track")
        self._touch()
        if start is not None:
            clip.start = max(0.0, float(start))
        if dst is not None:
            track.clips.remove(clip)
            dst.clips.append(clip)
            dst.clips.sort(key=lambda x: x.start)
        track.clips.sort(key=lambda x: x.start)
        self._allinea(clip)
        self._done()
        return clip

    def move_layer(self, clip_id: str, direction: str = "up") -> Clip:
        """Porta una clip davanti o dietro: la sposta su un'altra traccia video.

        ``direction``: up (un livello avanti), down (uno indietro), top (davanti
        a tutto), bottom (dietro a tutto). Chi copre chi lo decide l'ordine
        delle tracce, quindi "porta avanti" vuol dire cambiare traccia.

        La traccia di arrivo deve essere libera in quel tratto di tempo: due
        clip sovrapposte sulla stessa traccia si nascondono a vicenda in
        timeline e l'ordine fra loro non e' quello che ci si aspetta. Se non lo
        e', si inserisce una traccia nuova proprio li'. Un solo passo di undo.
        """
        if direction not in ("up", "down", "top", "bottom"):
            raise EditError("direction must be up, down, top or bottom")
        track, clip = self.clip_for_edit(clip_id)
        if track.kind != "video":
            raise EditError("audio clips have no front and back")
        video = self.project.video_tracks()
        i = video.index(track)
        if direction in ("down", "bottom") and i == 0:
            raise EditError("the clip is already on the bottom track")

        def libera(t: Track) -> bool:
            return not t.locked and all(
                c.end <= clip.start + 1e-6 or c.start >= clip.end - 1e-6
                for c in t.clips if c is not clip)

        dst: Track | None = None
        if direction == "up" and i + 1 < len(video) and libera(video[i + 1]):
            dst = video[i + 1]
        elif direction == "down" and libera(video[i - 1]):
            dst = video[i - 1]
        elif direction == "top" and i < len(video) - 1 and libera(video[-1]):
            dst = video[-1]
        elif direction == "bottom" and libera(video[0]):
            dst = video[0]

        with self.batch():
            if dst is None:
                # posizione nella lista completa (video e audio mescolati)
                vicino = {"up": track, "down": track,
                          "top": video[-1], "bottom": video[0]}[direction]
                dopo = direction in ("up", "top")
                pos = self.project.tracks.index(vicino) + (1 if dopo else 0)
                dst = self.add_track("video", index=pos)
            return self.move_clip(clip_id, track_id=dst.id)

    def trim_clip(self, clip_id: str, in_: float | None = None, duration: float | None = None,
                  out: float | None = None) -> Clip:
        """Cambia il punto di attacco e/o la durata. ``out`` = fine nella sorgente."""
        track, clip = self.clip_for_edit(clip_id)
        media = self.project.media_by_id(clip.media) if clip.media else None
        # calcolo su copie locali: una durata impossibile si rifiuta senza aver
        # gia' spostato l'attacco
        new_in, new_dur = clip.in_, clip.duration
        if in_ is not None:
            new_in = max(0.0, float(in_))
            if duration is None and out is None:
                delta = new_in - clip.in_
                new_dur = max(1.0 / 60, clip.duration - delta / max(abs(clip.speed), 1e-6))
        if out is not None:
            src_len = max(0.0, float(out) - new_in)
            new_dur = src_len / max(abs(clip.speed), 1e-6)
        if duration is not None:
            new_dur = float(duration)
        if new_dur <= 0:
            raise EditError("the resulting duration is <= 0")
        if media and media.duration > 0 and clip.type == "media":
            if new_in >= media.duration:
                raise EditError(f"in point {new_in}s past the media duration ({media.duration}s)")
            max_dur = (media.duration - new_in) / max(abs(clip.speed), 1e-6)
            if new_dur > max_dur + 1e-3:
                new_dur = max_dur
        self._touch()
        clip.in_, clip.duration = new_in, new_dur
        self._allinea(clip)
        self._done()
        return clip

    # ---- trim da montatore: ripple, roll, slip, slide ---------------------
    #
    # Tutti passano da ``_bordo``, che sposta un bordo di una clip di ``d``
    # secondi di timeline (positivo = verso destra) e sa cosa vuol dire per la
    # sorgente: velocita', reverse e lunghezza del media. Le collegate seguono
    # con ``_allinea``. Ogni operazione e' un solo passo di undo.

    MIN_DUR = 1.0 / 60

    @contextmanager
    def _tutto_o_niente(self):
        """Una modifica a piu' passi che, se un passo e' impossibile, non lascia niente a meta'."""
        prima, redo = self.project.to_dict(), list(self._redo)
        self._touch()
        try:
            yield
        except Exception:
            self.project = Project.from_obj(prima)
            if not self._batch:
                self._undo.pop()
            self._redo = redo
            raise
        self._done()

    def _bordo(self, clip: Clip, lato: str, d: float, fermo: bool = False) -> None:
        """Sposta il bordo ``lato`` ("start"/"end") di ``d`` s, rifiutando l'impossibile.

        ``fermo``: la clip resta al suo posto e cambia solo cosa contiene (il
        ripple della testa), quindi l'inizio della timeline non e' un limite.
        """
        k = abs(clip.speed or 1.0)
        start, dur, inp = clip.start, clip.duration, clip.in_
        if lato == "end":
            dur += d
            if clip.reverse:          # all'indietro la fine in timeline e' l'inizio in sorgente
                inp -= d * k
        else:
            start += d
            dur -= d
            if not clip.reverse:
                inp += d * k
        if dur < self.MIN_DUR - 1e-9:
            raise EditError(f"clip {clip.id} would be left with no duration")
        if start < -1e-9 and not fermo:
            raise EditError("you cannot go before the start of the timeline")
        media = self.project.media_by_id(clip.media) if clip.type == "media" and clip.media else None
        if media is not None:
            if inp < -1e-6:
                raise EditError(f"clip {clip.id} has no more material before its in point")
            if media.duration > 0 and media.kind != "image" and inp + dur * k > media.duration + 1e-3:
                raise EditError(f"clip {clip.id} has no more material after its end")
        clip.start, clip.duration, clip.in_ = max(0.0, start), dur, max(0.0, inp)

    def _dopo(self, track: Track, clip: Clip) -> Clip | None:
        """La clip che segue subito: attaccata, o sovrapposta per una transizione."""
        cand = [c for c in track.clips if c is not clip and c.start > clip.start + 1e-6
                and c.start <= clip.end + 1e-3]
        return min(cand, key=lambda c: c.start) if cand else None

    def _prima(self, track: Track, clip: Clip) -> Clip | None:
        cand = [c for c in track.clips if c is not clip and c.start < clip.start - 1e-6
                and c.end >= clip.start - 1e-3]
        return max(cand, key=lambda c: c.start) if cand else None

    def _libero(self, track: Track, a: float, b: float, escluse: set[int]) -> bool:
        return all(c.end <= a + 1e-3 or c.start >= b - 1e-3
                   for c in track.clips if id(c) not in escluse)

    def ripple_trim(self, clip_id: str, edge: str, delta: float) -> Clip:
        """Accorcia o allunga un bordo e sposta di conseguenza tutto quello che segue.

        ``edge="end"``, ``delta`` > 0 allunga la coda e spinge avanti le clip
        dopo; ``edge="start"``, ``delta`` > 0 toglie dalla testa e la clip resta
        al suo posto, con tutto il seguito che arretra. Nessun buco, nessuna
        sovrapposizione: e' il trim del montatore. Vale sulla traccia della
        clip e su quelle delle sue collegate.
        """
        if edge not in ("start", "end"):
            raise EditError("edge must be start or end")
        track, clip = self.clip_for_edit(clip_id)
        d = float(delta)
        if abs(d) < 1e-9:
            return clip
        gruppo = [(track, clip), *self.collegate(clip)]
        for t, _ in gruppo:
            if t.locked:
                raise EditError(f"track {t.id} is locked")
        with self._tutto_o_niente():
            for t, c in gruppo:
                fine = c.end
                if edge == "end":
                    self._bordo(c, "end", d)
                    spinta = d
                else:
                    tenuto = c.start
                    self._bordo(c, "start", d, fermo=True)
                    c.start = tenuto      # il contenuto si accorcia, la clip resta li'
                    spinta = -d
                for altra in t.clips:
                    if altra is not c and altra.start >= fine - 1e-3:
                        altra.start = max(0.0, altra.start + spinta)
                t.clips.sort(key=lambda x: x.start)
        return clip

    def roll_edit(self, clip_id: str, delta: float) -> tuple[Clip, Clip]:
        """Sposta il taglio fra la clip e quella che la segue, senza cambiare la durata totale.

        La prima si allunga di quanto la seconda si accorcia (o il contrario):
        niente si muove a valle. Serve a far cadere lo stacco un po' prima o un
        po' dopo, su un battito o su una parola.
        """
        track, clip = self.clip_for_edit(clip_id)
        dopo = self._dopo(track, clip)
        if dopo is None:
            raise EditError(f"clip {clip_id} has no clip butted after it: no cut to move")
        d = float(delta)
        with self._tutto_o_niente():
            self._bordo(clip, "end", d)
            self._bordo(dopo, "start", d)
            track.clips.sort(key=lambda x: x.start)
            self._allinea(clip)
            self._allinea(dopo)
        return clip, dopo

    def slip_clip(self, clip_id: str, delta: float) -> Clip:
        """Scorre il contenuto dentro la clip: stessa posizione e durata, altro tratto della sorgente.

        ``delta`` in secondi di sorgente: positivo mostra un tratto piu' avanti.
        """
        track, clip = self.clip_for_edit(clip_id)
        if clip.type != "media":
            raise EditError("slip works on media clips: text and graphics have no source")
        media = self.project.media_by_id(clip.media)
        if media is not None and media.kind == "image":
            raise EditError("a still image has no stretch to slip")
        nuovo = clip.in_ + float(delta)
        k = abs(clip.speed or 1.0)
        if nuovo < -1e-6:
            raise EditError("the source has no material before that")
        if media is not None and media.duration > 0 and nuovo + clip.duration * k > media.duration + 1e-3:
            raise EditError("the source has no material after that")
        self._touch()
        clip.in_ = max(0.0, nuovo)
        self._allinea(clip)
        self._done()
        return clip

    def slide_clip(self, clip_id: str, delta: float) -> Clip:
        """Fa scivolare la clip fra le vicine: lei resta uguale, le vicine cedono o prendono.

        La clip prima si allunga (o accorcia) fino al nuovo attacco, quella dopo
        parte piu' tardi (o prima): la durata totale non cambia. Senza vicine
        da un lato, da quel lato serve spazio libero.
        """
        track, clip = self.clip_for_edit(clip_id)
        d = float(delta)
        prima, dopo = self._prima(track, clip), self._dopo(track, clip)
        if clip.start + d < -1e-9:
            raise EditError("you cannot go before the start of the timeline")
        with self._tutto_o_niente():
            if prima is not None:
                self._bordo(prima, "end", d)
            if dopo is not None:
                self._bordo(dopo, "start", d)
            clip.start += d
            fuori = {id(clip), *(id(c) for c in (prima, dopo) if c is not None)}
            if not self._libero(track, clip.start, clip.end, fuori):
                raise EditError("the clip would land on top of another one: leave it room or move the neighbours")
            track.clips.sort(key=lambda x: x.start)
            for c in (clip, prima, dopo):
                if c is not None:
                    self._allinea(c)
        return clip

    def split_clip(self, clip_id: str, at: float) -> tuple[Clip, Clip]:
        """Taglia in due al tempo di timeline ``at``. Le clip collegate si tagliano insieme."""
        track, clip = self.clip_for_edit(clip_id)
        if not (clip.start + 1e-4 < at < clip.end - 1e-4):
            raise EditError(
                f"the split point {at}s is outside the clip ({clip.start:.3f}-{clip.end:.3f}s)"
            )
        self._touch()
        altre = self.collegate(clip)
        second = self._dividi(track, clip, at)
        if altre:
            # le due meta' restano collegate fra loro, ognuna col suo gruppo
            second.link = new_id("l")
            for t, c in altre:
                if c.start + 1e-4 < at < c.end - 1e-4:
                    self._dividi(t, c, at).link = second.link
        self._done()
        return clip, second

    @staticmethod
    def _dividi(track: Track, clip: Clip, at: float) -> Clip:
        head = at - clip.start
        tail = clip.duration - head
        k = abs(clip.speed or 1.0)
        second = copy.deepcopy(clip)
        second.id = new_id("c")
        second.start = at
        second.duration = tail
        if clip.reverse:
            # all'indietro la testa in timeline e' la *fine* del tratto sorgente:
            # la seconda meta' parte dall'attacco, la prima si sposta avanti
            second.in_ = clip.in_
            clip.in_ = clip.in_ + tail * k
        else:
            second.in_ = clip.in_ + head * k
        # dissolvenze e transizione d'ingresso restano alla prima meta', quelle
        # d'uscita passano alla seconda: sul punto di taglio non deve succedere
        # niente, se no il taglio "a meta'" si vede come un lampo o una tendina
        second.fade_in = 0.0
        second.audio.fade_in = 0.0
        second.fade_out = min(clip.fade_out, tail)
        second.audio.fade_out = min(clip.audio.fade_out, tail)

        clip.duration = head
        clip.fade_in = min(clip.fade_in, head)
        clip.audio.fade_in = min(clip.audio.fade_in, head)
        clip.fade_out = 0.0
        clip.audio.fade_out = 0.0
        clip.transition_out = Transition()

        track.clips.append(second)
        track.clips.sort(key=lambda x: x.start)
        return second

    def set_speed(self, clip_id: str, speed: float, keep_duration: bool = False) -> Clip:
        """Cambia velocita'. Di default la durata in timeline si accorcia/allunga."""
        track, clip = self.clip_for_edit(clip_id)
        if clip.type == "html":
            raise EditError("an html clip has no speed: its animation sets the pace")
        if speed <= 0:
            raise EditError("the speed must be > 0 (use reverse=true to play backwards)")
        if speed > 100 or speed < 0.01:
            raise EditError("speed out of range: allowed 0.01x - 100x")
        self._touch()
        src = clip.source_duration()
        clip.speed = float(speed)
        if not keep_duration:
            clip.duration = src / speed
        # a durata tenuta, accelerando si consuma piu' sorgente: oltre la fine
        # del file il render mostrerebbe nero
        media = self.project.media_by_id(clip.media) if clip.media else None
        if media and media.duration > 0 and clip.type == "media":
            max_dur = (media.duration - clip.in_) / clip.speed
            if clip.duration > max_dur + 1e-3:
                clip.duration = max(1.0 / 60, max_dur)
        self._allinea(clip)
        self._done()
        return clip

    def set_reverse(self, clip_id: str, reverse: bool = True) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        self._touch()
        clip.reverse = bool(reverse)
        self._allinea(clip)
        self._done()
        return clip

    def set_transform(self, clip_id: str, **values: Any) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        allowed = set(vars(Transform()))
        bad = set(values) - allowed
        if bad:
            raise EditError(f"unknown transform fields {sorted(bad)}; allowed: {sorted(allowed)}")
        clean = self._animabili(values)
        self._touch()
        for k, v in clean.items():
            setattr(clip.transform, k, v)
        self._done()
        return clip

    def set_audio(self, clip_id: str, **values: Any) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        allowed = set(vars(ClipAudio()))
        bad = set(values) - allowed
        if bad:
            raise EditError(f"unknown audio fields {sorted(bad)}; allowed: {sorted(allowed)}")
        clean = self._animabili(values)
        self._touch()
        for k, v in clean.items():
            setattr(clip.audio, k, v)
        self._done()
        return clip

    @staticmethod
    def _animabili(values: dict) -> dict:
        """Valida e normalizza tutti i valori *prima* di scriverne uno.

        Validando mentre si scrive, un keyframe malformato nel terzo campo
        lasciava i primi due gia' cambiati.
        """
        out = {}
        for k, v in values.items():
            if v is None:
                continue
            try:
                kf.validate(v)
            except ValueError as exc:
                raise EditError(f"{k}: {exc}") from exc
            out[k] = kf.coerce(v)
        return out

    def set_fades(self, clip_id: str, fade_in: float | None = None, fade_out: float | None = None,
                  audio: bool = True) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        self._touch()
        if fade_in is not None:
            clip.fade_in = max(0.0, min(float(fade_in), clip.duration))
            if audio:
                clip.audio.fade_in = clip.fade_in
        if fade_out is not None:
            clip.fade_out = max(0.0, min(float(fade_out), clip.duration))
            if audio:
                clip.audio.fade_out = clip.fade_out
        self._done()
        return clip

    def set_clip(self, clip_id: str, **values: Any) -> Clip:
        """Campi semplici: enabled, fit, blend, name, color, start, duration, in_."""
        track, clip = self.clip_for_edit(clip_id)
        allowed = {"enabled", "fit", "blend", "name", "color", "start", "duration", "in_"}
        bad = set(values) - allowed
        if bad:
            raise EditError(f"unknown fields {sorted(bad)}; allowed: {sorted(allowed)}")
        if values.get("fit") is not None and values["fit"] not in ("contain", "cover", "stretch", "none"):
            raise EditError("fit must be contain | cover | stretch | none")
        if values.get("blend") is not None and values["blend"] not in BLEND_MODES:
            raise EditError(f"blend must be one of {' | '.join(BLEND_MODES)}")
        for k in ("start", "duration", "in_"):
            if values.get(k) is not None and float(values[k]) < 0:
                raise EditError(f"{k} cannot be negative")
        if values.get("duration") is not None and float(values["duration"]) <= 0:
            raise EditError("the duration must be > 0")
        self._touch()
        for k, v in values.items():
            if v is not None:
                setattr(clip, k, float(v) if k in ("start", "duration", "in_") else v)
        # Il pannello proprieta' scrive qui durata e attacco: oltre la fine del
        # file il render mostrerebbe nero, quindi si tiene entro la sorgente
        # come fa trim_clip.
        media = self.project.media_by_id(clip.media) if clip.media else None
        if media and media.duration > 0 and clip.type == "media":
            if clip.in_ >= media.duration:
                clip.in_ = max(0.0, media.duration - 1.0 / 60)
            max_dur = (media.duration - clip.in_) / max(abs(clip.speed), 1e-6)
            if clip.duration > max_dur + 1e-3:
                clip.duration = max(1.0 / 60, max_dur)
        track.clips.sort(key=lambda x: x.start)
        self._allinea(clip)
        self._done()
        return clip

    def set_text(self, clip_id: str, **values: Any) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        if clip.type != "text" or clip.text is None:
            raise EditError(f"clip {clip_id} is not a text clip")
        allowed = set(vars(TextStyle()))
        bad = set(values) - allowed
        if bad:
            raise EditError(f"unknown text fields {sorted(bad)}; allowed: {sorted(allowed)}")
        self._touch()
        for k, v in values.items():
            if v is not None:
                setattr(clip.text, k, v)
        self._done()
        return clip

    # ---- effetti -------------------------------------------------------
    def add_effect(self, clip_id: str | None, effect: str, params: dict | None = None) -> Effect:
        """clip_id=None applica l'effetto al master."""
        clean = fx.validate_effect(effect, params or {})
        if clip_id is not None:
            self._effect_fits(clip_id, [effect])
        target = self.project.master.effects if clip_id is None else self.clip_for_edit(clip_id)[1].effects
        self._touch()
        e = Effect(type=effect, params=clean)
        target.append(e)
        self._done()
        return e

    def add_effects(self, clip_id: str | None, items: list[dict]) -> list[Effect]:
        """Applica piu' effetti come una sola modifica.

        Un preset e' una catena di effetti ma per chi monta e' un gesto solo:
        aggiungendoli con ``add_effect`` in fila servirebbero tanti Ctrl+Z
        quanti sono gli effetti. Qui la validazione avviene tutta prima, quindi
        o entra la catena intera o non cambia niente.
        """
        target = self._effect_list(clip_id)
        made = [Effect(type=it["type"], params=fx.validate_effect(it["type"], it.get("params") or {}))
                for it in items]
        if clip_id is not None:
            self._effect_fits(clip_id, [e.type for e in made])
        if not made:
            return []
        self._touch()
        target.extend(made)
        self._done()
        return made

    def clip_produces(self, clip_id: str) -> set[str]:
        """Cosa esce davvero da una clip nel render: ``video``, ``audio`` o tutti e due.

        Stessa regola del grafo: una traccia audio non viene mai disegnata, e su
        traccia video il suono c'e' solo se la clip e' un media che ne ha.
        """
        track, clip = self.clip_or_die(clip_id)
        if track.kind == "audio":
            return {"audio"}
        media = self.project.media_by_id(clip.media) if clip.type == "media" and clip.media else None
        return {"video", "audio"} if media is not None and media.has_audio else {"video"}

    def _effect_fits(self, clip_id: str, effects: list[str]) -> None:
        """Un effetto che la clip non puo' usare non entra: non cambierebbe niente."""
        ha = self.clip_produces(clip_id)
        for name in effects:
            kind = fx._spec(name).kind
            if kind not in ha:
                cosa = "sound" if kind == "audio" else "picture"
                raise EditError(f"{name!r} is a {kind} effect and clip {clip_id} has no {cosa}: "
                                f"it would change nothing")

    def _effect_list(self, clip_id: str | None) -> list[Effect]:
        return self.project.master.effects if clip_id is None else self.clip_for_edit(clip_id)[1].effects

    def update_effect(self, clip_id: str | None, index: int, params: dict | None = None,
                      enabled: bool | None = None) -> Effect:
        lst = self._effect_list(clip_id)
        if not (0 <= index < len(lst)):
            raise EditError(f"effect index {index} out of range (0..{len(lst) - 1})")
        e = lst[index]
        self._touch()
        if params:
            merged = dict(e.params)
            merged.update(params)
            e.params = fx.validate_effect(e.type, merged)
        if enabled is not None:
            e.enabled = bool(enabled)
        self._done()
        return e

    def remove_effect(self, clip_id: str | None, index: int) -> None:
        lst = self._effect_list(clip_id)
        if not (0 <= index < len(lst)):
            raise EditError(f"effect index {index} out of range (0..{len(lst) - 1})")
        self._touch()
        lst.pop(index)
        self._done()

    def move_effect(self, clip_id: str | None, index: int, to: int) -> list[Effect]:
        """Sposta un effetto nella catena: l'ordine cambia il risultato.

        Non e' un dettaglio estetico. Denoise prima di sharpen pulisce e poi
        incide; sharpen prima di denoise incide anche il rumore e poi lo
        ammorbidisce — stessa coppia, immagini diverse. Senza questo metodo
        l'unico modo di correggere l'ordine era togliere gli effetti e rimetterli
        tutti in fila.
        """
        lst = self._effect_list(clip_id)
        n = len(lst)
        if not (0 <= index < n):
            raise EditError(f"effect index {index} out of range (0..{n - 1})")
        to = max(0, min(int(to), n - 1))
        if to == index:
            return lst
        self._touch()
        lst.insert(to, lst.pop(index))
        self._done()
        return lst

    def set_matte(self, clip_id: str, file: str, t0: float = 0.0, feather: float = 2.0,
                  invert: bool = False) -> Effect:
        """Mette lo scontorno IA in testa alla catena della clip, o lo sostituisce.

        In testa perche' la maschera e' allineata all'immagine *prima* degli
        effetti: dopo un warp o un tilt3d il soggetto non sarebbe piu' dove la
        maschera lo aspetta.
        """
        track, clip = self.clip_for_edit(clip_id)
        if clip.type != "media":
            raise EditError("the cut-out only applies to media clips")
        if not Path(file).exists():
            raise EditError(f"matte does not exist: {file}")
        params = fx.validate_effect("matte", {"file": str(file), "t0": float(t0),
                                              "feather": float(feather), "invert": bool(invert)})
        self._touch()
        clip.effects = [e for e in clip.effects if e.type != "matte"]
        e = Effect(type="matte", params=params)
        clip.effects.insert(0, e)
        self._done()
        return e

    HIGHLIGHT_MODES = ("glow", "tint", "spotlight")

    def highlight_subject(self, clip_id: str, file: str, t0: float = 0.0,
                          mode: str = "glow", color: str = "#ffcc00",
                          amount: float = 0.7, feather: float = 2.0) -> dict:
        """Evidenzia il soggetto con la sua sagoma, non con un rettangolo.

        La clip viene duplicata su una traccia appena sopra; il doppione ha lo
        scontorno (``file``, da ``vision.segment_matte``) e quindi contiene solo
        il soggetto, allineato fotogramma per fotogramma all'originale perche'
        ha lo stesso attacco, velocita' e inquadratura. Poi:

        - ``glow``: il doppione colorato e sfocato si somma in screen, alone
          luminoso attorno alla sagoma;
        - ``tint``: il doppione colorato copre il soggetto, che cambia tinta;
        - ``spotlight``: l'originale si scurisce e desatura, il doppione resta
          com'era, quindi il soggetto e' l'unica cosa in luce.

        Il doppione e' muto: l'audio resta all'originale.
        """
        if mode not in self.HIGHLIGHT_MODES:
            raise EditError(f"mode must be {' | '.join(self.HIGHLIGHT_MODES)}")
        fx.tint_matrix(color, amount)   # colore sbagliato -> errore subito, non al render
        track, clip = self.clip_for_edit(clip_id)
        if clip.type != "media":
            raise EditError("highlighting applies to a clip with video")
        a = max(0.0, min(1.0, float(amount)))
        with self.batch():
            sopra = self.add_track("video", name="evidenzia",
                                   index=self.project.tracks.index(track) + 1)
            dup = copy.deepcopy(clip)
            dup.id = new_id("c")
            dup.name = f"{clip.name or clip.id} evidenziato"
            dup.audio.mute = True
            dup.transition_out = Transition()
            dup.effects = [e for e in dup.effects if e.type != "matte"]
            sopra.clips.append(dup)
            self.set_matte(dup.id, file, t0, feather)
            if mode == "glow":
                self.add_effects(dup.id, [
                    {"type": "tint", "params": {"color": color, "amount": 1.0}},
                    {"type": "blur", "params": {"sigma": 18, "steps": 2}},
                ])
                self.set_clip(dup.id, blend="screen")
                self.set_transform(dup.id, opacity=a)
            elif mode == "tint":
                self.add_effect(dup.id, "tint", {"color": color, "amount": a})
            else:
                self.add_effect(clip.id, "color", {"brightness": round(-0.35 * a, 3),
                                                   "saturation": round(1 - 0.8 * a, 3)})
        return {"clip": clip.id, "doppione": dup.id, "traccia": sopra.id, "mode": mode}

    def pin_to_subject(self, clip_id: str, target_id: str, track: list[dict],
                       src_w: int, src_h: int, offset_x: float = 0.0,
                       offset_y: float = 0.0) -> Clip:
        """Aggancia una clip (titolo, grafica, html) a un soggetto che si muove.

        ``track`` e' la traccia del soggetto nella sorgente di ``target_id``
        (``vision.follow``: tempi della sorgente, centri in pixel della
        sorgente). Ogni punto viene portato sul canvas passando per tutto quello
        che la clip bersaglio fa alla sua sorgente - attacco, velocita',
        adattamento al canvas, scala e posizione statiche - e diventa un
        keyframe di x/y della clip agganciata, nel suo tempo locale.
        """
        _, clip = self.clip_for_edit(clip_id)
        _, tgt = self.clip_or_die(target_id)
        st = self.project.settings
        W, H = float(st.width), float(st.height)
        if tgt.fit == "cover":
            k = max(W / src_w, H / src_h)
        elif tgt.fit == "stretch":
            k = None
        elif tgt.fit == "none":
            k = 1.0
        else:
            k = min(W / src_w, H / src_h)
        sc = float(kf.sample(tgt.transform.scale, 0, 1.0))
        tx = float(kf.sample(tgt.transform.x, 0, 0.0))
        ty = float(kf.sample(tgt.transform.y, 0, 0.0))
        speed = tgt.speed or 1.0
        kx, ky = [], []
        for p in track:
            if p.get("cx") is None:
                continue
            # tempo della sorgente -> tempo in timeline -> tempo locale della clip agganciata
            if tgt.reverse:
                t_tl = tgt.start + (tgt.in_ + tgt.source_duration() - p["t"]) / abs(speed)
            else:
                t_tl = tgt.start + (p["t"] - tgt.in_) / abs(speed)
            t_loc = t_tl - clip.start
            if t_loc < -1e-6 or t_loc > clip.duration + 1e-6:
                continue
            if k is None:
                dx, dy = (p["cx"] - src_w / 2) * W / src_w, (p["cy"] - src_h / 2) * H / src_h
            else:
                dx, dy = (p["cx"] - src_w / 2) * k, (p["cy"] - src_h / 2) * k
            kx.append({"t": round(t_loc, 3), "v": round(dx * sc + tx + offset_x, 1)})
            ky.append({"t": round(t_loc, 3), "v": round(dy * sc + ty + offset_y, 1)})
        if not kx:
            raise EditError("the subject is never visible while the pinned clip is on screen")
        kx.sort(key=lambda q: q["t"])
        ky.sort(key=lambda q: q["t"])
        return self.set_transform(clip_id, x={"kf": kx}, y={"kf": ky})

    # ---- montaggio -----------------------------------------------------
    def append_sequence(self, media_ids: list[str], track_id: str | None = None,
                        crossfade: float = 0.0) -> list[Clip]:
        """Mette in fila piu' media interi, con dissolvenza incrociata opzionale.

        Prende i media *per intero*: per una lista di tagli con punto d'attacco
        e durata serve :meth:`add_clips`.
        """
        with self.batch():
            clips = [self.add_clip(mid, track_id) for mid in media_ids]
            if crossfade > 0:
                for a, b in zip(clips, clips[1:]):
                    self.crossfade(a.id, b.id, crossfade)
        return clips

    def add_clips(self, items: list[dict], track_id: str | None = None,
                  gap: float = 0.0) -> list[Clip]:
        """Mette in timeline una lista di tagli in una sola modifica.

        Ogni voce e' ``{"media": id, "in": s, "duration": s, "start": s}``:
        ``start`` assente accoda in fila (rispettando ``gap``), ``duration``
        assente prende il resto del media. Accetta anche ``track`` per voce, per
        costruire piu' tracce in un colpo.

        Serve perche' un montaggio serrato e' fatto di decine o centinaia di
        tagli: metterli uno alla volta e' lento, riempie la cronologia di undo e
        soprattutto lascia mezza timeline costruita se qualcosa va storto a
        meta'. Qui o entrano tutti o non entra niente.
        """
        if not items:
            return []
        for i, it in enumerate(items):
            if not it.get("media"):
                raise EditError(f"item {i}: 'media' is missing")

        out: list[Clip] = []
        with self.batch():
            for dove in {it.get("track", track_id) for it in items} - {None}:
                self._crea_traccia(dove)
            for it in items:
                dove = it.get("track", track_id)
                start = it.get("start")
                if start is None:
                    tr = self.track_for_edit(dove or self._default_track(
                        "audio" if self.media_or_die(it["media"]).kind == "audio" else "video"))
                    start = self.track_end(tr) + (gap if tr.clips else 0.0)
                out.append(self.add_clip(
                    it["media"], dove, float(start),
                    float(it.get("in", it.get("in_", 0.0)) or 0.0),
                    it.get("duration"), it.get("name")))
        return out

    def add_voiceover(self, items: list[dict], track_id: str | None = None) -> list[Clip]:
        """Mette in timeline battute di voce gia' generate (``tts.genera``).

        Ogni voce e' ``{"path": file, "start": s, "text": battuta}``; ``start``
        assente mette la battuta dopo la precedente. Senza ``track_id`` la voce
        va sulla traccia audio "VO", creata se manca: non si mescola con la
        musica o il parlato gia' in A1. Una modifica sola, tutto o niente.
        """
        if not items:
            return []
        for i, it in enumerate(items):
            if not it.get("path"):
                raise EditError(f"line {i}: 'path' is missing")
        out: list[Clip] = []
        with self.batch():
            if track_id is None:
                vo = next((t for t in self.project.tracks
                           if t.kind == "audio" and t.name == "VO"), None)
                track_id = (vo or self.add_track("audio", "VO")).id
            track = self.track_for_edit(track_id)
            if track.kind != "audio":
                raise EditError(f"track {track_id} is not an audio track")
            self.import_media([it["path"] for it in items], folder="voice")
            for it in items:
                # per percorso: la stessa battuta due volte e' un media solo
                m = self.project.media_by_path(str(Path(it["path"]).resolve()))
                start = it.get("start")
                if start is None:
                    start = self.track_end(track)
                testo = " ".join(str(it.get("text") or "").split())
                nome = (testo[:40] + "…") if len(testo) > 40 else (testo or m.name)
                out.append(self.add_clip(m.id, track_id, float(start), 0.0, None, nome))
        return out

    def crossfade(self, clip_a: str, clip_b: str, duration: float = 1.0,
                  type: str = "dissolve") -> dict:
        """Transizione tra due clip consecutive: sovrappone B sotto A e la scopre.

        ``type`` sceglie il modo in cui A lascia il posto a B: dissolvenza,
        tendina, scorrimento o iris (vedi model.TRANSITIONS).
        """
        if type not in TRANSITIONS:
            raise EditError(f"unknown transition {type!r}; available: {', '.join(TRANSITIONS)}")
        ta, a = self.clip_for_edit(clip_a)
        tb, b = self.clip_for_edit(clip_b)
        if ta.id != tb.id:
            raise EditError("a transition needs two clips on the same track")
        if a.id == b.id or b.start <= a.start:
            raise EditError("the transition goes from the earlier clip (clip_a) to the later one (clip_b)")
        d = min(float(duration), a.duration * 0.9, b.duration * 0.9)
        if d <= 0:
            raise EditError("invalid transition duration")
        self._touch()
        # B (e tutto cio' che segue) risale fino a sovrapporsi ad A di d secondi
        delta = b.start - (a.end - d)
        spostate = [c for c in tb.clips if c.start >= b.start - 1e-6]
        for c in spostate:
            c.start = max(0.0, c.start - delta)
        for c in spostate:
            self._allinea(c)
        self._apply_transition(a, type, d)
        # l'audio si incrocia sempre in dissolvenza, qualunque sia l'effetto video
        a.audio.fade_out = d
        b.audio.fade_in = d
        self._done()
        return {"duration": d, "type": type, "a": a.id, "b": b.id, "shift": round(-delta, 3)}

    @staticmethod
    def _apply_transition(clip: Clip, type: str, duration: float) -> None:
        if type == "dissolve":
            clip.fade_out = duration
            clip.transition_out = Transition("dissolve", 0.0)
        else:
            clip.fade_out = 0.0
            clip.transition_out = Transition(type, duration)

    def set_transition(self, clip_id: str, type: str = "dissolve", duration: float = 1.0) -> dict:
        """Imposta la transizione in uscita senza spostare le clip.

        Utile quando le clip si sovrappongono gia' o quando si vuole cambiare
        solo il tipo di una transizione esistente.
        """
        if type not in TRANSITIONS:
            raise EditError(f"unknown transition {type!r}; available: {', '.join(TRANSITIONS)}")
        _, clip = self.clip_for_edit(clip_id)
        d = max(0.0, min(float(duration), clip.duration))
        self._touch()
        self._apply_transition(clip, type, d)
        clip.audio.fade_out = d
        self._done()
        return {"clip": clip.id, "type": type, "duration": d}

    def close_gaps(self, track_id: str) -> int:
        """Compatta le clip eliminando i buchi. Ritorna il numero di clip spostate."""
        track = self.track_for_edit(track_id)
        ordered = sorted(track.clips, key=lambda x: x.start)
        # Si tolgono solo i vuoti: due clip sovrapposte da una transizione
        # restano sovrapposte, se no compattare cancellerebbe le dissolvenze.
        shift, reach, starts = 0.0, 0.0, []
        for c in ordered:
            if c.start > reach:
                shift += c.start - reach
            starts.append(c.start - shift)
            reach = max(reach, c.end)
        moved = sum(1 for c, s in zip(ordered, starts) if abs(c.start - s) > 1e-4)
        if not moved:
            return 0        # niente da compattare: nessuna voce di undo vuota
        self._touch()
        for c, s in zip(ordered, starts):
            c.start = s
        for c in ordered:
            self._allinea(c)
        self._done()
        return moved

    def set_loudnorm(self, enabled: bool = True, target_lufs: float = -14.0,
                     true_peak: float = -1.0, lra: float = 11.0, measured: dict | None = None) -> dict:
        self._touch()
        ln = self.project.master.loudnorm
        ln.enabled = bool(enabled)
        ln.i = float(target_lufs)
        ln.tp = float(true_peak)
        ln.lra = float(lra)
        if measured is not None:
            ln.measured = measured
        self._done()
        return {"enabled": ln.enabled, "target_lufs": ln.i, "true_peak": ln.tp,
                "lra": ln.lra, "measured": bool(ln.measured)}

    def set_master_volume(self, volume: Any) -> Any:
        """Volume del master (1 = invariato), anche a keyframe: e' il fader generale."""
        kf.validate(volume)
        volume = kf.coerce(volume)
        if not kf.is_kf(volume) and not 0 <= float(volume) <= 4:
            raise EditError("master volume ranges from 0 to 4 (1 = unchanged)")
        self._touch()
        self.project.master.volume = volume
        self._done()
        return volume

    def set_settings(self, **values: Any) -> Settings:
        allowed = set(vars(Settings()))
        bad = set(values) - allowed
        if bad:
            raise EditError(f"unknown settings {sorted(bad)}; allowed: {sorted(allowed)}")
        if values.get("audio_layout") is not None and values["audio_layout"] not in AUDIO_LAYOUTS:
            raise EditError(f"unknown audio layout {values['audio_layout']!r}; allowed: "
                            f"{', '.join(AUDIO_LAYOUTS)}")
        self._touch()
        for k, v in values.items():
            if v is not None:
                setattr(self.project.settings, k, v)
        self._done()
        return self.project.settings

    def set_format(self, format: str, size: int | None = None, fill: bool = False) -> Settings:
        """Cambia il formato del video (16:9, 9:16, 1:1, 4:5... o WxH).

        La timeline resta quella: cambia il fotogramma, e le clip ci si
        adattano col proprio ``fit``. Senza ``size`` si tiene il lato corto
        attuale, cosi' 1920x1080 passa a 1080x1920 e non a 608x1080. ``fill``
        mette ``cover`` su tutte le clip video e immagine: riempiono il nuovo
        fotogramma tagliando i bordi invece di lasciare le bande.
        """
        st = self.project.settings
        w, h = risoluzione(format, size or min(st.width, st.height))
        self._touch()
        st.width, st.height = w, h
        if fill:
            for t in self.project.tracks:
                if t.kind != "video":
                    continue
                for c in t.clips:
                    if c.type == "media":
                        c.fit = "cover"
        self._done()
        return st

    # ---- lettura -------------------------------------------------------
    def summary(self, detail: str = "normal") -> dict:
        p = self.project
        out: dict[str, Any] = {
            "name": p.name,
            "path": self.path,
            "settings": {
                "resolution": f"{p.settings.width}x{p.settings.height}",
                "format": rapporto(p.settings.width, p.settings.height),
                "fps": p.settings.fps,
                "sample_rate": p.settings.sample_rate,
                "background": p.settings.background,
                "audio_layout": p.settings.audio_layout,
            },
            "duration": p.duration(),
            "media": [
                {"id": m.id, "name": m.name, "kind": m.kind, "duration": m.duration,
                 "resolution": f"{m.width}x{m.height}" if m.width else None,
                 "fps": m.fps or None, "audio": m.has_audio, "proxy": bool(m.proxy),
                 "path": m.path, "folder": m.folder}
                for m in p.media
            ],
            "tracks": [],
            "master": {
                "loudnorm": {"enabled": p.master.loudnorm.enabled, "target_lufs": p.master.loudnorm.i,
                             "measured": bool(p.master.loudnorm.measured)},
                "effects": [{"type": e.type, "params": e.params, "enabled": e.enabled}
                            for e in p.master.effects],
                "volume": p.master.volume,
            },
        }
        for t in p.tracks:
            tr: dict[str, Any] = {
                "id": t.id, "kind": t.kind, "name": t.name,
                "hidden": t.hidden, "muted": t.muted, "volume": t.volume,
                "locked": t.locked, "solo": t.solo, "sidechain": t.sidechain,
                "surround": t.surround,
                "clips": [],
            }
            for c in sorted(t.clips, key=lambda x: x.start):
                item: dict[str, Any] = {
                    "id": c.id, "type": c.type, "name": c.name,
                    "start": round(c.start, 3), "end": round(c.end, 3),
                    "duration": round(c.duration, 3),
                }
                if c.type == "media":
                    item["media"] = c.media
                    item["in"] = round(c.in_, 3)
                if c.link:
                    item["link"] = c.link
                if abs(c.speed - 1.0) > 1e-6:
                    item["speed"] = c.speed
                if c.reverse:
                    item["reverse"] = True
                if not c.enabled:
                    item["enabled"] = False
                if c.blend and c.blend != "normal":
                    item["blend"] = c.blend
                if c.fade_in or c.fade_out:
                    item["fades"] = [c.fade_in, c.fade_out]
                if c.transition_out and c.transition_out.duration > 0:
                    item["transition"] = {"type": c.transition_out.type,
                                          "duration": c.transition_out.duration}
                if c.effects:
                    item["effects"] = [
                        {"i": i, "type": e.type, "params": e.params, "enabled": e.enabled}
                        for i, e in enumerate(c.effects)
                    ]
                if detail == "full":
                    # la UI ha bisogno di tutti i campi, anche quelli ai valori
                    # di default, per poterli mostrare nei controlli
                    item.update(fit=c.fit, blend=c.blend, speed=c.speed, reverse=c.reverse,
                                enabled=c.enabled, color=c.color,
                                fade_in=c.fade_in, fade_out=c.fade_out,
                                transition_out=vars(c.transition_out))
                    item["transform"] = vars(c.transform)
                    item["audio"] = vars(c.audio)
                    if c.text:
                        item["text"] = vars(c.text)
                    if c.type == "html":
                        item["html"] = c.html
                        item["html_base"] = c.html_base
                else:
                    tf = c.transform
                    changed = {k: v for k, v in vars(tf).items()
                               if kf.is_kf(v) or abs(float(kf.sample(v, 0, 1.0 if k in ("scale", "opacity") else 0.0))
                                                     - (1.0 if k in ("scale", "opacity") else 0.0)) > 1e-6}
                    if changed:
                        item["transform"] = changed
                    if c.audio.mute or kf.is_kf(c.audio.gain_db) or abs(float(kf.sample(c.audio.gain_db, 0, 0.0))) > 1e-6:
                        item["audio"] = {"gain_db": c.audio.gain_db, "mute": c.audio.mute}
                    if c.text:
                        item["text"] = c.text.text[:60]
                    if c.type == "html":
                        item["html"] = f"{len(c.html or '')} caratteri"
                tr["clips"].append(item)
            out["tracks"].append(tr)
        return out
