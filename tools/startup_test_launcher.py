"""Startup test for the desktop launcher (ledger 0223).

Spawns tools/yhlz_launcher.py --stay, asserts the boot page is served with the
title and animation asset, /api/status responds, and the launcher exits 0 once
all services are ready.

Usage: python tools/startup_test_launcher.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PY = str(_ROOT / ".venv" / "Scripts" / "python.exe")
BOOT = "http://127.0.0.1:8577"


def _fetch(path: str, timeout: float = 4):
    with urllib.request.urlopen(BOOT + path, timeout=timeout) as r:
        return r.status, r.read()


def main() -> int:
    proc = subprocess.Popen(
        [_PY, "-B", str(_ROOT / "tools" / "yhlz_launcher.py"), "--stay"],
        cwd=str(_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        ok_page = False
        end = time.time() + 30
        while time.time() < end:
            try:
                code, body = _fetch("/")
                if code == 200 and "元 · 亨 · 利 · 贞" in body.decode("utf-8"):
                    ok_page = True
                    break
            except Exception:
                time.sleep(0.3)
        if not ok_page:
            print("FAIL: 启动页未就绪/缺标题", flush=True)
            return 1
        print("OK: boot page + title", flush=True)
        code, body = _fetch("/loading.webp")
        if code != 200 or not body.startswith(b"RIFF"):
            print("FAIL: loading.webp 未由启动页提供", flush=True)
            return 1
        print("OK: loading.webp served", flush=True)
        code, body = _fetch("/api/status")
        st = json.loads(body)
        print("OK: /api/status =", st, flush=True)
        rc = proc.wait(timeout=80)
        if rc != 0:
            print("FAIL: launcher exit", rc, flush=True)
            return 1
        print("STARTUP-TEST PASS (launcher exit 0)", flush=True)
        return 0
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
