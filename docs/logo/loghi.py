"""Logo di vedit: il "play" con una faccia, in tre varianti piatte e geometriche.

    python docs/logo/loghi.py      # rigenera gli SVG, i PNG e l'anteprima

Tutto a colori pieni (corallo, crema, inchiostro), niente sfumature ne' ombre:
regge da 512 px fino all'icona della scheda del browser.
"""
from pathlib import Path

QUI = Path(__file__).parent

CORALLO = "#ff7a4d"
CREMA = "#fff6ee"
INCHIOSTRO = "#2a1208"

FONDO = f'<rect x="16" y="16" width="480" height="480" rx="120" fill="{CORALLO}"/>'


def play(d="M200 160 L200 352 L362 256 Z"):
    """Triangolo con gli angoli morbidi: riempimento e contorno dello stesso colore."""
    return (f'<path d="{d}" fill="{CREMA}" stroke="{CREMA}" stroke-width="44" '
            f'stroke-linejoin="round"/>')


def faccia(occhiolino=False):
    occhio_sx = (f'<path d="M216 242 Q229 230 242 242" fill="none" stroke="{INCHIOSTRO}" '
                 f'stroke-width="11" stroke-linecap="round"/>' if occhiolino
                 else f'<circle cx="229" cy="240" r="13" fill="{INCHIOSTRO}"/>')
    return (occhio_sx
            + f'<circle cx="275" cy="240" r="13" fill="{INCHIOSTRO}"/>'
            + f'<path d="M232 278 Q252 296 272 278" fill="none" stroke="{INCHIOSTRO}" '
              f'stroke-width="11" stroke-linecap="round"/>')


# 1. ciak: una fascia sola a strisce, storta, appoggiata sulla punta in alto
CIAK = f"""<g transform="rotate(-20 210 128)">
  <rect x="150" y="104" width="120" height="40" rx="10" fill="{INCHIOSTRO}"/>
  <path d="M176 104 L196 104 L182 144 L162 144 Z M216 104 L236 104 L222 144 L202 144 Z
           M256 104 L270 104 L270 110 L262 144 L242 144 Z" fill="{CREMA}"/>
</g>"""

# 2. corsa: due scie e una stellina
CORSA = f"""<g stroke="{CREMA}" stroke-width="18" stroke-linecap="round">
  <line x1="84" y1="222" x2="132" y2="222"/><line x1="64" y1="290" x2="132" y2="290"/>
</g>
<path d="M404 138 Q410 166 438 172 Q410 178 404 206 Q398 178 370 172 Q398 166 404 138 Z" fill="{CREMA}"/>"""

# 3. taglio: la punta del play e' staccata da una fessura, come un taglio in timeline
PUNTA = "M318 191 L362 256 L318 321 Z"
TAGLIO_FESSURA = f'<rect x="300" y="120" width="14" height="272" rx="7" fill="{CORALLO}"/>'
TAGLIO_TRATTINI = f"""<g fill="{CREMA}">
  <rect x="301" y="72" width="12" height="26" rx="6"/><rect x="301" y="414" width="12" height="26" rx="6"/>
</g>"""


def svg(*parti):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
            + FONDO + "".join(parti) + "</svg>")


VARIANTI = {
    "1_ciak": svg(play(), faccia(), CIAK),
    "2_corsa": svg(CORSA, play(), faccia()),
    # la punta si sposta un poco a destra: il taglio si vede come uno stacco
    "3_taglio": svg(play(), TAGLIO_FESSURA,
                    f'<g transform="translate(10 0)"><path d="{PUNTA}" fill="{CREMA}" stroke="{CREMA}" '
                    f'stroke-width="44" stroke-linejoin="round"/></g>',
                    TAGLIO_FESSURA, TAGLIO_TRATTINI, faccia(occhiolino=True)),
}

# Quello scelto: "taglio". Per l'icona della scheda (16-32 px) la faccia e i
# trattini sparirebbero in un grumo: resta il play tagliato, che si legge.
SCELTO = "3_taglio"
FAVICON = svg(play(), TAGLIO_FESSURA,
              f'<g transform="translate(10 0)"><path d="{PUNTA}" fill="{CREMA}" stroke="{CREMA}" '
              f'stroke-width="44" stroke-linejoin="round"/></g>', TAGLIO_FESSURA)
PUBBLICO = QUI.parents[1] / "frontend" / "public"


if __name__ == "__main__":
    for nome, s in VARIANTI.items():
        (QUI / f"{nome}.svg").write_text(s, encoding="utf-8")
    PUBBLICO.mkdir(parents=True, exist_ok=True)
    for cartella in (QUI, PUBBLICO):
        (cartella / "logo.svg").write_text(VARIANTI[SCELTO], encoding="utf-8")
        (cartella / "favicon.svg").write_text(FAVICON, encoding="utf-8")
    righe = "".join(
        f'<div class="v"><img src="{n}.svg" width="256"><div class="p">'
        f'<img src="{n}.svg" width="64"><img src="{n}.svg" width="32"><img src="{n}.svg" width="16"></div>'
        f'<b>{n.split("_", 1)[1]}</b></div>' for n in VARIANTI)
    (QUI / "anteprima.html").write_text(
        "<!doctype html><html><body style='margin:0;background:#121119;color:#f3f0fa;font:600 18px sans-serif'>"
        "<div style='display:flex;gap:40px;padding:30px'>" + righe + "</div>"
        "<style>.v{display:flex;flex-direction:column;align-items:center;gap:14px}"
        ".p{display:flex;align-items:end;gap:14px;background:#1a1823;padding:10px 16px;border-radius:12px}</style>"
        "</body></html>", encoding="utf-8")
    print("ok")
