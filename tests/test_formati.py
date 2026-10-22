"""Formati del video: 16:9, 9:16, 1:1, 4:5... alla creazione e a progetto aperto."""

import json

import pytest

from vedit.store import EditError, Store, rapporto, risoluzione


@pytest.mark.parametrize("formato,lato,atteso", [
    ("16:9", 1080, (1920, 1080)),
    ("9:16", 1080, (1080, 1920)),
    ("1:1", 1080, (1080, 1080)),
    ("4:5", 1080, (1080, 1350)),
    ("21:9", 1080, (2520, 1080)),
    ("16:9", 2160, (3840, 2160)),
    ("9:16", 720, (720, 1280)),
    ("1280x720", 1080, (1280, 720)),
])
def test_risoluzione(formato, lato, atteso):
    assert risoluzione(formato, lato) == atteso
    assert rapporto(*atteso) == (formato if ":" in formato else "16:9")


def test_dimensioni_pari():
    w, h = risoluzione("16:9", 1001)
    assert w % 2 == 0 and h % 2 == 0


@pytest.mark.parametrize("cattivo", ["boh", "0:9", "16:0", "99999x10"])
def test_formato_sbagliato(cattivo):
    with pytest.raises(EditError):
        risoluzione(cattivo)


def test_create_con_formato(tmp_path):
    s = Store.create("f", "4:5", path=str(tmp_path / "p.json"))
    st = s.project.settings
    assert (st.width, st.height, st.fps) == (1080, 1350, 30.0)
    assert s.summary()["settings"]["format"] == "4:5"
    s = Store.create("f", "9:16", size=720, fps=60)
    assert (s.project.settings.width, s.project.settings.height, s.project.settings.fps) == (720, 1280, 60)
    with pytest.raises(EditError, match="unknown preset"):
        Store.create("f", "boh")


def test_set_format_tiene_il_lato_corto_e_si_annulla(tmp_path, assets):
    s = Store.create("f", "1080p", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, duration=1)
    s.set_format("9:16")
    assert (s.project.settings.width, s.project.settings.height) == (1080, 1920)
    assert s.project.clip(c.id).fit == "contain"
    # salvato su disco come ogni modifica
    assert json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))["settings"]["height"] == 1920
    s.undo()
    assert (s.project.settings.width, s.project.settings.height) == (1920, 1080)

    s.set_format("1:1", size=720, fill=True)
    assert (s.project.settings.width, s.project.settings.height) == (720, 720)
    assert s.project.clip(c.id).fit == "cover"
