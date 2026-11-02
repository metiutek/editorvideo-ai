"""Imparare uno stile: camera (zoom, panoramica), colore piatto, voce narrante e
descrizione visiva. Le misure devono ritrovare quello che il riferimento contiene."""

import http.server
import json
import subprocess
import threading

import pytest
from PIL import Image
from test_apprendi import _misure, _riferimento

from vedit import apprendi, ffmpeg, llm, stili


def _ff(*args):
    subprocess.run([ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True, capture_output=True)


@pytest.fixture(scope="module")
def trama(tmp_path_factory):
    """Un'immagine ricca di dettagli e ferma: serve a far muovere la camera sopra."""
    out = tmp_path_factory.mktemp("trama") / "trama.png"
    _ff("-f", "lavfi", "-i",
        "mandelbrot=s=1600x900:r=1:start_scale=0.004:start_x=-0.7436:start_y=0.1318:"
        "end_scale=0.004:maxiter=800", "-vf", "gblur=sigma=5", "-frames:v", "1", str(out))
    return str(out)


def _ripresa(cartella, trama, nome, vf):
    out = cartella / f"{nome}.mp4"
    _ff("-loop", "1", "-framerate", "25", "-i", trama, "-vf", vf + ",format=yuv420p", "-t", "6",
        "-c:v", "libx264", "-preset", "ultrafast", str(out))
    return str(out)


def test_misura_panoramica_zoom_e_camera_ferma(tmp_path, trama):
    pan = _ripresa(tmp_path, trama, "pan", "crop=640:360:x='14*t':y=200")
    zoom = _ripresa(tmp_path, trama, "zoom",
                    "zoompan=z='1+0.002*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    "d=1:s=640x360:fps=25")
    ferma = _ripresa(tmp_path, trama, "ferma", "crop=640:360:x=300:y=200")
    mp, mz, mf = (apprendi.misura(p)["movimento"] for p in (pan, zoom, ferma))
    assert mp["panoramiche"] == 1.0 and mp["pan_asse"] == "orizzontali"
    assert mz["inquadrature_con_zoom"] == 1.0 and mz["panoramiche"] == 0.0
    assert mf["inquadrature_con_zoom"] == 0.0 and mf["panoramiche"] == 0.0 \
        and mf["animazione"] == 0.0


def test_misura_passaggi_su_colore_piatto(tmp_path):
    out = tmp_path / "capitoli.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=s=640x360:r=25:d=3",
        "-f", "lavfi", "-i", "color=c=0xffa500:s=640x360:r=25:d=1",
        "-f", "lavfi", "-i", "rgbtestsrc=s=640x360:r=25:d=3",
        "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out))
    m = apprendi.misura(str(out))
    assert len(m["passaggi_colore"]) == 1
    p = m["passaggi_colore"][0]
    assert abs(p["t"] - 3.0) <= 0.3 and 0.8 <= p["durata"] <= 1.2
    r, g, b = (int(p["colore"][i:i + 2], 16) for i in (1, 3, 5))   # arancione, a meno del YUV
    assert abs(r - 255) <= 8 and abs(g - 165) <= 8 and abs(b) <= 8
    assert m["palette"] and all(c["colore"].startswith("#") for c in m["palette"])


def _con_audio(cartella, nome, audio):
    """12 s di video con due cambi d'inquadratura, a 4.0 e 7.6 s."""
    out = cartella / f"{nome}.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=s=320x180:r=25:d=4",
        "-f", "lavfi", "-i", "rgbtestsrc=s=320x180:r=25:d=3.6",
        "-f", "lavfi", "-i", "smptebars=s=320x180:r=25:d=4.4",
        "-f", "lavfi", "-i", audio,
        "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a",
        "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out))
    return str(out)


# un parlato finto: tono a fasce di 1.2 s e pause di 0.6 s, sopra un fondo leggero
_PARLATO = ("aevalsrc='0.5*sin(2*PI*500*t)*sin(2*PI*3*t)*gt(mod(t,1.8),0.6)"
            "+0.01*sin(2*PI*180*t)':s=16000:d=12")
_SOLO_MUSICA = "aevalsrc='0.05*sin(2*PI*220*t)+0.05*sin(2*PI*330*t)':s=16000:d=12"


def test_misura_voce_e_cambi_sulle_pause(tmp_path):
    v = apprendi.misura(_con_audio(tmp_path, "parlato", _PARLATO))["voce"]
    assert v["presente"] is True
    assert 1.0 <= v["frase_mediana"] <= 1.4 and 0.4 <= v["pausa_mediana"] <= 0.8
    # i cambi a 4.0 e 7.6 s cadono dentro le pause (3.6-4.2 e 7.2-7.8)
    assert v["tagli_su_pause"] == 1.0 and v["a_caso"] < 0.6


def test_misura_voce_assente_con_la_sola_musica(tmp_path):
    v = apprendi.misura(_con_audio(tmp_path, "musica", _SOLO_MUSICA))["voce"]
    assert v["presente"] is False


def test_guida_con_voce_e_movimento_nuovi():
    mis = _misure(
        voce={"presente": True, "metodo": "energia", "quota_parlato": 0.74, "frase_mediana": 3.0,
              "pausa_mediana": 0.5, "pause_al_minuto": 12, "tagli_su_pause": 0.8, "a_caso": 0.3},
        movimento={"inquadrature_con_zoom": 0.3, "zoom_medio": 0.1, "panoramiche": 0.4,
                   "pan_asse": "orizzontali", "animazione": 0.5, "punch_in": 0.0,
                   "mosso": 0.002, "scosse": 0.0},
        palette=[{"colore": "#6d4b31", "quota": 0.3}],
        passaggi_colore=[{"t": 10.0, "durata": 0.5, "colore": "#ffc06d"}])
    t = apprendi.guida(mis, "rif", None)
    assert "Voce narrante" in t and "a fine frase" in t and "74%" in t
    assert "Musica di sottofondo" in t and "non guida i tagli" in t   # con la voce il BPM non comanda
    assert "panoramiche lente orizzontali" in t and "animazione dentro la scena" in t
    assert "#6d4b31" in t and "passaggi su colore piatto" in t
    _, r = apprendi.ricetta(mis)
    assert r["movimento"] == "spinta"        # zoom 30% + panoramiche 40%: la camera si muove
    assert any("generate_voice" in x for x in r["da_fare"])
    assert any("colore piatto" in x for x in r["da_fare"])


def test_bpm_doppio_si_dimezza(monkeypatch):
    monkeypatch.setattr(apprendi.analyze, "beats", lambda p: {
        "bpm": 184.0, "beat": 0.326, "offset": 0.0, "profilo": [{"t": 0, "energia": 1.0}]})
    m = apprendi._musica("x.mp4", True, [1.0, 2.0], 10.0)
    assert m["bpm"] == 92.0 and abs(m["battito"] - 0.652) < 1e-6


def test_descrizione_visiva_entra_nella_guida(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))
    visti = {}

    def finto(prompt, percorsi, **k):
        visti["prompt"], visti["immagini"] = prompt, percorsi
        return "- animazione 2D, personaggi stilizzati a testa nera\n- cartellino di testo in basso"

    monkeypatch.setattr(llm, "chiedi_con_immagini", finto)
    res = apprendi.impara(_riferimento(tmp_path), "Visivo", descrivi=True)
    assert "Linguaggio visivo" in res["guida"] and "cartellino di testo" in res["guida"]
    assert apprendi._RIMANDO not in res["guida"]          # il rimando non serve piu'
    assert res["misure"]["visivo"].startswith("- animazione 2D")
    assert "VISUAL STYLE" in visti["prompt"] and visti["immagini"][0].endswith("_foglio.jpg")
    # lo stile salvato porta la descrizione: e' quello che l'agente rileggera' dopo
    assert "cartellino di testo" in stili.trova(res["stile"]["id"])["guida"]


def test_senza_modello_con_la_vista_lo_stile_esce_lo_stesso(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))

    def nessuno(*a, **k):
        raise RuntimeError("no model configured")

    monkeypatch.setattr(llm, "chiedi_con_immagini", nessuno)
    res = apprendi.impara(_riferimento(tmp_path), "Senza", descrivi=True)
    assert "stile" in res and apprendi._RIMANDO in res["guida"]
    assert "pick one in the assistant settings" in res["misure"]["avviso"]
    # senza chiederlo (agente che guarda da se') nessuna chiamata al modello
    monkeypatch.setattr(llm, "chiedi_con_immagini", lambda *a, **k: pytest.fail("non va chiamato"))
    apprendi.impara(_riferimento(tmp_path), "Muto")


def test_chiedi_con_immagini_servizio_openai(tmp_path):
    """Il corpo porta l'immagine in base64 e il testo; la risposta torna come testo."""
    ricevuti = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            ricevuti.append((self.path, self.headers.get("Authorization"),
                             json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            corpo = json.dumps({"choices": [{"message": {"content": " Palette calda. "}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        llm.salva({"provider": "custom", "chiavi": {"custom": "k1"}, "modelli": {"custom": "m1"},
                   "indirizzi": {"custom": f"http://127.0.0.1:{srv.server_address[1]}/v1"}})
        img = tmp_path / "f.png"
        Image.new("RGB", (8, 8), "orange").save(img)
        assert llm.chiedi_con_immagini("com'e' fatto?", [str(img)]) == "Palette calda."
        percorso, auth, corpo = ricevuti[0]
        assert percorso == "/v1/chat/completions" and auth == "Bearer k1" and corpo["model"] == "m1"
        parti = corpo["messages"][0]["content"]
        assert parti[0]["type"] == "image_url"
        assert parti[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert parti[-1] == {"type": "text", "text": "com'e' fatto?"}
        with pytest.raises(RuntimeError, match="no images"):
            llm.chiedi_con_immagini("x", [str(tmp_path / "manca.png")])
    finally:
        srv.shutdown()
