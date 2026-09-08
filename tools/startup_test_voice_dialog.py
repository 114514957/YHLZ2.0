"""Startup test for the main voice dialog entry (ledger 0219).

Proves it boots through ASR + Yuanheng(Gemma) + Qwen3-TTS to the command
loop, and that 2 cleanly closes. Speech turn (1) needs a real mic so it is
not exercised here.

Usage: python tools/startup_test_voice_dialog.py
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
        [_PY, "-B", str(_ROOT / "tools" / "voice_dialog.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    lines: list[str] = []
    lock = threading.Lock()

    def reader():
        try:
            for line in proc.stdout:
                with lock:
                    lines.append(line)
        finally:
            pass

    threading.Thread(target=reader, daemon=True).start()

    def wait_for(substr: str, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            with lock:
                if substr in "".join(lines):
                    return True
            time.sleep(0.2)
        return False

    try:
        if not wait_for("就绪。输入 1 说话", 150):
            with lock:
                blob = "".join(lines)[-260:].encode("ascii", "replace").decode()
            print("FAIL: 未就绪 tail:", blob, flush=True)
            proc.kill()
            return 1
        print("---- ready; send 2 (close) ----", flush=True)
        proc.stdin.write("2\n")
        proc.stdin.flush()
        if not wait_for("已关闭", 5):
            print("FAIL: 2 未关闭", flush=True)
            proc.kill()
            return 1
        rc = proc.wait(timeout=10)
        print(f"\nSTARTUP-TEST PASS (exit={rc})", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        print("FAIL:", type(exc).__name__, str(exc)[:160], flush=True)
        proc.kill()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
