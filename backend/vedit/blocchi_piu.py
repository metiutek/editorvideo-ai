"""Altri 23 blocchi grafici (si sommano a quelli di ``blocchi.py``).

Si importa solo da ``blocchi``, che alla fine del file li registra: i pezzi comuni
(``_t``, ``_lista``, la validazione) stanno di la'. Le regole sono le stesse: misure
in ``vw``/``vh``, tutto animato in CSS dal tempo della clip, l'uscita su un
contenitore esterno messo dal sistema. Niente ``random`` ne' orologio: la grana e il
glitch sono animazioni a passi, quindi anteprima e render coincidono.
"""

from __future__ import annotations

from . import blocchi as B

_C = "#ffd23b"
_PALETTE = ("#ffd23b", "#4cc9f0", "#f72585", "#80ed99", "#b388ff", "#ff9f1c")


# --------------------------------------------------------------------------
# titoli
# --------------------------------------------------------------------------


def _mask_reveal_title(v: dict) -> tuple[str, str]:
    css = B._t("""
.mr{position:absolute;inset:0;display:grid;place-content:center;text-align:center;gap:1vh}
.mr div{overflow:hidden;padding:1vh 2vw}
.mr h1{margin:0;font-size:max(7.4vw,7.4vh);font-weight:900;letter-spacing:-.03em;line-height:1.05;
 animation:sale .8s cubic-bezier(.16,1,.3,1) both}
.mr p{margin:0;font-size:max(2.3vw,2.3vh);font-weight:800;letter-spacing:.22em;text-transform:uppercase;
 color:§colore§;animation:sale .8s cubic-bezier(.16,1,.3,1) .22s both}
@keyframes sale{from{transform:translateY(115%)}to{transform:none}}""", v)
    sotto = f"<div><p>{v['sottotitolo']}</p></div>" if v["sottotitolo"] else ""
    return css, f'<div class="mr"><div><h1>{v["titolo"]}</h1></div>{sotto}</div>'


def _glitch_title(v: dict) -> tuple[str, str]:
    css = B._t("""
.gl{position:absolute;inset:0;display:grid;place-content:center;text-align:center}
.gl h1{position:relative;margin:0;font-size:max(8vw,8vh);font-weight:900;letter-spacing:-.02em;
 text-transform:uppercase;text-shadow:0 4px 30px rgba(0,0,0,.5);animation:vibra .9s steps(1) both}
.gl h1:before,.gl h1:after{content:attr(data-t);position:absolute;inset:0;mix-blend-mode:screen}
.gl h1:before{color:§colore§;animation:ga .9s steps(1) both}
.gl h1:after{color:#00e5ff;animation:gb .9s steps(1) both}
@keyframes vibra{0%{opacity:0}8%{opacity:1}14%{opacity:.2}20%{opacity:1}34%{opacity:.6}40%,100%{opacity:1}}
@keyframes ga{0%{transform:translate(-1.4vw,.5vh);clip-path:inset(8% 0 62% 0)}14%{transform:translate(1.1vw,-.3vh);clip-path:inset(55% 0 14% 0)}
 28%{transform:translate(-.8vw,.2vh);clip-path:inset(30% 0 40% 0)}42%{transform:translate(1.6vw,0);clip-path:inset(70% 0 5% 0)}
 56%{transform:translate(-.4vw,-.4vh);clip-path:inset(0 0 80% 0)}70%,100%{transform:none;clip-path:inset(0);opacity:0}}
@keyframes gb{0%{transform:translate(1.4vw,-.4vh);clip-path:inset(60% 0 10% 0)}18%{transform:translate(-1.2vw,.4vh);clip-path:inset(12% 0 55% 0)}
 36%{transform:translate(.9vw,0);clip-path:inset(40% 0 30% 0)}50%{transform:translate(-1.5vw,.3vh);clip-path:inset(5% 0 75% 0)}
 64%{transform:translate(.5vw,-.2vh);clip-path:inset(80% 0 0 0)}78%,100%{transform:none;clip-path:inset(0);opacity:0}}""", v)
    return css, f'<div class="gl"><h1 data-t="{v["titolo"]}">{v["titolo"]}</h1></div>'


def _word_cycle(v: dict) -> tuple[str, str]:
    voci = v["voci"]
    passo = round(min(1.0, 0.7 * v["durata"] / len(voci)), 2)
    pezzi = []
    for i, w in enumerate(voci):
        ultima = i == len(voci) - 1
        anim = f"rulloU .45s cubic-bezier(.16,1,.3,1) {i * passo:.2f}s both" if ultima \
            else f"rullo {passo + .25:.2f}s cubic-bezier(.16,1,.3,1) {i * passo:.2f}s both"
        pezzi.append(f'<span style="animation:{anim}">{w}</span>')
    css = B._t("""
.wc{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:1.6vw;
 font-size:max(6vw,6vh);font-weight:900;letter-spacing:-.02em;text-shadow:0 4px 24px rgba(0,0,0,.55)}
.wc .r{display:grid;overflow:hidden;padding:0 .2vw}
.wc .r span{grid-area:1/1;color:§colore§;opacity:0;white-space:nowrap}
@keyframes rullo{0%{opacity:0;transform:translateY(70%)}18%{opacity:1;transform:none}78%{opacity:1;transform:none}100%{opacity:0;transform:translateY(-70%)}}
@keyframes rulloU{0%{opacity:0;transform:translateY(70%)}100%{opacity:1;transform:none}}""", v)
    return css, f'<div class="wc"><div>{v["prefisso"]}</div><div class="r">{"".join(pezzi)}</div></div>'


def _countdown(v: dict) -> tuple[str, str]:
    voci = v["voci"]
    passo = round(min(1.0, 0.8 * v["durata"] / len(voci)), 2)
    pezzi = []
    for i, w in enumerate(voci):
        anim = f"conta .5s cubic-bezier(.2,.9,.3,1.2) {i * passo:.2f}s both" if i == len(voci) - 1 \
            else f"contaEsce {passo:.2f}s ease-out {i * passo:.2f}s both"
        pezzi.append(f'<b style="animation:{anim}">{w}</b>')
    css = B._t("""
.cd{position:absolute;inset:0;display:grid;place-items:center}
.cd b{grid-area:1/1;font-size:max(20vw,20vh);font-weight:900;letter-spacing:-.04em;opacity:0;color:§colore§;
 text-shadow:0 6px 40px rgba(0,0,0,.6)}
@keyframes conta{from{opacity:0;transform:scale(1.7)}to{opacity:1;transform:scale(1)}}
@keyframes contaEsce{0%{opacity:0;transform:scale(1.7)}18%{opacity:1;transform:scale(1)}80%{opacity:1;transform:scale(.96)}100%{opacity:0;transform:scale(.7)}}""", v)
    return css, f'<div class="cd">{"".join(pezzi)}</div>'


def _logo_shine(v: dict) -> tuple[str, str]:
    css = B._t("""
.ls{position:absolute;inset:0;display:grid;place-content:center;text-align:center;gap:2vh}
.ls h1{margin:0;font-size:max(9vw,9vh);font-weight:900;letter-spacing:-.03em;color:transparent;
 background:linear-gradient(110deg,§testo_colore§ 0 36%,§colore§ 50%,§testo_colore§ 64% 100%) 100% 0/260% 100%;
 -webkit-background-clip:text;background-clip:text;filter:drop-shadow(0 4px 24px rgba(0,0,0,.5));
 animation:pop .7s ease-out both,brilla 1.5s ease-in-out .55s both}
@keyframes brilla{from{background-position:100% 0}to{background-position:0 0}}
.ls hr{width:14vw;height:.6vh;border:0;border-radius:99px;margin:0 auto;background:§colore§;
 transform-origin:center;animation:cresce .7s ease-out .3s both}
.ls p{margin:0;font-size:max(2.2vw,2.2vh);font-weight:700;letter-spacing:.3em;text-transform:uppercase;opacity:.9;
 animation:entra .6s ease-out .8s both}""", v)
    sotto = f"<p>{v['sottotitolo']}</p>" if v["sottotitolo"] else ""
    return css, f'<div class="ls"><h1>{v["testo"]}</h1><hr>{sotto}</div>'


# --------------------------------------------------------------------------
# testi
# --------------------------------------------------------------------------


def _chat_messages(v: dict) -> tuple[str, str]:
    righe = []
    for i, m in enumerate(v["voci"]):
        lato = "me" if i % 2 else "lei"
        righe.append(f'<div class="m {lato}" style="animation-delay:{.7 * i:.2f}s">{m}</div>')
    css = B._t("""
.cm2{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(58vw,92vw);display:grid;gap:1.6vh}
.m{max-width:80%;padding:1.5vh 1.8vw;border-radius:2vw;font-size:max(2.2vw,2.2vh);font-weight:600;line-height:1.3;
 box-shadow:0 6px 22px rgba(0,0,0,.35);animation:pop .4s cubic-bezier(.2,.9,.3,1.2) both}
.m.lei{justify-self:start;background:#e9e9ef;color:#1b1b22;border-bottom-left-radius:.5vw;transform-origin:left bottom}
.m.me{justify-self:end;background:§colore§;color:#fff;border-bottom-right-radius:.5vw;transform-origin:right bottom}""", v)
    return css, f'<div class="cm2">{"".join(righe)}</div>'


def _notification_toast(v: dict) -> tuple[str, str]:
    css = B._t("""
.nt{position:absolute;left:0;right:0;top:5vh;display:flex;justify-content:center}
.nt div{display:grid;grid-template-columns:auto 1fr;gap:1.4vw;align-items:center;width:min(50vw,90vw);
 padding:1.8vh 1.8vw;border-radius:1.6vw;background:rgba(248,248,252,.96);color:#1b1b22;
 box-shadow:0 14px 44px rgba(0,0,0,.45);animation:cala .6s cubic-bezier(.2,.9,.3,1.1) both}
.nt i{width:max(5vw,5vh);height:max(5vw,5vh);border-radius:1.1vw;background:§colore§;display:block}
.nt small{display:block;font-size:max(1.4vw,1.4vh);font-weight:800;letter-spacing:.12em;text-transform:uppercase;opacity:.55}
.nt b{display:block;font-size:max(2.2vw,2.2vh);font-weight:800;margin-top:.3vh}
.nt span{display:block;font-size:max(1.8vw,1.8vh);font-weight:500;margin-top:.2vh;opacity:.8}
@keyframes cala{from{opacity:0;transform:translateY(-16vh)}to{opacity:1;transform:none}}""", v)
    corpo = (f'<div class="nt"><div><i></i><section><small>{v["app"]}</small><b>{v["titolo"]}</b>'
             f'<span>{v["testo"]}</span></section></div></div>')
    return css, corpo


def _marker_highlight(v: dict) -> tuple[str, str]:
    k = 0
    pezzi = []
    for p, forte in v["parole"]:
        if forte:
            pezzi.append(f'<mark style="animation-delay:{.5 + .45 * k:.2f}s">{p}</mark>')
            k += 1
        else:
            pezzi.append(f"<span>{p}</span>")
    css = B._t("""
.mh{position:absolute;inset:0;display:flex;flex-wrap:wrap;justify-content:center;align-content:center;
 gap:.8vh 1.2vw;padding:0 10vw;text-align:center;font-size:max(5.4vw,5.4vh);font-weight:900;letter-spacing:-.02em;
 line-height:1.15;text-shadow:0 3px 20px rgba(0,0,0,.55);animation:entra .5s ease-out both}
.mh mark{color:#10101a;padding:0 .8vw;text-shadow:none;border-radius:.4vw;
 background:linear-gradient(§colore§,§colore§) no-repeat 0 60%/0% 78%;animation:marca .6s cubic-bezier(.6,0,.2,1) forwards}
@keyframes marca{to{background-size:100% 78%}}""", v)
    return css, f'<div class="mh">{" ".join(pezzi)}</div>'


def _location_pin(v: dict) -> tuple[str, str]:
    css = B._t("""
.lp{position:absolute;left:§x§%;top:§y§%;width:0;height:0}
.lp svg{position:absolute;left:-2.6vw;top:-7.4vw;width:5.2vw;min-width:34px;height:7.4vw;min-height:48px;
 overflow:visible;filter:drop-shadow(0 6px 10px rgba(0,0,0,.5));transform-origin:50% 100%;animation:cade .7s cubic-bezier(.3,1.5,.5,1) both}
.lp .o{position:absolute;left:-3vw;top:-.8vh;width:6vw;height:1.6vh;border-radius:50%;border:max(.25vw,2px) solid §colore§;
 opacity:0;animation:onda 1.4s ease-out .5s infinite}
.lp div{position:absolute;left:3.6vw;top:-6.4vw;padding:.9vh 1.6vw;border-radius:.9vw;background:rgba(16,16,26,.9);
 white-space:nowrap;animation:entra .5s ease-out .45s both}
.lp b{display:block;font-size:max(2.4vw,2.4vh);font-weight:800}
.lp span{display:block;font-size:max(1.6vw,1.6vh);font-weight:600;opacity:.75}
@keyframes cade{0%{opacity:0;transform:translateY(-14vh)}60%{opacity:1;transform:translateY(0) scale(1,.86)}100%{opacity:1;transform:none}}
@keyframes onda{0%{opacity:.9;transform:scale(.3)}100%{opacity:0;transform:scale(1.5)}}""", v)
    pin = (f'<svg viewBox="0 0 52 74"><path d="M26 72C26 72 3 44 3 26a23 23 0 0 1 46 0C49 44 26 72 26 72Z" fill="{v["colore"]}"/>'
           '<circle cx="26" cy="26" r="9" fill="#fff"/></svg>')
    dettaglio = f"<span>{v['dettaglio']}</span>" if v["dettaglio"] else ""
    return css, f'<div class="lp"><i class="o"></i>{pin}<div><b>{v["luogo"]}</b>{dettaglio}</div></div>'


def _subscribe_button(v: dict) -> tuple[str, str]:
    css = B._t("""
.sbt{position:absolute;left:0;right:0;bottom:12vh;display:flex;justify-content:center;align-items:center;gap:1.6vw}
.sbt .bt{position:relative;display:grid;padding:1.5vh 3vw;border-radius:.9vw;background:§colore§;color:#fff;
 font-size:max(3vw,3vh);font-weight:900;letter-spacing:.06em;text-transform:uppercase;box-shadow:0 8px 28px rgba(0,0,0,.45);
 animation:pop .5s ease-out both,preme .35s ease-in-out 1.5s both}
.sbt .bt span{grid-area:1/1;text-align:center}
.sbt .bt .a{animation:svanisce .01s linear 1.7s both}
.sbt .bt .b{opacity:0;animation:compare .01s linear 1.7s both}
.sbt .bell{width:max(4.4vw,4.4vh);height:max(4.4vw,4.4vh);transform-origin:50% 8%;animation:pop .5s ease-out .3s both,suona .9s ease-in-out 1.9s both}
@keyframes preme{0%,100%{transform:scale(1)}50%{transform:scale(.92)}}
@keyframes svanisce{to{opacity:0}}@keyframes compare{to{opacity:1}}
@keyframes suona{0%,100%{transform:rotate(0)}15%{transform:rotate(22deg)}35%{transform:rotate(-18deg)}55%{transform:rotate(12deg)}75%{transform:rotate(-6deg)}}""", v)
    campana = ('<svg class="bell" viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 0-2 2v.7C7.7 5.5 6 7.6 6 10v4l-2 3h16l-2-3v-4c0-2.4-1.7-4.5-4-5.3V4a2 2 0 0 0-2-2Zm0 20a3 3 0 0 0 3-3H9a3 3 0 0 0 3 3Z" fill="#fff"/></svg>')
    return css, (f'<div class="sbt"><div class="bt"><span class="a">{v["testo"]}</span>'
                 f'<span class="b" style="background:#4a4a55">{v["fatto"]}</span></div>{campana}</div>')


# --------------------------------------------------------------------------
# dati
# --------------------------------------------------------------------------


def _donut_chart(v: dict) -> tuple[str, str]:
    voci = v["voci"]
    tot = sum(x for _, x in voci) or 1.0
    archi, legenda, inizio = [], [], 0.0
    for i, (nome, val) in enumerate(voci):
        pct = 100 * val / tot
        col = v["colore"] if i == 0 else _PALETTE[i % len(_PALETTE)]
        archi.append(f'<circle cx="50" cy="50" r="38" pathLength="100" stroke="{col}" '
                     f'stroke-dasharray="{max(pct - .6, .01):.2f} {100 - max(pct - .6, .01):.2f}" '
                     f'stroke-dashoffset="{-inizio:.2f}" transform="rotate(-90 50 50)"/>')
        legenda.append(f'<li style="animation-delay:{.5 + .15 * i:.2f}s"><i style="background:{col}"></i>'
                       f'<span>{B._html.escape(nome)}</span><em>{pct:.0f}%</em></li>')
        inizio += pct
    css = B._t("""
@property --a{syntax:'<angle>';initial-value:0deg;inherits:false}
.dn{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);display:flex;align-items:center;gap:3vw;
 padding:4vh 3vw;border-radius:1.4vw;background:rgba(14,14,20,.8)}
.dn svg{width:max(24vw,24vh);height:max(24vw,24vh);-webkit-mask:conic-gradient(#000 var(--a),transparent 0);
 mask:conic-gradient(#000 var(--a),transparent 0);animation:giro 1.3s cubic-bezier(.5,0,.2,1) .2s both}
.dn circle{fill:none;stroke-width:15}
@keyframes giro{from{--a:0deg}to{--a:360deg}}
.dn ul{list-style:none;margin:0;padding:0;display:grid;gap:1.6vh}
.dn li{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:1vw;font-size:max(2vw,2vh);font-weight:700;
 animation:entra .5s ease-out both}
.dn li i{width:1.8vh;height:1.8vh;min-width:12px;min-height:12px;border-radius:50%}
.dn li em{font-style:normal;font-variant-numeric:tabular-nums;opacity:.85;margin-left:1.6vw}""", v)
    titolo = f"<h3 style='margin:0 0 1.6vh;font-size:max(2.6vw,2.6vh);font-weight:800'>{v['titolo']}</h3>" if v["titolo"] else ""
    return css, (f'<div class="dn"><svg viewBox="0 0 100 100">{"".join(archi)}</svg>'
                 f'<div>{titolo}<ul>{"".join(legenda)}</ul></div></div>')


def _line_chart(v: dict) -> tuple[str, str]:
    voci = v["voci"]
    if len(voci) < 2:
        raise ValueError("dati needs at least 2 label:value pairs for a line chart")
    lo, hi = min(x for _, x in voci), max(x for _, x in voci)
    span = (hi - lo) or 1.0
    n = len(voci)
    pts = []
    for i, (_, val) in enumerate(voci):
        px = 100 * i / (n - 1)
        py = 90 - 80 * (val - lo) / span          # 10..90, il massimo in alto
        pts.append((px, py))
    linea = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    area = f"0,100 {linea} 100,100"
    punti, etichette = [], []
    for i, ((nome, val), (px, py)) in enumerate(zip(voci, pts)):
        ritardo = .2 + 1.3 * i / (n - 1)
        punti.append(f'<b style="left:{px:.2f}%;top:{py:.2f}%;animation-delay:{ritardo:.2f}s"><em>{val:g}</em></b>')
        etichette.append(f'<span style="left:{px:.2f}%">{B._html.escape(nome)}</span>')
    css = B._t("""
.lc{position:absolute;left:10vw;right:10vw;top:50%;transform:translateY(-50%);padding:4vh 3vw 3vh;border-radius:1.4vw;
 background:rgba(14,14,20,.8)}
.lc h3{margin:0 0 2vh;font-size:max(2.8vw,2.8vh);font-weight:800}
.lc .g{position:relative;height:30vh;margin:0 3vw}
.lc svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible;clip-path:inset(-5% 100% -5% -2%);
 animation:rivela 1.5s cubic-bezier(.4,0,.2,1) .15s forwards}
@keyframes rivela{to{clip-path:inset(-5% -2% -5% -2%)}}
.lc polyline{fill:none;stroke:§colore§;stroke-width:max(.5vw,4px);stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}
.lc polygon{fill:§colore§;opacity:.16}
.lc .g b{position:absolute;width:max(1.6vw,1.6vh);height:max(1.6vw,1.6vh);margin:calc(max(1.6vw,1.6vh) / -2) 0 0 calc(max(1.6vw,1.6vh) / -2);
 border-radius:50%;background:#fff;border:max(.4vw,3px) solid §colore§;box-sizing:border-box;animation:pop .35s ease-out both}
.lc .g b em{position:absolute;bottom:130%;left:50%;transform:translateX(-50%);font-style:normal;font-size:max(1.8vw,1.8vh);font-weight:800}
.lc .x{position:relative;height:4vh;margin:1.4vh 3vw 0}
.lc .x span{position:absolute;transform:translateX(-50%);font-size:max(1.6vw,1.6vh);font-weight:700;opacity:.8;white-space:nowrap}""", v)
    titolo = f"<h3>{v['titolo']}</h3>" if v["titolo"] else ""
    return css, (f'<div class="lc">{titolo}<div class="g"><svg viewBox="0 0 100 100" preserveAspectRatio="none">'
                 f'<polygon points="{area}"/><polyline points="{linea}"/></svg>{"".join(punti)}</div>'
                 f'<div class="x">{"".join(etichette)}</div></div>')


def _timeline(v: dict) -> tuple[str, str]:
    voci = v["voci"]
    n = len(voci)
    pezzi = []
    for i, txt in enumerate(voci):
        x = 50 if n == 1 else 8 + 84 * i / (n - 1)
        su = i % 2 == 0
        pezzi.append(f'<div class="e {"su" if su else "giu"}" style="left:{x:.1f}%;animation-delay:{.4 + .55 * i:.2f}s">'
                     f'<i></i><span>{txt}</span></div>')
    css = B._t("""
.tl{position:absolute;left:4vw;right:4vw;top:50%;height:0}
.tl:before{content:'';position:absolute;left:3%;right:3%;top:-.3vh;height:.6vh;border-radius:99px;background:§colore§;
 transform-origin:left;animation:cresce 1s cubic-bezier(.4,0,.2,1) both}
.tl .e{position:absolute;top:0;width:18vw;margin-left:-9vw;text-align:center;animation:entra .5s ease-out both}
.tl .e i{position:absolute;left:50%;top:-1.2vh;width:2.4vh;height:2.4vh;margin-left:-1.2vh;border-radius:50%;background:#fff;
 border:max(.4vw,3px) solid §colore§;box-sizing:border-box}
.tl .e span{position:absolute;left:0;right:0;padding:1vh 1vw;border-radius:.8vw;background:rgba(14,14,20,.86);
 font-size:max(1.9vw,1.9vh);font-weight:700;line-height:1.25}
.tl .su span{bottom:3vh}.tl .giu span{top:3vh}""", v)
    return css, f'<div class="tl">{"".join(pezzi)}</div>'


def _rating_stars(v: dict) -> tuple[str, str]:
    estrella = ('<path d="M12 2l2.9 6.6 7.1.6-5.4 4.7 1.7 7-6.3-3.8-6.3 3.8 1.7-7L2 9.2l7.1-.6z"/>')
    fila = "".join(f'<svg viewBox="0 0 24 24">{estrella}</svg>' for _ in range(5))
    pieno = 100 - 100 * v["valore"] / 5
    css = B._t("""
.rs{position:absolute;inset:0;display:grid;place-content:center;justify-items:center;gap:1.6vh}
.rs .f{position:relative;display:flex;gap:.8vw}
.rs .f svg{width:max(7vw,7vh);height:max(7vw,7vh);fill:rgba(255,255,255,.22);filter:drop-shadow(0 4px 10px rgba(0,0,0,.4))}
.rs .f.o{position:absolute;inset:0;clip-path:inset(0 100% 0 0);animation:pieno 1.3s cubic-bezier(.4,0,.2,1) .2s forwards}
.rs .f.o svg{fill:§colore§}
@keyframes pieno{to{clip-path:inset(0 §pieno§% 0 0)}}
.rs b{font-size:max(6vw,6vh);font-weight:900;font-variant-numeric:tabular-nums;animation:pop .5s ease-out .9s both}
.rs span{font-size:max(2.2vw,2.2vh);font-weight:700;opacity:.9;animation:entra .5s ease-out 1.1s both}""", v, pieno=f"{pieno:.1f}")
    nota = f"<span>{v['etichetta']}</span>" if v["etichetta"] else ""
    return css, (f'<div class="rs"><div class="f">{fila}<div class="f o">{fila}</div></div>'
                 f'<b>{v["valore"]:.1f}</b>{nota}</div>')


def _price_tag(v: dict) -> tuple[str, str]:
    css = B._t("""
.pw{position:absolute;inset:0;display:grid;place-content:center}
.pt{position:relative;display:grid;justify-items:center;gap:1.2vh;
 padding:4vh 5vw;border-radius:1.6vw;background:rgba(14,14,20,.86);box-shadow:0 12px 44px rgba(0,0,0,.5);
 animation:entra .5s ease-out both}
.pt small{font-size:max(1.9vw,1.9vh);font-weight:800;letter-spacing:.2em;text-transform:uppercase;color:§colore§}
.pt s{position:relative;font-size:max(3.2vw,3.2vh);font-weight:700;opacity:.7;text-decoration:none}
.pt s:after{content:'';position:absolute;left:-4%;top:52%;height:.5vh;width:108%;background:#e5383b;
 transform-origin:left;transform:scaleX(0);animation:cresce .35s ease-out .6s forwards}
.pt b{font-size:max(11vw,11vh);font-weight:900;letter-spacing:-.04em;line-height:1;animation:pop .55s ease-out .9s both}
.pt em{position:absolute;right:-1.4vw;top:-2.4vh;padding:.7vh 1.4vw;border-radius:99px;background:§colore§;color:#10101a;
 font-style:normal;font-size:max(2vw,2vh);font-weight:900;transform:rotate(6deg);animation:pop .45s ease-out 1.3s both}""", v)
    vecchio = f"<s>{v['vecchio']}</s>" if v["vecchio"] else ""
    etichetta = f"<small>{v['etichetta']}</small>" if v["etichetta"] else ""
    badge = f"<em>{v['badge']}</em>" if v["badge"] else ""
    return css, f'<div class="pw"><div class="pt">{etichetta}{vecchio}<b>{v["prezzo"]}</b>{badge}</div></div>'


def _checklist(v: dict) -> tuple[str, str]:
    righe = []
    for i, x in enumerate(v["voci"]):
        r = .4 * (i + 1) + .1 * i
        righe.append(f'<li style="animation-delay:{r:.2f}s"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="{v["colore"]}"/>'
                     f'<path d="M6.5 12.5l3.8 3.8 7.2-8" pathLength="1" style="animation-delay:{r + .15:.2f}s"/></svg>{x}</li>')
    css = B._t("""
.ck{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);max-width:70vw;padding:4vh 3.4vw;border-radius:1.4vw;
 background:rgba(14,14,20,.84)}
.ck h3{margin:0 0 2.4vh;font-size:max(3.2vw,3.2vh);font-weight:900;animation:entra .5s ease-out both}
.ck ul{list-style:none;margin:0;padding:0;display:grid;gap:2vh}
.ck li{display:flex;align-items:center;gap:1.4vw;font-size:max(2.5vw,2.5vh);font-weight:700;animation:entra .45s ease-out both}
.ck svg{flex:none;width:max(3.4vw,3.4vh);height:max(3.4vw,3.4vh)}
.ck path{fill:none;stroke:#10101a;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:1;
 animation:tratto .35s ease-out forwards}
@keyframes tratto{to{stroke-dashoffset:0}}""", v)
    titolo = f"<h3>{v['titolo']}</h3>" if v["titolo"] else ""
    return css, f'<div class="ck">{titolo}<ul>{"".join(righe)}</ul></div>'


# --------------------------------------------------------------------------
# enfasi
# --------------------------------------------------------------------------


def _alert_banner(v: dict) -> tuple[str, str]:
    css = B._t("""
.ab{position:absolute;left:0;right:0;top:0;display:flex;align-items:center;gap:1.6vw;padding:2vh 3vw;background:§colore§;
 color:#fff;box-shadow:0 8px 30px rgba(0,0,0,.45);animation:cala .5s cubic-bezier(.2,.9,.3,1.1) both}
.ab i{flex:none;display:grid;place-items:center;width:max(4.6vw,4.6vh);height:max(4.6vw,4.6vh);border-radius:50%;background:#fff;
 color:§colore§;font-style:normal;font-size:max(3.4vw,3.4vh);font-weight:900;animation:lampeggia .8s step-end .5s 3}
.ab small{display:block;font-size:max(1.5vw,1.5vh);font-weight:800;letter-spacing:.22em;text-transform:uppercase;opacity:.85}
.ab b{display:block;font-size:max(3vw,3vh);font-weight:900;line-height:1.1}
@keyframes cala{from{transform:translateY(-100%)}to{transform:none}}
@keyframes lampeggia{50%{opacity:.25}}""", v)
    return css, (f'<div class="ab"><i>!</i><div><small>{v["etichetta"]}</small><b>{v["testo"]}</b></div></div>')


# --------------------------------------------------------------------------
# transizioni
# --------------------------------------------------------------------------


def _iris_wipe(v: dict) -> tuple[str, str]:
    css = B._t("""
@property --r{syntax:'<percentage>';initial-value:101%;inherits:false}
.ir{position:absolute;inset:0;background:radial-gradient(circle farthest-corner at §x§% §y§%,transparent var(--r),§colore§ calc(var(--r) + .4%));
 animation:iride §durata§s cubic-bezier(.65,0,.35,1) both}
@keyframes iride{0%{--r:101%}45%{--r:0%}55%{--r:0%}100%{--r:101%}}""", v)
    return css, '<div class="ir"></div>'


def _blinds_wipe(v: dict) -> tuple[str, str]:
    n = int(v["strisce"])
    passo = v["durata"] * 0.15 / max(1, n - 1)     # lo sfasamento totale e' il 15% della clip
    dur = max(0.3, v["durata"] - passo * (n - 1))
    strisce = "".join(f'<i style="animation-delay:{i * passo:.3f}s"></i>' for i in range(n))
    css = B._t("""
.bw{position:absolute;inset:0;display:flex}
.bw i{flex:1;background:§colore§;transform:scaleY(0);animation:tendina §dur§s cubic-bezier(.65,0,.35,1) both}
@keyframes tendina{0%{transform-origin:top;transform:scaleY(0)}30%{transform-origin:top;transform:scaleY(1)}
 70%{transform-origin:bottom;transform:scaleY(1)}100%{transform-origin:bottom;transform:scaleY(0)}}""", v, dur=f"{dur:.3f}")
    return css, f'<div class="bw">{strisce}</div>'


# --------------------------------------------------------------------------
# stile
# --------------------------------------------------------------------------


def _film_grain(v: dict) -> tuple[str, str]:
    css = B._t("""
.fg{position:absolute;inset:0;overflow:hidden;opacity:§forza§}
.fg svg{position:absolute;left:-6%;top:-6%;width:112%;height:112%;animation:grana .5s steps(1) infinite}
@keyframes grana{0%{transform:translate(0,0)}17%{transform:translate(-3%,2%)}33%{transform:translate(2%,-3%)}
 50%{transform:translate(-2%,-2%)}67%{transform:translate(3%,3%)}83%{transform:translate(-1%,3%)}}""", v)
    svg = ('<svg><filter id="n" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".9" '
           'numOctaves="2" seed="7" stitchTiles="stitch"/><feColorMatrix type="matrix" values="0 0 0 0 .95  0 0 0 0 .95  0 0 0 0 .95  '
           '0 0 0 3.2 -1.3"/></filter><rect width="100%" height="100%" filter="url(#n)"/></svg>')
    return css, f'<div class="fg">{svg}</div>'


def _light_leak(v: dict) -> tuple[str, str]:
    css = B._t("""
.ll{position:absolute;inset:0;overflow:hidden}
.ll i{position:absolute;width:70%;height:140%;top:-20%;left:-40%;border-radius:50%;filter:blur(6vh);
 background:radial-gradient(closest-side,§colore§,transparent);opacity:.75;animation:leak §durata§s ease-in-out both}
.ll i:nth-child(2){width:50%;background:radial-gradient(closest-side,#ff5e3a,transparent);opacity:.55;animation-delay:.25s;top:10%}
@keyframes leak{0%{transform:translateX(0);opacity:0}30%{opacity:.8}100%{transform:translateX(190%);opacity:0}}""", v)
    return css, '<div class="ll"><i></i><i></i></div>'


def _scanlines(v: dict) -> tuple[str, str]:
    css = B._t("""
.sn{position:absolute;inset:0;background:repeating-linear-gradient(transparent 0 .3vh,rgba(0,0,0,§forza§) .3vh .6vh);
 animation:aparsi .5s ease-out both}
.sn:after{content:'';position:absolute;left:0;right:0;height:14vh;top:-14vh;
 background:linear-gradient(transparent,rgba(255,255,255,.07),transparent);animation:scende 4.5s linear infinite}
@keyframes aparsi{from{opacity:0}to{opacity:1}}
@keyframes scende{to{transform:translateY(130vh)}}""", v)
    return css, '<div class="sn"></div>'


def _viewfinder(v: dict) -> tuple[str, str]:
    css = B._t("""
.vf{position:absolute;inset:0;animation:entra .4s ease-out both}
.vf i{position:absolute;width:5vw;height:5vw;min-width:28px;min-height:28px;border:0 solid #fff;opacity:.9}
.vf i:nth-child(1){left:4vw;top:5vh;border-left-width:max(.35vw,3px);border-top-width:max(.35vw,3px)}
.vf i:nth-child(2){right:4vw;top:5vh;border-right-width:max(.35vw,3px);border-top-width:max(.35vw,3px)}
.vf i:nth-child(3){left:4vw;bottom:5vh;border-left-width:max(.35vw,3px);border-bottom-width:max(.35vw,3px)}
.vf i:nth-child(4){right:4vw;bottom:5vh;border-right-width:max(.35vw,3px);border-bottom-width:max(.35vw,3px)}
.vf b{position:absolute;left:8.6vw;top:6.4vh;display:flex;align-items:center;gap:.8vw;font-size:max(2.2vw,2.2vh);font-weight:800;
 letter-spacing:.14em;font-family:ui-monospace,'Cascadia Mono',Consolas,monospace;text-shadow:0 2px 10px rgba(0,0,0,.6)}
.vf b:before{content:'';width:max(1.5vw,1.5vh);height:max(1.5vw,1.5vh);border-radius:50%;background:§colore§;animation:rec 1s step-end infinite}
.vf u{position:absolute;left:50%;top:50%;width:3vw;height:3vw;min-width:20px;min-height:20px;margin:-1.5vw 0 0 -1.5vw;opacity:.7;text-decoration:none}
.vf u:before,.vf u:after{content:'';position:absolute;background:#fff}
.vf u:before{left:50%;top:0;bottom:0;width:max(.15vw,2px)}.vf u:after{top:50%;left:0;right:0;height:max(.15vw,2px)}
@keyframes rec{50%{opacity:0}}""", v)
    return css, f'<div class="vf"><i></i><i></i><i></i><i></i><b>{v["etichetta"]}</b><u></u></div>'


# --------------------------------------------------------------------------
# registro
# --------------------------------------------------------------------------


def _reg(descr: str, cat: str, durata: float, fn, parametri: dict) -> dict:
    return {"descrizione": descr, "categoria": cat, "durata": durata, "fn": fn, "parametri": parametri}


PIU: dict[str, dict] = {
    "mask_reveal_title": _reg(
        "Title whose lines rise out of an invisible mask, one after the other (editorial, kinetic).",
        "titles", 3.5, _mask_reveal_title,
        {"titolo": ("testo", "Big idea", "the title"),
         "sottotitolo": ("testo", "A smaller line", "second line (optional)"),
         "colore": ("colore", _C, "second line")}),
    "glitch_title": _reg(
        "Uppercase title that tears into red and cyan slices for a moment, then settles.",
        "titles", 2.5, _glitch_title,
        {"titolo": ("testo", "Signal lost", "the title", 40),
         "colore": ("colore", "#ff2d6f", "the first slice (the other is cyan)")}),
    "word_cycle": _reg(
        "A fixed phrase and one word that rolls through options and stops on the last ('We make FILMS').",
        "titles", 4.0, _word_cycle,
        {"prefisso": ("testo", "We make", "the fixed words", 40),
         "voci": ("lista", "ads, films, shorts, stories", "the words that roll, comma separated; the last one stays",
                  (2, 6)),
         "colore": ("colore", _C, "the rolling word")}),
    "countdown": _reg(
        "Big numbers that replace each other: '3, 2, 1, GO'. The last one stays.",
        "titles", 3.6, _countdown,
        {"voci": ("lista", "3, 2, 1, GO", "the steps, comma separated", (2, 6)),
         "colore": ("colore", _C, "the numbers")}),
    "logo_shine": _reg(
        "Wordmark that lands and gets swept by a glint of light, with an optional tagline.",
        "titles", 3.5, _logo_shine,
        {"testo": ("testo", "BRAND", "the wordmark", 30),
         "sottotitolo": ("testo", "", "tagline (optional)", 60),
         "colore": ("colore", _C, "the glint and the rule")}),
    "chat_messages": _reg(
        "Messenger-style bubbles popping in, alternating left (received) and right (sent). 1-5 messages.",
        "text", 5.0, _chat_messages,
        {"voci": ("lista", "Did you see it?, Seen what?, The new cut., Send it!", "messages, comma separated",
                  (1, 5)),
         "colore": ("colore", "#2b8cff", "the sent bubbles")}),
    "notification_toast": _reg(
        "Phone-style notification card dropping from the top.",
        "text", 4.0, _notification_toast,
        {"app": ("testo", "Messages", "app name", 30),
         "titolo": ("testo", "New message", "bold line", 50),
         "testo": ("testo", "You have a new follower", "body", 90),
         "colore": ("colore", "#34c759", "the app icon")}),
    "marker_highlight": _reg(
        "A sentence where *starred* words get a marker swipe behind them, one after the other.",
        "emphasis", 4.0, _marker_highlight,
        {"testo": ("testo", "The *only* thing that *matters*", "the sentence; wrap words in *stars*", 160),
         "colore": ("colore", _C, "the marker")}),
    "location_pin": _reg(
        "Map pin dropping at x, y (% of the frame, the tip) with a ripple and a place label.",
        "text", 4.0, _location_pin,
        {"luogo": ("testo", "Lisbon", "the place", 40),
         "dettaglio": ("testo", "Portugal", "second line (optional)", 50),
         "x": ("numero", 40, "tip, % of the width", (5, 95)),
         "y": ("numero", 62, "tip, % of the height", (15, 95)),
         "colore": ("colore", "#ff3b5c", "the pin")}),
    "subscribe_button": _reg(
        "Subscribe button that gets pressed, turns into 'Subscribed' and rings its bell.",
        "emphasis", 4.0, _subscribe_button,
        {"testo": ("testo", "Subscribe", "before the press", 20),
         "fatto": ("testo", "Subscribed", "after the press", 20),
         "colore": ("colore", "#ff0033", "the button")}),
    "donut_chart": _reg(
        "Donut chart sweeping round, with a legend of shares. 1-10 label:value pairs.",
        "data", 5.0, _donut_chart,
        {"dati": ("elenco", "Video:50, Shorts:30, Live:20", "label:value pairs, comma separated"),
         "titolo": ("testo", "", "title (optional)", 40),
         "colore": ("colore", _C, "the first slice")}),
    "line_chart": _reg(
        "Line chart drawn left to right with points popping on it. 2-10 label:value pairs.",
        "data", 5.0, _line_chart,
        {"dati": ("elenco", "2021:12, 2022:18, 2023:35, 2024:52", "label:value pairs, comma separated"),
         "titolo": ("testo", "", "title (optional)", 40),
         "colore": ("colore", _C, "the line")}),
    "timeline": _reg(
        "Horizontal timeline that draws itself, with milestones above and below. 2-6 items.",
        "data", 6.0, _timeline,
        {"voci": ("lista", "2019 Founded, 2021 First product, 2023 1M users, 2025 Global", "milestones, comma separated",
                  (2, 6)),
         "colore": ("colore", _C, "the line")}),
    "rating_stars": _reg(
        "Five stars filling up to a rating, with the number and a caption.",
        "data", 3.5, _rating_stars,
        {"valore": ("numero", 4.8, "rating, 0-5", (0, 5)),
         "etichetta": ("testo", "from 12,000 reviews", "caption (optional)", 60),
         "colore": ("colore", "#ffc400", "the stars")}),
    "price_tag": _reg(
        "Price card: the old price gets struck out, the new one pops, with an optional badge.",
        "data", 4.0, _price_tag,
        {"prezzo": ("testo", "$49", "the price", 14),
         "vecchio": ("testo", "$79", "the old price (optional)", 14),
         "etichetta": ("testo", "Limited offer", "line above (optional)", 40),
         "badge": ("testo", "-38%", "corner badge (optional)", 14),
         "colore": ("colore", _C, "label and badge")}),
    "checklist": _reg(
        "Panel whose items get ticked one by one, each tick drawn by hand. 1-6 items.",
        "data", 5.0, _checklist,
        {"titolo": ("testo", "", "title (optional)", 50),
         "voci": ("lista", "Script, Shoot, Edit, Publish", "items, comma separated", (1, 6)),
         "colore": ("colore", "#80ed99", "the ticks")}),
    "alert_banner": _reg(
        "Bar dropping from the top with a blinking '!' (warning, breaking, update).",
        "emphasis", 3.5, _alert_banner,
        {"testo": ("testo", "This changes everything", "the message", 70),
         "etichetta": ("testo", "Warning", "small line above", 30),
         "colore": ("colore", "#e5383b", "the bar")}),
    "iris_wipe": _reg(
        "Transition: the frame closes to a color through an iris and opens again. Cut at the middle.",
        "transitions", 1.2, _iris_wipe,
        {"colore": ("colore", "#10101a", "the iris"),
         "x": ("numero", 50, "center, % of the width", (0, 100)),
         "y": ("numero", 50, "center, % of the height", (0, 100))}),
    "blinds_wipe": _reg(
        "Transition: vertical blinds close in a ripple, stay shut for a beat, then open. Cut at the middle.",
        "transitions", 1.2, _blinds_wipe,
        {"colore": ("colore", "#10101a", "the blinds"),
         "strisce": ("numero", 8, "number of blinds", (3, 16))}),
    "film_grain": _reg(
        "Moving film grain over the whole frame (subtle; set the clip blend to overlay or soft light if you like).",
        "style", 6.0, _film_grain,
        {"forza": ("numero", 0.5, "how visible the grain is, 0-1", (0.05, 1))}),
    "light_leak": _reg(
        "Warm light drifting across the frame once, like a leak on film (set the clip blend to screen).",
        "style", 3.0, _light_leak,
        {"colore": ("colore", "#ffb347", "the main glow")}),
    "scanlines": _reg(
        "CRT scanlines with a slow rolling bar: retro monitor, VHS, found footage.",
        "style", 6.0, _scanlines,
        {"forza": ("numero", 0.28, "how dark the lines are, 0-1", (0.05, 0.8))}),
    "viewfinder": _reg(
        "Camera viewfinder: corner brackets, a blinking REC dot and a crosshair.",
        "style", 6.0, _viewfinder,
        {"etichetta": ("testo", "REC", "the label next to the dot", 20),
         "colore": ("colore", "#ff3b30", "the dot")}),
}
