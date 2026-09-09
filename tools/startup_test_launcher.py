"""Startup test for the desktop launcher (ledger 0223).

Spawns tools/yhlz_launcher.py --self-test and asserts the boot page serves
/, /api/status (all services ok) and /loading.webp, then exits cleanly.

Usage: python tools/startup_test_launcher.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    py = str(_ROOT / ".venv" / "Scripts" / "python.exe")
    p = subprocess.run(
        [py, "-B", str(_ROOT / "tools" / "yhlz_launcher.py"), "--self-test"],
        cwd=str(_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180,
    )
    out = (p.stdout or "") + (p.stderr or "")
    if "SELFTEST OK" in out and p.returncode == 0:
        print("LAUNCHER STARTUP-TEST PASS", flush=True)
        return 0
    print("FAIL rc=", p.returncode, out[-500:], flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
