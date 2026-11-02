"""Blocchi grafici pronti per ``add_html``: sottopancia, titoli, cartellini, badge,
contatori, grafici, capitoli.

Un'animazione in HTML non va riscritta ogni volta: un agente che deve mettere un
sottopancia scrive 80 righe di CSS e le rilegge a ogni giro. Qui ogni blocco e'
un documento gia' tarato — misure in ``vw``/``vh``, quindi uguale in 16:9, 9:16
e 1:1 — con dei parametri che si riempiono come i ``{{segnaposto}}`` di
``add_html(vars=...)``, solo controllati: un testo e' sempre scritto fra tag
(mai interpretato come HTML), un colore e' un colore, un numero e' un numero.

Il tempo dei blocchi e' quello della clip (``htmlclip.OROLOGIO``): entrata,
permanenza e uscita sono animazioni CSS che partono da 0 e finiscono prima della
fine della clip (``{{durata}}`` e' la durata vera, messa dal sistema), cosi'
anteprima e render mostrano lo stesso fotogramma. Il contatore e' l'unico a usare
``window.veditRender``.
"""

from __future__ import annotations

import html as _html
import math
import re
from typing import Any

# --------------------------------------------------------------------------
# pezzi comuni
# --------------------------------------------------------------------------

_BASE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}
body{font-family:{{font}};color:{{testo_colore}};-webkit-font-smoothing:antialiased}
.out{animation:fuori .35s linear calc({{durata}}s - .4s) forwards}
@keyframes fuori{to{opacity:0}}
@keyframes entra{from{opacity:0;transform:translateY(2vh)}to{opacity:1;transform:none}}
@keyframes cresce{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes pop{0%{opacity:0;transform:scale(.6)}70%{opacity:1;transform:scale(1.08)}100%{opacity:1;transform:scale(1)}}
{{css}}
</style></head><body>{{corpo}}</body></html>"""

_FONT = "'Segoe UI Variable Display','Segoe UI',system-ui,-apple-system,sans-serif"


def _colore(v: Any, nome: str) -> str:
    s = str(v).strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", s) or re.fullmatch(r"[a-zA-Z]{3,20}", s) \
            or re.fullmatch(r"(rgb|hsl)a?\(\s*[\d.,%\s/]+\)", s):
        return s
    raise ValueError(f"{nome} must be a color like #ff3b5c or 'white', got {v!r}")


def _testo(v: Any, nome: str, massimo: int = 200) -> str:
    s = str(v).strip()
    if len(s) > massimo:
        raise ValueError(f"{nome} is too long ({len(s)} characters, at most {massimo})")
    return _html.escape(s, quote=True)


def _numero(v: Any, nome: str, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{nome} must be a number between {lo} and {hi}") from None
    if not (lo <= x <= hi) or math.isnan(x):
        raise ValueError(f"{nome} out of range ({x}): between {lo} and {hi}")
    return x


def _scelta(v: Any, nome: str, ammessi: tuple[str, ...]) -> str:
    if v not in ammessi:
        raise ValueError(f"unknown {nome} {v!r}; allowed: {', '.join(ammessi)}")
    return str(v)


# --------------------------------------------------------------------------
# i blocchi
# --------------------------------------------------------------------------
# Ogni blocco: descrizione (inglese, la legge chi usa l'editor), durata di
# default, parametri {nome: (tipo, default, descrizione[, ammessi o limiti])} e
# una funzione che dai valori gia' controllati restituisce (css, corpo).


def _lower_third(v: dict) -> tuple[str, str]:
    css = f"""
.lt{{position:absolute;left:6vw;bottom:9vh;display:flex;align-items:stretch;gap:1.4vw;
 animation:entra .5s cubic-bezier(.2,.8,.2,1) both}}
.lt i{{display:block;width:.7vw;min-width:6px;background:{v['colore']};border-radius:99px;
 transform-origin:top;animation:cresce .5s ease-out both}}
.lt div{{padding:.4vh 0}}
.lt b{{display:block;font-size:max(3.2vw,3.2vh);font-weight:800;letter-spacing:-.01em;
 text-shadow:0 2px 14px rgba(0,0,0,.55)}}
.lt span{{display:block;margin-top:.4vh;font-size:max(1.8vw,1.8vh);font-weight:600;opacity:.92;
 text-shadow:0 2px 10px rgba(0,0,0,.55)}}"""
    ruolo = f"<span>{v['ruolo']}</span>" if v["ruolo"] else ""
    return css, f'<div class="lt"><i></i><div><b>{v["nome"]}</b>{ruolo}</div></div>'


def _title(v: dict) -> tuple[str, str]:
    css = f"""
.tt{{position:absolute;inset:0;display:grid;place-content:center;text-align:center;gap:1.6vh}}
.tt h1{{margin:0;font-size:max(7vw,7vh);font-weight:900;letter-spacing:-.025em;line-height:1.02;
 text-shadow:0 4px 30px rgba(0,0,0,.5);animation:pop .7s cubic-bezier(.2,.9,.3,1.2) both}}
.tt p{{margin:0;font-size:max(2.4vw,2.4vh);font-weight:600;color:{v['colore']};
 text-shadow:0 2px 12px rgba(0,0,0,.5);animation:entra .6s ease-out .35s both}}
.tt hr{{width:9vw;height:.7vh;border:0;border-radius:99px;margin:0 auto;background:{v['colore']};
 transform-origin:center;animation:cresce .6s ease-out .2s both}}"""
    sotto = f"<p>{v['sottotitolo']}</p>" if v["sottotitolo"] else ""
    return css, f'<div class="tt"><h1>{v["titolo"]}</h1><hr>{sotto}</div>'


def _caption_pill(v: dict) -> tuple[str, str]:
    lato = "top:8vh" if v["posizione"] == "top" else "bottom:9vh"
    css = f"""
.cp{{position:absolute;left:0;right:0;{lato};display:flex;justify-content:center}}
.cp span{{max-width:80vw;padding:1.2vh 2.2vw;border-radius:99px;background:{v['sfondo']};
 color:{v['testo_colore']};font-size:max(2.1vw,2.1vh);font-weight:700;text-align:center;
 box-shadow:0 6px 24px rgba(0,0,0,.35);animation:pop .45s ease-out both}}"""
    return css, f'<div class="cp"><span>{v["testo"]}</span></div>'


def _date_badge(v: dict) -> tuple[str, str]:
    lato = "left:4vw" if v["posizione"] == "top_left" else "right:4vw"
    css = f"""
.db{{position:absolute;top:5vh;{lato};padding:.8vh 1.6vw;border-radius:.8vw;background:#fff;
 color:#1b1b22;font-size:max(1.7vw,1.7vh);font-weight:800;letter-spacing:.08em;text-transform:uppercase;
 box-shadow:0 5px 18px rgba(0,0,0,.35);border-top:1.1vh solid {v['colore']};
 animation:pop .45s ease-out both}}"""
    return css, f'<div class="db">{v["testo"]}</div>'


def _counter(v: dict) -> tuple[str, str]:
    css = f"""
.ct{{position:absolute;inset:0;display:grid;place-content:center;text-align:center}}
.ct b{{font-size:max(11vw,11vh);font-weight:900;font-variant-numeric:tabular-nums;letter-spacing:-.03em;
 text-shadow:0 4px 30px rgba(0,0,0,.5)}}
.ct span{{display:block;font-size:max(2.4vw,2.4vh);font-weight:700;color:{v['colore']};
 text-shadow:0 2px 12px rgba(0,0,0,.5)}}"""
    corpo = (f'<div class="ct"><b id="n">{v["prefisso"]}{v["da"]:.{int(v["decimali"])}f}{v["suffisso"]}</b>'
             f'<span>{v["etichetta"]}</span></div>'
             "<script>"
             f"const DA={v['da']},A={v['a']},D={int(v['decimali'])},T={v['durata'] * 0.7:.3f};"
             f"const PRE='{v['prefisso_js']}',SUF='{v['suffisso_js']}';"
             "window.veditRender=t=>{const k=Math.min(1,Math.max(0,t/T)),e=1-Math.pow(1-k,3);"
             "document.getElementById('n').textContent=PRE+(DA+(A-DA)*e).toFixed(D)+SUF};"
             "window.veditRender(0);</script>")
    return css, corpo


def _chapter_card(v: dict) -> tuple[str, str]:
    css = f"""
.cc{{position:absolute;inset:0;background:{v['sfondo']};display:grid;place-content:center;text-align:center;
 gap:1.2vh;animation:vela .45s ease-out both,velaFuori .4s ease-in calc({{{{durata}}}}s - .45s) forwards}}
@keyframes vela{{from{{clip-path:inset(0 100% 0 0)}}to{{clip-path:inset(0 0 0 0)}}}}
@keyframes velaFuori{{from{{clip-path:inset(0 0 0 0)}}to{{clip-path:inset(0 0 0 100%)}}}}
.cc small{{font-size:max(2vw,2vh);font-weight:800;letter-spacing:.35em;text-transform:uppercase;
 color:{v['testo_colore']};opacity:.75;animation:entra .5s ease-out .2s both}}
.cc h2{{margin:0;font-size:max(6vw,6vh);font-weight:900;letter-spacing:-.02em;color:{v['testo_colore']};
 animation:entra .55s ease-out .3s both}}"""
    etichetta = f"<small>{v['etichetta']} {v['numero']}</small>" if v["numero"] else ""
    return css, f'<div class="cc">{etichetta}<h2>{v["titolo"]}</h2></div>'


def _quote(v: dict) -> tuple[str, str]:
    css = f"""
.qt{{position:absolute;inset:0;display:grid;place-content:center;padding:0 12vw;text-align:center;
 background:linear-gradient(rgba(0,0,0,.45),rgba(0,0,0,.45));animation:entra .6s ease-out both}}
.qt p{{margin:0;font-family:Georgia,'Times New Roman',serif;font-style:italic;font-size:max(4vw,4vh);
 line-height:1.25;text-shadow:0 3px 20px rgba(0,0,0,.6)}}
.qt p:before{{content:'\\201C';display:block;font-size:max(9vw,9vh);line-height:.6;color:{v['colore']}}}
.qt span{{display:block;margin-top:3vh;font-size:max(2vw,2vh);font-weight:800;letter-spacing:.18em;
 text-transform:uppercase;color:{v['colore']};animation:entra .6s ease-out .5s both}}"""
    autore = f"<span>{v['autore']}</span>" if v["autore"] else ""
    return css, f'<div class="qt"><div><p>{v["testo"]}</p>{autore}</div></div>'


def _bar_chart(v: dict) -> tuple[str, str]:
    voci = v["voci"]
    massimo = max(x for _, x in voci) or 1.0
    righe = []
    for i, (nome, val) in enumerate(voci):
        larg = 100 * val / massimo
        righe.append(
            f'<div class="r" style="animation-delay:{.15 * i:.2f}s"><span>{_html.escape(nome)}</span>'
            f'<div class="b"><i style="width:{larg:.1f}%;animation-delay:{.15 * i + .2:.2f}s"></i></div>'
            f'<em>{val:g}</em></div>')
    css = f"""
.bc{{position:absolute;left:12vw;right:12vw;top:50%;transform:translateY(-50%);display:grid;gap:2.4vh;
 padding:4vh 3vw;border-radius:1.4vw;background:rgba(14,14,20,.78)}}
.bc h3{{margin:0 0 1vh;font-size:max(3vw,3vh);font-weight:800}}
.r{{display:grid;grid-template-columns:14vw 1fr 6vw;align-items:center;gap:1.4vw;
 font-size:max(2vw,2vh);font-weight:700;animation:entra .5s ease-out both}}
.r span{{text-align:right;opacity:.9}} .r em{{font-style:normal;font-variant-numeric:tabular-nums}}
.b{{height:3.2vh;border-radius:99px;background:rgba(255,255,255,.12);overflow:hidden}}
.b i{{display:block;height:100%;border-radius:99px;background:{v['colore']};transform-origin:left;
 animation:cresceBarra .8s cubic-bezier(.2,.8,.2,1) both}}
@keyframes cresceBarra{{from{{clip-path:inset(0 100% 0 0)}}to{{clip-path:inset(0 0 0 0)}}}}"""
    titolo = f"<h3>{v['titolo']}</h3>" if v["titolo"] else ""
    return css, f'<div class="bc">{titolo}{"".join(righe)}</div>'


def _kinetic_words(v: dict) -> tuple[str, str]:
    parole = v["parole"]
    passo = min(0.35, max(0.08, 0.7 * v["durata"] / max(1, len(parole))))
    pezzi = []
    for i, (p, forte) in enumerate(parole):
        classe = ' class="h"' if forte else ""
        pezzi.append(f'<span{classe} style="animation-delay:{i * passo:.2f}s">{p}</span>')
    css = f"""
.kw{{position:absolute;inset:0;display:flex;flex-wrap:wrap;justify-content:center;align-content:center;
 gap:1vh 1.6vw;padding:0 10vw;text-align:center}}
.kw span{{font-size:max(6.4vw,6.4vh);font-weight:900;letter-spacing:-.02em;text-transform:uppercase;
 text-shadow:0 4px 24px rgba(0,0,0,.6);animation:pop .4s cubic-bezier(.2,.9,.3,1.2) both}}
.kw .h{{color:{v['colore']}}}"""
    return css, f'<div class="kw">{"".join(pezzi)}</div>'


def _highlight_box(v: dict) -> tuple[str, str]:
    css = f"""
.hb{{position:absolute;left:{v['x']:g}%;top:{v['y']:g}%;width:{v['larghezza']:g}%;height:{v['altezza']:g}%;
 border:max(.45vw,4px) solid {v['colore']};border-radius:1vw;box-shadow:0 0 0 9999px rgba(0,0,0,.35),0 0 26px {v['colore']};
 animation:pop .45s ease-out both,batte 1.4s ease-in-out .5s infinite}}
@keyframes batte{{50%{{box-shadow:0 0 0 9999px rgba(0,0,0,.35),0 0 46px {v['colore']}}}}}
.hb span{{position:absolute;left:0;top:-5.2vh;padding:.5vh 1.2vw;border-radius:.6vw;background:{v['colore']};
 color:#10101a;font-size:max(1.8vw,1.8vh);font-weight:800;white-space:nowrap}}"""
    etichetta = f"<span>{v['etichetta']}</span>" if v["etichetta"] else ""
    return css, f'<div class="hb">{etichetta}</div>'


def _progress_bar(v: dict) -> tuple[str, str]:
    lato = "top:0" if v["posizione"] == "top" else "bottom:0"
    css = f"""
.pb{{position:absolute;left:0;right:0;{lato};height:max(1vh,7px);background:rgba(255,255,255,.18)}}
.pb i{{display:block;height:100%;background:{v['colore']};transform-origin:left;
 animation:cresce {{{{durata}}}}s linear both}}"""
    return css, '<div class="pb"><i></i></div>'


# nome -> (descrizione, durata, categoria, parametri, funzione)
# parametri: nome -> (tipo, default, descrizione, vincolo)
_C = "#ffd23b"
BLOCCHI: dict[str, dict] = {
    "lower_third": {
        "descrizione": "Name and role bar at the bottom left, with an accent line.",
        "categoria": "titles", "durata": 4.0, "fn": _lower_third,
        "parametri": {"nome": ("testo", "Name Surname", "main line"),
                      "ruolo": ("testo", "", "second line (optional)"),
                      "colore": ("colore", _C, "accent line")}},
    "title": {
        "descrizione": "Big centered title with an accent rule and optional subtitle.",
        "categoria": "titles", "durata": 3.0, "fn": _title,
        "parametri": {"titolo": ("testo", "Title", "the title"),
                      "sottotitolo": ("testo", "", "subtitle (optional)"),
                      "colore": ("colore", _C, "rule and subtitle")}},
    "caption_pill": {
        "descrizione": "Short caption in a rounded pill, at the bottom or the top.",
        "categoria": "text", "durata": 3.0, "fn": _caption_pill,
        "parametri": {"testo": ("testo", "Caption", "the caption"),
                      "posizione": ("scelta", "bottom", "bottom or top", ("bottom", "top")),
                      "sfondo": ("colore", "rgba(16,16,26,.82)", "pill background")}},
    "date_badge": {
        "descrizione": "Small tag in a top corner for years, dates, counters: 'YEAR 20', '+50 YEARS'.",
        "categoria": "text", "durata": 3.0, "fn": _date_badge,
        "parametri": {"testo": ("testo", "Year 1", "the tag"),
                      "posizione": ("scelta", "top_right", "top_right or top_left",
                                    ("top_right", "top_left")),
                      "colore": ("colore", "#e5383b", "top edge")}},
    "counter": {
        "descrizione": "Big number that counts from one value to another and holds.",
        "categoria": "data", "durata": 4.0, "fn": _counter,
        "parametri": {"da": ("numero", 0, "start value", (-1e9, 1e9)),
                      "a": ("numero", 100, "end value", (-1e9, 1e9)),
                      "decimali": ("numero", 0, "decimal places", (0, 4)),
                      "prefisso": ("testo", "", "before the number, e.g. $"),
                      "suffisso": ("testo", "", "after the number, e.g. %"),
                      "etichetta": ("testo", "", "what the number is"),
                      "colore": ("colore", _C, "label")}},
    "chapter_card": {
        "descrizione": "Full-frame chapter card on a flat color: it wipes in and out. Opaque: put it in the timeline between scenes.",
        "categoria": "titles", "durata": 2.5, "fn": _chapter_card,
        "parametri": {"titolo": ("testo", "Chapter title", "the title"),
                      "numero": ("testo", "", "chapter number (optional)"),
                      "etichetta": ("testo", "Chapter", "word before the number"),
                      "sfondo": ("colore", "#ffc06d", "card color"),
                      "testo_colore": ("colore", "#1b1b22", "text color")}},
    "quote": {
        "descrizione": "Serif quote on a darkened frame, with the author below.",
        "categoria": "text", "durata": 5.0, "fn": _quote,
        "parametri": {"testo": ("testo", "A memorable sentence.", "the quote", 400),
                      "autore": ("testo", "", "author (optional)"),
                      "colore": ("colore", _C, "quote mark and author")}},
    "bar_chart": {
        "descrizione": "Horizontal bar chart on a dark panel; bars grow one after the other.",
        "categoria": "data", "durata": 5.0, "fn": _bar_chart,
        "parametri": {"dati": ("elenco", "A:40, B:75, C:20", "label:value pairs, comma separated"),
                      "titolo": ("testo", "", "chart title (optional)"),
                      "colore": ("colore", _C, "bars")}},
    "kinetic_words": {
        "descrizione": "A sentence whose words pop in one after the other; *word* is highlighted.",
        "categoria": "text", "durata": 4.0, "fn": _kinetic_words,
        "parametri": {"testo": ("testo", "Make it *move*", "the sentence; wrap words in *stars*", 160),
                      "colore": ("colore", _C, "highlighted words")}},
    "highlight_box": {
        "descrizione": "Pulsing frame that darkens the rest to point at one area (x, y, size in % of the frame).",
        "categoria": "emphasis", "durata": 3.0, "fn": _highlight_box,
        "parametri": {"x": ("numero", 30, "left edge, % of the width", (0, 100)),
                      "y": ("numero", 30, "top edge, % of the height", (0, 100)),
                      "larghezza": ("numero", 40, "width, %", (1, 100)),
                      "altezza": ("numero", 30, "height, %", (1, 100)),
                      "etichetta": ("testo", "", "label above the frame (optional)"),
                      "colore": ("colore", _C, "frame")}},
    "progress_bar": {
        "descrizione": "Thin bar along an edge that fills over the whole clip.",
        "categoria": "emphasis", "durata": 10.0, "fn": _progress_bar,
        "parametri": {"posizione": ("scelta", "top", "top or bottom", ("top", "bottom")),
                      "colore": ("colore", _C, "the bar")}},
}

# parametri comuni a tutti: carattere e colore del testo
_COMUNI = {"font": ("font", _FONT, "font stack"),
           "testo_colore": ("colore", "#ffffff", "text color")}


def elenco() -> list[dict]:
    """I blocchi, compatti: id, a cosa servono, durata e parametri con i default."""
    out = []
    for nome, b in BLOCCHI.items():
        par = {k: {"default": p[1], "descrizione": p[2]} for k, p in b["parametri"].items()}
        out.append({"id": nome, "categoria": b["categoria"], "descrizione": b["descrizione"],
                    "durata": b["durata"], "parametri": par})
    return out


def _elenco_dati(s: str) -> list[tuple[str, float]]:
    voci = []
    for pezzo in str(s).split(","):
        if not pezzo.strip():
            continue
        nome, _, val = pezzo.rpartition(":")
        if not nome.strip():
            raise ValueError("dati must look like 'A:40, B:75': a label, a colon and a number")
        try:
            voci.append((nome.strip(), float(val)))
        except ValueError:
            raise ValueError(f"the value of {nome.strip()!r} is not a number: {val.strip()!r}") from None
    if not 1 <= len(voci) <= 10:
        raise ValueError("dati needs between 1 and 10 label:value pairs")
    if any(x < 0 for _, x in voci):
        raise ValueError("dati values cannot be negative")
    return voci


def _parole(s: str) -> list[tuple[str, bool]]:
    out = []
    for w in str(s).split():
        forte = w.startswith("*") and w.endswith("*") and len(w) > 2
        out.append((_html.escape(w.strip("*") if forte else w, quote=True), forte))
    if not out:
        raise ValueError("testo is empty")
    return out


def documento(nome: str, vars: dict | None, durata: float | None = None) -> tuple[str, float]:
    """(documento HTML, durata) del blocco ``nome`` con i parametri ``vars``.

    Un parametro sconosciuto o un valore sbagliato e' un errore con l'elenco di
    quelli ammessi: chi scrive e' spesso un modello e deve potersi correggere.
    """
    if nome not in BLOCCHI:
        raise ValueError(f"unknown block {nome!r}; allowed: {', '.join(BLOCCHI)}")
    b = BLOCCHI[nome]
    vars = dict(vars or {})
    parametri = {**_COMUNI, **b["parametri"]}
    ignoti = [k for k in vars if k not in parametri]
    if ignoti:
        raise ValueError(f"unknown parameters for {nome}: {', '.join(ignoti)}; "
                         f"allowed: {', '.join(parametri)}")
    d = float(durata) if durata is not None else float(b["durata"])
    if d <= 0:
        raise ValueError("the duration must be > 0")
    v: dict[str, Any] = {"durata": d}
    for k, p in parametri.items():
        tipo, default = p[0], p[1]
        val = vars.get(k, default)
        if tipo == "colore":
            v[k] = _colore(val, k)
        elif tipo == "testo":
            v[k] = _testo(val, k, p[3] if len(p) > 3 else 120)
        elif tipo == "numero":
            v[k] = _numero(val, k, *p[3])
        elif tipo == "scelta":
            v[k] = _scelta(val, k, p[3])
        elif tipo == "font":
            s = str(val)
            if re.search(r"[;{}<>]", s):
                raise ValueError("font cannot contain ; { } < >")
            v[k] = s
        elif tipo == "elenco":
            pass
    # forme che servono ai singoli blocchi
    if nome == "bar_chart":
        v["voci"] = _elenco_dati(vars.get("dati", parametri["dati"][1]))
    if nome == "kinetic_words":
        v["parole"] = _parole(vars.get("testo", parametri["testo"][1]))
    if nome == "counter":
        for k in ("prefisso", "suffisso"):   # dentro uno script: senza apici ne' barre
            v[k + "_js"] = re.sub(r"[^\w%$€£ .,:+\-]", "", str(vars.get(k, parametri[k][1])))
    css, corpo = b["fn"](v)
    if nome not in ("chapter_card", "progress_bar"):
        # l'uscita sta su un contenitore a parte: la regola ``animation`` del
        # blocco, sullo stesso elemento, la cancellerebbe
        corpo = f'<div class="out" style="position:absolute;inset:0">{corpo}</div>'
    doc = _BASE.replace("{{css}}", css).replace("{{corpo}}", corpo)
    for k in ("font", "testo_colore"):
        doc = doc.replace("{{" + k + "}}", v[k])
    doc = doc.replace("{{durata}}", f"{d:g}")
    return doc, d
