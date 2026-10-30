"""Imparare uno stile di montaggio da un video gia' montato.

Si da' un video (file, link o media del progetto) e si misura *come* e'
montato: ritmo dei tagli e come cambia, transizioni, movimento dentro
l'inquadratura e punch-in, colore, formato, aperture e chiusure, quanto gli
stacchi cadono sul battito. Le misure diventano uno stile personale
(``stili.salva``): una guida a parole con i numeri veri e una ricetta che
``apply_style`` applica davvero.

Quello che non si misura (testi, grafica, sottotitoli, contenuto) lo vede il
modello nel foglio dei fotogrammi, uno per inquadratura, e con quello
completa la guida.

Tutto numpy su un flusso a bassa risoluzione (``LARGHEZZA`` px, ``FPS``
fotogrammi al secondo): niente modelli, niente dipendenze nuove.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import analyze, ffmpeg, probe, review, stili

LIMITE = 600.0          # secondi analizzati al massimo: lo stile si vede presto
FPS = 10.0              # fotogrammi al secondo del flusso di analisi
LARGHEZZA = 96          # px: bastano per colore, movimento e dissolvenze
SOGLIA_TAGLIO = 0.30    # scene score di ffmpeg per un taglio netto
MAX_FOGLIO = 16         # fotogrammi nel foglio


def cartella() -> Path:
    """Dove finiscono i video di riferimento scaricati o caricati."""
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    d = base / "riferimenti"
    d.mkdir(parents=True, exist_ok=True)
    return d


def procura(fonte: str, limite: float = LIMITE) -> str:
    """Il file locale di ``fonte``: un percorso, o un link scaricato (anche
    YouTube, TikTok, Instagram... con yt-dlp)."""
    fonte = (fonte or "").strip()
    if fonte.startswith(("http://", "https://")):
        from . import web
        try:
            # 480p bastano per misurare, e da una pagina video si scarica solo il
            # tratto che si analizza
            return web.scarica(fonte, cartella(), 480, secondi=limite + 5)["path"]
        except web.WebError as exc:
            raise ValueError(str(exc)) from exc
    p = Path(fonte).expanduser()
    if not p.is_file():
        raise ValueError(f"video not found: {fonte}")
    return str(p)


# --------------------------------------------------------------------------
# misure
# --------------------------------------------------------------------------


def _tagli(path: str, durata: float) -> list[float]:
    """Tagli netti, con lo scene score di ffmpeg su una copia rimpicciolita."""
    log = analyze._run_detect([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "info",
        "-t", f"{durata:.3f}", "-i", str(path),
        "-vf", f"scale=240:-2,select='gt(scene,{SOGLIA_TAGLIO})',metadata=print:file=-",
        "-an", "-sn", "-f", "null", "-",
    ])
    tagli: list[float] = []
    for m in re.finditer(r"pts_time:([0-9.]+)", log):
        t = round(float(m.group(1)), 3)
        if t >= 0.15 and (not tagli or t - tagli[-1] >= 0.15) and t < durata - 0.15:
            tagli.append(t)
    return tagli


def _flusso(path: str, durata: float, w: int, h: int):
    """I fotogrammi RGB a bassa risoluzione, come array (n, h, w, 3) in 0..1."""
    import numpy as np

    proc = subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-t", f"{durata:.3f}", "-i", str(path), "-an", "-sn",
        "-vf", f"fps={FPS},scale={w}:{h},format=rgb24", "-f", "rawvideo", "-",
    ], capture_output=True, timeout=3600)
    raw = proc.stdout or b""
    n = len(raw) // (w * h * 3)
    if n < 3:
        raise ValueError("cannot read the video frames")
    return np.frombuffer(raw[: n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3) / 255.0


def _zoom(img, s: float):
    """``img`` ingrandita di ``s`` attorno al centro (s<1 allarga), stessa misura."""
    import numpy as np

    h, w = img.shape
    ys = np.clip(((np.arange(h) - h / 2 + 0.5) / s + h / 2 - 0.5).round().astype(int), 0, h - 1)
    xs = np.clip(((np.arange(w) - w / 2 + 0.5) / s + w / 2 - 0.5).round().astype(int), 0, w - 1)
    return img[np.ix_(ys, xs)]


def _scala(a, b) -> float:
    """Di quanto ``b`` e' ``a`` ingrandita (1.0 = non lo e', o non si capisce)."""
    import numpy as np

    m = 4  # i bordi si escludono: l'ingrandimento li riempie di pixel ripetuti
    def err(s):
        return float(np.abs(_zoom(a, s)[m:-m, m:-m] - b[m:-m, m:-m]).mean())
    base = err(1.0)
    migliore, s_best = base, 1.0
    for s in (0.8, 0.85, 0.9, 0.94, 0.97, 1.03, 1.06, 1.1, 1.15, 1.2, 1.3, 1.4):
        e = err(s)
        if e < migliore:
            migliore, s_best = e, s
    # deve spiegare la differenza molto meglio dell'immagine ferma
    return s_best if base > 0.01 and migliore < base * 0.7 else 1.0


def _mediana(v, default=0.0) -> float:
    v = sorted(v)
    if not v:
        return default
    k = len(v) // 2
    return float(v[k] if len(v) % 2 else (v[k - 1] + v[k]) / 2)


def _quantile(v, q: float) -> float:
    v = sorted(v)
    return float(v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]) if v else 0.0


def misura(path: str, limite: float = LIMITE) -> dict:
    """Tutte le misure di montaggio di un video: e' la parte che non indovina."""
    import numpy as np

    m = probe.probe(path)
    if not m.has_video:
        raise ValueError(f"{Path(path).name} has no video: there is no editing to learn")
    durata = min(float(m.duration or 0.0), limite)
    if durata < 2.0:
        raise ValueError("the video is too short to learn a style from it")
    W = LARGHEZZA
    H = max(2, int(round(W * (m.height or 9) / (m.width or 16) / 2)) * 2)

    tagli = _tagli(path, durata)
    rgb = _flusso(path, durata, W, H)
    luma = rgb @ np.array([0.2126, 0.7152, 0.0722])

    # bande nere (letterbox, pillarbox): righe e colonne sempre nere. Sono una
    # scelta di stile, e fuori dal conto del colore non lo falsano
    def bande(profilo) -> tuple[int, int]:
        nere = profilo < 0.06
        a = int(np.argmin(nere)) if not nere.all() else 0
        b = int(np.argmin(nere[::-1])) if not nere.all() else 0
        return a, b
    alto, basso = bande(luma.max(axis=(0, 2)))
    sx, dx = bande(luma.max(axis=(0, 1)))
    if alto + basso < 0.04 * H:
        alto = basso = 0
    if sx + dx < 0.04 * W:
        sx = dx = 0
    quadro = (slice(None), slice(alto, H - basso or None), slice(sx, W - dx or None))
    l_q = luma[quadro]
    lq_m = l_q.mean(axis=(1, 2))
    vista = ((W - sx - dx) * (m.width or 16) / W) / max(1e-3, (H - alto - basso) * (m.height or 9) / H)
    n = len(luma)
    d1 = np.concatenate([[0.0], np.abs(np.diff(luma, axis=0)).mean(axis=(1, 2))])
    lum = luma.mean(axis=(1, 2))

    # tagli che lo scene score non vede: un punch-in sulla stessa ripresa
    # cambia poco l'istogramma, ma e' un salto netto fra due fotogrammi
    for i in range(1, n):
        intorno = np.concatenate([d1[max(1, i - 5):i], d1[i + 1:i + 6]])
        t = i / FPS
        if len(intorno) and d1[i] > max(0.04, 6 * float(np.median(intorno))) \
                and 0.15 <= t < durata - 0.15 and all(abs(t - c) > 0.3 for c in tagli):
            tagli.append(round(t, 3))
    tagli.sort()

    def vicino_taglio(i: int, raggio: float = 0.4) -> bool:
        t = i / FPS
        return any(abs(t - c) <= raggio for c in tagli)

    # dissolvenze e passaggi sul nero: un fotogramma che e' la media dei suoi
    # vicini (fusione lineare) senza un salto netto in mezzo
    k = 3
    candidati: list[tuple[int, str]] = []
    for i in range(k, n - k):
        if vicino_taglio(i):
            continue
        a, b, c = luma[i - k], luma[i], luma[i + k]
        lontano = float(np.abs(c - a).mean())
        if lontano < 0.10 or d1[i - k + 1:i + k + 1].max() > 0.6 * lontano:
            continue
        if lum[i] < 0.06 and lum[i - k] > 0.1 and lum[i + k] > 0.1:
            candidati.append((i, "nero"))
        elif min(lum[i - k], lum[i + k]) < 0.1 or float(np.abs(
                a / max(lum[i - k], 1e-3) - c / max(lum[i + k], 1e-3)).mean()) < 0.15:
            continue  # stessa immagine piu' chiara o piu' scura: sfuma da o verso il nero
        elif float(np.abs(b - (a + c) / 2).mean()) < 0.35 * lontano:
            candidati.append((i, "dissolvenza"))
    # fotogrammi vicini sono la stessa transizione: centro e durata del gruppo
    morbide: list[tuple[float, str]] = []
    durate_morbide: list[float] = []
    gruppo: list[tuple[int, str]] = []
    for cand in [*candidati, (n + 100, "")]:
        if gruppo and cand[0] - gruppo[-1][0] > FPS * 0.5:
            primo, ultimo = gruppo[0][0], gruppo[-1][0]
            tipo = "nero" if any(x == "nero" for _, x in gruppo) else "dissolvenza"
            morbide.append((round((primo + ultimo) / 2 / FPS, 2), tipo))
            durate_morbide.append((ultimo - primo) / FPS + 0.2)
            gruppo = []
        gruppo.append(cand)
    # un taglio che arriva dal nero o ci va (dissolvenza al nero e stacco)
    for c in tagli:
        i = int(round(c * FPS))
        buio = float(lum[max(0, i - 2):i + 2].min()) < 0.1
        attorno = max(lum[max(0, i - 12)], lum[min(n - 1, i + 12)]) > 0.15
        if buio and attorno and all(abs(c - t) > 1.0 for t, _ in morbide):
            morbide.append((c, "nero"))
    # tratti di nero fra due scene (sfuma al nero, resta, riapre): un
    # passaggio sul nero lungo, che il confronto a 0.3 s non vede
    buio = (lq_m < 0.04) & (l_q.max(axis=(1, 2)) < 0.2)
    i = 0
    while i < n:
        if not buio[i]:
            i += 1
            continue
        j = i
        while j < n and buio[j]:
            j += 1
        centro = (i + j) / 2 / FPS
        if i > 0 and j < n and (j - i) / FPS <= 4.0                 and all(abs(centro - t) > 1.0 for t, _ in morbide):
            morbide.append((round(centro, 2), "nero"))
        i = j
    morbide.sort()
    dissolvenze = [t for t, x in morbide if x == "dissolvenza"]
    sul_nero = [t for t, x in morbide if x == "nero"]

    # inquadrature e ritmo: anche una dissolvenza e' un cambio d'inquadratura
    cambi = sorted([*tagli, *(t for t, _ in morbide if all(abs(t - c) > 0.5 for c in tagli))])
    bordi = [0.0, *cambi, durata]
    durate = [round(b - a, 3) for a, b in zip(bordi, bordi[1:]) if b - a > 0.05]
    terzo = max(1, len(durate) // 3)
    accelera = (_mediana(durate[-terzo:]) / _mediana(durate[:terzo], 1.0)
                if len(durate) >= 6 else 1.0)
    media = float(np.mean(durate))
    variazione = float(np.std(durate) / media) if media else 0.0

    # flash: un picco di luce di uno o due fotogrammi
    flash = []
    for i in range(3, n - 3):
        intorno = np.median(np.concatenate([lum[i - 3:i - 1], lum[i + 2:i + 4]]))
        if lum[i] - intorno > 0.25 and lum[i] > 0.7 and (not flash or i / FPS - flash[-1] > 0.5):
            flash.append(i / FPS)

    # movimento dentro l'inquadratura (zoom lenti) e punch-in fra inquadrature
    def fotogramma(t: float):
        return luma[min(n - 1, max(0, int(round(t * FPS))))]

    zoom_inq, mosso, scosse = [], [], 0
    for a, b in zip(bordi, bordi[1:]):
        if b - a < 0.8:
            continue
        s = _scala(fotogramma(a + 0.2), fotogramma(b - 0.2))
        zoom_inq.append(s)
        # il primo fotogramma intero dopo il taglio: d1 li' misura gia' la ripresa
        i0, i1 = int(np.ceil(a * FPS)) + 1, int(b * FPS) - 1
        if i1 > i0 + 5:
            corpo = float(np.median(d1[i0 + 5:i1 + 1]))
            mosso.append(corpo)
            # una scossa sull'attacco: movimento forte che poi si spegne (non
            # la coda di una dissolvenza, che all'attacco si muove anche lei)
            morbido = any(abs(a - tm) < 1.0 for tm, _ in morbide)
            if not morbido and float(d1[i0:i0 + 3].mean()) > max(0.01, 3 * corpo):
                scosse += 1
    punch = 0
    for c in tagli:
        if _scala(fotogramma(c - 0.15), fotogramma(c + 0.15)) not in (1.0,):
            punch += 1
    con_zoom = [abs(s - 1) for s in zoom_inq if s != 1.0]

    # colore: campioni ogni mezzo secondo
    campioni = rgb[quadro][:: max(1, int(FPS / 2))]
    r, g, bl = campioni[..., 0], campioni[..., 1], campioni[..., 2]
    l_c = luma[quadro][:: max(1, int(FPS / 2))]
    mx, mn = campioni.max(axis=-1), campioni.min(axis=-1)
    saturazione = float(((mx - mn) / np.maximum(mx, 1e-3)).mean())
    ombre, luci = l_c < 0.3, l_c > 0.6
    colore = {
        "luminosita": round(float(l_c.mean()), 3),
        "contrasto": round(float(l_c.std()), 3),
        "saturazione": round(saturazione, 3),
        "caldo": round(float((r - bl).mean()), 3),
        "ombre_blu": round(float((bl - r)[ombre].mean()) if ombre.any() else 0.0, 3),
        "luci_calde": round(float((r - bl)[luci].mean()) if luci.any() else 0.0, 3),
        "neri": round(float(np.quantile(l_c, 0.02)), 3),
        # per apply_style: le statistiche che colormatch porta sulle riprese
        "statistiche": {"mean": [round(float(x), 5) for x in campioni.reshape(-1, 3).mean(0)],
                        "std": [round(float(x), 5) for x in campioni.reshape(-1, 3).std(0)]},
    }

    # cartelli su nero: un'inquadratura quasi tutta nera con poche cose chiare
    # (titoli, date, loghi fra le scene)
    cartelli = []
    for a, b in zip(bordi, bordi[1:]):
        i0, i1 = int(a * FPS) + 1, max(int(a * FPS) + 2, int(b * FPS))
        pezzo = l_q[i0:i1]
        if len(pezzo) and float(np.median(pezzo.mean(axis=(1, 2)))) < 0.1                 and float(pezzo.max()) > 0.3:
            # il testo piccolo a bassa risoluzione e' sfumato: soglia bassa
            chiari = float((pezzo > 0.25).mean())
            if 0.0002 < chiari < 0.2:
                cartelli.append(round(a, 2))

    # aperture e chiusure dal nero: una salita entro tre secondi, non un
    # cartello o un logo su nero
    def dissolvenza_bordo(seq) -> float:
        if seq[0] > 0.05:
            return 0.0
        rif = float(np.median(seq[int(FPS * 2):int(FPS * 5)])) if len(seq) > FPS * 3 else 0.0
        if rif < 0.1:
            return 0.0
        for i, v in enumerate(seq[: int(FPS * 5)]):
            if v > 0.8 * rif:
                return round(i / FPS, 2)
        return 0.0

    misure = {
        "fonte": str(path),
        "durata": round(float(m.duration or 0.0), 2),
        "analizzati_s": round(durata, 2),
        "formato": _formato(m.width, m.height),
        "bande_nere": round(vista, 2) if (alto or basso or sx or dx) else None,
        "cartelli_su_nero": cartelli[:20],
        "tagli": {
            "numero": len(cambi),
            "al_minuto": round(len(cambi) / durata * 60, 1),
            "inquadratura_mediana": round(_mediana(durate), 2),
            "inquadratura_p10": round(_quantile(durate, 0.1), 2),
            "inquadratura_p90": round(_quantile(durate, 0.9), 2),
            "variazione": round(variazione, 2),
            "prima_inquadratura": durate[0] if durate else round(durata, 2),
            "accelera": round(accelera, 2),
        },
        "transizioni": {"dissolvenze": len(dissolvenze), "sul_nero": len(sul_nero),
                        "flash": len(flash),
                        "durata_dissolvenza": round(_mediana(durate_morbide), 2),
                        # gli istanti, per andarli a guardare nel riferimento
                        "dove": [round(x, 1) for x in sorted(dissolvenze + sul_nero + flash)][:20]},
        "movimento": {
            "inquadrature_con_zoom": round(len(con_zoom) / len(zoom_inq), 2) if zoom_inq else 0.0,
            "zoom_medio": round(_mediana(con_zoom), 3),
            "punch_in": round(punch / len(tagli), 2) if tagli else 0.0,
            "mosso": round(_mediana(mosso), 4),
            "scosse": round(scosse / len(zoom_inq), 2) if zoom_inq else 0.0,
        },
        "colore": colore,
        "apertura": dissolvenza_bordo(l_q.mean(axis=(1, 2))),
        "chiusura": dissolvenza_bordo(l_q.mean(axis=(1, 2))[::-1]),
        "musica": _musica(path, m.has_audio, tagli, durata),
    }
    misure["_tempi_foglio"] = [round((a + b) / 2, 2) for a, b in zip(bordi, bordi[1:])]
    return misure


def _formato(w: int | None, h: int | None) -> str:
    if not w or not h:
        return "16:9"
    r = w / h
    noti = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": 0.8, "4:3": 4 / 3,
            "21:9": 21 / 9, "3:4": 0.75}
    return min(noti, key=lambda k: abs(noti[k] - r))


def _musica(path: str, ha_audio: bool, tagli: list[float], durata: float) -> dict | None:
    """BPM, quanti tagli cadono sul battito (e quanti ci cadrebbero a caso), forma."""
    if not ha_audio:
        return None
    try:
        b = analyze.beats(path)
    except analyze.AnalysisError:
        return {"bpm": None}
    battito, offset = b["beat"], b["offset"]
    tolleranza = min(0.08, battito * 0.15)
    sul = [t for t in tagli
           if abs(((t - offset) / battito - round((t - offset) / battito)) * battito) <= tolleranza]
    energia = [p["energia"] for p in b["profilo"] if p["t"] < durata] or [1.0]
    terzo = max(1, len(energia) // 3)
    inizio, fine = sum(energia[:terzo]) / terzo, sum(energia[-terzo:]) / terzo
    if fine > inizio * 1.3:
        forma = "crescendo"
    elif max(energia) - min(energia) > 0.4:
        forma = "arco"
    else:
        forma = "piatta"
    return {"bpm": b["bpm"], "battito": round(battito, 3),
            "tagli_sul_battito": round(len(sul) / len(tagli), 2) if tagli else 0.0,
            "a_caso": round(min(1.0, 2 * tolleranza / battito), 2), "forma": forma}


# --------------------------------------------------------------------------
# dalle misure allo stile
# --------------------------------------------------------------------------


def _look(c: dict) -> str | None:
    if c["saturazione"] < 0.07:
        return "bn_contrastato" if c["contrasto"] > 0.24 else "bianco_e_nero"
    if c["ombre_blu"] > 0.02 and c["luci_calde"] > 0.04:
        return "cinema_teal_orange"
    if c["neri"] > 0.08 and c["contrasto"] < 0.2:
        return "vhs" if c["saturazione"] < 0.2 else "sbiadito_pellicola"
    if c["caldo"] > 0.07:
        return "caldo_tramonto"
    if c["caldo"] < -0.03 and c["luminosita"] < 0.35:
        return "freddo_notturno"
    return None


def ricetta(mis: dict) -> tuple[str, dict]:
    """(ritmo di base, ricetta) dalle misure."""
    t, tr, mv, mu = mis["tagli"], mis["transizioni"], mis["movimento"], mis["musica"]
    mediana = t["inquadratura_mediana"]
    morbide = tr["dissolvenze"] + tr["sul_nero"]
    quota_morbide = morbide / max(1, t["numero"])
    if mediana <= 1.6:
        piano = "shortform"
    elif mediana <= 3.5:
        piano = "vlog"
    else:
        piano = "cinematic" if quota_morbide > 0.1 or mis["colore"]["contrasto"] > 0.22 \
            else "documentary"

    # il colore vero del riferimento al posto del look piu' vicino: apply_style
    # lo porta su ogni ripresa con colormatch (il look resta nominato nella guida)
    r: dict = {"look": None, "colore": mis["colore"].get("statistiche")}
    if mv["punch_in"] >= 0.15:
        r["movimento"], r["zoom"] = "punch", round(min(0.3, max(0.06, mv["zoom_medio"] or 0.12)), 3)
    elif mv["inquadrature_con_zoom"] >= 0.3:
        r["movimento"], r["zoom"] = "spinta", round(min(0.3, max(0.02, mv["zoom_medio"])), 3)
    else:
        r["movimento"], r["zoom"] = None, 0.0
    if quota_morbide >= 0.08:
        ogni = max(1, min(50, round(1 / quota_morbide)))
        # il passaggio sul nero non e' una transizione del registro: la
        # dissolvenza e' la piu' vicina, e la guida lo dice a parole
        durata = min(2.0, max(0.2, tr.get("durata_dissolvenza") or 0.6))
        r["transizioni"] = {"tipo": "dissolve", "durata": round(durata, 2), "ogni": ogni}
    else:
        r["transizioni"] = None
    r["apertura"] = min(5.0, mis["apertura"])
    r["chiusura"] = min(5.0, mis["chiusura"])
    r["musica"] = None if mu is None or mu.get("bpm") is None else \
        {"crescendo": "crescendo", "arco": "arco"}.get(mu["forma"], "arco")
    r["accenti"] = {"effetto": "shake", "ogni": max(1, min(50, round(1 / mv["scosse"])))} \
        if mv["scosse"] >= 0.15 else None
    r["atti"] = t["accelera"] < 0.6 and t["numero"] >= 12
    attese = []
    if r["movimento"]:
        attese.append("movimento")
    if r["look"] or r["colore"]:
        attese.append("colore")
    if r["transizioni"]:
        attese.append("transizioni")
    if r["musica"]:
        attese.append("musica_viva")
    if t["variazione"] >= 0.5:
        attese.append("ritmo_vario")
    if r["accenti"] or tr["flash"]:
        attese.append("effetti")
    if mis.get("cartelli_su_nero"):
        attese.append("grafica")
    r["attese"] = attese
    r["da_fare"] = _da_fare(mis)
    return piano, r


def _da_fare(mis: dict) -> list[str]:
    t, mu, tr = mis["tagli"], mis["musica"], mis["transizioni"]
    out = [f"inquadrature di {t['inquadratura_p10']}-{t['inquadratura_p90']} s "
           f"(mediana {t['inquadratura_mediana']} s), circa {t['al_minuto']} tagli al minuto"]
    if mu and mu.get("bpm") and mu["tagli_sul_battito"] >= max(0.5, mu["a_caso"] + 0.2):
        out.append(f"stacchi sul battito: music_beats e tagli sulla griglia "
                   f"({round(mu['tagli_sul_battito'] * 100)}% dei tagli nel riferimento)")
    if t["prima_inquadratura"] < 0.6 * t["inquadratura_mediana"]:
        out.append(f"gancio: la prima inquadratura dura solo {t['prima_inquadratura']} s")
    if t["accelera"] < 0.7:
        out.append("il ritmo accelera verso la fine: inquadrature sempre piu' corte")
    elif t["accelera"] > 1.4:
        out.append("il ritmo rallenta verso la fine: chiudi con inquadrature tenute")
    if tr["flash"]:
        out.append(f"flash bianchi brevi sui colpi ({tr['flash']} nel riferimento)")
    if mis["formato"] != "16:9":
        out.append(f"formato {mis['formato']}")
    if mis.get("bande_nere"):
        out.append(f"bande nere: immagine {mis['bande_nere']}:1 dentro il quadro "
                   "(due add_color neri sopra e sotto, su una traccia in cima)")
    if mis.get("cartelli_su_nero"):
        out.append(f"cartelli di testo su nero fra le scene ({len(mis['cartelli_su_nero'])} "
                   "nel riferimento): add_text o add_html su fondo nero")
    return out


def guida(mis: dict, nome_fonte: str, look: str | None) -> str:
    """La guida a parole, con i numeri misurati: e' cio' che il modello legge."""
    t, tr, mv, mu, c = (mis["tagli"], mis["transizioni"], mis["movimento"], mis["musica"],
                        mis["colore"])
    righe = [f"Stile imparato da un video di riferimento ({nome_fonte}, "
             f"{mis['durata']:.0f} s, formato {mis['formato']}). Riproducine il modo di "
             "montare, non il contenuto."]
    if mis.get("analizzati_s", mis["durata"]) < mis["durata"] - 1:
        righe.append(f"(Misurati i primi {mis['analizzati_s']:.0f} s.)")
    ritmo = (f"Ritmo: {t['al_minuto']} tagli al minuto, inquadrature di "
             f"{t['inquadratura_p10']}-{t['inquadratura_p90']} s (mediana "
             f"{t['inquadratura_mediana']} s), ")
    ritmo += "durate molto varie, alterna raffiche e inquadrature tenute." \
        if t["variazione"] >= 0.6 else "durate regolari."
    if t["prima_inquadratura"] < 0.6 * t["inquadratura_mediana"]:
        ritmo += f" Apre con un gancio rapido ({t['prima_inquadratura']} s)."
    if t["accelera"] < 0.7:
        ritmo += " Accelera verso la fine."
    elif t["accelera"] > 1.4:
        ritmo += " Rallenta verso la fine."
    righe.append(ritmo)
    if mu and mu.get("bpm"):
        sul = mu["tagli_sul_battito"]
        if sul >= max(0.5, mu["a_caso"] + 0.2):
            righe.append(f"Musica a {mu['bpm']:.0f} BPM e {round(sul * 100)}% dei tagli sul "
                         "battito: usa music_beats e metti gli stacchi sulla griglia.")
        else:
            righe.append(f"Musica a {mu['bpm']:.0f} BPM ma i tagli non seguono il battito: "
                         "taglia sul contenuto (azione, frasi).")
        righe.append({"crescendo": "La musica cresce verso la fine.",
                      "arco": "La musica ha un arco: intro, picco, uscita."}.get(
            mu["forma"], "Musica di energia costante."))
    morbide = tr["dissolvenze"] + tr["sul_nero"]
    if not morbide:
        righe.append("Transizioni: solo stacchi secchi.")
    else:
        resto = "; il resto stacchi secchi" if morbide < t["numero"] else ""
        righe.append(f"Transizioni: {tr['dissolvenze']} dissolvenze (circa "
                     f"{tr['durata_dissolvenza'] or 0.6} s) e {tr['sul_nero']} passaggi sul nero "
                     f"su {t['numero']} cambi d'inquadratura{resto}.")
    if tr["flash"]:
        righe.append(f"{tr['flash']} flash bianchi brevi sui momenti forti.")
    mov = []
    if mv["punch_in"] >= 0.15:
        mov.append(f"punch-in fra inquadrature ({round(mv['punch_in'] * 100)}% dei tagli)")
    if mv["inquadrature_con_zoom"] >= 0.3:
        mov.append(f"zoom lenti dentro l'inquadratura ({round(mv['inquadrature_con_zoom'] * 100)}% "
                   f"delle inquadrature, circa {round(mv['zoom_medio'] * 100)}%)")
    if mv["scosse"] >= 0.15:
        mov.append("scosse sull'attacco delle inquadrature")
    if mv["mosso"] > 0.03:
        mov.append("camera a mano, immagine viva")
    righe.append("Movimento: " + (", ".join(mov) if mov else "inquadrature ferme") + ".")
    tono = "caldo" if c["caldo"] > 0.04 else "freddo" if c["caldo"] < -0.02 else "neutro"
    sat = "desaturato" if c["saturazione"] < 0.15 else "saturo" if c["saturazione"] > 0.4 \
        else "saturazione naturale"
    righe.append(f"Colore: tono {tono}, {sat}, contrasto "
                 f"{'alto' if c['contrasto'] > 0.24 else 'basso' if c['contrasto'] < 0.15 else 'medio'}"
                 + (f" (look piu' vicino: {look})." if look else "."))
    if mis.get("bande_nere"):
        righe.append(f"Bande nere da cinema: immagine {mis['bande_nere']}:1 dentro il "
                     f"{mis['formato']}.")
    if mis.get("cartelli_su_nero"):
        righe.append(f"{len(mis['cartelli_su_nero'])} cartelli di testo su nero fra le scene "
                     f"(a {', '.join(f'{x:.0f}' for x in mis['cartelli_su_nero'][:8])} s): "
                     "titoli brevi, centrati, piccoli.")
    bordi = []
    if mis["apertura"]:
        bordi.append(f"apre dal nero in {mis['apertura']} s")
    if mis["chiusura"]:
        bordi.append(f"chiude al nero in {mis['chiusura']} s")
    if bordi:
        righe.append(", ".join(bordi).capitalize() + ".")
    righe.append("Testi, grafica, sottotitoli e scelta delle inquadrature non si misurano: "
                 "guardali nel foglio dei fotogrammi del riferimento e imitali.")
    return "\n".join(righe)


def foglio(path: str, tempi: list[float], output: str) -> str | None:
    """Un fotogramma per inquadratura (al massimo ``MAX_FOGLIO``), col tempo stampato."""
    if not tempi:
        return None
    passo = max(1, len(tempi) // MAX_FOGLIO + (1 if len(tempi) % MAX_FOGLIO else 0))
    scelti = tempi[::passo][:MAX_FOGLIO]
    tmp = Path(tempfile.mkdtemp(prefix="vedit_impara_"))
    frames = []
    for i, t in enumerate(scelti):
        f = tmp / f"{i:03d}.jpg"
        subprocess.run([
            ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
            "-y", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
            "-vf", "scale=320:-2", "-q:v", "4", str(f),
        ], capture_output=True, timeout=120)
        if f.exists() and f.stat().st_size > 0:
            frames.append((review._timecode(t), str(f)))
    if not frames:
        return None
    return review.griglia(frames, output, cols=4)["file"]


def impara(fonte: str, nome: str | None = None, salva: bool = True,
           stile_id: str | None = None, limite: float = LIMITE) -> dict:
    """Misura il video ``fonte`` e ne fa uno stile personale (se ``salva``).

    ``limite``: secondi analizzati dall'inizio (un film intero non serve, e da
    un link si scarica solo quel tratto).
    """
    limite = max(10.0, min(float(limite), 3600.0))
    path = procura(fonte, limite)
    mis = misura(path, limite)
    tempi = mis.pop("_tempi_foglio")
    piano, r = ricetta(mis)
    nome_fonte = Path(path).stem
    testo = guida(mis, nome_fonte, _look(mis["colore"]))
    out = str(cartella() / f"{Path(path).stem}_foglio.jpg")
    try:
        mis["foglio"] = foglio(path, tempi, out)
    except Exception:  # noqa: BLE001 - senza Pillow o fotogrammi, lo stile esce lo stesso
        mis["foglio"] = None
    t = mis["tagli"]
    breve = (f"Learned: {t['al_minuto']:.0f} cuts/min, {t['inquadratura_mediana']} s shots"
             + (", on the beat" if any("battito" in x for x in r["da_fare"]) else ""))
    out_d = {"misure": mis, "piano": piano, "ricetta": r, "guida": testo, "breve": breve}
    if salva:
        stile = stili.salva(nome or f"Like {nome_fonte}"[:60], testo, breve, piano,
                            stile_id, r)
        out_d["stile"] = {"id": stile["id"], "nome": stile["nome"]}
    return out_d
