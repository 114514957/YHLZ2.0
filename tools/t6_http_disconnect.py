"""段5：断连恢复（按 request_id 取结果，不重放）+ 工具"核验后发布"标记。

- 客户端读到若干 `delta` 后**主动断开**；服务端照常完成并**留存结果**；
- 之后 `GET /talk_result?request_id=...` **取回结果**（不再跑一遍）；
- 普通回答 `published=streamed`；工具轮 `published=after_verification`。
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

tmp = pathlib.Path(tempfile.mkdtemp(prefix="t6_disc_"))
saved = _sandbox_writes(tmp)

import backend.talk_results as tr  # noqa: E402

tr.DIR = tmp / "talk_results"

from backend.console_server import make_console_server  # noqa: E402
from backend.target_entry import ConversationSession  # noqa: E402
from backend.target_kw_index import KeywordIndex  # noqa: E402
from backend.target_memory import TargetMemoryService  # noqa: E402

import asyncio  # noqa: E402


class IsoRuntime:
    def __init__(self):
        self._sessions = {}

    def _session(self, key="console"):
        if key not in self._sessions:
            mem = TargetMemoryService(db_path=tmp / "mem.db", kw_index=KeywordIndex(tmp / "kw.db"))
            mem._auto_adjudicate = lambda item: None  # type: ignore[method-assign]
            mem._auto_link_causal = lambda item: None  # type: ignore[method-assign]
            self._sessions[key] = ConversationSession(memory=mem, channel=key)
        return self._sessions[key]

    def console_turn_stream(self, text, on_delta):
        s = self._session("console")

        async def run():
            return await s.run_turn(text, on_delta=on_delta)

        return asyncio.run(run())

    def health(self):
        return {"status": "ok"}


PORT = 18423
srv = make_console_server(PORT, "127.0.0.1", IsoRuntime())
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.3)

# A) 断连恢复：带 request_id，读几行即断开
rid = "disc-test-0001"
conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=180)
conn.request("POST", "/talk", json.dumps({"text": "在吗？", "request_id": rid}),
             {"Content-Type": "application/json"})
resp = conn.getresponse()
seen = 0
for raw in resp:
    if b"delta" in raw:
        seen += 1
    if seen >= 2:      # 读到 2 段就断开（模拟断连）
        break
conn.close()
print(f"A) 断开前收到 {seen} 段；等待服务端完成…")
time.sleep(8)          # 服务端照常完成

# GET /talk_result（不重跑）
conn2 = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
conn2.request("GET", f"/talk_result?request_id={rid}")
r2 = conn2.getresponse()
body2 = json.loads(r2.read().decode("utf-8", "replace") or "{}")
conn2.close()
print(f"A) GET /talk_result -> HTTP {r2.status} | answer={str(body2.get('answer',''))[:50]!r} "
      f"published={body2.get('published')}")

# B) 工具轮发布标记（不断连）
rid2 = "tool-test-0002"
conn3 = http.client.HTTPConnection("127.0.0.1", PORT, timeout=180)
conn3.request("POST", "/talk", json.dumps({"text": "现在几点了？", "request_id": rid2}),
              {"Content-Type": "application/json"})
resp3 = conn3.getresponse()
done = {}
for raw in resp3:
    line = raw.decode("utf-8", "replace").strip()
    if line.startswith("data: "):
        ev = json.loads(line[6:])
        if ev.get("type") == "turn_done":
            done = ev
conn3.close()
print(f"B) turn_done: request_id={done.get('request_id')} tool_uses={done.get('tool_uses')} "
      f"published={done.get('published')}")

srv.shutdown()
_restore_writes(saved)

ok = (r2.status == 200 and body2.get("answer")
      and done.get("request_id") == rid2
      and done.get("published") == "after_verification")
print("\nVERDICT:", "PASS" if ok else "CHECK")
raise SystemExit(0 if ok else 1)
