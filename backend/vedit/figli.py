"""I processi figli muoiono con vedit.

Un export lanciato dall'interfaccia e' un ffmpeg figlio del server. Chiudendo
l'editor il server muore, ma su Windows i figli no: un export a grafo unico e'
rimasto acceso da solo per ore a 20 GB di memoria, con l'editor gia' chiuso e
riaperto, rallentando tutto il resto senza che si vedesse da dove.

Su Windows vedit entra all'avvio in un Job Object con "uccidi alla chiusura":
ogni processo che lancia (ffmpeg, Chromium per le clip html, la CLI di Claude
Code) eredita il job, e quando vedit muore — chiuso, terminato o caduto — il
sistema chiude anche loro. Il browser aperto per mostrare l'interfaccia e'
l'unica eccezione: e' dell'utente, quindi esce dal job (``apri_nel_browser``).

Altrove non serve: chiudendo il terminale il segnale arriva a tutto il gruppo.
"""

from __future__ import annotations

import os
import subprocess
import webbrowser

_job = None   # resta aperto per tutta la vita del processo: chiuderlo uccide i figli


def lega_figli() -> bool:
    """Mette questo processo in un job che chiude i figli quando muore. Vero se fatto."""
    global _job
    if os.name != "nt" or _job is not None:
        return _job is not None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                wintypes.LPVOID, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.GetCurrentProcess.restype = wintypes.HANDLE

        class _Base(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _Esteso(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Base), ("IoInfo", _Io),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        KILL_ON_JOB_CLOSE = 0x2000
        BREAKAWAY_OK = 0x800          # il browser dell'utente puo' uscirne
        ESTESO = 9                    # JobObjectExtendedLimitInformation

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = _Esteso()
        info.BasicLimitInformation.LimitFlags = KILL_ON_JOB_CLOSE | BREAKAWAY_OK
        if not k32.SetInformationJobObject(job, ESTESO, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return False
        if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            # gia' in un job che non lo permette: si resta come prima
            k32.CloseHandle(job)
            return False
        _job = job
        return True
    except (OSError, AttributeError, ValueError):
        return False


def apri_nel_browser(url: str) -> None:
    """Apre l'indirizzo nel browser dell'utente, fuori dal job: chiudere vedit non lo chiude."""
    if os.name == "nt" and _job is not None:
        try:
            CREATE_BREAKAWAY_FROM_JOB = 0x01000000
            subprocess.Popen(["cmd", "/c", "start", "", url],
                             creationflags=CREATE_BREAKAWAY_FROM_JOB
                             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return
        except OSError:
            pass
    webbrowser.open(url)
