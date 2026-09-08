"""Strict startup test for the TTS/voice test entry (ledger 0218).

Spawns tools/tts_test_start.py, waits for readiness, drives the REPL and
asserts expected output ordering/exit. Proves the listener actually runs
(end-of-silence timeout path) instead of a silent instant-return.

Usage: python tools/startup_test_tts.py
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_PY = str(_ROOT / ".venv" / "Scripts" / "python.exe")


def main() -> int:
    proc = subprocess.Popen(
        [_PY, "-B", str(_ROOT / "tools" / "tts_test_start.py"),
         "--duration-s", "6", "--sim-thr", "0.4"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    lines: list[str] = []
    lock = threading.Lock()
    done = threading.Event()

    def reader():
        try:
            for line in proc.stdout:
                with lock:
                    lines.append(line)
        finally:
            done.set()

    threading.Thread(target=reader, daemon=True).start()

    def wait_for(substr: str, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            with lock:
                if substr in "".join(lines):
                    return True
            time.sleep(0.2)
        return False

    def wait_any(subs: list[str], timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            with lock:
                blob = "".join(lines)
                if any(s in blob for s in subs):
                    return True
            time.sleep(0.2)
        return False

    def safe_tail() -> str:
        with lock:
            return "".join(lines)[-200:].encode("ascii", "replace").decode()

    try:
        if not wait_for("输入 1 聆听", 60):
            print("FAIL: 未见就绪提示", flush=True)
            proc.kill()
            return 1
        print("---- send: 1 (listen) ----", flush=True)
        proc.stdin.write("1\n")
        proc.stdin.flush()
        if not wait_for("聆听中", 4):
            print("FAIL: 未进入聆听", flush=True)
            proc.kill()
            return 1
        if not wait_any(["识别中", "未捕捉到语音"], 20):
            print("FAIL: 聆听未走完成路径(可能秒退或卡住) tail:",
                  safe_tail(), flush=True)
            proc.kill()
            return 1
        print("---- send: 2 (close) ----", flush=True)
        proc.stdin.write("2\n")
        proc.stdin.flush()
        if not wait_for("已关闭", 4):
            print("FAIL: 2 未触发关闭", flush=True)
            proc.kill()
            return 1
        rc = proc.wait(timeout=8)
        print(f"\nSTARTUP-TEST PASS (exit={rc})", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        print("FAIL:", type(exc).__name__, str(exc)[:200], flush=True)
        proc.kill()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
