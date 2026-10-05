"""T6/段5：真实 UI/HTTP 整机——增量消费 SSE（首字/到达时间/完整拼接核对）。

- 增量：按行消费 `text/event-stream`，记录每个事件的**到达单调时间**；
- 核对：**拼接(deltas) == turn_done 文本**（合成数据）；工具轮标"核验后发布"；
- 模板残片定位：打印拼接全文，检查是否含 `<|turn>` 类 marker 及其位置。
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

tmp = pathlib.Path(tempfile.mkdtemp(prefix="t6_http2_"))
saved = _sandbox_writes(tmp)

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


PORT = 18422
srv = make_console_server(PORT, "127.0.0.1", IsoRuntime())
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.3)

results = []
for text in ("现在几点了？", "在吗？"):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=180)
    conn.request("POST", "/talk", json.dumps({"text": text}),
                 {"Content-Type": "application/json"})
    resp = conn.getresponse()
    t0 = time.monotonic()
    events = []
    for raw in resp:  # 增量按行消费
        t = round(time.monotonic() - t0, 3)
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except Exception:
            continue
        ev["_t"] = t
        events.append(ev)
    conn.close()

    deltas = [e for e in events if e.get("type") == "delta"]
    assembled = "".join(str(e.get("delta", "")) for e in deltas)
    done = next((e for e in events if e.get("type") == "turn_done"), {})
    done_text = str(done.get("text", ""))
    first_delta_t = deltas[0]["_t"] if deltas else None
    last_t = events[-1]["_t"] if events else None
    has_marker = "<|turn" in assembled or "<|turn" in done_text
    rec = {"q": text, "n_delta": len(deltas), "first_delta_t": first_delta_t,
           "last_event_t": last_t, "assembled_eq_done": assembled.strip() == done_text.strip(),
           "tool_uses": done.get("tool_uses"), "has_turn_marker": has_marker,
           "assembled_head": assembled[:90]}
    results.append(rec)
    print(f"\nQ: {text} | HTTP {resp.status}")
    print(f"  deltas={len(deltas)} 首段@{first_delta_t}s 末事件@{last_t}s")
    print(f"  拼接==turn_done: {rec['assembled_eq_done']} | tool_uses={done.get('tool_uses')}")
    print(f"  含模板marker: {has_marker}")
    print(f"  拼接全文: {assembled[:120]!r}")

srv.shutdown()
_restore_writes(saved)
out = pathlib.Path("artifacts/nonvoice_next_stage/t6_http_incremental.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
ok = all(r["n_delta"] > 0 and r["assembled_eq_done"] for r in results)
print("\nVERDICT:", "PASS" if ok else "CHECK", "| ->", out)
raise SystemExit(0 if ok else 1)
