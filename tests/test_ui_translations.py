"""Le etichette integrate lette dall'API hanno una traduzione locale."""
import json
import re
from pathlib import Path

from vedit import blocchi, effects, llm, presets


def test_cataloghi_integrati_tradotti():
    dizionario = json.loads((Path(__file__).resolve().parents[1] / "frontend/src/locales/zh-CN.json").read_text(encoding="utf-8"))
    testi = []
    for effetto in effects.describe():
        testi.extend([effetto["label"], effetto["desc"]])
        for parametro in effetto["params"]:
            testi.extend([parametro["name"], parametro["desc"], *parametro["choices"]])
    for categoria in presets.describe().values():
        for p in categoria:
            testi.extend([p["name"], p["desc"], p["group"]])
    for blocco in blocchi.elenco():
        testi.extend([blocco["id"].replace("_", " "), blocco["categoria"], blocco["descrizione"]])
        for nome, parametro in blocco["parametri"].items():
            testi.extend([nome.replace("_", " "), parametro["descrizione"], *parametro.get("scelte", [])])
    for provider in llm.PROVIDERS:
        testi.extend([provider["nome"], provider.get("nota", "")])
    mancanti = {t for t in testi if isinstance(t, str) and re.search("[A-Za-z]", t) and t not in dizionario}
    assert not mancanti, f"Missing Chinese catalog labels: {sorted(mancanti)}"
