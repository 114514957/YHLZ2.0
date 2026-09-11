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
LEDGER_FILE = _PROJECT_ROOT / "docs" / "上下文台账.md"
_LOG_RING: list[dict] = []
from collections import deque as _deque

_LOG_RING = _deque(maxlen=60)
_sessions: dict[str, float] = {}

SETTINGS_FILE = _PROJECT_ROOT / "data" / "console.json"
DEFAULT_SETTINGS = {
    "device": 1,
    "denoise": "rnnoise",
    "duration": 60.0,
    "asr": "sensevoice",
    "tts_speaker": "Vivian",
    "tts_speak": True,
    "tts_model": "0.6B",
}

TTS_DIRS = {
    "0.6B": _PROJECT_ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-0.6B-CustomVoice",
    "1.7B": _PROJECT_ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-1.7B-CustomVoice",
}
_TTS = {"model": None, "key": None}


def _get_tts(which: str):
    """Resident TTS model (load once per process; ledger 0226 perf)."""
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    key = str(which or "0.6B")
    path = TTS_DIRS.get(key) or TTS_DIRS["0.6B"]
    if _TTS["model"] is None or _TTS["key"] != key:
        try:
            if _TTS["model"] is not None:
                del _TTS["model"]
                import gc

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        except Exception:
            pass
        _TTS["model"] = FasterQwen3TTS.from_pretrained(
            str(path), device="cuda", dtype=torch.bfloat16)
        _TTS["key"] = key
    return _TTS["model"]


def _settings_load() -> dict:
    d = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            import json as _j

            d.update(_j.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return d


def _settings_save(patch: dict) -> dict:
    import json as _j

    cur = _settings_load()
    for k in list(DEFAULT_SETTINGS):
        if k in patch:
            try:
                if isinstance(DEFAULT_SETTINGS[k], bool):
                    cur[k] = str(patch[k]).lower() in ("1", "true", "yes", "on")
                elif isinstance(DEFAULT_SETTINGS[k], float):
                    cur[k] = float(patch[k])
                elif isinstance(DEFAULT_SETTINGS[k], int):
                    cur[k] = int(patch[k])
                else:
                    cur[k] = str(patch[k])
            except Exception:
                pass
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(_j.dumps(cur, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    _log("settings", ",".join(k for k in patch if k in DEFAULT_SETTINGS))
    return cur


def _audio_devices() -> list[dict]:
    try:
        import sounddevice as sd

        return [
            {"index": i, "name": d["name"]}
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]
    except Exception:
        return []


def _log(event: str, detail: str = "") -> None:
    _LOG_RING.append({"t": time.time(), "event": event, "detail": detail[:160]})


def _bring_qq_front(delay: float = 8.0) -> None:
    """After NapCat starts, bring the QQ/NapCat login window to the foreground."""
    import threading

    def _go() -> None:
        time.sleep(delay)
        try:
            import subprocess

            ps = (
                "Add-Type -Namespace N -Name W -MemberDefinition "
                "'[DllImport(\"user32.dll\")] public static extern bool "
                "ShowWindow(IntPtr h,int n); "
                "[DllImport(\"user32.dll\")] public static extern bool "
                "SetForegroundWindow(IntPtr h);'; "
                "Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and ("
                "$_.MainWindowTitle -like '*launcher-user*' -or "
                "$_.MainWindowTitle -like '*NapCat*' -or "
                "$_.ProcessName -like 'QQ*' -or $_.ProcessName -like '*NapCat*') } | "
                "ForEach-Object { [N.W]::ShowWindow($_.MainWindowHandle,9); "
                "[N.W]::SetForegroundWindow($_.MainWindowHandle) }"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=20)
        except Exception:
            pass

    threading.Thread(target=_go, daemon=True).start()


def _drives_list() -> list:
    try:
        from backend import intrinsic_drives

        ds = [d for d in intrinsic_drives.load() if d.get("status") == "active"]
        ds.sort(key=lambda d: (int(d.get("priority", 0)),
                               float(d.get("strength", 0))), reverse=True)
        return [{"id": d.get("id"), "name": d.get("name"),
                 "category": d.get("category"),
                 "strength": round(float(d.get("strength", 0)), 2),
                 "priority": d.get("priority"),
                 "note": str(d.get("note", ""))[:80]} for d in ds[:12]]
    except Exception:
        return []


_SHERPA = {"m": None, "tried": False}


def _get_sherpa():
    """Lazy singleton streaming ASR (sherpa zh-en) for live partials."""
    if not _SHERPA["tried"]:
        _SHERPA["tried"] = True
        try:
            from backend.target_sherpa_asr import (
                SherpaOnlineASRConfig,
                SherpaOnlineASRProvider,
            )

            _SHERPA["m"] = SherpaOnlineASRProvider(
                SherpaOnlineASRConfig(min_available_memory_bytes=256 * 1024 * 1024))
            _SHERPA["m"].start()
        except Exception:
            _SHERPA["m"] = None
    return _SHERPA["m"]


def _qq_status() -> dict:
    """元亨 QQ / NapCat / bridge status for the workbench."""
    out = {"uin": "3655185302", "name": "元亨", "online": False,
           "ws": False, "bridge": False, "since": 0.0}
    try:
        p = _PROJECT_ROOT / "cache" / "tmp" / "napcat_status.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in ("online", "ws", "since"):
            if k in d:
                out[k] = d[k]
    except Exception:
        pass
    try:
        import psutil

        out["bridge"] = any(
            "qq_bot.py" in " ".join(pi.info.get("cmdline") or [])
            for pi in psutil.process_iter(["cmdline"]))
    except Exception:
        pass
    return out


def _sse(data: dict) -> bytes:
    return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")


GET_UI = {"/", "/index.html", "/console.css", "/console.js", "/state",
          "/history", "/monitor", "/settings", "/devices", "/logs",
          "/ledger", "/mem", "/favicon.png", "/loading.webp", "/sessions",
          "/avatar.html", "/avatar.js", "/avatar-models", "/chat_popup.html",
          "/emotion", "/qq-qrcode", "/growth"}
MODEL_DIR = _PROJECT_ROOT / "角色皮套"
VENDOR_DIR = _PROJECT_ROOT / "assets" / "vendor" / "live2d"
POST_UI = {"/talk", "/voice", "/reset", "/settings", "/control", "/session",
           "/tap"}


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

    def _qq_qrcode(self) -> None:
        """Serve NapCat's login QR (saved to qrcode.png) so the workbench can
        show it directly — NapCat is headless (no console/QQ window needed)."""
        qr = Path(r"C:\Users\ACE_WAN——PROJECT\qqwatch\shell\cache\qrcode.png")
        try:
            if qr.exists() and (time.time() - qr.stat().st_mtime) < 300:
                body = qr.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        except Exception:
            pass
        self.send_response(404)
        self.end_headers()

    # ---------- routing (shared with daemon _Handler via inheritance) ----------
    def _serve_under(self, route_prefix: str, base_dir) -> None:
        from urllib.parse import unquote

        p = self.path.split("?", 1)[0]
        if not p.startswith(route_prefix):
            self._send_json(404, {"error": "未找到"})
            return
        rel = unquote(p[len(route_prefix):]).lstrip("/")
        target = (base_dir / rel).resolve()
        try:
            if not str(target).startswith(str(base_dir.resolve())) or \
                    not target.is_file():
                self._send_json(404, {"error": "未找到"})
                return
        except Exception:
            self._send_json(404, {"error": "未找到"})
            return
        ext = target.suffix.lower()
        ctype = ("image/png" if ext == ".png"
                 else "application/json" if ext == ".json"
                 else "image/webp" if ext == ".webp"
                 else "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _tap(self, body: dict) -> dict:
        """Pet tap/greet: Yuanheng answers a short impromptu line."""
        speak = str(body.get("speak", "0")) not in ("0", "false", "off")
        text = ("（有人轻轻碰了你一下）用一两句自然、有你自己味道的话回应，"
                "别太长的总结，说点什么心里话。")
        try:
            info = self.runtime.console_turn_stream(
                text, lambda _c: None)
            answer = str(info.get("answer", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            answer = ""
            return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        if speak and answer:
            st = _settings_load()
            try:
                import threading as _th

                _th.Thread(target=self._speak,
                           args=(answer, st.get("tts_speaker", "Vivian")),
                           daemon=True).start()
            except Exception:
                pass
        _log("tap", answer[:60])
        return {"ok": True, "answer": answer}

    def console_do_GET(self):
        p = self.path.split("?", 1)[0]
        if p.startswith("/live2d/"):
            self._serve_under("/live2d/", VENDOR_DIR)
            return
        if p.startswith("/live2d-models/"):
            self._serve_under("/live2d-models/", MODEL_DIR)
            return
        if p in ("/", "/index.html"):
            self._serve_file("index.html")
        elif p == "/avatar.html":
            self._serve_file("avatar.html")
        elif p == "/chat_popup.html":
            self._serve_file("chat_popup.html")
        elif p == "/avatar.js":
            self._serve_file("avatar.js")
        elif p == "/favicon.png":
            self._serve_file("favicon.png")
        elif p == "/qq-qrcode":
            self._qq_qrcode()
        elif p == "/loading.webp":
            self._serve_file("loading.webp")
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
        elif p == "/ledger":
            self._send_json(200, self._ledger())
        elif p == "/growth":
            try:
                from backend import growth_log

                self._send_json(200, {"items": growth_log.recent(30)})
            except Exception as exc:
                self._send_json(200, {"items": [], "error": type(exc).__name__})
        elif p == "/mem":
            self._send_json(200, self._mem())
        elif p == "/sessions":
            self._send_json(200, self._sessions())
        elif p == "/avatar-models":
            self._send_json(200, self._avatar_models())
        elif p == "/emotion":
            from urllib.parse import parse_qs, urlparse

            q = (parse_qs(urlparse(self.path).query).get("text", [""])[0]).strip()
            try:
                from backend.emotion_classifier import classify_emotion

                self._send_json(200, {"ok": True,
                                      "emotion": classify_emotion(q)})
            except Exception as exc:
                self._send_json(200, {"ok": False,
                                      "error": type(exc).__name__})
        elif p == "/logs":
            self._send_json(200, {"ok": True, "logs": list(_LOG_RING)})
        elif p == "/settings":
            self._send_json(200, {"ok": True, "settings": _settings_load()})
        elif p == "/devices":
            self._send_json(200, {"ok": True, "devices": _audio_devices()})
        else:
            self._send_json(404, {"error": "未找到"})

    def do_GET(self):
        self.console_do_GET()

    def console_do_POST(self):
        p = self.path.split("?", 1)[0]
        if p == "/talk":
            self._do_talk()
            return
        if p == "/tap":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, self._tap(body))
            return
        if p == "/voice":
            self._do_voice()
            return
        if p == "/reset":
            self._do_reset()
            return
        if p == "/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, {"ok": True,
                                  "settings": _settings_save(body)})
            return
        if p == "/control":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, self._control(body))
            return
        if p == "/session":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, self._session_load(body))
            return
        self._send_json(404, {"error": "未找到"})

    def do_POST(self):
        self.console_do_POST()

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
            _log("reset", "新对话")
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
            self._send_json(400, {"error": "请求格式错误"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        import threading

        alive = {"ok": True}
        _emit_lock = threading.Lock()

        def emit(data: dict) -> None:
            if not alive["ok"]:
                return
            with _emit_lock:
                try:
                    self.wfile.write(_sse(data))
                    self.wfile.flush()
                except Exception:
                    alive["ok"] = False  # client gone -> stop the loop

        import time as _t

        try:
            st = _settings_load()
            mock_text = str(body.get("text", "") or "").strip()
            continuous = str(body.get("continuous", "")).lower() in (
                "1", "true", "yes", "on")
            _log("voice", ("mock:" + mock_text) if mock_text
                 else ("continuous" if continuous else "listen"))
            speak_default = "1" if st.get("tts_speak", True) else "0"
            speak = str(body.get("speak", speak_default)) not in ("0", "false", "off")
            if mock_text:
                emit({"type": "state", "value": "thinking"})
                info = self.runtime.console_turn_stream(
                    mock_text, lambda c: emit({"type": "delta", "delta": c}))
                answer = str(info.get("answer", ""))
                emit({"type": "turn_done", "text": answer,
                      "tool_uses": len(info.get("tool_uses") or [])})
                if speak and answer.strip():
                    emit({"type": "state", "value": "speaking"})
                    self._speak(answer, st.get("tts_speaker", "Vivian"),
                                st.get("tts_model", "0.6B"))
                emit({"type": "state", "value": "idle"})
                emit({"type": "voice_done", "status": "ok"})
                return
            from tools.tts_test_start import _get_sv, release_sv

            rounds = 0
            idle = 0
            while alive["ok"] and rounds < (999 if continuous else 4):
                rounds += 1
                emit({"type": "state", "value": "listening"})
                # streaming recognition worker: transcribe each segment as it
                # closes, accumulate text, and speculatively prefetch memory
                # while the user is still speaking (ledger 0226)
                import queue as _queue
                import threading as _th

                seg_q: "_queue.Queue" = _queue.Queue()
                _stop = object()
                parts: list[str] = []
                pre: list[str] = []

                # V3: streaming ASR for live partial (sherpa zh-en), fed by chunks
                _sherpa = _get_sherpa()
                sherpa_q: "_queue.Queue" = _queue.Queue()
                if _sherpa is not None:
                    def _sherpa_worker():
                        from backend.target_chain import CancellationSignal

                        sig = CancellationSignal()
                        try:
                            _sherpa.open_stream("cap", 1, 16000, 1, sig)
                        except Exception:
                            return
                        last = ""
                        while True:
                            it = sherpa_q.get()
                            if it is _stop:
                                break
                            try:
                                for u in _sherpa.push_audio("cap", it, 16000, sig):
                                    t = str(getattr(u, "text", "") or "")
                                    if t and t != last:
                                        last = t
                                        emit({"type": "partial", "text": t})
                            except Exception:
                                pass
                    _th.Thread(target=_sherpa_worker, daemon=True).start()

                def _worker():
                    import re as _re2

                    try:
                        sv = _get_sv()
                    except Exception:
                        sv = None
                    acc = ""
                    last_pre = 0.0
                    while True:
                        item = seg_q.get()
                        if item is _stop:
                            break
                        if sv is None:
                            continue
                        try:
                            res = sv.generate(input=item, language="zh",
                                              use_itn=True, batch_size_s=60)
                            raw = str((res[0] or {}).get("text") or "")
                            t = _re2.sub(r"<\|[^|]+\|>", "", raw).strip()
                        except Exception:
                            t = ""
                        if t:
                            parts.append(t)
                            acc = "".join(parts)
                            if _sherpa is None:  # fallback: segment-based partial
                                emit({"type": "partial", "text": acc})
                            if len(acc) >= 6 and time.time() - last_pre > 2.0:
                                last_pre = time.time()
                                try:
                                    s = self.runtime._session("console")
                                    pre[:] = [str(h.get("summary", ""))[:150]
                                              for h in s.memory.contextual_recall(
                                                  acc, limit=3)]
                                except Exception:
                                    pass

                wt = _th.Thread(target=_worker, daemon=True)
                wt.start()
                r = self._listen(body, st, on_segment=seg_q.put,
                                 on_chunk=(sherpa_q.put if _sherpa is not None else None))
                seg_q.put(_stop)
                sherpa_q.put(_stop)
                wt.join(timeout=8)
                if not r.get("started"):
                    if continuous:
                        idle += 1
                        if idle >= 3 or not alive["ok"]:
                            break
                        continue
                    if rounds == 1:
                        emit({"type": "state", "value": "idle"})
                        emit({"type": "voice_done", "status": "no-speech"})
                        return
                    break
                idle = 0
                text = "".join(parts).strip()
                if not text:
                    # fallback: whole-segment transcribe (worker produced none)
                    emit({"type": "state", "value": "asr"})
                    try:
                        sv = _get_sv()
                        res = sv.generate(input=r["audio"], language="zh",
                                          use_itn=True, batch_size_s=60)
                        raw = str((res[0] or {}).get("text") or "") if res else ""
                        import re as _re3

                        text = _re3.sub(r"<\|[^|]+\|>", "", raw).strip()
                    except Exception:
                        text = ""
                release_sv()
                emit({"type": "voice_text", "kind": "user", "text": text})
                if not text:
                    break
                emit({"type": "state", "value": "thinking"})
                info = self.runtime.console_turn_stream(
                    text, lambda c: emit({"type": "delta", "delta": c}),
                    pre_recall=pre or None)
                answer = str(info.get("answer", ""))
                emit({"type": "turn_done", "text": answer,
                      "tool_uses": len(info.get("tool_uses") or [])})
                if speak and answer.strip():
                    emit({"type": "state", "value": "speaking"})
                    rr = self._speak_interruptible(
                        answer, st.get("tts_speaker", "Vivian"),
                        int(st.get("device", 1) or 1),
                        st.get("tts_model", "0.6B"))
                    if rr == "interrupted":
                        emit({"type": "interrupted"})
                        continue  # back to listening (barge-in)
                if not continuous:
                    break
                # continuous: keep listening for the next turn
            emit({"type": "state", "value": "idle"})
            emit({"type": "voice_done", "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            import traceback

            _log("voice_error", f"{type(exc).__name__}: {str(exc)[:160]}")
            try:
                _d = _PROJECT_ROOT / "cache" / "tmp"
                _d.mkdir(parents=True, exist_ok=True)
                with (_d / "voice_error.log").open("a", encoding="utf-8") as f:
                    f.write(f"\n=== {time.strftime('%H:%M:%S')} ===\n")
                    f.write(traceback.format_exc())
            except Exception:
                pass
            emit({"type": "error", "message": f"{type(exc).__name__}: "
                                              f"{str(exc)[:200]}"})
            emit({"type": "state", "value": "idle"})

    # ---------- voice helpers ----------
    def _control(self, body: dict) -> dict:
        action = str(body.get("action", ""))
        if action == "release_vram":
            try:
                from tools.tts_test_start import release_sv

                release_sv()
                import gc
                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                _log("control", "release_vram")
                return {"ok": True, "note": "ASR/TTS cuda 已释放"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}"}
        if action == "reload_settings":
            return {"ok": True, "settings": _settings_load()}
        if action in ("drives_add", "drives_reinforce", "drives_fade"):
            try:
                from backend import intrinsic_drives

                if action == "drives_add":
                    name = str(body.get("name", "")).strip()
                    if not name:
                        return {"ok": False, "error": "name required"}
                    intrinsic_drives.add(
                        name, str(body.get("category", "其他") or "其他"),
                        float(body.get("strength", 0.6) or 0.6),
                        evidence="老爹在工作台添加", channel="老爹")
                elif action == "drives_reinforce":
                    intrinsic_drives.reinforce(str(body.get("id", "")))
                else:
                    # 淡出（软，不删除）
                    ds = intrinsic_drives.load()
                    for d in ds:
                        if d.get("id") == str(body.get("id", "")):
                            d["status"] = "faded"
                    intrinsic_drives.save(ds)
                _log("control", action)
                return {"ok": True, "drives": _drives_list()}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action == "napcat_login":
            try:
                import subprocess

                shell = Path(r"C:\Users\ACE_WAN——PROJECT\qqwatch\shell")
                kill = shell / "KillQQ.bat"
                launch = shell / "launcher-user.bat"
                if not launch.exists():
                    return {"ok": False, "error": "找不到 launcher-user.bat"}
                if kill.exists():
                    subprocess.run(["cmd", "/c", str(kill)], cwd=str(shell),
                                   capture_output=True)
                subprocess.Popen(
                    ["cmd", "/c", str(launch), "3655185302"],
                    cwd=str(shell), close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                _bring_qq_front(delay=12)
                _log("control", "napcat_login")
                return {"ok": True,
                        "note": "已唤起 NapCat，请在弹出的窗口登录元亨号 3655185302"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action == "launch_pet":
            try:
                import subprocess

                desktop = _PROJECT_ROOT / "desktop"
                exe = desktop / "node_modules" / ".bin" / "electron.cmd"
                if not exe.exists():
                    return {"ok": False, "error": "未找到 electron（desktop/node_modules）"}
                subprocess.Popen(["cmd", "/c", str(exe), "."],
                                 cwd=str(desktop), close_fds=True)
                _log("control", "launch_pet")
                return {"ok": True, "note": "已启动桌宠"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action == "launch_all":
            try:
                import subprocess

                bat = _PROJECT_ROOT / "YHLZ_全家桶.bat"
                if not bat.exists():
                    return {"ok": False, "error": "找不到 YHLZ_全家桶.bat"}
                subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(_PROJECT_ROOT),
                                 close_fds=True)
                _log("control", "launch_all")
                return {"ok": True, "note": "已启动全家桶"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action == "cancel_turn":
            try:
                from backend import turn_control

                turn_control.request(str(body.get("channel", "console")))
                _log("control", "cancel_turn")
                return {"ok": True, "note": "已请求停止"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}"}
        return {"ok": False, "error": "未知操作：" + action}

    def _listen(self, body, st: dict, on_segment=None, on_chunk=None) -> dict:
        from tools.tts_test_start import _capture_loop

        device = int(body.get("device", st.get("device", 1)))
        dur = float(body.get("duration", st.get("duration", 60.0)))
        denoise = str(body.get("denoise", st.get("denoise", "rnnoise")))
        emit = self._emit_level

        def on_level(level, is_speech):
            try:
                emit(level, is_speech)
            except Exception:
                pass

        return _capture_loop(device, 1.0, dur, denoise, None, False, False,
                             on_level=on_level, on_segment=on_segment,
                             on_chunk=on_chunk)

    def _emit_level(self, level, is_speech):
        self.wfile.write(_sse({"type": "level", "value": round(float(level), 4),
                               "speech": bool(is_speech)}))
        self.wfile.flush()

    @staticmethod
    def _sentences(text: str, maxlen: int = 60) -> list[str]:
        import re as _re

        t = str(text or "").strip()
        if not t:
            return []
        parts = [p for p in _re.split(r"(?<=[。！？!?；;…])", t) if p.strip()]
        out, cur = [], ""
        for p in parts:
            if len(cur) + len(p) <= maxlen:
                cur += p
            else:
                if cur:
                    out.append(cur)
                cur = p if len(p) <= maxlen else p[:maxlen]
        if cur:
            out.append(cur)
        return out[:6] or [t[:maxlen]]

    def _speak_interruptible(self, text: str, speaker: str = "Vivian",
                             device: int = 1,
                             model_key: str = "0.6B") -> str:
        """Sentence-by-sentence resident TTS with barge-in (echo-masked).
        First sentence is synthesized+played immediately (faster first sound);
        if the user speaks over it, stop and return 'interrupted'."""
        import numpy as np
        import sounddevice as sd

        try:
            m = _get_tts(model_key)
        except Exception:
            return "done"
        chunks = self._sentences(text)
        try:
            with sd.InputStream(device=int(device), samplerate=16000,
                                channels=1, dtype="float32",
                                blocksize=1600, latency="low") as inp:
                for chunk in chunks:
                    try:
                        wavs, sr = m.generate_custom_voice(
                            text=str(chunk)[:120], language="Chinese",
                            speaker=str(speaker),
                            instruct="自然地说，像和亲近的人聊天，别播音腔。")
                        samples = np.asarray(wavs[0], dtype="float32")
                    except Exception:
                        continue
                    play_rms = float(np.sqrt(np.mean(samples * samples)) + 1e-9)
                    thr = max(0.05, play_rms * 1.5)
                    sd.play(samples, int(sr))
                    dur = len(samples) / float(sr)
                    t0 = time.time()
                    hot = 0
                    while time.time() - t0 < dur + 0.3:
                        data, _ = inp.read(1600)
                        mono = np.asarray(
                            data[:, 0] if data.ndim > 1 else data,
                            dtype="float32")
                        rms = float(np.sqrt(np.mean(mono * mono)) + 1e-9)
                        if rms > thr:
                            hot += 1
                            if hot >= 2:
                                sd.stop()
                                _log("voice", f"tts interrupted (rms={rms:.3f} "
                                              f"thr={thr:.3f})")
                                return "interrupted"
                        else:
                            hot = 0
        except Exception:
            pass
        try:
            sd.stop()
        except Exception:
            pass
        _log("voice", "tts done")
        return "done"

    def _speak(self, text: str, speaker: str = "Vivian",
               model_key: str = "0.6B") -> None:
        import numpy as np
        import sounddevice as sd

        try:
            m = _get_tts(model_key)
        except Exception:
            return
        for chunk in self._sentences(text):
            try:
                wavs, sr = m.generate_custom_voice(
                    text=str(chunk)[:120], language="Chinese",
                    speaker=str(speaker),
                    instruct="自然地说，像和亲近的人聊天，别播音腔。")
                sd.play(np.asarray(wavs[0], dtype="float32"), int(sr))
                sd.wait()
            except Exception:
                continue

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

    def _sessions(self) -> dict:
        from backend.target_entry import ConversationSession

        try:
            rows = ConversationSession.recent_sessions(14)
            return {"ok": True, "items": rows}
        except Exception as exc:
            return {"ok": False, "items": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def _session_load(self, body: dict) -> dict:
        name = str(body.get("name", "")).strip()
        if not name or "/" in name or "\\" in name:
            return {"ok": False, "error": "bad name"}
        try:
            s = self.runtime._session("console")
            # archive current console first if it has content
            if s.history:
                try:
                    import time as _t

                    s.save_session(f"archive_{int(_t.time())}")
                except Exception:
                    pass
            n = s.load_session(name)
            s.save_session("console")
            _log("session", "load " + name)
            return {"ok": True, "loaded": name, "messages": n}
        except Exception as exc:
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def _avatar_models(self) -> dict:
        items = []
        try:
            for p in sorted(MODEL_DIR.rglob("*.model3.json")):
                rel = p.relative_to(MODEL_DIR).as_posix()
                name = p.parent.name
                items.append({"name": name, "rel": rel})
        except Exception as exc:
            return {"ok": False, "items": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        return {"ok": True, "items": items}

    def _ledger(self) -> dict:
        from urllib.parse import parse_qs, urlparse

        q = (parse_qs(urlparse(self.path).query).get("q", [""])[0]).strip()
        if not q or not LEDGER_FILE.exists():
            return {"ok": bool(q), "query": q, "items": []}
        import re

        lines = LEDGER_FILE.read_text(encoding="utf-8").splitlines()
        recs: list[tuple[str, list[str]]] = []
        cur: list[str] | None = None
        title = ""
        for ln in lines:
            m = re.match(r"^## 记录 (\d+)[:：]?\s*(.*)", ln)
            if m:
                if cur is not None:
                    recs.append((title, cur))
                title = f"记录 {m.group(1)}：{m.group(2).strip()}"
                cur = []
            elif cur is not None:
                cur.append(ln)
        if cur is not None:
            recs.append((title, cur))
        low = q.lower()
        out = []
        for title, body in recs:
            hit = low in title.lower() or any(low in b.lower() for b in body[:60])
            if not hit:
                continue
            first = next((b.strip()[:150] for b in body
                          if low in b.lower() and b.strip()), body[0].strip()[:150]
                         if body else "")
            out.append({"id": title, "text": first})
            if len(out) >= 10:
                break
        out.reverse()  # newest first
        return {"ok": True, "query": q, "items": out}

    def _mem(self) -> dict:
        from urllib.parse import parse_qs, urlparse

        q = (parse_qs(urlparse(self.path).query).get("q", [""])[0]).strip()
        limit = int(parse_qs(urlparse(self.path).query).get("limit", ["8"])[0])
        if not q:
            return {"ok": True, "query": q, "items": []}
        try:
            s = self.runtime._session("console")
            hits = s.memory.recall(q, limit=min(limit, 20))
            items = [{"id": h.get("id"), "type": h.get("type"),
                      "importance": h.get("importance"),
                      "status": h.get("status"),
                      "summary": str(h.get("summary", ""))[:180]}
                     for h in (hits or [])]
            return {"ok": True, "query": q, "items": items}
        except Exception as exc:
            return {"ok": False, "query": q,
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
            try:
                o = json.loads(urllib.request.urlopen(
                    "http://127.0.0.1:11434/api/tags", timeout=3).read())
                out["ollama"] = "ok" if "models" in o else "down"
            except Exception:
                out["ollama"] = "down"
            out["qq"] = _qq_status()
            try:
                dp = _PROJECT_ROOT / "cache" / "dev" / "state.json"
                dd = json.loads(dp.read_text(encoding="utf-8"))
                out["dev"] = {"status": str(dd.get("status", "idle")),
                              "task": str(dd.get("task", ""))[:60]}
            except Exception:
                out["dev"] = {"status": "idle", "task": ""}
            out["drives"] = _drives_list()
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
            self._send_json(400, {"error": "请求格式错误"})
            return
        if not text:
            self._send_json(400, {"error": "empty text"})
            return
        _log("talk", text[:80])
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
