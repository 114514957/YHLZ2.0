"""YHLZ Workbench console server (ledger 0222, M1): single-page control deck.

Serves assets/webui/* on port 8322 and streams Yuanheng turns back as SSE:
    GET  /                -> index.html (static)
    GET  /console.css     -> styles
    GET  /console.js      -> app
    GET  /state           -> json status (daemon/gemma/session/memory)
    POST /talk {text}     -> SSE stream of {state|delta|turn_done|error} frames

Design notes (v2): backend-owned audio/ASR/TTS come in M2+; M1 is the control
deck shell + streaming text dialog. Rolling back = just stop port 8322.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = _PROJECT_ROOT / "assets" / "webui"
_sessions: dict[str, float] = {}


def _sse(data: dict) -> bytes:
    return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")


class ConsoleHandler(BaseHTTPRequestHandler):
    runtime = None

    # ---------- plumbing ----------
    def log_message(self, fmt, *args):  # quieter
        pass

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if not path.is_file() or STATIC_DIR not in path.parents:
            self.send_error(404)
            return
        body = path.read_bytes()
        ctype = ("text/html; charset=utf-8" if name.endswith(".html")
                 else "text/css; charset=utf-8" if name.endswith(".css")
                 else "application/javascript; charset=utf-8"
                 if name.endswith(".js") else "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- routing ----------
    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p in ("/", "/index.html"):
            self._serve_file("index.html")
        elif p == "/console.css":
            self._serve_file("console.css")
        elif p == "/console.js":
            self._serve_file("console.js")
        elif p == "/state":
            self._send_json(200, self._state())
        elif p == "/history":
            self._send_json(200, self._history())
        elif p == "/monitor":
            self._send_json(200, self._monitor())
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        p = self.path.split("?", 1)[0]
        if p == "/talk":
            self._do_talk()
            return
        if p == "/voice":
            self._do_voice()
            return
        if p == "/reset":
            self._do_reset()
            return
        self._send_json(404, {"error": "not found"})

    def _do_reset(self):
        """Clear the console conversation (new chat)."""
        try:
            s = self.runtime._session("console")
            s.history = []
            try:
                s.memory._turns = []
            except Exception:
                pass
            s.save_session("console")
            self._send_json(200, {"ok": True})
        except Exception as exc:
            self._send_json(500, {"ok": False,
                                  "error": f"{type(exc).__name__}: {str(exc)[:120]}"})

    def _monitor(self) -> dict:
        out = {"ok": True, "now": time.time()}
        try:
            import psutil
            import subprocess

            out["cpu"] = psutil.cpu_percent(interval=None)
            vm = psutil.virtual_memory()
            out["ram"] = {"used_gb": round(vm.used / 1e9, 2),
                          "total_gb": round(vm.total / 1e9, 2)}
            du = psutil.disk_usage(str(_PROJECT_ROOT))
            out["disk"] = {"used_gb": round(du.used / 1e9, 1),
                           "total_gb": round(du.total / 1e9, 1)}
            try:
                g = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,"
                                    "memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=8)
                parts = g.stdout.strip().split(",")
                if len(parts) == 3:
                    out["gpu"] = {"util": float(parts[0]),
                                  "used_gb": round(float(parts[1]) / 1024, 1),
                                  "total_gb": round(float(parts[2]) / 1024, 1)}
            except Exception:
                out["gpu"] = None
            out["services"] = self._state()
            out["procs"] = len(psutil.pids())
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
        return out

    def _do_voice(self):
        """One voice turn over SSE: listen(gated 3s) -> SenseVoice -> LLM
        stream -> TTS speak. {text} present => mock mode (skip mic, use text)."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send_json(400, {"error": "bad json"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(data: dict) -> None:
            try:
                self.wfile.write(_sse(data))
                self.wfile.flush()
            except Exception:
                pass

        import time as _t

        try:
            mock_text = str(body.get("text", "") or "").strip()
            if mock_text:
                text = mock_text
            else:
                emit({"type": "state", "value": "listening"})
                r = self._listen(body)
                if not r.get("started"):
                    emit({"type": "state", "value": "idle"})
                    emit({"type": "voice_done",
                          "status": "no-speech"})
                    return
                audio = r["audio"]
                emit({"type": "voice_text", "kind": "asr",
                      "text": "(语音已采集，识别中…)"})
                from tools.tts_test_start import _get_sv, release_sv

                emit({"type": "state", "value": "asr"})
                sv = _get_sv()
                res = sv.generate(input=audio, language="zh",
                                  use_itn=True, batch_size_s=60)
                raw = str((res[0] or {}).get("text") or "") if res else ""
                import re

                text = re.sub(r"<\|[^|]+\|>", "", raw).strip()
                release_sv()
                emit({"type": "voice_text", "kind": "user", "text": text})
            emit({"type": "state", "value": "thinking"})
            if not text:
                emit({"type": "state", "value": "idle"})
                return
            info = self.runtime.console_turn_stream(
                text, lambda c: emit({"type": "delta", "delta": c}))
            answer = str(info.get("answer", ""))
            emit({"type": "turn_done", "text": answer,
                  "tool_uses": len(info.get("tool_uses") or [])})
            speak = str(body.get("speak", "1")) not in ("0", "false", "off")
            if speak and answer.strip():
                emit({"type": "state", "value": "speaking"})
                self._speak(answer)
            emit({"type": "state", "value": "idle"})
            emit({"type": "voice_done", "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            emit({"type": "error", "message": f"{type(exc).__name__}: "
                                              f"{str(exc)[:200]}"})
            emit({"type": "state", "value": "idle"})

    # ---------- voice helpers ----------
    def _listen(self, body) -> dict:
        from tools.tts_test_start import _capture_loop

        device = int(body.get("device", 1))
        dur = float(body.get("duration", 60.0))
        denoise = str(body.get("denoise", "rnnoise"))
        emit = self._emit_level

        def on_level(level, is_speech):
            try:
                emit(level, is_speech)
            except Exception:
                pass

        return _capture_loop(device, 1.0, dur, denoise, None, False, False,
                             on_level=on_level)

    def _emit_level(self, level, is_speech):
        self.wfile.write(_sse({"type": "level", "value": round(float(level), 4),
                               "speech": bool(is_speech)}))
        self.wfile.flush()

    def _speak(self, text: str) -> None:
        import torch

        import numpy as np
        import sounddevice as sd
        from faster_qwen3_tts import FasterQwen3TTS

        t0 = time.time()
        m = FasterQwen3TTS.from_pretrained(
            str(_PROJECT_ROOT / "models" / "qwen3-tts" /
                "Qwen3-TTS-12Hz-1.7B-CustomVoice"),
            device="cuda", dtype=torch.bfloat16)
        wavs, sr = m.generate_custom_voice(
            text=str(text)[:180], language="Chinese", speaker="Vivian",
            instruct="自然地说，像和亲近的人聊天，别播音腔。")
        samples = np.asarray(wavs[0], dtype="float32")
        sd.play(samples, int(sr))
        sd.wait()
        del m
        import gc

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"[console][tts] ok {time.time()-t0:.0f}s", flush=True)

    # ---------- logic ----------
    def _history(self) -> dict:
        """Console session dialogue history (persisted per turn in cache/sessions/
        console.json) so a page refresh restores the conversation."""
        try:
            s = self.runtime._session("console")
            msgs = [
                {"role": m.get("role"), "content": str(m.get("content", ""))}
                for m in (s.history or [])
            ]
            return {"ok": True, "messages": msgs}
        except Exception as exc:
            return {"ok": False, "messages": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def _state(self) -> dict:
        out = {"ok": True, "now": time.time()}
        try:
            import urllib.request

            try:
                g = json.loads(urllib.request.urlopen(
                    "http://127.0.0.1:8081/health", timeout=3).read())
                out["gemma"] = "ok" if g.get("status") == "ok" else "down"
            except Exception:
                out["gemma"] = "down"
            out["daemon"] = "ok"
            st = self.runtime.health() if hasattr(self.runtime, "health") else None
            out["turns"] = 0
            if st:
                try:
                    counts = {k: v for k, v in (st.get("turns") or {}).items()}
                    out["turns"] = counts
                except Exception:
                    pass
            try:
                s = self.runtime._session("console")
                out["history"] = len(s.history) // 2
                out["l2"] = s.memory.health().get("l2_items", 0)
            except Exception:
                pass
        except Exception:
            out["daemon"] = "down"
        return out

    def _do_talk(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            text = str(body.get("text", "")).strip()
        except Exception:
            self._send_json(400, {"error": "bad json"})
            return
        if not text:
            self._send_json(400, {"error": "empty text"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(_sse({"type": "state", "value": "thinking"}))
            self.wfile.flush()

            def on_delta(chunk: str) -> None:
                try:
                    self.wfile.write(_sse({"type": "delta", "delta": chunk}))
                    self.wfile.flush()
                except Exception:
                    pass

            info = self.runtime.console_turn_stream(text, on_delta)
            answer = str(info.get("answer", ""))
            self.wfile.write(_sse({"type": "turn_done", "text": answer,
                                   "tool_uses": len(info.get("tool_uses") or [])}))
            self.wfile.write(_sse({"type": "state", "value": "idle"}))
            self.wfile.flush()
        except Exception as exc:
            try:
                self.wfile.write(_sse({"type": "error",
                                       "message": f"{type(exc).__name__}: "
                                                  f"{str(exc)[:160]}"}))
                self.wfile.write(_sse({"type": "state", "value": "idle"}))
                self.wfile.flush()
            except Exception:
                pass


def make_console_server(port: int, host: str, runtime) -> ThreadingHTTPServer:
    ConsoleHandler.runtime = runtime
    return ThreadingHTTPServer((host, port), ConsoleHandler)


def serve_in_thread(port: int = 8322, host: str = "127.0.0.1",
                    runtime=None) -> threading.Thread:
    server = make_console_server(port, host, runtime)
    t = threading.Thread(target=server.serve_forever, daemon=True,
                         name="console-web")
    t.start()
    print(f"[console] workbench http://{host}:{port}", flush=True)
    return t
