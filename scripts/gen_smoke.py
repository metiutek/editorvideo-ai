"""Prova di `generate_media` contro un servizio vero, con la TUA chiave.

    python scripts/gen_smoke.py --kind image --prompt "a red apple on a wooden table"
    python scripts/gen_smoke.py --kind video --prompt "a slow dolly toward a lighthouse" --yes
    python scripts/gen_smoke.py --kind image --service fal --yes

Perche' esiste: i test usano servizi finti, quindi non dicono se i modelli predefiniti
(`generativo.MOTORI`) esistono ancora o se il servizio e' cambiato. Questo si'. Senza
``--yes`` stampa cosa partirebbe (servizio, modello, prompt) e si ferma: generare costa e il
prompt va a un terzo. Con ``--yes`` genera in una cartella temporanea, controlla che il file
si apra e lo stampa. Le chiavi sono quelle gia' configurate (`vedit gen-setup`, o le
variabili d'ambiente): niente viene scritto qui.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "backend"))

from vedit import ffmpeg, generativo  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kind", choices=("image", "video"), default="image")
    ap.add_argument("--prompt", default="a red apple on a wooden table, soft window light")
    ap.add_argument("--service", help="openai, fal... (default: quello impostato)")
    ap.add_argument("--model", help="modello (default: quello del servizio)")
    ap.add_argument("--duration", type=float, help="secondi, per il video")
    ap.add_argument("--yes", action="store_true", help="genera davvero (costa)")
    a = ap.parse_args()

    try:
        m = generativo.scelto(a.service, a.kind)
    except generativo.GenError as exc:
        print(f"niente da provare: {exc}")
        return 2
    modello = a.model or generativo._modello(m, generativo.carica(), a.kind)
    print(f"servizio: {m['nome']}   modello: {modello}   tipo: {a.kind}")
    print(f"prompt:   {a.prompt}")
    if not a.yes:
        print("\nNon e' partito niente. Con --yes genera davvero (puo' costare crediti).")
        return 0

    cartella = Path(tempfile.mkdtemp(prefix="vedit_gen_smoke_"))
    try:
        res = generativo.genera(a.kind, a.prompt, cartella, a.service, a.model, "16:9", a.duration,
                                avanza=lambda f, nota: print(f"  {f:4.0%} {nota}"))
    except generativo.GenError as exc:
        print(f"\nFALLITO: {exc}")
        return 1
    p = Path(res["path"])
    print(f"\nfile: {p}  ({p.stat().st_size // 1024} KB)  servizio={res['servizio']} modello={res['modello']}")
    if a.kind == "image":
        from PIL import Image

        with Image.open(p) as im:
            print(f"si apre: {im.size[0]}x{im.size[1]}")
    else:
        out = subprocess.run([ffmpeg.binary("ffprobe"), "-v", "error", "-show_entries",
                              "stream=codec_name,width,height,duration", "-of", "default=nw=1", str(p)],
                             capture_output=True, text=True)
        print(out.stdout.strip() or out.stderr.strip())
    print("\nOK: il servizio risponde e i modelli predefiniti esistono.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
