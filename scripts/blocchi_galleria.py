"""Galleria dei blocchi grafici: un fotogramma per blocco, renderizzato davvero.

    python scripts/blocchi_galleria.py            # scrive docs/blocchi/*.png e docs/blocchi/README.md
    python scripts/blocchi_galleria.py --solo lower_third counter

Serve Playwright e Chrome/Edge (extra ``html``), come per qualunque clip html. Le
immagini sono quelle che il render produce: non sono mockup.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "backend"))

from PIL import Image, ImageDraw  # noqa: E402

from vedit import blocchi, render  # noqa: E402
from vedit.store import Store  # noqa: E402

DEST = RADICE / "docs" / "blocchi"
LARGHEZZA = 640
SFONDO = "#3a5a7a"


def fotogramma(nome: str) -> Image.Image:
    s = Store.create("galleria", "720p")
    s.add_color(SFONDO, duration=12)
    traccia = s.add_track("video")
    c = s.add_block(nome, None, track_id=traccia.id)
    t = blocchi.istante_vetrina(nome)
    out = DEST / f"{nome}.png"
    render.render_frame(s.project, t, str(out), width=LARGHEZZA, use_proxy=False)
    return Image.open(out).convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--solo", nargs="*", help="solo questi blocchi")
    a = ap.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    nomi = a.solo or list(blocchi.BLOCCHI)
    immagini: dict[str, Image.Image] = {}
    for nome in nomi:
        print(f"  {nome}")
        immagini[nome] = fotogramma(nome)
    if a.solo:
        return 0

    # il foglio d'insieme, con il nome sotto ogni blocco
    colonne, w, h, riga = 4, 400, 225 + 26, 26
    righe = -(-len(immagini) // colonne)
    foglio = Image.new("RGB", (colonne * w, righe * h), (14, 14, 20))
    d = ImageDraw.Draw(foglio)
    for i, (nome, im) in enumerate(immagini.items()):
        x, y = (i % colonne) * w, (i // colonne) * h
        foglio.paste(im.resize((w, 225)), (x, y))
        d.text((x + 8, y + 225 + 6), nome, fill=(235, 235, 240))
    foglio.save(DEST / "galleria.png", optimize=True)

    righe_md = ["# Motion graphics blocks", "",
                "Rendered by vedit itself (`python scripts/blocchi_galleria.py`), default parameters. "
                "Use them with `list_blocks` / `add_block`.", "",
                "![ten blocks edited into a short video](demo.gif)", "",
                "*Ten blocks cut into a short video by vedit itself (`python scripts/blocchi_demo.py`).*", "",
                "![all blocks](galleria.png)", ""]
    per_categoria: dict[str, list[dict]] = {}
    for b in blocchi.elenco():
        per_categoria.setdefault(b["categoria"], []).append(b)
    for cat, voci in per_categoria.items():
        righe_md += [f"## {cat.capitalize()}", ""]
        for b in voci:
            parametri = ", ".join(f"`{k}`" for k in b["parametri"])
            righe_md += [f"### `{b['id']}`", "", f"![{b['id']}]({b['id']}.png)", "",
                         f"{b['descrizione']} Default length {b['durata']:g} s. Parameters: {parametri}.", ""]
    (DEST / "README.md").write_text("\n".join(righe_md), encoding="utf-8")
    print(f"scritto {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
