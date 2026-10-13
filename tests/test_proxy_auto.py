"""Proxy automatici: i file che il browser non sa riprodurre non restano neri."""

import subprocess
from pathlib import Path

import pytest

from vedit import api as api_mod
from vedit import ffmpeg, probe, proxy
from vedit.model import Media
from vedit.store import Store


@pytest.fixture(scope="module")
def dnxhr(tmp_path_factory) -> str:
    """Come gli export di Resolve: .mov DNxHR HQ 4:2:2 con audio PCM."""
    p = tmp_path_factory.mktemp("dnx") / "pronto.mov"
    subprocess.run([ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=s=640x360:r=25:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                    "-c:v", "dnxhd", "-profile:v", "dnxhr_hq", "-pix_fmt", "yuv422p",
                    "-c:a", "pcm_s16le", "-shortest", str(p)],
                   check=True, capture_output=True)
    return str(p)


def test_capisce_cosa_il_browser_sa_riprodurre(assets, dnxhr):
    assert not proxy.serve_proxy(probe.probe(assets["red"]))      # h264 + aac in mp4
    m = probe.probe(dnxhr)
    assert (m.vcodec, m.acodec, m.pix_fmt) == ("dnxhd", "pcm_s16le", "yuv422p")
    assert proxy.serve_proxy(m)
    # il codec da solo non basta: anche il formato dei pixel e il contenitore
    assert proxy.serve_proxy(Media(path="a.mp4", vcodec="h264", pix_fmt="yuv420p10le"))
    assert proxy.serve_proxy(Media(path="a.mts", vcodec="h264", pix_fmt="yuv420p"))
    assert proxy.serve_proxy(Media(path="a.mp4", vcodec="hevc", pix_fmt="yuv420p"))
    wav = Media(path="a.wav", kind="audio", has_video=False, has_audio=True, acodec="pcm_s16le")
    assert not proxy.serve_proxy(wav)


def test_progetti_vecchi_leggono_il_codec_dal_file(dnxhr):
    m = probe.probe(dnxhr)
    m.vcodec = m.acodec = m.pix_fmt = ""          # salvato prima del campo
    proxy.completa_codec(m)
    assert m.vcodec == "dnxhd"


@pytest.mark.slow
def test_il_proxy_si_prepara_da_solo(tmp_path, assets, dnxhr):
    s = Store.create(name="t", path=str(tmp_path / "p.json"))
    s.import_media([assets["red"], dnxhr])
    api_mod.S.store = s
    try:
        api_mod._proxy_mancanti()
    finally:
        api_mod.S.store = None
    rosso, pronto = s.project.media
    assert rosso.proxy is None                     # l'mp4 si riproduce com'e'
    assert pronto.proxy and Path(pronto.proxy).is_file()
    m = probe.probe(pronto.proxy)
    assert (m.vcodec, m.acodec, m.pix_fmt) == ("h264", "aac", "yuv420p")
    assert not proxy.serve_proxy(m)
    # salvato: alla riapertura il proxy c'e' gia', niente da rifare
    assert Store.open(s.path).project.media[1].proxy == pronto.proxy
    assert proxy.da_preparare(s.project) == []
