"""dsh worker for the 利贞 dual-track backend (v1.1, ledger 0446).

Runs under `venv-dsh` (the isolated venv that carries deepseek-harness-sdk).
A DeepSeekHarness instance must stay alive across dev_runner invocations
because the SDK has no cross-process session resume (`session_prompt` only
creates). HTTP on 127.0.0.1:8347; state is written to cache/dev/state.json —
the same contract the opencode backend uses, so QQ/daemon flows are unchanged.

Usage: venv-dsh\\Scripts\\python.exe tools/dsh_worker.py [--port 8347]
       [--workdir <dir>] [--model deepseek-v4-flash]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_TOOLS = pathlib.Path(__file__).resolve().parent
_ROOT = _TOOLS.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_TOOLS))

import dev_runner as dr  # noqa: E402  (prompts/state/classify contract)

STATE = _ROOT / "cache" / "dev" / "state.json"
LOG = _ROOT / "cache" / "dev" / "dsh.log"
LOCK = _ROOT / "cache" / "tmp" / "dsh_worker.lock"

_harness = None
_harness_lock = threading.Lock()
_busy = False
_worker_cfg = {"workdir": str(_ROOT), "dsh_home": str(_ROOT / "cache" / "dsh-home"),
               "model": os.getenv("YHLZ_DSH_MODEL", "deepseek-v4-flash")}


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _harness_get():
    global _harness
    with _harness_lock:
        if _harness is None:
            from backend.env_loader import ensure_env_loaded

            ensure_env_loaded()
            from deepseek_harness import DeepSeekHarness

            _harness = DeepSeekHarness(
                provider="deepseek-official",
                model=_worker_cfg["model"],
                max_tokens=49152,
                cwd=_worker_cfg["workdir"],
                dsh_home=_worker_cfg["dsh_home"],
                profile="sdk-minimal",
                # A1 hardening (ledger 0450): never inherit a wider sandbox —
                # production gray runs as workspace-write unless explicitly
                # overridden via YHLZ_DSH_PERMISSION_MODE.
                env={"DSH_PERMISSION_MODE": os.getenv(
                    "YHLZ_DSH_PERMISSION_MODE", "workspace-write")},
            )
            _harness.start()
            _log(f"harness started model={_worker_cfg['model']} "
                 f"workdir={_worker_cfg['workdir']}")
        return _harness


def _run_async(prompt: str, session: str, task: str) -> None:
    global _busy
    _busy = True
    try:
        h = _harness_get()
        r = h.run(prompt, session_id=session)
        text = (r.final_response or "").strip()
        status = dr._classify(text) if text else "error"
        dr._save({"status": status, "session": session, "task": task,
                  "text": text or "(无输出)", "backend": "dsh"})
        _log(f"done status={status} sid={session} text={text[:80]}")
    except Exception as exc:  # noqa: BLE001
        _log(f"run error {type(exc).__name__}: {exc}")
        dr._save({"status": "error", "session": session, "task": task,
                  "text": f"{type(exc).__name__}: {exc}", "backend": "dsh"})
    finally:
        _busy = False


def start(task: str) -> dict:
    if _busy:
        return {"ok": False, "error": "busy: 已有任务在跑"}
    sid = f"dev-{int(time.time() * 1000)}"
    dr._save({"status": "running", "session": "", "task": task,
              "text": "", "backend": "dsh"})
    threading.Thread(
        target=_run_async,
        args=(dr.START_PROMPT.format(task=task), sid, task),
        daemon=True, name="dsh-start").start()
    return {"ok": True, "status": "running", "session": sid}


def answer(text: str) -> dict:
    if _busy:
        return {"ok": False, "error": "busy: 已有任务在跑"}
    d = dr._load()
    sid = str(d.get("session") or "")
    if not sid:
        return {"ok": False, "error": "没有进行中的 dsh 会话"}
    d["status"] = "running"
    dr._save(d)
    threading.Thread(
        target=_run_async,
        args=(dr.ANSWER_PROMPT.format(answer=text), sid,
              str(d.get("task") or "")),
        daemon=True, name="dsh-answer").start()
    return {"ok": True, "status": "running", "session": sid}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/health":
            d = dr._load()
            self._send(200, {"status": "ok", "busy": _busy,
                             "task_status": d.get("status", ""),
                             "session": d.get("session", ""),
                             "backend": "dsh"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, {"error": "bad json"})
            return
        p = self.path.split("?")[0]
        if p == "/start":
            res = start(str(payload.get("task", "")).strip())
        elif p == "/answer":
            res = answer(str(payload.get("text", "")).strip())
        else:
            self._send(404, {"error": "not found"})
            return
        self._send(200 if res.get("ok") else 409, res)


def _acquire_singleton() -> bool:
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        if LOCK.exists():
            try:
                old = int(LOCK.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                old = 0
            if old > 0:
                try:
                    os.kill(old, 0)
                    return False
                except OSError:
                    LOCK.unlink(missing_ok=True)
        LOCK.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception:
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8347)
    ap.add_argument("--workdir", default=str(_ROOT))
    ap.add_argument("--dsh-home", default=str(_ROOT / "cache" / "dsh-home"))
    ap.add_argument("--model", default=os.getenv("YHLZ_DSH_MODEL",
                                                 "deepseek-v4-flash"))
    a = ap.parse_args()
    if not _acquire_singleton():
        print("[dsh-worker] 已有实例在运行，退出", flush=True)
        return 1
    _worker_cfg["workdir"] = str(pathlib.Path(a.workdir).resolve())
    _worker_cfg["dsh_home"] = str(pathlib.Path(a.dsh_home).resolve())
    _worker_cfg["model"] = str(a.model)
    srv = ThreadingHTTPServer(("127.0.0.1", int(a.port)), _Handler)
    _log(f"listening 127.0.0.1:{a.port} workdir={_worker_cfg['workdir']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
