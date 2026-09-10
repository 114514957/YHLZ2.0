"""Reliably (re)start the NapCat online watcher: kill all napcat_watch
processes, clear the stale lock, spawn ONE, verify. 
Usage: python tools/napcat_watch_restart.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

import psutil

_ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = _ROOT / ".venv" / "Scripts" / "python.exe"


def _pids() -> list[int]:
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = p.info.get("cmdline") or []
        except Exception:
            continue
        if any("napcat_watch.py" in str(x) for x in cl):
            out.append(p.info["pid"])
    return out


def main() -> int:
    killed = 0
    for pid in _pids():
        try:
            psutil.Process(pid).kill()
            killed += 1
        except Exception:
            pass
    time.sleep(2)
    for f in ("napcat_watch.lock", "napcat_status.json"):
        try:
            (_ROOT / "cache" / "tmp" / f).unlink()
        except Exception:
            pass
    subprocess.Popen([str(PY), "-B", str(_ROOT / "tools" / "napcat_watch.py")],
                     cwd=str(_ROOT), close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(7)
    now = _pids()
    print(f"killed={killed} now={len(now)} pids={now}")
    return 0 if now else 1


if __name__ == "__main__":
    raise SystemExit(main())
