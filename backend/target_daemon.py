"""Always-on daemon (ledger 0168): hosts one ConversationSession over HTTP.

Routes:
  GET  /health         -> status (provider rail, session, memory)
  POST /turn           -> {"text": ...} => {"answer", "tools", ...}

Dual rail: the LLM turn factory falls back to the local Ollama endpoint when
the cloud (DeepSeek) is unreachable, so the daemon keeps answering offline.
Zero deps: stdlib http.server + threading.

Run:  python -m backend.target_daemon [--port 8321] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

_PROJECT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

LOCAL_BASE = "http://127.0.0.1:11434/v1/chat/completions"
LOCAL_MODEL = "qwen2.5:3b"


class DaemonRuntime:
    """Owns one persistent ConversationSession (dual-rail LLM)."""

    def __init__(self, session_factory: Optional[Callable[[], Any]] = None,
                 llm_turn: Any = None) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._session_factory = session_factory or self._default_session
        self._llm_turn_override = llm_turn
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()
        self._ready.wait(timeout=10)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    @staticmethod
    def _default_session():
        from backend.env_loader import ensure_env_loaded

        ensure_env_loaded()
        from backend.target_entry import ConversationSession
        from backend.target_orchestrator import build_openai_compatible_llm_turn

        llm = build_openai_compatible_llm_turn(
            fallback_base_url=LOCAL_BASE, fallback_model=LOCAL_MODEL)
        s = ConversationSession(llm_turn=llm)
        try:
            s.load_session("default")
        except Exception:
            pass
        return s

    def _get_session(self) -> Any:
        if not hasattr(self, "_session"):
            self._session = self._session_factory()
            if self._llm_turn_override is not None:
                self._session.llm_turn = self._llm_turn_override
        return self._session

    def health(self) -> dict:
        try:
            s = self._get_session()
            st = s.status()
        except Exception as exc:
            return {"status": "degraded", "detail": type(exc).__name__}
        return {"status": "ok", "provider": "dual-rail",
                "session": st, "llm": "deepseek->ollama"}

    def turn(self, text: str) -> dict:
        future = asyncio.run_coroutine_threadsafe(
            self._get_session().run_turn(str(text)), self._loop)
        info = future.result(timeout=240)
        try:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self._get_session().save_session(), loop=self._loop))
        except Exception:
            pass
        return info


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
        if self.path != "/turn":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            text = str(payload.get("text", "")).strip()
        except Exception:
            self._send(400, {"error": "bad json"})
            return
        if not text:
            self._send(400, {"error": "empty text"})
            return
        try:
            info = self.runtime.turn(text)
            self._send(200, info)
        except Exception as exc:
            self._send(500, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"})


def make_server(port: int, host: str, runtime: DaemonRuntime) -> ThreadingHTTPServer:
    _Handler.runtime = runtime
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="元亨常驻 daemon（双轨）")
    parser.add_argument("--port", type=int, default=8321)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    runtime = DaemonRuntime()
    server = make_server(args.port, args.host, runtime)
    print(f"元亨常驻 daemon: http://{args.host}:{args.port} (云端→本地双轨)",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutdown", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
