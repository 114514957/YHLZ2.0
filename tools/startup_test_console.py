"""Startup test for the workbench console (M1, ledger 0222).

Spawns an isolated daemon (8331) + console (8332), waits for /state, does one
streaming /talk and asserts deltas + turn_done arrive, then closes.

Usage: python tools/startup_test_console.py
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


def _wait_state(port: int, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/state",
                                       timeout=3)
            return json.loads(r.read())["ok"] is True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    proc = subprocess.Popen(
        [_PY, "-B", "-m", "backend.target_daemon", "--port", "8331",
         "--console-port", "8332"],
        cwd=str(_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_state(8332, 45):
            print("FAIL: console /state 未就绪", flush=True)
            return 1
        print("OK: /state ready", flush=True)
        body = json.dumps({"text": "说三个字"}).encode()
        req = urllib.request.Request("http://127.0.0.1:8332/talk",
                                     data=body,
                                     headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=90)
        frames = 0
        deltas = 0
        done = False
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            frames += 1
            if ev["type"] == "delta":
                deltas += 1
            elif ev["type"] == "turn_done":
                done = True
        if frames >= 3 and deltas >= 1 and done:
            print(f"OK: talk stream frames={frames} deltas={deltas} done=Y",
                  flush=True)
            return 0
        print(f"FAIL: talk stream frames={frames} deltas={deltas} done={done}",
              flush=True)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
