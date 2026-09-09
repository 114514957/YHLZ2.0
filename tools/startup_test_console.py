"""Startup test for the workbench UI on the DAEMON port (ledger 0223, port
consolidation). Spawns an isolated daemon (8331) whose handler now also
serves the console UI + /talk + /voice; asserts readiness + streams.

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
PORT = 8331


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


def _stream_post(path: str, body: dict, timeout: float = 90) -> dict:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=payload,
                                 headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=timeout)
    frames = deltas = 0
    done = ok = False
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
        elif ev["type"] == "voice_done":
            ok = ev.get("status") == "ok"
    return {"frames": frames, "deltas": deltas, "done": done, "voice_ok": ok}


def main() -> int:
    proc = subprocess.Popen(
        [_PY, "-B", "-m", "backend.target_daemon", "--port", str(PORT)],
        cwd=str(_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_state(PORT, 45):
            print("FAIL: /state 未就绪", flush=True)
            return 1
        print("OK: /state on daemon port", flush=True)
        home = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/",
                                      timeout=5).read()
        if "元亨" not in home.decode("utf-8", "replace"):
            print("FAIL: index 未由 daemon 端口提供", flush=True)
            return 1
        print("OK: index.html served on daemon port", flush=True)
        t = _stream_post("/talk", {"text": "说三个字"})
        if t["frames"] >= 3 and t["deltas"] >= 1 and t["done"]:
            print(f"OK: /talk stream deltas={t['deltas']}", flush=True)
        else:
            print(f"FAIL: /talk {t}", flush=True)
            return 1
        v = _stream_post("/voice", {"text": "说三个字", "speak": "0"})
        if v["deltas"] >= 1 and v["voice_ok"]:
            print(f"OK: /voice mock deltas={v['deltas']}", flush=True)
            return 0
        print(f"FAIL: /voice {v}", flush=True)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
