"""La correzione colore fa quello che dice, nella direzione giusta.

test_effects verifica che ogni filtro renda; qui si guarda il *risultato*. E'
il controllo che mancava: la temperatura colore era descritta al contrario
("sotto 6500 raffredda") e due preset ne erano usciti invertiti — il
"caldo tramonto" veniva blu e il "freddo notturno" arancione.
"""

import pytest
from PIL import Image

from vedit import presets, render
from vedit.store import Store

pytestmark = pytest.mark.slow


def _pixel(tmp_path, colore: str, effetti: list[tuple[str, dict]]) -> tuple[int, int, int]:
    """Colore al centro di un fotogramma pieno, dopo gli effetti."""
    s = Store.create("c", "720p")
    s.set_settings(width=320, height=180)
    c = s.add_color(colore, duration=1)
    for nome, params in effetti:
        s.add_effect(c.id, nome, params)
    out = tmp_path / "f.png"
    render.render_frame(s.project, 0.5, str(out), width=320, use_proxy=False)
    return Image.open(out).convert("RGB").getpixel((160, 90))


def _luma(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _sat(rgb):
    return max(rgb) - min(rgb)


GRIGIO = "0x808080"


def test_temperatura_bassa_scalda_alta_raffredda(tmp_path):
    caldo = _pixel(tmp_path, GRIGIO, [("temperature", {"temperature": 3000})])
    freddo = _pixel(tmp_path, GRIGIO, [("temperature", {"temperature": 11000})])
    assert caldo[0] > caldo[2] + 20, caldo
    assert freddo[2] > freddo[0] + 10, freddo


def test_preset_caldo_e_freddo_non_sono_invertiti(tmp_path):
    def preset(pid):
        p = presets.find(pid)
        return _pixel(tmp_path, GRIGIO, [(e["type"], e["params"]) for e in p["effects"]])

    caldo = preset("caldo_tramonto")
    freddo = preset("freddo_notturno")
    assert caldo[0] > caldo[2], f"il caldo tramonto e' blu: {caldo}"
    assert freddo[2] > freddo[0], f"il freddo notturno e' arancione: {freddo}"


def test_bilanciamento_del_bianco_temperatura_e_tinta(tmp_path):
    caldo = _pixel(tmp_path, GRIGIO, [("whitebalance", {"temperature": 3500})])
    assert caldo[0] > caldo[2] + 15
    magenta = _pixel(tmp_path, GRIGIO, [("whitebalance", {"tint": 0.8})])
    verde = _pixel(tmp_path, GRIGIO, [("whitebalance", {"tint": -0.8})])
    assert magenta[1] < min(magenta[0], magenta[2]), magenta
    assert verde[1] > max(verde[0], verde[2]), verde
    # a zero non tocca niente
    neutro = _pixel(tmp_path, GRIGIO, [("whitebalance", {})])
    assert _sat(neutro) <= 4


def test_bilanciamento_automatico_toglie_la_dominante(tmp_path):
    dominante = _pixel(tmp_path, "0xa07060", [])
    corretto = _pixel(tmp_path, "0xa07060", [("autowhite", {})])
    assert _sat(corretto) < _sat(dominante) / 2, (dominante, corretto)


def test_esposizione_e_luminosita(tmp_path):
    base = _luma(_pixel(tmp_path, GRIGIO, []))
    assert _luma(_pixel(tmp_path, GRIGIO, [("exposure", {"exposure": 1})])) > base + 30
    assert _luma(_pixel(tmp_path, GRIGIO, [("exposure", {"exposure": -1})])) < base - 30
    assert _luma(_pixel(tmp_path, GRIGIO, [("color", {"brightness": 0.2})])) > base + 20


def test_saturazione_e_vividezza(tmp_path):
    spento = "0x8c7a70"
    base = _sat(_pixel(tmp_path, spento, []))
    assert _sat(_pixel(tmp_path, spento, [("vibrance", {"intensity": 1.5})])) > base
    assert _sat(_pixel(tmp_path, "0xc04040", [("color", {"saturation": 0})])) <= 4


def test_tonalita_ruota_i_colori(tmp_path):
    rosso = _pixel(tmp_path, "0xc03030", [("hue", {"hue": 120})])
    assert rosso[1] > rosso[0] and rosso[1] > rosso[2], f"ruotato di 120 gradi il rosso diventa verde: {rosso}"


def test_correzione_di_un_solo_colore(tmp_path):
    """Spegnere i blu non deve toccare i rossi."""
    blu = _pixel(tmp_path, "0x3050d0", [("hsl", {"colors": "blu", "saturation": -1})])
    rosso = _pixel(tmp_path, "0xd03030", [("hsl", {"colors": "blu", "saturation": -1})])
    rosso_base = _pixel(tmp_path, "0xd03030", [])
    assert _sat(blu) < 40, blu
    assert abs(_sat(rosso) - _sat(rosso_base)) < 12, (rosso, rosso_base)


def test_livelli_schiacciano_i_neri(tmp_path):
    scuro = "0x404040"
    base = _luma(_pixel(tmp_path, scuro, []))
    assert _luma(_pixel(tmp_path, scuro, [("levels", {"black_in": 0.2})])) < base - 15
    assert _luma(_pixel(tmp_path, scuro, [("levels", {"black_out": 0.3})])) > base + 15


def test_bilanciamento_per_zone(tmp_path):
    """colorbalance: piu' rosso nelle ombre arrossa un grigio scuro."""
    scuro = _pixel(tmp_path, "0x303030", [("colorbalance", {"rs": 0.5})])
    assert scuro[0] > scuro[2] + 10, scuro


def test_bilanciamento_mezzitoni_su_tutti_i_grigi(tmp_path):
    """Il difetto del colorbalance di ffmpeg: i mezzitoni non toccavano il grigio medio."""
    for g in ("0x404040", "0x808080", "0xc0c0c0"):
        r, _, b = _pixel(tmp_path, g, [("colorbalance", {"rm": 0.5})])
        assert r > b + 8, (g, r, b)
    # ombre e luci restano dove devono
    scuro = _pixel(tmp_path, "0x202020", [("colorbalance", {"bh": 0.6})])
    chiaro = _pixel(tmp_path, "0xe0e0e0", [("colorbalance", {"bh": 0.6})])
    assert chiaro[2] - chiaro[0] > scuro[2] - scuro[0], (scuro, chiaro)


def test_teal_and_orange_resta_teal_and_orange(tmp_path):
    p = presets.find("cinema_teal_orange")
    eff = [(e["type"], e["params"]) for e in p["effects"]]
    ombra = _pixel(tmp_path, "0x303030", eff)
    luce = _pixel(tmp_path, "0xd0d0d0", eff)
    assert ombra[2] > ombra[0], f"ombre non fredde: {ombra}"
    assert luce[0] > luce[2], f"luci non calde: {luce}"
