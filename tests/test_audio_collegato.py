"""Video e audio della stessa ripresa: in timeline come clip separate, collegate."""

import pytest

from vedit import ops
from vedit.store import Store


@pytest.fixture
def s(tmp_path, assets):
    st = Store.create(name="t", path=str(tmp_path / "p.json"))
    st.import_media([assets["red"]])
    return st


def _coppia(s):
    v = s.project.tracks[0].clips[0]
    a = next(t for t in s.project.tracks if t.kind == "audio").clips[0]
    return v, a


def test_l_audio_entra_su_una_traccia_audio(s):
    m = s.project.media[0]
    passi = len(s._undo)
    v = s.add_clip(m.id, start=1.0, audio_collegato=True)
    v2, a = _coppia(s)
    assert v is v2 and a.media == m.id and a.link == v.link != ""
    assert (a.start, a.in_, a.duration) == (v.start, v.in_, v.duration)
    assert v.audio.mute and not a.audio.mute         # suona una volta sola
    assert len(s._undo) == passi + 1                  # un gesto, un undo
    s.undo()
    assert all(not t.clips for t in s.project.tracks)


def test_senza_flag_l_audio_resta_dentro_il_video(s):
    s.add_clip(s.project.media[0].id)
    assert sum(len(t.clips) for t in s.project.tracks) == 1


def test_spostare_tagliare_cambiare_velocita_muove_tutte_e_due(s):
    v = s.add_clip(s.project.media[0].id, audio_collegato=True)
    _, a = _coppia(s)
    s.move_clip(v.id, start=2.0)
    assert a.start == 2.0
    s.trim_clip(a.id, in_=1.0)                        # anche partendo dall'audio
    assert (v.in_, v.duration) == (a.in_, a.duration)
    s.set_speed(v.id, 2.0)
    assert (a.speed, a.duration) == (2.0, v.duration)
    s.set_clip(v.id, start=0.5)
    assert a.start == 0.5


def test_dividere_taglia_anche_l_audio_e_le_meta_restano_in_coppia(s):
    v = s.add_clip(s.project.media[0].id, audio_collegato=True)
    _, a = _coppia(s)
    _, seconda = s.split_clip(v.id, 2.0)
    audio = next(t for t in s.project.tracks if t.kind == "audio").clips
    assert len(audio) == 2
    assert v.link == a.link and seconda.link == audio[1].link != v.link
    assert audio[1].start == seconda.start == 2.0


def test_cancellare_toglie_la_coppia(s):
    v = s.add_clip(s.project.media[0].id, audio_collegato=True)
    s.remove_clip(v.id)
    assert all(not t.clips for t in s.project.tracks)


def test_scollegare_e_jl_cut(s):
    v = s.add_clip(s.project.media[0].id, start=1.0, in_=1.0, audio_collegato=True)
    _, a = _coppia(s)
    r = ops.jl_cut(s, v.id, 0.5, "J")
    assert r["audio_clip"] == a.id and r["applicato"] == 0.5
    assert a.start == 0.5 and v.start == 1.0         # solo l'audio si e' mosso
    assert not v.link and not a.link
    # detach su una coppia ancora collegata: niente audio doppio
    v2 = s.add_clip(s.project.media[0].id, start=10.0, audio_collegato=True)
    n = sum(len(t.clips) for t in s.project.tracks)
    ops.detach_audio(s, v2.id)
    assert sum(len(t.clips) for t in s.project.tracks) == n and not v2.link


def test_audio_su_traccia_libera_se_a1_e_occupata(s):
    m = s.project.media[0]
    a1 = next(t for t in s.project.tracks if t.kind == "audio")
    s.add_clip(m.id, track_id=a1.id, start=0.0)       # musica gia' su A1
    s.add_clip(m.id, start=1.0, audio_collegato=True)
    audio = [t for t in s.project.tracks if t.kind == "audio"]
    assert len(audio) == 2 and len(audio[1].clips) == 1


def test_il_collegamento_si_salva(s):
    v = s.add_clip(s.project.media[0].id, audio_collegato=True)
    s.save()
    r = Store.open(s.path)
    assert [c.link for t in r.project.tracks for c in t.clips] == [v.link, v.link]
    assert s.summary("full")["tracks"][0]["clips"][0]["link"] == v.link
