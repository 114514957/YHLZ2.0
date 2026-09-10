"""Reliably (re)start the QQ dev bridge: kill all qq_bot processes, clear the
stale lock, spawn ONE pythonw bridge, verify. Usage: python tools/qq_bot_restart.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

import psutil

_ROOT = pathlib.Path(__file__).resolve().parent.parent
UIN = "3655185302"
MASTER = "2258374446"


def _pids() -> list[int]:
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = p.info.get("cmdline") or []
        except Exception:
            continue
        if any("qq_bot.py" in str(x) for x in cl):
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
    lock = _ROOT / "cache" / "tmp" / "qqbot.lock"
    try:
        lock.unlink()
    except Exception:
        pass
    pyw = _ROOT / ".venv" / "Scripts" / "pythonw.exe"
    subprocess.Popen([str(pyw), "-B", str(_ROOT / "tools" / "qq_bot.py"),
                      "--uin", UIN, "--master", MASTER],
                     cwd=str(_ROOT), close_fds=True)
    time.sleep(7)
    now = _pids()
    print(f"killed={killed} now={len(now)} pids={now}")
    return 0 if now else 1


if __name__ == "__main__":
    raise SystemExit(main())
