"""Offline fake dev agent for P3 tests (no harness, no network).

Used through the stub seam ``YHLZ_QQ_DEV_AGENT_CMD`` in tools/qq_dev_worker.py:
reads the prompt from stdin and emits the historical opencode-style JSON
events the stub executor still parses.
Env: FAKE_AGENT_MODE=auto|ask|done|sleep|crash, FAKE_AGENT_FILES=json list,
FAKE_AGENT_STDERR_MB, FAKE_AGENT_SESSION.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time


def _event(kind: str, text: str = "") -> str:
    if kind == "text":
        return json.dumps({"type": "text", "sessionID": SESSION,
                           "part": {"text": text}}, ensure_ascii=False)
    return json.dumps(kind, ensure_ascii=False)


def main() -> int:
    global SESSION
    SESSION = os.getenv("FAKE_AGENT_SESSION", "sess-1")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raw = sys.stdin.buffer.read()
    prompt = raw.decode("utf-8", "replace")
    mode = os.getenv("FAKE_AGENT_MODE", "auto").strip().lower()
    if mode == "auto":
        mode = "done" if "（用户答复）" in prompt else "ask"
    stderr_mb = int(os.getenv("FAKE_AGENT_STDERR_MB", "0") or "0")
    if stderr_mb:
        chunk = ("fake-stderr " * 1000 + "\n") * 100
        for _ in range(max(1, stderr_mb * 10)):
            sys.stderr.write(chunk)
        sys.stderr.write("fake-stderr-tail\n")
        sys.stderr.flush()
    if mode == "sleep":
        time.sleep(120)
        return 0
    if mode == "crash":
        sys.stderr.write("fake-agent-crash\n")
        return 3
    print(_event("text", f"[SESSION-START] mode={mode}"), flush=True)
    if mode == "ask":
        print(_event("text", "[QUESTION] 1) 目标文件是哪个？ 2) 需要测试吗？\n"
                              "方案：先改 a.txt 再补测试。\n把握：高"), flush=True)
        return 0
    files = json.loads(os.getenv("FAKE_AGENT_FILES", '["a.txt","b.txt"]'))
    cwd = pathlib.Path.cwd()
    for name in files:
        p = cwd / str(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"fake agent wrote {name}\n", encoding="utf-8")
    print(_event("text", "[DONE] 已完成：写入 " + ", ".join(map(str, files))
                          + "；验证通过。"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
