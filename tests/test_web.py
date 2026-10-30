"""Web: ricerca, lettura, download e import. Niente rete vera: risposte finte."""

import http.server
import json
import threading

import pytest

from vedit import chat, web
from vedit import mcp_server as srv
from vedit.store import Store

_DDG_HTML = """<div class="result"><a class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fit.wikipedia.org%2Fwiki%2FTre_Cime&rut=x">Tre
 <b>Cime</b> di Lavaredo</a><a class="result__snippet">Tre vette delle Dolomiti</a></div>"""

_BING = ('<a class="iusc" m="{&quot;murl&quot;:&quot;https://esempio.org/cime.jpg&quot;,'
         '&quot;purl&quot;:&quot;https://esempio.org/pagina&quot;,&quot;turl&quot;:'
         '&quot;https://tse.example/th&quot;,&quot;t&quot;:&quot;Le Tre Cime&quot;}">')


def test_ricerca_senza_chiave(monkeypatch):
    def testo(url, dati=None, headers=None):
        if "html.duckduckgo.com" in url:
            return _DDG_HTML
        if "bing.com/images" in url:
            return _BING
        if url.startswith("https://duckduckgo.com/?"):
            return "<script>vqd='4-123'</script>"
        raise AssertionError(url)

    def js(url, dati=None, headers=None):
        assert "vqd=4-123" in url
        return {"results": [{"title": "Timelapse", "content": "https://youtube.com/watch?v=x",
                             "images": {"medium": "https://i/t.jpg"}, "duration": "1:02"}]}

    monkeypatch.setattr(web, "_testo", testo)
    monkeypatch.setattr(web, "_json", js)
    r = web.cerca("tre cime", "web", motore="duckduckgo")["risultati"]
    assert r == [{"title": "Tre Cime di Lavaredo", "url": "https://it.wikipedia.org/wiki/Tre_Cime",
                  "snippet": "Tre vette delle Dolomiti"}]
    im = web.cerca("tre cime", "images", motore="duckduckgo")["risultati"][0]
    assert im["media"] == "https://esempio.org/cime.jpg" and im["source"] == "esempio.org"
    v = web.cerca("tre cime", "videos", motore="duckduckgo")["risultati"][0]
    assert v["media"] == "https://youtube.com/watch?v=x" and v["duration"] == "1:02"


def test_brave_con_chiave(monkeypatch):
    viste = []

    def js(url, dati=None, headers=None):
        viste.append((url, headers))
        return {"results": [{"title": "Foto", "url": "https://p", "properties": {"url": "https://f.jpg"},
                             "thumbnail": {"src": "https://t"}}]}

    monkeypatch.setattr(web, "_json", js)
    web.imposta("brave", chiave="BRAVE-KEY")
    try:
        r = web.cerca("cime", "images")
        assert r["motore"] == "brave" and r["risultati"][0]["media"] == "https://f.jpg"
        assert "/res/v1/images/search" in viste[0][0]
        assert viste[0][1]["X-Subscription-Token"] == "BRAVE-KEY"
        assert web.stato()["motore"] == "brave"
        assert "BRAVE-KEY" not in json.dumps(web.stato())
    finally:
        web.imposta("duckduckgo", chiave="")
        web.imposta("brave", chiave="")
        web.imposta("duckduckgo")


def test_rete_locale_chiusa(monkeypatch):
    monkeypatch.delenv("VEDIT_WEB_LOCALE", raising=False)
    for u in ("http://127.0.0.1:8760/api/state", "http://localhost/", "http://10.0.0.1/",
              "file:///etc/passwd"):
        with pytest.raises(web.WebError):
            web.leggi(u)


class _Sito(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/foto.png":
            corpo, ct = _Sito.png, "image/png"
        elif self.path == "/vai":
            self.send_response(302)
            self.send_header("Location", "/foto.png")
            self.end_headers()
            return
        else:
            corpo = (b"<html><head><title>Rifugio</title><meta property='og:image' "
                     b"content='/foto.png'></head><body><p>Il rifugio sta a 2405 m.</p>"
                     b"<img src='/foto.png' width='800'><img src='/pixel.gif' width='1'>"
                     b"<video src='/clip.mp4'></video><script>ignora()</script></body></html>")
            ct = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


@pytest.fixture
def sito(monkeypatch, assets):
    monkeypatch.setenv("VEDIT_WEB_LOCALE", "1")
    with open(assets["logo"], "rb") as f:
        _Sito.png = f.read()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Sito)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_leggi_pagina(sito):
    p = web.leggi(f"{sito}/pagina")
    assert p["title"] == "Rifugio" and "2405 m" in p["testo"] and "ignora" not in p["testo"]
    assert p["immagini"] == [f"{sito}/foto.png"]          # og:image e <img>, una volta; niente pixel
    assert p["video"] == [f"{sito}/clip.mp4"]


def test_scarica_e_fonti(sito, tmp_path):
    d = web.scarica(f"{sito}/vai", tmp_path, titolo="Il rifugio")   # anche dopo un redirect
    f = tmp_path / "foto.png"
    assert d["path"] == str(f) and f.read_bytes() == _Sito.png
    fonti = (tmp_path / "FONTI.md").read_text(encoding="utf-8")
    assert "`foto.png` \"Il rifugio\"" in fonti
    ok, ko = web.scarica_molti([f"{sito}/foto.png", "http://127.0.0.1:1/x.jpg"], tmp_path)
    assert len(ok) == 1 and len(ko) == 1 and (tmp_path / "foto_1.png").is_file()


@pytest.mark.anyio
async def test_strumenti_mcp(sito, tmp_path):
    from test_mcp import call

    srv._stores.clear()
    await call("project_create", path=str(tmp_path / "w.json"))
    r = await call("web_download", urls=[f"{sito}/foto.png"])
    assert r["media"][0]["kind"] == "image"
    info = await call("project_info")
    assert any(m["id"] == r["media"][0]["id"] for m in info["media"])
    assert (tmp_path / "w_web" / "FONTI.md").is_file()
    pagina = await call("web_read", url=f"{sito}/pagina")
    assert pagina["title"] == "Rifugio"


def test_chat_scarica(sito, tmp_path):
    s = Store.create("c", path=str(tmp_path / "c.json"))
    out = json.loads(chat.execute(s, "web_download", {"urls": [f"{sito}/foto.png"]}))
    assert out["media"][0]["kind"] == "image" and s.project.media[0].folder == "web"
    nomi = {t["name"] for t in chat.build_tools()}
    assert {"web_search", "web_read", "web_download"} <= nomi


def test_tratto_con_ripiego(sito, tmp_path, monkeypatch):
    """Da una pagina video si chiede solo l'inizio; se il sito rifiuta il taglio
    (YouTube con ffmpeg diretto) si scarica tutto invece di fallire."""
    chieste = []

    def finto(url, cartella, altezza, secondi=None):
        chieste.append(secondi)
        if secondi:
            raise web.WebError("ffmpeg exited with code 1")
        f = cartella / "intero.mp4"
        f.write_bytes(b"x")
        return f

    monkeypatch.setattr(web, "_scarica_ytdlp", finto)
    d = web.scarica(f"{sito}/pagina", tmp_path, 480, secondi=95)
    assert d["path"].endswith("intero.mp4") and chieste == [95, None]
    with pytest.raises(web.WebError):
        monkeypatch.setattr(web, "_scarica_ytdlp", lambda *a, **k: (_ for _ in ()).throw(
            web.WebError("rotto")))
        web.scarica(f"{sito}/pagina", tmp_path)
