"""GPU 唱窗 (ledger 0457): free the 8GB card for SoulX-Singer singing.

Measured peaks: SVC ~7.4GB; the v7b LLM holds ~4.5GB and the daemon's resident
Qwen-TTS clone ~2.4GB — so singing needs an exclusive window. open_window()
pauses llama-server via a flag and keeps the independent watchdog alive;
close_window() clears the flag and lets the supervisor resume llama. All
steps are best-effort and reported.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

_WATCH = "yhlz_watch" + "dog"   # running as yhlz_watchdog.py (python)
_LLAMA = "llama-serv" + "er"    # image name: llama-server.exe
_FLAG = _ROOT / "cache" / "gpu_window.lock"


def _set_window(active: bool) -> None:
    try:
        if active:
            _FLAG.parent.mkdir(parents=True, exist_ok=True)
            _FLAG.write_text(str(time.time()), encoding="utf-8")
        else:
            _FLAG.unlink(missing_ok=True)
    except Exception:
        pass


def _find_pids(*, exe: str = "", script: str = "") -> list[int]:
    """Robust service detection (2026-10-12 hardening).

    - `exe`: image-name EXACT match (llama-server.exe);
    - `script`: python/pythonw interpreter whose argv carries the script
      (element ends with the marker or marker + ".py").

    Shells/tails/scripts that merely *mention* a name in their command text
    no longer count as the service being alive — that false positive once
    skipped the llama respawn after an official-UI session.
    """
    try:
        import psutil
    except Exception:
        return []
    out: list[int] = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            nm = str(p.info.get("name") or "").lower()
            cl = [str(x).replace("\\", "/").lower()
                  for x in (p.info.get("cmdline") or [])]
        except Exception:
            continue
        hit = False
        if exe and nm == exe.lower():
            hit = True
        if script and nm.startswith("python"):
            lo = script.lower()
            if any(x.endswith(lo) or x.endswith(lo + ".py") for x in cl):
                hit = True
        if hit:
            out.append(int(p.info["pid"]))
    return out


def _kill_pids(pids: list[int]) -> int:
    n = 0
    try:
        import psutil
    except Exception:
        return 0
    for pid in pids:
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
    return {"free_mb": _free_mb(),
            "llama": bool(_find_pids(exe=_LLAMA + ".exe")),
            "watchdog": bool(_find_pids(script=_WATCH)),
            "window": _FLAG.exists()}


def open_window(require_free_mb: int = 6500, timeout: float = 150.0) -> dict:
    """Pause LLM for a singing/Seed-VC window.

    2026-10-21 P0: do **not** kill the watchdog. It is the independent
    supervisor; killing it here is what left the stack down on 21:02. Write a
    flag instead, so the watchdog stays alive but skips llama while the window
    is open. Only llama (the VRAM holder) is stopped.
    """
    _set_window(True)
    killed = {"llama": _kill_pids(_find_pids(exe=_LLAMA + ".exe")),
              "watchdog_kept": bool(_find_pids(script=_WATCH))}
    # WSL caches GPU memory for the VM lifetime — drop the distro so the
    # window actually gets the VRAM back (it restarts in seconds).
    try:
        subprocess.run(["wsl.exe", "--terminate", "Ubuntu-22.04"],
                       capture_output=True, timeout=20)
    except Exception:
        pass
    t0 = time.time()
    free = _free_mb()
    while free < require_free_mb and time.time() - t0 < timeout:
        time.sleep(1)
        free = _free_mb()
    if free < require_free_mb:
        # A failed window must not keep the LLM down forever.
        _set_window(False)
    return {"ok": free >= require_free_mb, "free_mb": free,
            "killed": killed, "waited_s": round(time.time() - t0, 1)}


def close_window() -> dict:
    """Close the GPU window and let the independent supervisor resume llama."""
    _set_window(False)
    out: dict = {"llama": False, "watchdog": False}
    try:
        if _find_pids(exe=_LLAMA + ".exe"):
            out["llama"] = True          # already running (or never stopped)
        else:
            tools = str(_ROOT / "tools")
            if tools not in sys.path:
                sys.path.insert(0, tools)
            import yhlz_launcher as yl

            yl._spawn_llama()
            out["llama"] = True
    except Exception as exc:  # noqa: BLE001
        out["llama_error"] = type(exc).__name__
    try:
        if not _find_pids(script=_WATCH):
            pyw = _ROOT / ".venv" / "Scripts" / "pythonw.exe"
            flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                     | getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
            try:
                subprocess.Popen(
                    [str(pyw), "-B", str(_ROOT / "tools" / "yhlz_watchdog.py")],
                    cwd=str(_ROOT), close_fds=True, creationflags=flags)
            except Exception:
                subprocess.Popen(
                    [str(pyw), "-B", str(_ROOT / "tools" / "yhlz_watchdog.py")],
                    cwd=str(_ROOT), close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out["watchdog"] = True
    except Exception as exc:  # noqa: BLE001
        out["watchdog_error"] = type(exc).__name__
    return out
