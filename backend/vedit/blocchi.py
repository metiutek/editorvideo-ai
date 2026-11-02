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



# --------------------------------------------------------------------------
# altri blocchi. Il CSS e' testo semplice con segnaposto §nome§ (le graffe del
# CSS non si mescolano bene con le f-string): ``_t`` li riempie.
# --------------------------------------------------------------------------


def _t(txt: str, v: dict, **extra) -> str:
    for k, val in {**v, **extra}.items():
        txt = txt.replace(f"§{k}§", str(val))
    return txt


def _lista(val: Any, nome: str, lo: int, hi: int, massimo: int = 70) -> list[str]:
    voci = [x.strip() for x in str(val).split(",") if x.strip()]
    if not lo <= len(voci) <= hi:
        raise ValueError(f"{nome} needs between {lo} and {hi} items separated by commas")
    return [_testo(x, nome, massimo) for x in voci]


def _end_card(v: dict) -> tuple[str, str]:
    css = _t("""
.ec{position:absolute;inset:0;display:grid;place-content:center;text-align:center;gap:2.4vh;
 background:radial-gradient(ellipse at center,rgba(0,0,0,.55),rgba(0,0,0,.8));animation:entra .6s ease-out both}
.ec h1{margin:0;font-size:max(6vw,6vh);font-weight:900;letter-spacing:-.02em;animation:pop .6s ease-out .15s both}
.ec span{justify-self:center;padding:1.2vh 2.4vw;border-radius:99px;background:§colore§;color:#10101a;
 font-size:max(2.4vw,2.4vh);font-weight:800;animation:pop .5s ease-out .5s both,batte 1.2s ease-in-out 1.1s infinite}
@keyframes batte{50%{transform:scale(1.06)}}""", v)
    pillola = f"<span>{v['handle']}</span>" if v["handle"] else ""
    return css, f'<div class="ec"><div><h1>{v["titolo"]}</h1></div>{pillola}</div>'


def _section_label(v: dict) -> tuple[str, str]:
    css = _t("""
.sl{position:absolute;left:4vw;top:5vh;display:flex;align-items:center;gap:.9vw;padding:.9vh 1.6vw;
 border-radius:99px;background:rgba(16,16,26,.82);font-size:max(1.7vw,1.7vh);font-weight:800;
 letter-spacing:.14em;text-transform:uppercase;animation:entra .45s ease-out both}
.sl i{width:1.1vh;height:1.1vh;min-width:8px;min-height:8px;border-radius:50%;background:§colore§}""", v)
    return css, f'<div class="sl"><i></i>{v["testo"]}</div>'


def _typewriter(v: dict) -> tuple[str, str]:
    n = max(1, len(_html.unescape(v["testo"])))
    t = min(n * 0.06, 0.7 * v["durata"])
    css = _t("""
.tw{position:absolute;inset:0;display:grid;place-content:center;padding:0 6vw}
.tw span{font-family:ui-monospace,'Cascadia Mono',Consolas,monospace;font-size:max(4vw,4vh);font-weight:700;
 white-space:nowrap;overflow:hidden;width:§n§ch;border-right:.5vw solid §colore§;
 text-shadow:0 3px 18px rgba(0,0,0,.6);animation:digita §t§s steps(§n§) both,cursore .7s step-end infinite}
@keyframes digita{from{width:0}to{width:§n§ch}}
@keyframes cursore{50%{border-color:transparent}}""", v, n=n, t=f"{t:.2f}")
    return css, f'<div class="tw"><span>{v["testo"]}</span></div>'


def _ticker(v: dict) -> tuple[str, str]:
    css = _t("""
.tk{position:absolute;left:0;right:0;bottom:6vh;height:7.4vh;display:flex;align-items:center;
 background:§sfondo§;overflow:hidden;box-shadow:0 -4px 20px rgba(0,0,0,.35)}
.tk b{flex:none;height:100%;display:grid;place-items:center;padding:0 2vw;background:§colore§;color:#10101a;
 font-size:max(2vw,2vh);font-weight:900;letter-spacing:.12em;text-transform:uppercase;z-index:1}
.tk div{flex:1;overflow:hidden}
.tk span{display:inline-block;white-space:nowrap;font-size:max(2.4vw,2.4vh);font-weight:700;
 animation:scorre §durata§s linear both}
@keyframes scorre{from{transform:translateX(70vw)}to{transform:translateX(-100%)}}""", v)
    return css, f'<div class="tk"><b>{v["etichetta"]}</b><div><span>{v["testo"]}</span></div></div>'


def _sticker_text(v: dict) -> tuple[str, str]:
    css = _t("""
.st{position:absolute;inset:0;display:grid;place-content:center}
.st span{padding:1.4vh 2.6vw;background:§colore§;color:#10101a;font-size:max(6vw,6vh);font-weight:900;
 letter-spacing:-.02em;text-transform:uppercase;border-radius:1vw;transform:rotate(§angolo§deg);
 box-shadow:0 8px 0 rgba(0,0,0,.35);animation:slam .4s cubic-bezier(.2,1.4,.4,1) both}
@keyframes slam{from{opacity:0;transform:rotate(§angolo§deg) scale(2.2)}to{opacity:1;transform:rotate(§angolo§deg) scale(1)}}""", v)
    return css, f'<div class="st"><span>{v["testo"]}</span></div>'


def _progress_ring(v: dict) -> tuple[str, str]:
    css = _t("""
.pr{position:absolute;inset:0;display:grid;place-content:center;justify-items:center;gap:1.4vh}
.pr div{position:relative;width:max(26vw,26vh);height:max(26vw,26vh)}
.pr svg{width:100%;height:100%;filter:drop-shadow(0 4px 18px rgba(0,0,0,.45))}
.pr circle{fill:none;stroke-width:9;stroke-linecap:round}
.pr .bg{stroke:rgba(255,255,255,.18)} .pr .fg{stroke:§colore§}
.pr b{position:absolute;inset:0;display:grid;place-items:center;font-size:max(6vw,6vh);font-weight:900;
 font-variant-numeric:tabular-nums;text-shadow:0 3px 14px rgba(0,0,0,.5)}
.pr span{font-size:max(2.4vw,2.4vh);font-weight:700;text-shadow:0 2px 12px rgba(0,0,0,.6)}""", v)
    corpo = ('<div class="pr"><div><svg viewBox="0 0 100 100"><circle class="bg" cx="50" cy="50" r="45"/>'
             '<circle class="fg" id="arc" cx="50" cy="50" r="45" pathLength="100" stroke-dasharray="0 100" '
             'transform="rotate(-90 50 50)"/></svg><b id="n">0%</b></div>'
             f'<span>{v["etichetta"]}</span></div>'
             "<script>"
             f"const V={v['valore']:g},T={v['durata'] * 0.7:.3f};"
             "window.veditRender=t=>{const k=Math.min(1,Math.max(0,t/T)),e=1-Math.pow(1-k,3),x=V*e;"
             "document.getElementById('arc').setAttribute('stroke-dasharray',x+' '+(100-x));"
             "document.getElementById('n').textContent=Math.round(x)+'%'};window.veditRender(0);</script>")
    return css, corpo


def _stat_card(v: dict) -> tuple[str, str]:
    css = _t("""
.sc{position:absolute;left:8vw;bottom:12vh;padding:3vh 3vw;border-radius:1.4vw;background:rgba(14,14,20,.86);
 border-left:1vh solid §colore§;box-shadow:0 10px 40px rgba(0,0,0,.45);animation:entra .55s cubic-bezier(.2,.8,.2,1) both}
.sc b{display:block;font-size:max(8vw,8vh);font-weight:900;letter-spacing:-.03em;line-height:1}
.sc span{display:block;margin-top:1vh;font-size:max(2.2vw,2.2vh);font-weight:700;opacity:.9}
.sc em{display:inline-block;margin-top:1.4vh;padding:.5vh 1.2vw;border-radius:99px;background:§colore§;
 color:#10101a;font-style:normal;font-size:max(1.9vw,1.9vh);font-weight:800;animation:pop .45s ease-out .5s both}""", v)
    delta = f"<em>{v['delta']}</em>" if v["delta"] else ""
    return css, f'<div class="sc"><b>{v["valore"]}</b><span>{v["etichetta"]}</span>{delta}</div>'


def _steps(v: dict) -> tuple[str, str]:
    voci = v["voci"]
    css = _t("""
.sp{position:absolute;left:6vw;right:6vw;top:50%;transform:translateY(-50%);display:flex;
 padding:4vh 2vw;border-radius:1.4vw;background:rgba(14,14,20,.8)}
.sp .s{flex:1;position:relative;display:grid;justify-items:center;gap:1.6vh;text-align:center;
 animation:entra .5s ease-out both}
.sp .s b{width:max(6vw,6vh);height:max(6vw,6vh);display:grid;place-items:center;border-radius:50%;
 background:§colore§;color:#10101a;font-size:max(3vw,3vh);font-weight:900;animation:pop .45s ease-out both;z-index:1}
.sp .s span{font-size:max(2.1vw,2.1vh);font-weight:700;padding:0 .6vw}
.sp .s:not(:last-child):after{content:'';position:absolute;top:max(3vw,3vh);left:50%;width:100%;height:.6vh;
 background:rgba(255,255,255,.35);transform-origin:left;transform:scaleX(0);animation:cresce .5s ease-out forwards}""", v)
    pezzi = []
    for i, voce in enumerate(voci):
        ritardo = 0.5 * i
        pezzi.append(f'<div class="s" style="animation-delay:{ritardo:.2f}s"><b style="animation-delay:'
                     f'{ritardo:.2f}s">{i + 1}</b><span>{voce}</span>'
                     f'<style>.sp .s:nth-child({i + 1}):after{{animation-delay:{ritardo + .3:.2f}s}}</style></div>')
    return css, f'<div class="sp">{"".join(pezzi)}</div>'


def _comparison(v: dict) -> tuple[str, str]:
    css = _t("""
.cm{position:absolute;left:7vw;right:7vw;top:50%;transform:translateY(-50%);display:grid;
 grid-template-columns:1fr auto 1fr;align-items:stretch;gap:2vw}
.cm .p{padding:4vh 2.4vw;border-radius:1.4vw;background:rgba(14,14,20,.84);text-align:center;
 animation:entra .55s ease-out both}
.cm .p:last-child{animation-delay:.2s}
.cm h3{margin:0 0 1.6vh;font-size:max(3vw,3vh);font-weight:900;color:§colore§}
.cm p{margin:0;font-size:max(2.2vw,2.2vh);font-weight:600;line-height:1.35}
.cm .vs{align-self:center;width:max(6vw,6vh);height:max(6vw,6vh);display:grid;place-items:center;
 border-radius:50%;background:§colore§;color:#10101a;font-size:max(2.4vw,2.4vh);font-weight:900;
 animation:pop .45s ease-out .35s both}""", v)
    corpo = (f'<div class="cm"><div class="p"><h3>{v["sinistra"]}</h3><p>{v["sinistra_testo"]}</p></div>'
             f'<div class="vs">VS</div><div class="p"><h3>{v["destra"]}</h3><p>{v["destra_testo"]}</p></div></div>')
    return css, corpo


def _list_reveal(v: dict) -> tuple[str, str]:
    css = _t("""
.lr{position:absolute;left:7vw;top:50%;transform:translateY(-50%);max-width:52vw;padding:4vh 3vw;
 border-radius:1.4vw;background:rgba(14,14,20,.84)}
.lr h3{margin:0 0 2.4vh;font-size:max(3.4vw,3.4vh);font-weight:900;animation:entra .5s ease-out both}
.lr ul{list-style:none;margin:0;padding:0;display:grid;gap:1.8vh}
.lr li{display:flex;align-items:center;gap:1.2vw;font-size:max(2.4vw,2.4vh);font-weight:700;animation:entra .5s ease-out both}
.lr li:before{content:'';flex:none;width:1.4vh;height:1.4vh;min-width:9px;min-height:9px;border-radius:50%;background:§colore§}""", v)
    voci = "".join(f'<li style="animation-delay:{.35 * (i + 1):.2f}s">{x}</li>' for i, x in enumerate(v["voci"]))
    titolo = f"<h3>{v['titolo']}</h3>" if v["titolo"] else ""
    return css, f'<div class="lr">{titolo}<ul>{voci}</ul></div>'


def _arrow_pointer(v: dict) -> tuple[str, str]:
    css = _t("""
.ap{position:absolute;left:§x§%;top:§y§%;transform:rotate(§angolo§deg);transform-origin:0 50%}
.ap svg{position:absolute;right:0;top:-5vh;width:max(13vw,13vh);height:10vh;overflow:visible;
 filter:drop-shadow(0 4px 12px rgba(0,0,0,.5));animation:pop .45s ease-out both,vai 1s ease-in-out .5s infinite}
@keyframes vai{50%{transform:translateX(1.6vw)}}
.ap em{position:absolute;right:max(13vw,13vh);top:-3.2vh;transform:rotate(calc(-1 * §angolo§deg));padding:.6vh 1.2vw;
 border-radius:.7vw;background:§colore§;color:#10101a;font-style:normal;font-size:max(1.9vw,1.9vh);font-weight:800;white-space:nowrap}""", v)
    freccia = (f'<svg viewBox="0 0 130 100"><path d="M5 50 H105 M78 18 L108 50 L78 82" fill="none" stroke="{v["colore"]}" '
               'stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    etichetta = f"<em>{v['etichetta']}</em>" if v["etichetta"] else ""
    return css, f'<div class="ap">{freccia}{etichetta}</div>'


def _circle_highlight(v: dict) -> tuple[str, str]:
    css = _t("""
@property --a{syntax:'<angle>';initial-value:0deg;inherits:false}
.ch{position:absolute;left:§x§%;top:§y§%;width:§larghezza§%;height:§altezza§%;box-sizing:border-box;
 border:max(.55vw,5px) solid §colore§;border-radius:50%;filter:drop-shadow(0 0 10px rgba(0,0,0,.5));
 -webkit-mask:conic-gradient(#000 var(--a),transparent 0);mask:conic-gradient(#000 var(--a),transparent 0);
 animation:giro .8s ease-out .15s both}
@keyframes giro{from{--a:0deg}to{--a:360deg}}""", v)
    return css, '<div class="ch"></div>'


def _color_wipe(v: dict) -> tuple[str, str]:
    asse = "X" if v["direzione"] == "horizontal" else "Y"
    css = _t("""
.cw{position:absolute;inset:0;background:§colore§;animation:cw §durata§s cubic-bezier(.7,0,.3,1) both}
@keyframes cw{0%{transform:translate§asse§(-101%)}45%{transform:none}55%{transform:none}100%{transform:translate§asse§(101%)}}""",
             v, asse=asse)
    return css, '<div class="cw"></div>'


def _flash_frame(v: dict) -> tuple[str, str]:
    css = _t("""
.fl{position:absolute;inset:0;background:§colore§;animation:fl §durata§s ease-out both}
@keyframes fl{0%{opacity:0}12%{opacity:1}100%{opacity:0}}""", v)
    return css, '<div class="fl"></div>'


def _letterbox(v: dict) -> tuple[str, str]:
    css = _t("""
.lb i{position:absolute;left:0;right:0;height:§altezza§vh;background:#000;animation:barra .7s cubic-bezier(.2,.8,.2,1) both}
.lb i:first-child{top:0;transform-origin:top}.lb i:last-child{bottom:0;transform-origin:bottom}
@keyframes barra{from{transform:scaleY(0)}to{transform:scaleY(1)}}""", v)
    return css, '<div class="lb"><i></i><i></i></div>'


def _vignette(v: dict) -> tuple[str, str]:
    css = _t("""
.vg{position:absolute;inset:0;background:radial-gradient(ellipse at center,transparent 42%,rgba(0,0,0,§forza§) 100%);
 animation:aparsi 1s ease-out both}
@keyframes aparsi{from{opacity:0}to{opacity:1}}""", v)
    return css, '<div class="vg"></div>'


def _speech_bubble(v: dict) -> tuple[str, str]:
    css = _t("""
.sb{position:absolute;left:§x§%;top:§y§%;max-width:38vw;padding:2vh 2vw;border-radius:1.6vw;background:#fff;
 color:#1b1b22;font-size:max(2.4vw,2.4vh);font-weight:800;line-height:1.25;box-shadow:0 8px 30px rgba(0,0,0,.4);
 animation:pop .5s ease-out both}
.sb:after{content:'';position:absolute;left:2.4vw;bottom:-2.6vh;border:1.6vh solid transparent;border-top-color:#fff;
 border-bottom:0;border-left-width:1.4vh}
.sb i{position:absolute;right:-1vw;top:-1vh;width:2.2vh;height:2.2vh;border-radius:50%;background:§colore§}""", v)
    return css, f'<div class="sb"><i></i>{v["testo"]}</div>'


def _handle_tag(v: dict) -> tuple[str, str]:
    css = _t("""
.ht{position:absolute;right:3vw;bottom:4vh;display:flex;align-items:center;gap:.8vw;padding:.8vh 1.4vw;
 border-radius:99px;background:rgba(16,16,26,.72);font-size:max(1.8vw,1.8vh);font-weight:700;
 animation:entra .5s ease-out both}
.ht i{width:1.6vh;height:1.6vh;min-width:10px;min-height:10px;border-radius:50%;background:§colore§}""", v)
    return css, f'<div class="ht"><i></i>{v["handle"]}</div>'


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


_ALTRI: dict[str, dict] = {
    "end_card": {
        "descrizione": "Closing screen: darkened frame, big title and a pulsing @handle pill.",
        "categoria": "titles", "durata": 5.0, "fn": _end_card,
        "parametri": {"titolo": ("testo", "Thanks for watching", "the title"),
                      "handle": ("testo", "@yourchannel", "channel or call to action (optional)"),
                      "colore": ("colore", _C, "the pill")}},
    "section_label": {
        "descrizione": "Small tag in the top-left corner naming the part: 'Chapter 1 - The hook'.",
        "categoria": "text", "durata": 3.0, "fn": _section_label,
        "parametri": {"testo": ("testo", "Chapter 1", "the label"),
                      "colore": ("colore", _C, "the dot")}},
    "typewriter": {
        "descrizione": "One line typed out letter by letter, with a blinking cursor (monospace).",
        "categoria": "text", "durata": 4.0, "fn": _typewriter,
        "parametri": {"testo": ("testo", "It starts with one line.", "the line", 60),
                      "colore": ("colore", _C, "the cursor")}},
    "ticker": {
        "descrizione": "News-style bar at the bottom with a label and text scrolling across it.",
        "categoria": "text", "durata": 8.0, "fn": _ticker,
        "parametri": {"testo": ("testo", "Breaking: something worth reading is scrolling by", "the text", 300),
                      "etichetta": ("testo", "News", "the label box"),
                      "sfondo": ("colore", "rgba(16,16,26,.9)", "bar background"),
                      "colore": ("colore", "#e5383b", "label box")}},
    "sticker_text": {
        "descrizione": "Loud rotated label that slams in the middle of the frame ('WAIT FOR IT').",
        "categoria": "text", "durata": 2.0, "fn": _sticker_text,
        "parametri": {"testo": ("testo", "Wait for it", "the label", 40),
                      "angolo": ("numero", -6, "rotation in degrees", (-30, 30)),
                      "colore": ("colore", _C, "label background")}},
    "speech_bubble": {
        "descrizione": "White speech bubble placed at x, y (% of the frame), popping in.",
        "categoria": "text", "durata": 3.0, "fn": _speech_bubble,
        "parametri": {"testo": ("testo", "Say something", "the words", 120),
                      "x": ("numero", 55, "left edge, % of the width", (0, 90)),
                      "y": ("numero", 25, "top edge, % of the height", (0, 90)),
                      "colore": ("colore", _C, "the dot on the corner")}},
    "handle_tag": {
        "descrizione": "Small @handle watermark in the bottom-right corner.",
        "categoria": "text", "durata": 6.0, "fn": _handle_tag,
        "parametri": {"handle": ("testo", "@yourchannel", "the handle"),
                      "colore": ("colore", _C, "the dot")}},
    "progress_ring": {
        "descrizione": "Ring that fills to a percentage while the number counts up.",
        "categoria": "data", "durata": 4.0, "fn": _progress_ring,
        "parametri": {"valore": ("numero", 75, "percentage, 0-100", (0, 100)),
                      "etichetta": ("testo", "", "what it measures"),
                      "colore": ("colore", _C, "the ring")}},
    "stat_card": {
        "descrizione": "Big figure on a card with a label and an optional delta chip ('+12%').",
        "categoria": "data", "durata": 4.0, "fn": _stat_card,
        "parametri": {"valore": ("testo", "1.2M", "the figure", 14),
                      "etichetta": ("testo", "views this month", "what it is"),
                      "delta": ("testo", "", "change chip (optional)", 14),
                      "colore": ("colore", _C, "accent")}},
    "steps": {
        "descrizione": "Numbered steps joined by a line, revealed one after the other (2-6).",
        "categoria": "data", "durata": 5.0, "fn": _steps,
        "parametri": {"voci": ("lista", "Plan, Shoot, Edit, Publish", "steps separated by commas", (2, 6)),
                      "colore": ("colore", _C, "numbers")}},
    "comparison": {
        "descrizione": "Two panels side by side joined by a VS badge.",
        "categoria": "data", "durata": 5.0, "fn": _comparison,
        "parametri": {"sinistra": ("testo", "Before", "left heading", 30),
                      "sinistra_testo": ("testo", "How it was", "left text", 90),
                      "destra": ("testo", "After", "right heading", 30),
                      "destra_testo": ("testo", "How it is now", "right text", 90),
                      "colore": ("colore", _C, "headings and badge")}},
    "list_reveal": {
        "descrizione": "Panel with a title and bullet points appearing one by one (1-7).",
        "categoria": "data", "durata": 5.0, "fn": _list_reveal,
        "parametri": {"titolo": ("testo", "", "title (optional)"),
                      "voci": ("lista", "First point, Second point, Third point", "bullets separated by commas",
                               (1, 7)),
                      "colore": ("colore", _C, "bullets")}},
    "arrow_pointer": {
        "descrizione": "Bobbing arrow whose tip is at x, y (% of the frame); angle = where it points.",
        "categoria": "emphasis", "durata": 3.0, "fn": _arrow_pointer,
        "parametri": {"x": ("numero", 60, "tip, % of the width", (0, 100)),
                      "y": ("numero", 50, "tip, % of the height", (0, 100)),
                      "angolo": ("numero", 0, "0 points right, 90 down, 180 left, 270 up", (-360, 360)),
                      "etichetta": ("testo", "", "label next to the arrow (optional)", 40),
                      "colore": ("colore", _C, "the arrow")}},
    "circle_highlight": {
        "descrizione": "Ellipse drawn around an area, like circling it with a pen (x, y, size in %).",
        "categoria": "emphasis", "durata": 3.0, "fn": _circle_highlight,
        "parametri": {"x": ("numero", 35, "left edge, % of the width", (0, 100)),
                      "y": ("numero", 30, "top edge, % of the height", (0, 100)),
                      "larghezza": ("numero", 30, "width, %", (1, 100)),
                      "altezza": ("numero", 35, "height, %", (1, 100)),
                      "colore": ("colore", "#e5383b", "the line")}},
    "color_wipe": {
        "descrizione": "Transition: a flat color sweeps across the frame and out again. The cut between scenes goes at the middle of the clip.",
        "categoria": "transitions", "durata": 1.2, "fn": _color_wipe,
        "parametri": {"colore": ("colore", "#ffc06d", "the sweep"),
                      "direzione": ("scelta", "horizontal", "horizontal or vertical",
                                    ("horizontal", "vertical"))}},
    "flash_frame": {
        "descrizione": "Transition: a short flash of color, for impact or a hard beat.",
        "categoria": "transitions", "durata": 0.4, "fn": _flash_frame,
        "parametri": {"colore": ("colore", "#ffffff", "the flash")}},
    "letterbox": {
        "descrizione": "Cinema bars sliding in at the top and bottom.",
        "categoria": "style", "durata": 6.0, "fn": _letterbox,
        "parametri": {"altezza": ("numero", 11, "height of each bar, % of the frame", (2, 25))}},
    "vignette": {
        "descrizione": "Soft dark edges that fade in, to pull the eye to the center.",
        "categoria": "style", "durata": 6.0, "fn": _vignette,
        "parametri": {"forza": ("numero", 0.55, "how dark the edges get, 0-1", (0, 1))}},
}
BLOCCHI.update(_ALTRI)
# altri 23 blocchi, in un file a parte (importa questo modulo: non va importato prima)
from .blocchi_piu import PIU as _PIU  # noqa: E402

BLOCCHI.update(_PIU)

# parametri comuni a tutti: carattere e colore del testo
_COMUNI = {"font": ("font", _FONT, "font stack"),
           "testo_colore": ("colore", "#ffffff", "text color")}


# da quanto la grafica e' a regime (secondi dall'inizio della clip): e' li' che si
# fotografa per la galleria e per i test. Gli altri: poco dopo l'entrata.
_VETRINA = {"counter": 3.0, "progress_ring": 3.0, "bar_chart": 3.5, "ticker": 3.0, "steps": 3.5,
            "list_reveal": 3.5, "typewriter": 2.6, "kinetic_words": 3.0, "comparison": 1.6,
            "color_wipe": 0.55, "flash_frame": 0.1, "letterbox": 1.2, "vignette": 1.5,
            "chapter_card": 1.2, "quote": 2.5, "end_card": 2.0, "sticker_text": 1.0,
            "iris_wipe": 0.55, "blinds_wipe": 0.55, "countdown": 3.0, "word_cycle": 3.4,
            "chat_messages": 3.5, "marker_highlight": 2.8, "subscribe_button": 3.0,
            "donut_chart": 3.0, "line_chart": 3.5, "timeline": 4.5, "rating_stars": 2.5,
            "price_tag": 2.5, "checklist": 3.5, "film_grain": 1.0, "light_leak": 1.2,
            "scanlines": 1.0, "mask_reveal_title": 1.8, "logo_shine": 2.5}


def istante_vetrina(nome: str) -> float:
    """Il secondo della clip in cui il blocco si vede meglio."""
    if nome not in BLOCCHI:
        raise ValueError(f"unknown block {nome!r}; allowed: {', '.join(BLOCCHI)}")
    return _VETRINA.get(nome, max(0.8, min(1.5, BLOCCHI[nome]["durata"] * 0.45)))


def elenco() -> list[dict]:
    """I blocchi, compatti: id, a cosa servono, durata e parametri con i default."""
    out = []
    for nome, b in BLOCCHI.items():
        par = {}
        for k, p in b["parametri"].items():
            voce = {"default": p[1], "descrizione": p[2], "tipo": p[0]}
            if p[0] == "scelta":
                voce["scelte"] = list(p[3])
            if p[0] == "numero":
                voce["min"], voce["max"] = p[3]
            par[k] = voce
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


# hanno la loro entrata e uscita (coprono il fotogramma o durano quanto la clip)
_SENZA_USCITA = ("chapter_card", "progress_bar", "color_wipe", "flash_frame", "iris_wipe",
                 "blinds_wipe")


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
        elif tipo == "lista":
            v[k] = _lista(val, k, *p[3])
        elif tipo == "elenco":
            pass
    # forme che servono ai singoli blocchi
    if "dati" in parametri:
        v["voci"] = _elenco_dati(vars.get("dati", parametri["dati"][1]))
    if nome in ("kinetic_words", "marker_highlight"):
        v["parole"] = _parole(vars.get("testo", parametri["testo"][1]))
    if nome == "counter":
        for k in ("prefisso", "suffisso"):   # dentro uno script: senza apici ne' barre
            v[k + "_js"] = re.sub(r"[^\w%$€£ .,:+\-]", "", str(vars.get(k, parametri[k][1])))
    css, corpo = b["fn"](v)
    if nome not in _SENZA_USCITA:
        # l'uscita sta su un contenitore a parte: la regola ``animation`` del
        # blocco, sullo stesso elemento, la cancellerebbe
        corpo = f'<div class="out" style="position:absolute;inset:0">{corpo}</div>'
    doc = _BASE.replace("{{css}}", css).replace("{{corpo}}", corpo)
    for k in ("font", "testo_colore"):
        doc = doc.replace("{{" + k + "}}", v[k])
    doc = doc.replace("{{durata}}", f"{d:g}")
    return doc, d
