"""Una demo dei blocchi grafici, montata e renderizzata da vedit stesso.

    python scripts/blocchi_demo.py        # scrive docs/blocchi/demo.mp4 e docs/blocchi/demo.gif

Il montaggio e' fatto con gli stessi strumenti di un agente (``add_color``, ``add_block``): se
un blocco cambia, la demo si rifa' con lo stesso comando. Serve Playwright e Chrome o Edge.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "backend"))

from vedit import ffmpeg, render  # noqa: E402
from vedit.store import Store  # noqa: E402

DEST = RADICE / "docs" / "blocchi"

# (inizio, durata, colore dello sfondo): una scena ogni tanto cambia, come in un montaggio vero
SCENE = [(0.0, 4.6, "#24324d"), (4.6, 7.2, "#3b2a55"), (11.8, 3.2, "#1d4a43"), (15.0, 1.9, "#4a2a2f"),
         (16.9, 2.0, "#ffc06d"), (18.9, 3.1, "#10131c")]

# (blocco, inizio, durata, parametri, traccia)
BLOCCHI = [
    ("title", 0.3, 2.9, {"titolo": "vedit", "sottotitolo": "ready-made motion graphics"}, 0),
    ("lower_third", 3.2, 2.4, {"nome": "Anna Rossi", "ruolo": "Director"}, 0),
    ("date_badge", 3.4, 2.2, {"testo": "Year 20"}, 1),
    ("counter", 5.0, 3.4, {"a": 98, "etichetta": "people left", "suffisso": ""}, 0),
    ("section_label", 5.2, 3.2, {"testo": "The numbers"}, 1),
    ("bar_chart", 8.6, 3.2, {"dati": "Plan:40, Shoot:75, Edit:60", "titolo": "Hours"}, 0),
    ("steps", 11.9, 3.0, {"voci": "Plan, Shoot, Edit, Publish"}, 0),
    ("sticker_text", 15.2, 1.6, {"testo": "Wait for it"}, 0),
    ("chapter_card", 16.9, 2.0, {"titolo": "One call each", "numero": "2"}, 0),
    ("end_card", 19.0, 3.0, {"titolo": "No CSS written", "handle": "pip install vedit-mcp"}, 0),
]


def main() -> int:
    s = Store.create("demo blocchi", "720p")
    for inizio, durata, colore in SCENE:
        s.add_color(colore, start=inizio, duration=durata)
    sopra = [s.add_track("video"), s.add_track("video")]
    for blocco, inizio, durata, vars_, riga in BLOCCHI:
        s.add_block(blocco, vars_, track_id=sopra[riga].id, start=inizio, duration=durata)
    DEST.mkdir(parents=True, exist_ok=True)
    mp4, gif = DEST / "demo.mp4", DEST / "demo.gif"
    print(f"render {s.project.duration():.1f} s")
    render.render(s.project, render.RenderOptions(output=str(mp4), quality="medium", width=960,
                                                  height=540, fps=25))
    ff = ffmpeg.binary("ffmpeg")
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4), "-vf",
                    "fps=12,scale=560:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];"
                    "[b][p]paletteuse=dither=bayer:bayer_scale=4", str(gif)], check=True)
    print(f"{mp4.name} {mp4.stat().st_size // 1024} KB, {gif.name} {gif.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
