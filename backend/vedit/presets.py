"""Preset pronti all'uso: look, ritocchi audio e transizioni.

Il catalogo effetti (``effects.describe()``) elenca i mattoni con tutti i loro
parametri: utile per regolare, inutile per scegliere. Qui ci sono combinazioni
gia' tarate con un nome riconoscibile, raggruppate come nella libreria di un
montatore: si trascinano su una clip e basta.

Un preset e' solo una lista di effetti con i parametri gia' scelti, quindi
applicarlo equivale a chiamare ``add_effect`` una volta per effetto: niente
formato nuovo da mantenere e resta tutto modificabile dal pannello proprieta'.
"""

from __future__ import annotations

from .model import TRANSITIONS

# --------------------------------------------------------------------------
# look video
# --------------------------------------------------------------------------

LOOKS: list[dict] = [
    {
        "id": "cinema_teal_orange",
        "name": "Cinema teal & orange",
        "group": "Colour",
        "desc": "Cool shadows, warm skin tones: the trailer look.",
        "effects": [
            {"type": "colorbalance", "params": {"bs": 0.14, "gs": 0.04, "rh": 0.12, "gh": 0.03}},
            {"type": "color", "params": {"contrast": 1.12, "saturation": 1.08}},
        ],
    },
    {
        "id": "bianco_e_nero",
        "name": "Black and white",
        "group": "Colour",
        "desc": "Full desaturation with a touch more contrast.",
        "effects": [{"type": "color", "params": {"saturation": 0.0, "contrast": 1.15}}],
    },
    {
        "id": "bn_contrastato",
        "name": "High-contrast black and white",
        "group": "Colour",
        "desc": "Deep blacks, reportage style.",
        "effects": [
            {"type": "color", "params": {"saturation": 0.0, "contrast": 1.45, "brightness": -0.04}},
            {"type": "grain", "params": {"strength": 8}},
        ],
    },
    {
        "id": "caldo_tramonto",
        "name": "Warm sunset",
        "group": "Colour",
        "desc": "Temperature towards orange, end-of-day light.",
        "effects": [
            # sotto 6500 K colortemperature scalda: 8200 dava un tramonto blu
            {"type": "temperature", "params": {"temperature": 4200}},
            {"type": "color", "params": {"saturation": 1.12, "brightness": 0.03}},
        ],
    },
    {
        "id": "freddo_notturno",
        "name": "Cold night",
        "group": "Colour",
        "desc": "Blue, high contrast: night or neon interiors.",
        "effects": [
            {"type": "temperature", "params": {"temperature": 9000}},
            {"type": "color", "params": {"contrast": 1.2, "brightness": -0.06, "saturation": 0.9}},
        ],
    },
    {
        "id": "sbiadito_pellicola",
        "name": "Faded film",
        "group": "Colour",
        "desc": "Lifted blacks and grain: looks shot on film.",
        "effects": [
            {"type": "curves", "params": {"preset": "lighter"}},
            {"type": "color", "params": {"saturation": 0.82, "contrast": 0.92}},
            {"type": "grain", "params": {"strength": 14}},
        ],
    },
    {
        "id": "vhs",
        "name": "90s VHS",
        "group": "Stylised",
        "desc": "Heavy grain, washed-out colours, soft edges.",
        "effects": [
            {"type": "color", "params": {"saturation": 0.75, "contrast": 1.1}},
            {"type": "blur", "params": {"sigma": 2}},
            {"type": "grain", "params": {"strength": 26}},
            {"type": "vignette", "params": {"angle": 0.9}},
        ],
    },
    {
        "id": "sogno",
        "name": "Dream",
        "group": "Stylised",
        "desc": "Diffuse glowing halo, memory or flashback.",
        "effects": [
            {"type": "glow", "params": {"amount": 0.55, "sigma": 16}},
            {"type": "color", "params": {"brightness": 0.06, "saturation": 0.9}},
        ],
    },
    {
        "id": "nitido",
        "name": "Sharp",
        "group": "Touch-up",
        "desc": "Extra detail without touching the colours.",
        "effects": [{"type": "sharpen", "params": {"amount": 1.1}}],
    },
    {
        "id": "pulisci_ripresa",
        "name": "Clean up footage",
        "group": "Touch-up",
        "desc": "Noise reduction and contrast recovery: shot in low light.",
        "effects": [
            {"type": "denoise", "params": {"strength": 4}},
            {"type": "color", "params": {"contrast": 1.08, "brightness": 0.04}},
        ],
    },
    {
        "id": "vignettatura",
        "name": "Vignette",
        "group": "Touch-up",
        "desc": "Darkened edges, the eye goes to the centre.",
        "effects": [{"type": "vignette", "params": {"angle": 0.85}}],
    },
    {
        "id": "censura",
        "name": "Censor (pixelate)",
        "group": "Stylised",
        "desc": "Mosaic on the whole picture: faces or number plates.",
        "effects": [{"type": "pixelate", "params": {"size": 24}}],
    },
    {
        "id": "specchia",
        "name": "Mirror",
        "group": "Touch-up",
        "desc": "Flips horizontally: fixes mirrored shots.",
        "effects": [{"type": "mirror", "params": {"horizontal": True}}],
    },
    {
        "id": "stabilizza",
        "name": "Stabilise",
        "group": "Touch-up",
        "desc": "Removes handheld camera shake. Slower render.",
        "effects": [{"type": "stabilize", "params": {}}],
    },
]

# --------------------------------------------------------------------------
# catene audio
# --------------------------------------------------------------------------

AUDIO: list[dict] = [
    {
        "id": "voce_pulita",
        "name": "Clean voice",
        "group": "Voice",
        "desc": "Cuts the booming lows, compresses, reduces hiss.",
        "effects": [
            {"type": "highpass", "params": {"freq": 90}},
            {"type": "adenoise", "params": {"reduction": 10}},
            {"type": "compressor", "params": {"threshold": -20, "ratio": 3.5}},
        ],
    },
    {
        "id": "voce_radio",
        "name": "Radio voice",
        "group": "Voice",
        "desc": "Firm compression and presence in the mids.",
        "effects": [
            {"type": "highpass", "params": {"freq": 110}},
            {"type": "compressor", "params": {"threshold": -24, "ratio": 6}},
            {"type": "eq3", "params": {"mid": 3.5, "treble": 2.0}},
            {"type": "limiter", "params": {"limit": 0.9}},
        ],
    },
    {
        "id": "telefono",
        "name": "Telephone",
        "group": "Effects",
        "desc": "Narrow band: voice on the phone or the radio.",
        "effects": [
            {"type": "highpass", "params": {"freq": 400}},
            {"type": "lowpass", "params": {"freq": 3000}},
        ],
    },
    {
        "id": "sala_grande",
        "name": "Large hall",
        "group": "Effects",
        "desc": "Wide reverb.",
        "effects": [{"type": "reverb", "params": {"amount": 0.4, "size": 0.8}}],
    },
    {
        "id": "eco",
        "name": "Echo",
        "group": "Effects",
        "desc": "Rhythmic repeats.",
        "effects": [{"type": "echo", "params": {"delay_ms": 350, "decay": 0.4}}],
    },
    {
        "id": "musica_sotto_voce",
        "name": "Music under the voice",
        "group": "Music",
        "desc": "Lowers and darkens the music so it does not cover the speech.",
        "effects": [
            {"type": "lowpass", "params": {"freq": 9000}},
            {"type": "compressor", "params": {"threshold": -18, "ratio": 2.5}},
        ],
    },
    {
        "id": "volume_costante",
        "name": "Steady volume",
        "group": "Music",
        "desc": "Dynamic normalisation: evens out the parts that are too loud or too quiet.",
        "effects": [{"type": "dynnorm", "params": {}}],
    },
]

# --------------------------------------------------------------------------
# transizioni
# --------------------------------------------------------------------------

_TR_META = {
    "dissolve": ("Dissolve", "Classic", "One fades into the other.", 1.0),
    "iris": ("Iris", "Classic", "A circle opening from the centre.", 1.0),
    "wipe_right": ("Wipe ▸", "Wipe", "Reveals from left to right.", 0.8),
    "wipe_left": ("Wipe ◂", "Wipe", "Reveals from right to left.", 0.8),
    "wipe_down": ("Wipe ▾", "Wipe", "Reveals from the top.", 0.8),
    "wipe_up": ("Wipe ▴", "Wipe", "Reveals from the bottom.", 0.8),
    "slide_left": ("Slide ◂", "Slide", "The clip exits to the left.", 0.7),
    "slide_right": ("Slide ▸", "Slide", "The clip exits to the right.", 0.7),
    "slide_up": ("Slide ▴", "Slide", "The clip exits upwards.", 0.7),
    "slide_down": ("Slide ▾", "Slide", "The clip exits downwards.", 0.7),
}


def transitions() -> list[dict]:
    """Transizioni del motore con nome leggibile, gruppo e durata consigliata."""
    out = []
    for t in TRANSITIONS:
        name, group, desc, dur = _TR_META.get(t, (t, "Other", "", 1.0))
        out.append({"id": t, "name": name, "group": group, "desc": desc, "duration": dur})
    return out


def describe() -> dict:
    """Libreria completa per la UI."""
    return {
        "video": LOOKS,
        "audio": AUDIO,
        "transitions": transitions(),
    }


def find(preset_id: str) -> dict | None:
    for p in LOOKS + AUDIO:
        if p["id"] == preset_id:
            return p
    return None
