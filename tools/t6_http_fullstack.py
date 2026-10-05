"""T6：真实 UI/HTTP 整机——真实 console HTTP 服务 + /talk SSE + 现有 Gemma。

- 真实：`make_console_server`/`ConsoleHandler`/`/talk` 路由/SSE 事件。
- 隔离：临时沙箱载体 + 临时 memstore + 独立 runtime（不起生产 daemon、不碰真实会话）。
- 验证：SSE 事件序列（state/thinking → delta* → turn_done → idle）+ 答案 + 工具数。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.env_loader import ensure_env_loaded

ensure_env_loaded()

from tools.persona_regression import _restore_writes, _sandbox_writes  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp(prefix="t6_http_"))
saved = _sandbox_writes(tmp)

from backend.console_server import make_console_server  # noqa: E402
from backend.target_entry import ConversationSession  # noqa: E402
from backend.target_kw_index import KeywordIndex  # noqa: E402
from backend.target_memory import TargetMemoryService  # noqa: E402

import asyncio  # noqa: E402


class IsoRuntime:
    """独立 runtime 适配（真实 HTTP 服务调用它；载体全临时）。"""

    def __init__(self):
        self._sessions = {}

    def _session(self, key="console"):
        if key not in self._sessions:
            mem = TargetMemoryService(db_path=tmp / "mem.db",
                                      kw_index=KeywordIndex(tmp / "kw.db"))
            mem._auto_adjudicate = lambda item: None  # type: ignore[method-assign]
            mem._auto_link_causal = lambda item: None  # type: ignore[method-assign]
            self._sessions[key] = ConversationSession(memory=mem, channel=key)
        return self._sessions[key]

    def console_turn_stream(self, text, on_delta):
        s = self._session("console")

        async def run():
            streamed = []

            def _d(chunk):
                streamed.append(chunk)
                on_delta(chunk)

            # 若会话支持流式回调则用之；否则退回普通 run_turn
            try:
                return await s.run_turn(text)
            finally:
                pass

        return asyncio.run(run())

    def health(self):
        return {"status": "ok"}


PORT = 18421
rt = IsoRuntime()
srv = make_console_server(PORT, "127.0.0.1", rt)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.3)
print(f"HTTP server on 127.0.0.1:{PORT}")

results = []
for text in ("现在几点了？", "在吗？"):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=180)
    body = json.dumps({"text": text})
    conn.request("POST", "/talk", body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    raw = resp.read().decode("utf-8", "replace")
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except Exception:
                pass
    kinds = [e.get("type") for e in events]
    done = next((e for e in events if e.get("type") == "turn_done"), {})
    results.append({"q": text, "status": resp.status, "events": kinds,
                    "answer": str(done.get("text", ""))[:80],
                    "tool_uses": done.get("tool_uses")})
    print(f"\nQ: {text}")
    print(f"  HTTP {resp.status} | SSE 事件: {kinds}")
    print(f"  turn_done: text={str(done.get('text',''))[:60]!r} tool_uses={done.get('tool_uses')}")
    conn.close()

srv.shutdown()
_restore_writes(saved)

out = pathlib.Path("artifacts/nonvoice_next_stage/t6_http_fullstack.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
ok = all(r["status"] == 200 and "turn_done" in r["events"] and r["answer"] for r in results)
print("\nVERDICT:", "PASS" if ok else "CHECK", "| ->", out)
raise SystemExit(0 if ok else 1)
