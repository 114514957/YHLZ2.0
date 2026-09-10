"""Startup test for the watchdog (ledger 0226): --once ensures stack healthy.

Usage: python tools/startup_test_watchdog.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    py = str(_ROOT / ".venv" / "Scripts" / "python.exe")
    p = subprocess.run([py, "-B", str(_ROOT / "tools" / "yhlz_watchdog.py"),
                        "--once"], cwd=str(_ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=180)
    out = (p.stdout or "") + (p.stderr or "")
    if "once:" in out and p.returncode == 0:
        print("WATCHDOG STARTUP-TEST PASS", flush=True)
        return 0
    print("FAIL rc=", p.returncode, out[-400:], flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
