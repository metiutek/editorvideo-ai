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
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import effects as fx
from . import htmlclip
from . import keyframes as kf
from . import probe as probe_mod
from .model import (
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
               width: int | None = None, height: int | None = None, fps: float | None = None) -> "Store":
        if preset not in PRESETS:
            raise EditError(f"preset sconosciuto {preset!r}; disponibili: {', '.join(PRESETS)}")
        w, h, f = PRESETS[preset]
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
            raise EditError(f"progetto non trovato: {path}")
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
            raise EditError("nessun percorso di salvataggio: passa path=")
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
            raise EditError(f"salvataggio non riuscito su {target}: {last}")

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
    def import_media(self, paths: list[str]) -> list[Media]:
        # un file illeggibile a meta' lista non deve lasciare importati i primi
        with self._edit():
            out = []
            for p in paths:
                existing = self.project.media_by_path(str(Path(p).resolve()))
                if existing:
                    out.append(existing)
                    continue
                m = probe_mod.probe(p)
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
                f"{m.name} e' usato da {len(used)} clip ({', '.join(used[:4])}"
                f"{'...' if len(used) > 4 else ''}); usa force=true per eliminarle"
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
            raise EditError(f"media {media_id!r} inesistente; importati: {known}")
        return m

    # ---- tracce --------------------------------------------------------
    def add_track(self, kind: str = "video", name: str | None = None, index: int | None = None) -> Track:
        if kind not in ("video", "audio"):
            raise EditError("kind deve essere 'video' o 'audio'")
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

    def track_or_die(self, track_id: str) -> Track:
        t = self.project.track_by_id(track_id)
        if t is None:
            known = ", ".join(x.id for x in self.project.tracks)
            raise EditError(f"traccia {track_id!r} inesistente; disponibili: {known}")
        return t

    def track_for_edit(self, track_id: str) -> Track:
        """Come ``track_or_die``, ma rifiuta le tracce bloccate."""
        t = self.track_or_die(track_id)
        if t.locked:
            raise EditError(f"la traccia {t.id} e' bloccata: sbloccala per modificarla")
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
                  solo: bool | None = None) -> Track:
        # volutamente non passa da track_for_edit: e' anche il modo di sbloccare
        t = self.track_or_die(track_id)
        if volume is not None:
            kf.validate(volume)
            volume = kf.coerce(volume)
        self._touch()
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
            raise EditError("una traccia non puo' abbassarsi ascoltando se stessa")
        ignoti = set(valori) - set(self.SIDECHAIN_DEFAULT)
        if ignoti:
            raise EditError(f"parametri sidechain sconosciuti {sorted(ignoti)}; "
                            f"ammessi: {sorted(self.SIDECHAIN_DEFAULT)}")
        conf = {**self.SIDECHAIN_DEFAULT, **(t.sidechain or {})}
        for k, v in valori.items():
            if v is None:
                continue
            lo, hi = self._SIDECHAIN_LIMITI[k]
            if not lo <= float(v) <= hi:
                raise EditError(f"sidechain {k}={v} fuori da {lo}..{hi}")
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
            raise EditError(f"clip {clip_id!r} inesistente; presenti: {', '.join(ids) or 'nessuna'}")
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
                f"la clip {clip_id} sta sulla traccia bloccata {track.id}: sbloccala prima"
            )
        return track, clip

    def track_end(self, track: Track) -> float:
        return max((c.end for c in track.clips), default=0.0)

    def add_clip(self, media_id: str, track_id: str | None = None, start: float | None = None,
                 in_: float = 0.0, duration: float | None = None, name: str | None = None) -> Clip:
        m = self.media_or_die(media_id)
        if track_id is None:
            track_id = self._default_track("audio" if m.kind == "audio" else "video")
        track = self.track_for_edit(track_id)
        if m.kind == "audio" and track.kind != "audio":
            raise EditError(f"{m.name} e' solo audio: mettilo su una traccia audio")

        if duration is None:
            duration = m.duration - in_ if m.duration > 0 else 5.0  # immagini: 5s
        if duration <= 0:
            raise EditError(f"durata non valida ({duration}s): in_={in_} oltre la fine del media ({m.duration}s)")
        if m.duration > 0 and in_ + duration > m.duration + 1e-3:
            duration = max(0.0, m.duration - in_)
            if duration <= 0:
                raise EditError(f"in_={in_}s e' oltre la durata del media ({m.duration}s)")

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
                raise EditError(f"stile testo sconosciuto {k!r}; ammessi: {', '.join(vars(st))}")
            setattr(st, k, v)
        if float(duration) <= 0:
            raise EditError("la durata deve essere > 0")
        track = self.track_for_edit(track_id or self._traccia_in_cima())
        self._touch()
        c = Clip(type="text", start=float(start), duration=float(duration), text=st,
                 name=(text[:24] or "testo"))
        track.clips.append(c)
        track.clips.sort(key=lambda x: x.start)
        self._done()
        return c

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
    def _sorgente_html(html: str | None, path: str | None) -> tuple[str, str | None]:
        """Documento e cartella base da ``html`` (testo) o ``path`` (file .html).

        Il documento entra *nel progetto*: il render resta funzione del solo
        JSON anche se il file viene cambiato o spostato. La cartella serve ai
        percorsi relativi (immagini, font) e resta quella del file.
        """
        if (html is None) == (path is None):
            raise EditError("passa html (il documento) oppure path (un file .html), uno dei due")
        base = None
        if path is not None:
            f = Path(path)
            if not f.is_file():
                raise EditError(f"file html non trovato: {path}")
            html = f.read_text(encoding="utf-8", errors="replace")
            base = str(f.resolve().parent)
        assert html is not None
        if not html.strip():
            raise EditError("il documento html e' vuoto")
        if len(html) > htmlclip.MAX_HTML:
            raise EditError(f"documento html troppo grande ({len(html)} caratteri)")
        return html, base

    def add_html(self, html: str | None = None, path: str | None = None, track_id: str | None = None,
                 start: float = 0.0, duration: float = 4.0, name: str | None = None,
                 base: str | None = None) -> Clip:
        """Grafica animata in HTML/CSS/JS sopra il video (vedi htmlclip.py).

        Senza ``html`` ne' ``path`` parte da un sottopancia di esempio.
        """
        if html is None and path is None:
            html = htmlclip.template(self.project.settings.width, self.project.settings.height)
        doc, cartella = self._sorgente_html(html, path)
        if base is not None:
            if not Path(base).is_dir():
                raise EditError(f"cartella base inesistente: {base}")
            cartella = str(Path(base).resolve())
        if float(duration) <= 0:
            raise EditError("la durata deve essere > 0")
        track = self.track_for_edit(track_id or self._traccia_in_cima())
        if track.kind != "video":
            raise EditError("una clip html va su una traccia video")
        self._touch()
        c = Clip(type="html", html=doc, html_base=cartella, start=max(0.0, float(start)),
                 duration=float(duration), name=name or (Path(path).stem if path else "html"))
        track.clips.append(c)
        track.clips.sort(key=lambda x: x.start)
        self._done()
        return c

    def set_html(self, clip_id: str, html: str | None = None, path: str | None = None,
                 base: str | None = None) -> Clip:
        """Sostituisce il documento di una clip html (o solo la cartella base)."""
        track, clip = self.clip_for_edit(clip_id)
        if clip.type != "html":
            raise EditError(f"la clip {clip_id} non e' di tipo html")
        doc, cartella = (None, None)
        if html is not None or path is not None:
            doc, cartella = self._sorgente_html(html, path)
        if base is not None and base != "" and not Path(base).is_dir():
            raise EditError(f"cartella base inesistente: {base}")
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

    def remove_clip(self, clip_id: str, ripple: bool = False) -> None:
        track, clip = self.clip_for_edit(clip_id)
        self._touch()
        gap = clip.duration
        track.clips.remove(clip)
        if ripple:
            for c in track.clips:
                if c.start >= clip.start:
                    c.start = max(0.0, c.start - gap)
        self._done()

    def move_clip(self, clip_id: str, start: float | None = None, track_id: str | None = None) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        dst = None
        if track_id and track_id != track.id:
            # controlli prima di toccare qualcosa: un rifiuto non deve lasciare
            # la clip spostata nel tempo ma sulla traccia di prima
            dst = self.track_for_edit(track_id)
            if dst.kind != track.kind:
                raise EditError(f"non posso spostare una clip {track.kind} su una traccia {dst.kind}")
        self._touch()
        if start is not None:
            clip.start = max(0.0, float(start))
        if dst is not None:
            track.clips.remove(clip)
            dst.clips.append(clip)
            dst.clips.sort(key=lambda x: x.start)
        track.clips.sort(key=lambda x: x.start)
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
            raise EditError("direction deve essere up, down, top o bottom")
        track, clip = self.clip_for_edit(clip_id)
        if track.kind != "video":
            raise EditError("le clip audio non hanno un davanti e un dietro")
        video = self.project.video_tracks()
        i = video.index(track)
        if direction in ("down", "bottom") and i == 0:
            raise EditError("la clip e' gia' sulla traccia piu' in fondo")

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
            raise EditError("la durata risultante e' <= 0")
        if media and media.duration > 0 and clip.type == "media":
            if new_in >= media.duration:
                raise EditError(f"attacco {new_in}s oltre la durata del media ({media.duration}s)")
            max_dur = (media.duration - new_in) / max(abs(clip.speed), 1e-6)
            if new_dur > max_dur + 1e-3:
                new_dur = max_dur
        self._touch()
        clip.in_, clip.duration = new_in, new_dur
        self._done()
        return clip

    def split_clip(self, clip_id: str, at: float) -> tuple[Clip, Clip]:
        """Taglia in due al tempo di timeline ``at``."""
        track, clip = self.clip_for_edit(clip_id)
        if not (clip.start + 1e-4 < at < clip.end - 1e-4):
            raise EditError(
                f"il punto di taglio {at}s e' fuori dalla clip ({clip.start:.3f}-{clip.end:.3f}s)"
            )
        self._touch()
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
        self._done()
        return clip, second

    def set_speed(self, clip_id: str, speed: float, keep_duration: bool = False) -> Clip:
        """Cambia velocita'. Di default la durata in timeline si accorcia/allunga."""
        track, clip = self.clip_for_edit(clip_id)
        if clip.type == "html":
            raise EditError("una clip html non ha velocita': il ritmo lo decide la sua animazione")
        if speed <= 0:
            raise EditError("la velocita' deve essere > 0 (usa reverse=true per il contrario)")
        if speed > 100 or speed < 0.01:
            raise EditError("velocita' fuori scala: ammessa 0.01x - 100x")
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
        self._done()
        return clip

    def set_reverse(self, clip_id: str, reverse: bool = True) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        self._touch()
        clip.reverse = bool(reverse)
        self._done()
        return clip

    def set_transform(self, clip_id: str, **values: Any) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        allowed = set(vars(Transform()))
        bad = set(values) - allowed
        if bad:
            raise EditError(f"campi transform sconosciuti {sorted(bad)}; ammessi: {sorted(allowed)}")
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
            raise EditError(f"campi audio sconosciuti {sorted(bad)}; ammessi: {sorted(allowed)}")
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
        """Campi semplici: enabled, fit, name, color, start, duration, in_."""
        track, clip = self.clip_for_edit(clip_id)
        allowed = {"enabled", "fit", "name", "color", "start", "duration", "in_"}
        bad = set(values) - allowed
        if bad:
            raise EditError(f"campi sconosciuti {sorted(bad)}; ammessi: {sorted(allowed)}")
        if "fit" in values and values["fit"] not in ("contain", "cover", "stretch", "none"):
            raise EditError("fit deve essere contain | cover | stretch | none")
        for k in ("start", "duration", "in_"):
            if values.get(k) is not None and float(values[k]) < 0:
                raise EditError(f"{k} non puo' essere negativo")
        if values.get("duration") is not None and float(values["duration"]) <= 0:
            raise EditError("la durata deve essere > 0")
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
        self._done()
        return clip

    def set_text(self, clip_id: str, **values: Any) -> Clip:
        track, clip = self.clip_for_edit(clip_id)
        if clip.type != "text" or clip.text is None:
            raise EditError(f"la clip {clip_id} non e' di tipo testo")
        allowed = set(vars(TextStyle()))
        bad = set(values) - allowed
        if bad:
            raise EditError(f"campi testo sconosciuti {sorted(bad)}; ammessi: {sorted(allowed)}")
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
                cosa = "suono" if kind == "audio" else "immagine"
                raise EditError(f"{name!r} e' un effetto {kind} e la clip {clip_id} non ha {cosa}: "
                                f"non cambierebbe niente")

    def _effect_list(self, clip_id: str | None) -> list[Effect]:
        return self.project.master.effects if clip_id is None else self.clip_for_edit(clip_id)[1].effects

    def update_effect(self, clip_id: str | None, index: int, params: dict | None = None,
                      enabled: bool | None = None) -> Effect:
        lst = self._effect_list(clip_id)
        if not (0 <= index < len(lst)):
            raise EditError(f"indice effetto {index} fuori range (0..{len(lst) - 1})")
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
            raise EditError(f"indice effetto {index} fuori range (0..{len(lst) - 1})")
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
            raise EditError(f"indice effetto {index} fuori range (0..{n - 1})")
        to = max(0, min(int(to), n - 1))
        if to == index:
            return lst
        self._touch()
        lst.insert(to, lst.pop(index))
        self._done()
        return lst

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
                raise EditError(f"voce {i}: manca 'media'")

        out: list[Clip] = []
        with self.batch():
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

    def crossfade(self, clip_a: str, clip_b: str, duration: float = 1.0,
                  type: str = "dissolve") -> dict:
        """Transizione tra due clip consecutive: sovrappone B sotto A e la scopre.

        ``type`` sceglie il modo in cui A lascia il posto a B: dissolvenza,
        tendina, scorrimento o iris (vedi model.TRANSITIONS).
        """
        if type not in TRANSITIONS:
            raise EditError(f"transizione {type!r} sconosciuta; disponibili: {', '.join(TRANSITIONS)}")
        ta, a = self.clip_for_edit(clip_a)
        tb, b = self.clip_for_edit(clip_b)
        if ta.id != tb.id:
            raise EditError("la transizione richiede due clip sulla stessa traccia")
        if a.id == b.id or b.start <= a.start:
            raise EditError("la transizione va dalla clip che viene prima (clip_a) a quella dopo (clip_b)")
        d = min(float(duration), a.duration * 0.9, b.duration * 0.9)
        if d <= 0:
            raise EditError("durata di transizione non valida")
        self._touch()
        # B (e tutto cio' che segue) risale fino a sovrapporsi ad A di d secondi
        delta = b.start - (a.end - d)
        for c in sorted(tb.clips, key=lambda x: x.start):
            if c.start >= b.start - 1e-6:
                c.start = max(0.0, c.start - delta)
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
            raise EditError(f"transizione {type!r} sconosciuta; disponibili: {', '.join(TRANSITIONS)}")
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

    def set_settings(self, **values: Any) -> Settings:
        allowed = set(vars(Settings()))
        bad = set(values) - allowed
        if bad:
            raise EditError(f"impostazioni sconosciute {sorted(bad)}; ammesse: {sorted(allowed)}")
        self._touch()
        for k, v in values.items():
            if v is not None:
                setattr(self.project.settings, k, v)
        self._done()
        return self.project.settings

    # ---- lettura -------------------------------------------------------
    def summary(self, detail: str = "normal") -> dict:
        p = self.project
        out: dict[str, Any] = {
            "name": p.name,
            "path": self.path,
            "settings": {
                "resolution": f"{p.settings.width}x{p.settings.height}",
                "fps": p.settings.fps,
                "sample_rate": p.settings.sample_rate,
                "background": p.settings.background,
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
                if abs(c.speed - 1.0) > 1e-6:
                    item["speed"] = c.speed
                if c.reverse:
                    item["reverse"] = True
                if not c.enabled:
                    item["enabled"] = False
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
                    item.update(fit=c.fit, speed=c.speed, reverse=c.reverse,
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
