"""I processi lanciati da vedit muoiono con vedit (Windows).

Il difetto da cui nasce: chiuso l'editor, un export a grafo unico e' rimasto
acceso da solo per ore a 20 GB di memoria.
"""

import os
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Job Object: solo Windows")

PADRE = r"""
import os, subprocess, sys, time
from vedit import figli
assert figli.lega_figli()
zitto = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
figlio = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **zitto)
staccato = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            creationflags=0x01000000, **zitto)   # come il browser dell'utente
print(figlio.pid, staccato.pid, flush=True)
time.sleep(0.5)
os._exit(0)   # muore di colpo, come un editor chiuso
"""


def _vivo(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                         capture_output=True, text=True).stdout
    return str(pid) in out


def test_i_figli_muoiono_col_padre_il_browser_no():
    r = subprocess.run([sys.executable, "-c", PADRE], capture_output=True, text=True, timeout=60)
    figlio, staccato = map(int, r.stdout.split())
    try:
        for _ in range(50):
            if not _vivo(figlio):
                break
            time.sleep(0.1)
        assert not _vivo(figlio), "il processo figlio e' sopravvissuto a vedit"
        assert _vivo(staccato), "il browser dell'utente non deve chiudersi con vedit"
    finally:
        subprocess.run(["taskkill", "/F", "/PID", str(staccato)], capture_output=True)
