"""Copertine fatte dal montaggio: i fotogrammi migliori, con un titolo sopra.

Il montaggio si divide in tanti tratti quante copertine si vogliono; in ogni
tratto si guardano tre istanti e si tiene il piu' nitido e contrastato, cosi'
le opzioni sono diverse fra loro invece di essere tre fotogrammi della stessa
inquadratura. Il titolo, se c'e', cambia posizione da un'opzione all'altra.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import render
from .model import Project

PROVE = 3                       # istanti guardati per ogni tratto
POSIZIONI = ("bottom", "top", "center")
# font in grassetto da cercare, nell'ordine: Windows, macOS, Linux
FONT = (
    "arialbd.ttf", "seguisb.ttf", "Arial Bold.ttf", "Helvetica.ttc",
    "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def punteggio(img: Image.Image) -> float:
    """Quanto un fotogramma regge da copertina: nitido, contrastato, colorato, non buio."""
    a = np.asarray(img.convert("RGB").resize((160, 90)), dtype=np.float32) / 255.0
    luma = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    nitidezza = float(np.abs(np.diff(luma, axis=0)).mean() + np.abs(np.diff(luma, axis=1)).mean())
    contrasto = float(luma.std())
    colore = float((a.max(axis=2) - a.min(axis=2)).mean())
    esposizione = 1.0 - min(1.0, abs(float(luma.mean()) - 0.45) * 2)
    if luma.mean() < 0.06 or luma.mean() > 0.95:   # nero di una dissolvenza, bianco di un lampo
        return 0.0
    return (nitidezza * 4 + contrasto * 2 + colore) * (0.4 + 0.6 * esposizione)


def istanti(durata: float, quante: int) -> list[list[float]]:
    """Per ogni tratto del montaggio, gli istanti da provare (lontano dai bordi)."""
    margine = min(0.5, durata * 0.03)
    utile = max(0.0, durata - 2 * margine)
    passo = utile / quante
    return [[margine + passo * (i + (k + 1) / (PROVE + 1)) for k in range(PROVE)]
            for i in range(quante)]


def _font(dim: int) -> ImageFont.ImageFont:
    for nome in FONT:
        try:
            return ImageFont.truetype(nome, dim)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=dim)
    except TypeError:   # Pillow < 10.1
        return ImageFont.load_default()


def _righe(draw: ImageDraw.ImageDraw, testo: str, font, larghezza: int) -> list[str]:
    righe: list[str] = []
    for parola in testo.split():
        prova = f"{righe[-1]} {parola}" if righe else parola
        if righe and draw.textlength(prova, font=font) <= larghezza:
            righe[-1] = prova
        else:
            righe.append(parola)
    return righe


def con_titolo(img: Image.Image, titolo: str, posizione: str = "bottom") -> Image.Image:
    """Il titolo grande, bianco col bordo nero, su una sfumatura che lo fa leggere."""
    img = img.convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    dim = int(min(w, h) * 0.14)
    while True:
        font = _font(dim)
        righe = _righe(draw, titolo, font, int(w * 0.88))
        larga = max(draw.textlength(r, font=font) for r in righe)
        if (len(righe) <= 3 and larga <= w * 0.88) or dim <= 14:
            break
        dim = int(dim * 0.88)
    interlinea = int(dim * 1.15)
    alto = interlinea * len(righe)
    y0 = {"top": int(h * 0.07), "center": (h - alto) // 2}.get(posizione, h - alto - int(h * 0.08))

    # sfumatura scura dietro il testo, verso il bordo piu' vicino
    ombra = Image.new("L", (1, h), 0)
    for y in range(h):
        if posizione == "top":
            v = 1 - y / max(1, y0 + alto + dim)
        elif posizione == "center":
            v = 1 - abs(y - (y0 + alto / 2)) / max(1, alto)
        else:
            v = (y - (y0 - dim)) / max(1, h - (y0 - dim))
        ombra.putpixel((0, y), int(max(0.0, min(1.0, v)) * 170))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, ombra.resize((w, h)))

    draw = ImageDraw.Draw(img)
    bordo = max(2, dim // 12)
    for i, riga in enumerate(righe):
        x = (w - draw.textlength(riga, font=font)) / 2
        draw.text((x, y0 + i * interlinea), riga, font=font, fill=(255, 255, 255),
                  stroke_width=bordo, stroke_fill=(0, 0, 0))
    return img


def nuovo_nome(cartella: Path) -> Path:
    n = 1
    while (cartella / f"cover_{n:02d}.jpg").exists():
        n += 1
    return cartella / f"cover_{n:02d}.jpg"


def fai(project: Project, cartella: str | Path, quante: int = 6, titolo: str = "",
        tempi: list[float] | None = None) -> list[dict]:
    """Crea le copertine e restituisce ``[{path, t}]``.

    ``tempi`` sceglie gli istanti a mano (una copertina per istante); senza,
    li cerca il punteggio, un tratto del montaggio per copertina.
    """
    durata = project.duration()
    if durata <= 0:
        raise ValueError("the timeline is empty: there is nothing to make a cover from")
    quante = max(1, min(int(quante), 12))
    prove = [[min(max(0.0, float(t)), durata)] for t in tempi] if tempi else istanti(durata, quante)
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    lavoro = Path(tempfile.mkdtemp(prefix="vedit_copertine_"))
    fatte = []
    try:
        for i, tratto in enumerate(prove):
            migliore = None
            for k, t in enumerate(tratto):
                f = lavoro / f"{i:02d}_{k}.jpg"
                render.render_frame(project, t, str(f), use_proxy=False)
                with Image.open(f) as im:
                    im.load()
                    s = punteggio(im)
                    if migliore is None or s > migliore[0]:
                        migliore = (s, t, im.copy())
            _, t, img = migliore
            if titolo.strip():
                img = con_titolo(img, titolo.strip(), POSIZIONI[i % len(POSIZIONI)])
            out = nuovo_nome(cartella)
            img.convert("RGB").save(out, "JPEG", quality=90)
            fatte.append({"path": str(out.resolve()), "t": round(t, 2)})
    finally:
        shutil.rmtree(lavoro, ignore_errors=True)
    return fatte
