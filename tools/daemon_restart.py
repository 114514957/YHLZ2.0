"""Reliably (re)start the YHLZ daemon (8321): kill all target_daemon
processes, spawn one, verify. Usage: python tools/daemon_restart.py
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
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cl = p.info.get("cmdline") or []
        except Exception:
            continue
        if ("target_daemon" in " ".join(str(x) for x in cl)
                and (p.info.get("name") or "").startswith("python")):
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
    time.sleep(3)
    subprocess.Popen([str(PY), "-B", "-m", "backend.target_daemon",
                      "--port", "8321"], cwd=str(_ROOT), close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(10)
    now = _pids()
    print(f"killed={killed} now={len(now)} pids={now}")
    return 0 if now else 1


if __name__ == "__main__":
    raise SystemExit(main())
