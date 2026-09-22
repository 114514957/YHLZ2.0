"""GPU 唱窗 (ledger 0457): free the 8GB card for SoulX-Singer singing.

Measured peaks: SVC ~7.4GB; the v7b LLM holds ~4.5GB and the daemon's resident
Qwen-TTS clone ~2.4GB — so singing needs an exclusive window. open_window()
stops the watchdog + llama-server (the caller must also unload its TTS engine);
close_window() brings both back. All steps are best-effort and reported.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

_WATCH = "yhlz_watch" + "dog"   # split so process scans never self-match
_LLAMA = "llama-serv" + "er"


def _procs(match: str) -> list[int]:
    try:
        import psutil
    except Exception:
        return []
    out: list[int] = []
    for p in psutil.process_iter(["pid", "cmdline", "name"]):
        try:
            cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
            nm = str(p.info.get("name") or "")
            if match in cl or match in nm:
                out.append(int(p.info["pid"]))
        except Exception:
            continue
    return out


def _kill(match: str) -> int:
    n = 0
    try:
        import psutil
    except Exception:
        return 0
    for pid in _procs(match):
        try:
            psutil.Process(pid).kill()
            n += 1
        except Exception:
            pass
    return n


def _free_mb() -> int:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
        return int(str(r.stdout).strip().splitlines()[0])
    except Exception:
        return 0


def state() -> dict:
    return {"free_mb": _free_mb(), "llama": bool(_procs(_LLAMA)),
            "watchdog": bool(_procs(_WATCH))}


def open_window(require_free_mb: int = 6500, timeout: float = 150.0) -> dict:
    """Stop the watchdog + LLM and wait until enough VRAM is free."""
    killed = {"watchdog": _kill(_WATCH), "llama": _kill(_LLAMA)}
    t0 = time.time()
    free = _free_mb()
    while free < require_free_mb and time.time() - t0 < timeout:
        time.sleep(3)
        free = _free_mb()
    return {"ok": free >= require_free_mb, "free_mb": free,
            "killed": killed, "waited_s": round(time.time() - t0, 1)}


def close_window() -> dict:
    """Bring back llama-server and the watchdog."""
    out: dict = {"llama": False, "watchdog": False}
    try:
        tools = str(_ROOT / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import yhlz_launcher as yl

        yl._spawn_llama()
        out["llama"] = True
    except Exception as exc:  # noqa: BLE001
        out["llama_error"] = type(exc).__name__
    try:
        if not _procs(_WATCH):
            pyw = _ROOT / ".venv" / "Scripts" / "pythonw.exe"
            subprocess.Popen(
                [str(pyw), "-B", str(_ROOT / "tools" / "yhlz_watchdog.py")],
                cwd=str(_ROOT), close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out["watchdog"] = True
    except Exception as exc:  # noqa: BLE001
        out["watchdog_error"] = type(exc).__name__
    return out
