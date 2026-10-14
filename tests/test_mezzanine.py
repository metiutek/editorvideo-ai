"""Export da montaggio: ProRes e DNxHR in .mov e .mxf, con audio PCM 24 bit.

Sono i file che si passano a chi finisce il lavoro in Premiere, Resolve, Avid o
Final Cut: ogni fotogramma a se', 10 bit, nessuna perdita al passaggio.
"""

import json
import subprocess

import pytest

from vedit import ffmpeg, hw, render
from vedit.store import Store


def _streams(path) -> list[dict]:
    out = subprocess.run([ffmpeg.binary("ffprobe"), "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,profile,pix_fmt,sample_fmt,sample_rate",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["streams"]


def test_codec_e_contenitore_controllati_prima():
    render.controlla_codec("prores", "x.mov")
    render.controlla_codec("dnxhr", "x.mxf")
    # .mxf impone DNxHR come .webm impone VP9: non e' un errore
    render.controlla_codec("h264", "x.mxf")
    with pytest.raises(ValueError, match="mov"):
        render.controlla_codec("prores", "x.mp4")
    with pytest.raises(ValueError, match="unknown"):
        render.controlla_codec("mpeg2", "x.mov")


def test_profili_per_qualita():
    # niente GPU per i mezzanine, anche se la macchina ne ha una
    assert hw.detect().encoder_for("prores") == "prores_ks"
    assert hw.detect().encoder_for("dnxhr", prefer_hw=True) == "dnxhd"
    assert hw.encoder_args("prores_ks", "draft")[:4] == ["-c:v", "prores_ks", "-profile:v", "0"]
    assert hw.encoder_args("prores_ks", "high")[3] == "3"
    assert hw.encoder_args("prores_ks", "max")[3] == "4"
    assert hw.encoder_args("dnxhd", "medium")[-1] == "dnxhr_sq"
    assert hw.encoder_args("dnxhd", "max")[-1] == "dnxhr_hqx"
    # il bitrate non tocca un profilo fisso
    assert "-b:v" not in hw.encoder_args("dnxhd", "high", "10M")
    assert hw.pix_fmt("prores_ks", "high") == "yuv422p10le"
    assert hw.pix_fmt("prores_ks", "max") == "yuv444p10le"
    assert hw.pix_fmt("dnxhd", "max") == "yuv422p10le"
    assert hw.pix_fmt("libx264") == "yuv420p"


def test_comando_mezzanine(tmp_path, assets):
    s = Store.create("m", "720p")
    m = s.import_media([assets["red"]])[0]
    s.add_clip(m.id, duration=1)
    args, _, _, enc = render.build_command(
        s.project, render.RenderOptions(output=str(tmp_path / "o.mxf"), codec="h264"), tmp_path)
    assert enc == "dnxhd"
    assert args[args.index("-c:a") + 1] == "pcm_s24le" and "-b:a" not in args
    assert args[args.index("-pix_fmt") + 1] == "yuv422p"


@pytest.mark.slow
@pytest.mark.parametrize("codec, nome, quality, atteso, profilo, pix", [
    ("prores", "o.mov", "high", "prores", "HQ", "yuv422p10le"),
    ("dnxhr", "o.mxf", "high", "dnxhd", "DNXHR HQ", "yuv422p"),
    ("prores", "o.mxf", "max", "prores", "4444", None),
])
def test_render_mezzanine(tmp_path, assets, codec, nome, quality, atteso, profilo, pix):
    s = Store.create("m", "720p")
    m = s.import_media([assets["red"]])[0]
    s.add_clip(m.id, duration=1)
    out = tmp_path / nome
    render.render(s.project, render.RenderOptions(output=str(out), codec=codec, quality=quality))
    st = _streams(out)
    v = next(x for x in st if x["codec_type"] == "video")
    a = next(x for x in st if x["codec_type"] == "audio")
    assert (v["codec_name"], v["profile"]) == (atteso, profilo)
    if pix:
        assert v["pix_fmt"] == pix
    assert a["codec_name"] == "pcm_s24le" and a["sample_rate"] == "48000"


@pytest.mark.slow
def test_mezzanine_a_pezzi(tmp_path, assets):
    """Il render a pezzi paralleli incolla ProRes senza ricodifica e senza perdere l'audio."""
    s = Store.create("m", "720p")
    m = s.import_media([assets["red"]])[0]
    for _ in range(8):
        s.add_clip(m.id, duration=3)
    out = tmp_path / "lungo.mov"
    r = render.render(s.project, render.RenderOptions(output=str(out), codec="prores",
                                                      quality="draft"))
    assert any("pezzi" in w for w in r.warnings)
    st = _streams(out)
    assert {x["codec_name"] for x in st} == {"prores", "pcm_s24le"}
