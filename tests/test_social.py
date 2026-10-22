"""Pubblicazione: YouTube a riprese e TikTok contro un server finto locale."""

import http.server
import json
import threading

import pytest

from vedit import social
from vedit import mcp_server as srv


class _Finto(http.server.BaseHTTPRequestHandler):
    """Fa la parte di Google e TikTok: registra cosa arriva e risponde come loro."""

    viste: list = []
    ricevuti = bytearray()

    def _corpo(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _rispondi(self, codice, dati=None, headers=None):
        corpo = json.dumps(dati).encode() if dati is not None else b""
        self.send_response(codice)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):  # noqa: N802
        corpo = self._corpo()
        type(self).viste.append(("POST", self.path, dict(self.headers), corpo))
        if self.path == "/token":
            self._rispondi(200, {"access_token": "acc"})
        elif self.path.startswith("/yt-upload"):
            self._rispondi(200, {}, {"Location": f"http://127.0.0.1:{self.server.server_port}/sessione"})
        elif self.path == "/tt/inbox/video/init/":
            self._rispondi(200, {"data": {"publish_id": "p1", "upload_url":
                                          f"http://127.0.0.1:{self.server.server_port}/tt-put"},
                                 "error": {"code": "ok"}})
        else:
            self._rispondi(404, {"error": {"message": "no"}})

    def do_PUT(self):  # noqa: N802
        corpo = self._corpo()
        type(self).viste.append(("PUT", self.path, dict(self.headers), corpo))
        type(self).ricevuti += corpo
        totale = int(self.headers["Content-Range"].rsplit("/", 1)[1])
        if self.path == "/sessione" and len(type(self).ricevuti) < totale:
            # YouTube: "continua", con quanto ha ricevuto davvero
            self._rispondi(308, None, {"Range": f"bytes=0-{len(type(self).ricevuti) - 1}"})
        elif self.path == "/sessione":
            self._rispondi(200, {"id": "VID123"})
        else:
            self._rispondi(201, {})

    def log_message(self, *a):
        pass


@pytest.fixture
def finto(monkeypatch):
    _Finto.viste = []
    _Finto.ricevuti = bytearray()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Finto)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(social, "_TOKEN", f"{base}/token")
    monkeypatch.setattr(social, "_UPLOAD", f"{base}/yt-upload?uploadType=resumable")
    monkeypatch.setattr(social, "_TIKTOK", f"{base}/tt")
    monkeypatch.setattr(social, "_PEZZO_YT", 256 * 1024)
    yield _Finto
    server.shutdown()
    for p in social.PIATTAFORME:
        social.scollega(p)
    social.imposta("youtube", client_id="", client_secret="")


@pytest.fixture
def video(tmp_path):
    f = tmp_path / "finale.mp4"
    f.write_bytes(bytes(range(256)) * 3000)   # 768 kB: tre pezzi da 256 KiB
    return f


def test_stato_senza_segreti():
    social.imposta("youtube", client_id="id", client_secret="SEGRETO-XYZ")
    social.imposta("tiktok", token="TOKEN-XYZ")
    st = social.stato()
    assert st["youtube"] == {**st["youtube"], "client": True, "collegato": False}
    assert st["tiktok"]["collegato"] and not st["tiktok"]["scaduto"]
    assert "XYZ" not in json.dumps(st)
    social.scollega("tiktok")
    social.imposta("youtube", client_id="", client_secret="")


def test_youtube_a_riprese(finto, video):
    social.imposta("youtube", client_id="id", client_secret="s")
    social._aggiorna("youtube", refresh_token="r")
    passi = []
    r = social.pubblica("youtube", str(video), "Il <mio> video", "desc", ["#viaggi", " "],
                        progresso=passi.append)
    assert r == {"piattaforma": "youtube", "id": "VID123", "url": "https://youtu.be/VID123",
                 "privacy": "private"}
    assert bytes(finto.ricevuti) == video.read_bytes()
    meta = json.loads(next(v[3] for v in finto.viste if v[1].startswith("/yt-upload")))
    assert meta["snippet"]["title"] == "Il mio video"
    assert meta["snippet"]["tags"] == ["viaggi"]
    assert meta["status"]["privacyStatus"] == "private"
    assert passi[-1] == 1.0 and len(passi) == 3


def test_youtube_senza_login(video):
    with pytest.raises(social.SocialError, match="not connected"):
        social.pubblica("youtube", str(video), "t")
    with pytest.raises(social.SocialError, match="Export it first"):
        social.pubblica("youtube", "manca.mp4", "t")


def test_tiktok_casella(finto, video):
    social.imposta("tiktok", token="tok")
    r = social.pubblica("tiktok", str(video))
    assert r["id"] == "p1" and "inbox" in r["nota"]
    init = json.loads(next(v[3] for v in finto.viste if v[1].endswith("/init/")))
    n = video.stat().st_size
    assert init["source_info"] == {"source": "FILE_UPLOAD", "video_size": n,
                                   "chunk_size": n, "total_chunk_count": 1}
    put = next(v for v in finto.viste if v[0] == "PUT")
    assert put[2]["Content-Range"] == f"bytes 0-{n - 1}/{n}"
    assert bytes(finto.ricevuti) == video.read_bytes()


@pytest.mark.anyio
async def test_mcp_vuole_conferma(video):
    from test_mcp import call

    r = await call("publish_video", file=str(video), platform="youtube", title="t")
    assert r["pubblicato"] is False and "confirmed" in r["motivo"]
    assert "youtube" in await call("social_accounts")
