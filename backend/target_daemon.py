"""Always-on daemon (ledger 0168/0169): multi-channel ConversationSessions.

Routes:
  GET  /health                     -> status (sessions, memory)
  POST /turn      {"text","channel"} -> per-channel turn (private default)
  POST /v1/chat/completions        -> OpenAI-compatible (AstrBot provider):
          messages last user text; "user" field = channel id (public).

Per-channel sessions: each group/user gets an independent conversation +
session file (cache/sessions/qq_<id>.json). Public channels add the
PUBLIC_CONVERGENCE_CLAUSE (privacy guard).  Dual-rail LLM (cloud -> local).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

_PROJECT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

LOCAL_BASE = "http://127.0.0.1:11434/v1/chat/completions"
LOCAL_MODEL = "qwen2.5:3b"

NOTIFY_DIR = _PROJECT / "cache" / "qqwatch"
NOTIFY_FILE = NOTIFY_DIR / "notifications.json"
NOTIFY_LAST_POP = NOTIFY_DIR / "notifications.popup.json"
NOTIFY_RESULT_WORDS = ("完成", "已导出", "已入库", "入库", "导出", "总结", "已生成",
                       "汇报", "抽取", "处理完", "技能", "已启动", "已停止")
# write/action tools only — read tools (kb.query, file.read, ...) never notify
NOTIFY_TOOL_HINTS = ("qq.export", "qq.process", "qq.runbatch", "qq.bootstrap",
                     "qq.shutdown", "qq.digest", "qq.summarize",
                     "memory.save", "diary.write", "task.plan",
                     "skill.add", "kb.add")


def notify_push(text: str) -> None:
    """Append a Yuanheng activity notification (bounded queue)."""
    import pathlib

    NOTIFY_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    if NOTIFY_FILE.exists():
        try:
            entries = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
        except Exception:
            entries = []
    entries.append({"ts": time.time(), "text": str(text)[:600]})
    del entries[:-8]
    NOTIFY_FILE.write_text(json.dumps(entries, ensure_ascii=False),
                           encoding="utf-8")


def notify_should(text: str, tools: list[dict]) -> bool:
    """Heuristic: is this turn worth pushing to the owner's desktop?"""
    joined = " ".join(
        str(u.get("name", "")) for u in (tools or []))
    if any(h in joined for h in NOTIFY_TOOL_HINTS):
        return True
    return any(w in text for w in NOTIFY_RESULT_WORDS)


class DaemonRuntime:
    def __init__(self, session_factory: Optional[Callable[[], Any]] = None,
                 llm_turn: Any = None) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._factory = session_factory or self._default_session
        self._llm_turn_override = llm_turn
        self._sessions: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()
        self._ready.wait(timeout=10)
        self.selfcheck_hour = -1  # selfcheck superseded by schedule plan_night
        self._selfcheck_last = ""
        threading.Thread(target=self._selfcheck_loop, daemon=True).start()
        # batch-2 #2 (ledger 0196) -> superseded by schedule-driven autonomy
        # (ledger 0209): Yuanheng designs its own recurring plans; the daemon
        # reads the schedule table and nudges when an entry is due.
        self._sched_checked = ""
        threading.Thread(target=self._schedule_loop, daemon=True).start()
        self._upkeep_last = ""
        threading.Thread(target=self._memory_upkeep_loop, daemon=True).start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    @staticmethod
    def _default_session(channel: str = "private"):
        from backend.env_loader import ensure_env_loaded

        ensure_env_loaded()
        from backend.target_entry import ConversationSession
        from backend.target_orchestrator import build_openai_compatible_llm_turn

        llm = build_openai_compatible_llm_turn(
            fallback_base_url=LOCAL_BASE, fallback_model=LOCAL_MODEL)
        s = ConversationSession(llm_turn=llm, channel=channel)
        if channel != "private":
            try:
                s.load_session(f"qq_{channel}")
            except Exception:
                pass
        else:
            try:
                s.load_session("default")
            except Exception:
                pass
        return s

    def _session(self, channel: str) -> Any:
        key = channel or "private"
        with self._lock:
            s = self._sessions.get(key)
            if s is None:
                s = self._factory(key)
                if self._llm_turn_override is not None:
                    s.llm_turn = self._llm_turn_override
                self._sessions[key] = s
            return s

    def health(self) -> dict:
        try:
            counts = {k: self._sessions[k].status()["history_turns"]
                      for k in self._sessions}
        except Exception as exc:
            return {"status": "degraded", "detail": type(exc).__name__}
        return {"status": "ok", "provider": "dual-rail",
                "sessions": len(self._sessions), "turns": counts,
                "llm": "deepseek->ollama"}

    def turn(self, text: str, channel: str = "private") -> dict:
        key = channel or "private"
        s = self._session(key)
        future = asyncio.run_coroutine_threadsafe(s.run_turn(str(text)),
                                                  self._loop)
        info = future.result(timeout=240)
        try:
            s.save_session("qq_" + key if key != "private" else "default")
        except Exception:
            pass
        self._maybe_consolidate(key)
        try:
            answer = str(info.get("answer", ""))
            if key == "private" and answer:
                try:
                    from backend.target_signals import capture as _sig_capture

                    _sig_capture(str(text), channel=key)
                except Exception:
                    pass
                try:
                    from backend.target_scheduler_tools import skill_hint

                    hint = skill_hint(str(text), [u.get("name", "") for u in (info.get("tool_uses") or [])])
                    if hint:
                        info["answer"] = answer + hint
                except Exception:
                    pass
                try:
                    from backend.target_persona_loop import (
                        PENDING_FILE, maybe_open_refute_proposal)

                    s = self._session(key)
                    from backend.target_persona_loop import COGNITION_FILE

                    msg = ""
                    try:
                        msg = maybe_open_refute_proposal(
                            COGNITION_FILE.read_text(encoding="utf-8"),
                            str(text), pending_file=PENDING_FILE)
                    except Exception:
                        msg = ""
                    if msg:
                        info["answer"] = info.get("answer", "") + "\n\n（证伪联动）" + msg
                except Exception:
                    pass
            if key == "private" and notify_should(answer, info.get("tool_uses") or []):
                tools = [u.get("name", "") for u in (info.get("tool_uses") or [])]
                head = answer[:150].replace("\n", " ")
                notify_push(f"任务完成汇报：{head}" + (f"（工具：{'、'.join(tools)}）" if tools else ""))
        except Exception:
            pass
        return info

    # auto-consolidation: every N turns on the private channel run the persona
    # loop once (idempotent by design — stamped items are never re-proposed).
    AUTO_CONSOLIDATE_EVERY = 15

    def _maybe_consolidate(self, key: str) -> None:
        try:
            if key != "private":
                return
            s = self._session(key)
            st = s.status()
            if int(st.get("history_turns", 0)) < 1:
                return
            counter = getattr(self, "_consolidate_counter", 0) + 1
            self._consolidate_counter = counter
            if counter % self.AUTO_CONSOLIDATE_EVERY != 0:
                return
            from backend.target_persona_loop import PersonaConsolidationLoop

            pc = PersonaConsolidationLoop(s.llm_turn, s.memory)
            future = asyncio.run_coroutine_threadsafe(pc.consolidate_once(),
                                                      self._loop)
            info = future.result(timeout=180)
            print(f"[auto-consolidate] {info.get('status')}", flush=True)
            if info.get("status") == "pending-approval":
                notify_push("有认知提炼待你确认：在 CLI 输入 /review-cognition 逐条 y/n 批准（写进元亨认知根基）")
        except Exception as exc:
            print(f"[auto-consolidate] skip: {type(exc).__name__}", flush=True)

    def _schedule_loop(self) -> None:
        """Schedule-driven autonomy (ledger 0209): every 30s, if any recurring
        plan in data/yuanheng_schedule.json is due now, nudge Yuanheng (private
        channel) with the plan name + its self-written steps — it decides."""
        import pathlib as _pl

        sched_mod = None
        while True:
            time.sleep(30)
            try:
                now = time.localtime()
                if sched_mod is None:
                    from backend import target_schedule as sched_mod
                due = []
                try:
                    for plan in sched_mod._load():
                        if not plan.get("enabled", True):
                            continue
                        if sched_mod.is_due(plan, now, plan.get("last_run", "")):
                            due.append(plan)
                except Exception as exc:
                    print(f"[schedule] load err {type(exc).__name__}", flush=True)
                    continue
                for plan in due:
                    try:
                        steps = plan.get("steps") or []
                        body = (f"（计划表到点）你的例行计划：{plan.get('name')}。"
                                f"{'步骤：' + '；'.join(steps[:3]) if steps else ''}"
                                " 想做才做——需要我配合跑工具（如 summarize/consolidate/清理任务表）就说一声。")
                        self.turn(body, "private")
                        sched_mod.mark_run(plan.get("id", ""), now)
                        print(f"[schedule] ran {plan.get('name')}", flush=True)
                    except Exception as exc:
                        print(f"[schedule] run err {type(exc).__name__}", flush=True)
            except Exception as exc:
                print(f"[schedule] loop err {type(exc).__name__}", flush=True)

    def _selfcheck_loop(self) -> None:
        """Nightly nudge: at selfcheck_hour, invite Yuanheng (private channel)
        to write today's diary and refresh its own task board — it decides."""
        while True:
            time.sleep(45)
            try:
                now = time.localtime()
                if now.tm_hour == int(self.selfcheck_hour) and now.tm_min < 6:
                    today = time.strftime("%Y-%m-%d")
                    if self._selfcheck_last != today:
                        self._selfcheck_last = today
                        self.turn(
                            "夜深了——每日自省时刻。这一天的经历与学到的东西，你可以："
                            "1) 用 diary.write 写下今天想写的日记（不强制，真实就好）；"
                            "2) 用 task.plan 梳理任务表：今天做完了什么、明天想做什么。"
                            "这两样是你自己的工具，想用才用。",
                            "private",
                        )
                        print(f"[selfcheck] {today} nudge done", flush=True)
            except Exception as exc:
                print(f"[selfcheck] skip: {type(exc).__name__}", flush=True)

    def _memory_upkeep_loop(self) -> None:
        """Weekly memory upkeep (ledger 0189): every Sunday 12:00 run belief
        time-decay + downgrades (cold) so L2 behaves like a real memory
        (unused items fade, nothing is ever deleted)."""
        import pathlib

        stamp_file = pathlib.Path(_PROJECT) / "cache" / "memory_upkeep_last.json"
        while True:
            time.sleep(60)
            try:
                now = time.localtime()
                if now.tm_wday != 6 or now.tm_hour != 12:  # Sunday 12:00-12:59
                    continue
                today = time.strftime("%Y-%m-%d")
                if self._upkeep_last == today:
                    continue
                try:
                    if stamp_file.exists():
                        last = json.loads(stamp_file.read_text(encoding="utf-8")).get("date", "")
                        if last == today:
                            self._upkeep_last = today
                            continue
                except Exception:
                    pass
                self._upkeep_last = today
                from backend.target_memory import TargetMemoryService

                svc = TargetMemoryService()
                reinforced = svc.review_reinforce()
                decayed = svc.apply_belief_decay()
                downgraded = svc.apply_belief_downgrades()
                stamp_file.write_text(
                    json.dumps({"date": today, "reinforced": reinforced,
                                "decayed": decayed, "downgraded": downgraded}),
                    encoding="utf-8")
                print(f"[memory-upkeep] {today} reinforced={reinforced} "
                      f"decayed={decayed} downgraded={downgraded}", flush=True)
            except Exception as exc:
                print(f"[memory-upkeep] skip: {type(exc).__name__}", flush=True)

    def stream_chat(self, payload: dict, sink) -> str:
        """Dual-rail streaming chat (ledger 0204 + 0212): local Gemma first
        (llama.cpp 8081), Ollama Qwen fallback. Emits OpenAI-style SSE frames
        via `sink(text_chunk, reasoning_chunk=None)`; returns model used."""
        from backend.env_loader import ensure_env_loaded

        messages = payload.get("messages") or []
        ensure_env_loaded()
        import os

        key = os.getenv("DEEPSEEK_API_KEY", "")

        async def _stream_to(base_url, api_key, model):
            from backend.llm_stream import stream_openai_compatible

            async def _on(ev):
                if ev["kind"] == "delta":
                    if ev["stage"] == "content":
                        sink(ev["delta"], None)
                    else:
                        sink(None, ev["delta"])
                # done frame ignored here (client closes on [DONE])

            await stream_openai_compatible(
                base_url=base_url, api_key=api_key, model=model,
                messages=messages, on_event=_on,
                temperature=float(payload.get("temperature", 0.7)),
                max_tokens=int(payload.get("max_tokens", 1200) or 1200),
            )

        async def _try_cloud():
            await _stream_to("http://127.0.0.1:8081/v1/chat/completions",
                              key, "gemma-4-e4b")

        try:
            fut = asyncio.run_coroutine_threadsafe(_try_cloud(), self._loop)
            fut.result(timeout=300)
            return "gemma-4-e4b"
        except Exception:
            async def _try_local():
                await _stream_to(LOCAL_BASE, "", LOCAL_MODEL)

            fut = asyncio.run_coroutine_threadsafe(_try_local(), self._loop)
            fut.result(timeout=300)
            return LOCAL_MODEL

    def openai_chat(self, payload: dict) -> dict:
        messages = payload.get("messages") or []
        user_msgs = [m for m in messages if m.get("role") == "user"]
        text = str((user_msgs[-1] or {}).get("content", "")).strip()
        if not text:
            return {"error": "empty user message"}
        channel = str(payload.get("user") or "public")
        info = self.turn(text, channel=channel)
        return {
            "id": f"chatcmpl-yhlz-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": str(payload.get("model", "yhlz-yuanheng")),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant",
                            "content": info.get("answer", "")},
                "finish_reason": "stop",
            }],
        }


class _Handler(BaseHTTPRequestHandler):
    runtime: DaemonRuntime = None  # type: ignore[assignment]

    def _handle_stream_chat(self, payload: dict) -> None:
        """SSE streaming chat (ledger 0204): OpenAI-style frames."""
        import os

        from backend.env_loader import ensure_env_loaded

        ensure_env_loaded()
        messages = payload.get("messages") or []
        if not any(m.get("role") == "user" for m in messages):
            self._send(400, {"error": "empty user message"})
            return
        model = str(payload.get("model", "yhlz-yuanheng"))
        cid = f"chatcmpl-yhlz-{int(time.time() * 1000)}"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def _frame(obj: dict) -> bytes:
            return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")

        def _sink(text_chunk, reason_chunk):
            delta = {}
            if text_chunk:
                delta["content"] = text_chunk
            if reason_chunk:
                delta["reasoning_content"] = reason_chunk
            if delta:
                try:
                    self.wfile.write(_frame({
                        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                    }))
                    self.wfile.flush()
                except Exception:
                    pass

        try:
            used_model = self.runtime.stream_chat(payload, _sink)
        except Exception:
            used_model = model
        self.wfile.write(_frame({
            "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": used_model or model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, fmt, *args):
        return

    def _send(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, self.runtime.health())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, {"error": "bad json"})
            return
        if self.path == "/turn":
            text = str(payload.get("text", "")).strip()
            if not text:
                self._send(400, {"error": "empty text"})
                return
            try:
                info = self.runtime.turn(text,
                                         str(payload.get("channel", "private")))
                self._send(200, info)
            except Exception as exc:
                self._send(500, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            return
        if self.path == "/tool/schedule":
            from backend.target_scheduler_tools import schedule_handle
            try:
                pl = payload if isinstance(payload, dict) else {}
                method = str(pl.get("method") or pl.get("action") or "list")
                kw = dict(
                    name=pl.get("name", ""),
                    time_=pl.get("time") or pl.get("time_", ""),
                    cadence=pl.get("cadence", "daily"),
                    steps=pl.get("steps", ""),
                    plan_id=pl.get("plan_id", ""),
                    weekday=pl.get("weekday", ""),
                    day=pl.get("day", ""),
                    enabled=pl.get("enabled", ""),
                    fields_json=pl.get("fields_json", ""),
                )
                out = schedule_handle(method, **kw)
                self._send(200, {"ok": True, "output": out})
            except Exception as exc:
                self._send(500, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            return
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            if payload.get("stream"):
                self._handle_stream_chat(payload)
                return
            try:
                out = self.runtime.openai_chat(payload)
            except Exception as exc:
                self._send(500, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"})
                return
            if "error" in out:
                self._send(400, out)
                return
            self._send(200, out)
            return
        if self.path == "/notifications":
            # owner-side poll: return queued Yuanheng activity then clear
            import pathlib

            try:
                entries = []
                if NOTIFY_FILE.exists():
                    entries = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
                NOTIFY_FILE.write_text("[]", encoding="utf-8")
                self._send(200, {"notifications": entries})
            except Exception as exc:
                self._send(500, {"error": type(exc).__name__})
            return
        self._send(404, {"error": "not found"})


def make_server(port: int, host: str, runtime: DaemonRuntime) -> ThreadingHTTPServer:
    _Handler.runtime = runtime
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="元亨常驻 daemon（双轨+多渠道）")
    parser.add_argument("--port", type=int, default=8321)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    runtime = DaemonRuntime()
    server = make_server(args.port, args.host, runtime)
    print(f"元亨 daemon: http://{args.host}:{args.port} "
          f"(OpenAI 兼容 {args.host}:{args.port}/v1/chat/completions)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutdown", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
