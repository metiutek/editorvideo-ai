"""Trim da montatore: ripple, roll, slip, slide.

Ognuno sposta bordi senza lasciare buchi ne' sovrapposizioni, rispetta la
sorgente (velocita', reverse, lunghezza del media), porta con se' le clip
collegate e, se un passo e' impossibile, non lascia niente a meta'.
"""

import pytest

from vedit.store import EditError, Store


@pytest.fixture
def lunga(tmp_path, assets):
    """Tre clip attaccate da una ripresa di 5 s: 0-1.5 (da 0), 1.5-3 (da 2), 3-4 (da 3.5)."""
    s = Store.create("t", "720p")
    m = s.import_media([assets["red"]])[0]
    ids = [s.add_clip(m.id, duration=1.5, in_=0).id,
           s.add_clip(m.id, duration=1.5, in_=2).id,
           s.add_clip(m.id, duration=1.0, in_=3.5).id]
    return s, ids


def _v(s):
    return [(round(c.start, 3), round(c.duration, 3), round(c.in_, 3))
            for c in s.project.tracks[0].clips]


def test_ripple_coda_spinge_il_seguito(lunga):
    s, (a, b, c) = lunga
    s.ripple_trim(a, "end", 0.5)
    assert _v(s) == [(0, 2.0, 0), (2.0, 1.5, 2), (3.5, 1.0, 3.5)]
    s.ripple_trim(a, "end", -1.0)
    assert _v(s) == [(0, 1.0, 0), (1.0, 1.5, 2), (2.5, 1.0, 3.5)]


def test_ripple_testa_toglie_e_tira_indietro(lunga):
    s, (a, b, c) = lunga
    s.ripple_trim(b, "start", 0.5)
    # la clip resta dove sta, perde mezzo secondo di testa, il seguito arretra
    assert _v(s) == [(0, 1.5, 0), (1.5, 1.0, 2.5), (2.5, 1.0, 3.5)]
    with pytest.raises(EditError, match="prima del suo attacco"):
        s.ripple_trim(a, "start", -0.5)


def test_roll_sposta_solo_il_taglio(lunga):
    s, (a, b, c) = lunga
    s.roll_edit(a, 0.4)
    assert _v(s) == [(0, 1.9, 0), (1.9, 1.1, 2.4), (3.0, 1.0, 3.5)]
    with pytest.raises(EditError, match="attaccata dopo"):
        s.roll_edit(c, 0.2)
    with pytest.raises(EditError, match="senza durata"):
        s.roll_edit(a, -2)
    with pytest.raises(EditError, match="dopo la sua fine"):
        s.roll_edit(a, 5)


def test_slip_cambia_solo_il_tratto(lunga):
    s, (a, b, c) = lunga
    s.slip_clip(b, 1.0)
    assert _v(s)[1] == (1.5, 1.5, 3.0)
    with pytest.raises(EditError, match="dopo di cosi'"):
        s.slip_clip(b, 1.0)        # 4.0 + 1.5 > 5
    with pytest.raises(EditError, match="prima di cosi'"):
        s.slip_clip(a, -0.1)


def test_slide_le_vicine_cedono(lunga):
    s, (a, b, c) = lunga
    s.slide_clip(b, 0.5)
    assert _v(s) == [(0, 2.0, 0), (2.0, 1.5, 2), (3.5, 0.5, 4.0)]
    s.slide_clip(b, -1.0)
    assert _v(s) == [(0, 1.0, 0), (1.0, 1.5, 2), (2.5, 1.5, 3.0)]


def test_un_passo_impossibile_non_lascia_niente(lunga):
    s, (a, b, c) = lunga
    prima, passi = _v(s), len(s._undo)
    with pytest.raises(EditError):
        s.slide_clip(b, 3.0)       # la clip dopo resterebbe senza durata
    assert _v(s) == prima and len(s._undo) == passi
    # dentro un blocco l'errore non si porta via lo snapshot del blocco
    with s.batch():
        with pytest.raises(EditError):
            s.roll_edit(a, 10)
        s.slip_clip(b, 0.5)
    assert len(s._undo) == passi + 1
    s.undo()
    assert _v(s) == prima


def test_velocita_e_reverse(tmp_path, assets):
    s = Store.create("t", "720p")
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, duration=1.0, in_=1.0)
    s.set_speed(c.id, 2.0, keep_duration=True)
    c = s.clip_or_die(c.id)[1]
    s.ripple_trim(c.id, "end", 0.5)
    c = s.clip_or_die(c.id)[1]
    # a 2x mezzo secondo di timeline e' un secondo di sorgente
    assert (round(c.duration, 3), round(c.in_, 3)) == (1.5, 1.0)
    with pytest.raises(EditError, match="dopo la sua fine"):
        s.ripple_trim(c.id, "end", 0.6)          # 1 + 2.1*2 > 5
    s.set_reverse(c.id, True)
    s.ripple_trim(c.id, "end", -0.5)
    c = s.clip_or_die(c.id)[1]
    # all'indietro la coda in timeline e' l'inizio della sorgente: l'attacco avanza
    assert (round(c.duration, 3), round(c.in_, 3)) == (1.0, 2.0)


def test_collegate_seguono_e_traccia_bloccata(tmp_path, assets):
    s = Store.create("t", "720p")
    m = s.import_media([assets["red"]])[0]
    a = s.add_clip(m.id, duration=2, audio_collegato=True)
    b = s.add_clip(m.id, duration=2, in_=2, audio_collegato=True)
    s.ripple_trim(a.id, "end", -0.5)
    audio = next(t for t in s.project.tracks if t.kind == "audio")
    assert [(round(c.start, 3), round(c.duration, 3)) for c in audio.clips] == [(0, 1.5), (1.5, 2)]
    s.slip_clip(b.id, 0.5)
    assert round(audio.clips[1].in_, 3) == 2.5
    s.set_track(audio.id, locked=True)
    with pytest.raises(EditError, match="bloccata"):
        s.ripple_trim(a.id, "end", 0.2)

