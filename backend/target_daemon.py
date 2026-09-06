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
NOTIFY_TOOL_HINTS = ("qq.", "kb.", "skill.", "diary.", "task.", "memory.save")


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


def notify_popup_loop() -> None:
    """Every ~12s pop any not-yet-popped notification as a Windows toast-ish
    WScript popup (auto-closes after 6 s). Never blocks the daemon."""
    import pathlib
    import subprocess
    import tempfile

    popped: set[float] = set()
    if NOTIFY_LAST_POP.exists():
        try:
            for e in json.loads(NOTIFY_LAST_POP.read_text(encoding="utf-8")):
                popped.add(float(e.get("ts", 0)))
        except Exception:
            pass
    while True:
        time.sleep(12)
        try:
            entries = []
            if NOTIFY_FILE.exists():
                entries = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
            fresh = [e for e in entries if float(e.get("ts", 0)) not in popped]
            if not fresh:
                continue
            latest = fresh[-1]
            body = str(latest.get("text", ""))[:200]
            vbs = tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False,
                                              encoding="utf-8")
            vbs.write(
                'Set s = CreateObject("WScript.Shell")\r\n'
                f's.Popup {json.dumps("元亨主动汇报：" + body)}, 8, '
                f'{json.dumps("元亨汇报")}, 64\r\n'
            )
            vbs.close()
            subprocess.Popen(
                ["wscript.exe", vbs.name],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            for e in fresh:
                popped.add(float(e.get("ts", 0)))
            NOTIFY_LAST_POP.write_text(
                json.dumps([{"ts": float(e["ts"])} for e in fresh],
                           ensure_ascii=False),
                encoding="utf-8")
        except Exception as exc:
            print(f"[notify] skip: {type(exc).__name__}", flush=True)


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
        self.selfcheck_hour = 23  # nightly self-check reminder (Yuanheng's own hour)
        self._selfcheck_last = ""
        threading.Thread(target=self._selfcheck_loop, daemon=True).start()
        threading.Thread(target=notify_popup_loop, daemon=True).start()

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
        except Exception as exc:
            print(f"[auto-consolidate] skip: {type(exc).__name__}", flush=True)

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
        if self.path in ("/v1/chat/completions", "/chat/completions"):
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
