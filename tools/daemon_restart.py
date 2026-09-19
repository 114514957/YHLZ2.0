"""Reliably (re)start the YHLZ daemon (8321): kill all target_daemon
processes, spawn one, verify. Usage: python tools/daemon_restart.py
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import psutil  # noqa: E402

from yhlz_launcher import _spawn_daemon  # noqa: E402

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
    _spawn_daemon()  # F1: shared spawn with cache/logs/daemon.log redirect
    time.sleep(10)
    now = _pids()
    print(f"killed={killed} now={len(now)} pids={now}")
    return 0 if now else 1


if __name__ == "__main__":
    raise SystemExit(main())
