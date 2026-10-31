"""dsh (harness) worker for 利贞 — resident executor, v1.2 (ledger 0797).

Runs under `venv-dsh` (the isolated venv that carries deepseek-harness-sdk).
A DeepSeekHarness instance must stay alive across dev_runner/qq_dev_worker
invocations because the SDK has no cross-process session resume
(`session_prompt` only creates), so this process is the single owner of every
harness instance and exposes it over HTTP on 127.0.0.1:8347.

Two contracts share the one process:

* Full path — `POST /start` / `POST /answer`: one active session, progress
  mirrored into `cache/dev/state.json` (unchanged since ledger 0446; the QQ
  Full bridge and `tools/dev_runner.py` keep reading it).
* Job path — `POST /job/start` / `POST /job/answer` / `GET /job/state` /
  `POST /job/cancel` / `POST /job/dispose`: profile-scoped QQ Bridge Lite jobs.
  One harness instance per job workspace (git worktree), state mirrored into
  `cache/dev/harness_jobs/<job_id>.json`.

Both paths run with `DSH_PERMISSION_MODE=workspace-write` unless explicitly
overridden (ledger 0450 hard gate: a dev run never inherits
danger-full-access), and both inject the yhlz MCP bridge so 利贞 keeps the
ledger/memory tools that opencode used to provide (AGENTS.md tool-first rule).

Usage: venv-dsh\\Scripts\\python.exe tools/dsh_worker.py [--port 8347]
       [--workdir <dir>] [--dsh-home <dir>] [--model deepseek-v4-flash]
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

import dev_contract as dc  # noqa: E402  (prompts/classification contract)
import dev_runner as dr  # noqa: E402  (Full-path state.json contract)

STATE = _ROOT / "cache" / "dev" / "state.json"
LOG = _ROOT / "cache" / "dev" / "dsh.log"
LOCK = _ROOT / "cache" / "tmp" / "dsh_worker.lock"
JOBS_DIR = _ROOT / "cache" / "dev" / "harness_jobs"
MCP_PATCH = _ROOT / "cache" / "dev" / "harness_mcp.patch.yml"
MCP_SERVER = _TOOLS / "yhlz_mcp_server.py"
POOL_MAX = 2
# A job client polls /job/state every ~2s. If nobody asks for this long the
# client died (killed bridge/worker), so the run is stopped instead of being
# left writing into the workspace — a backstop for a stale bridge whose
# #cancel predates the gateway (ledger 0797).
LEASE_SECONDS = float(os.getenv("YHLZ_DSH_JOB_LEASE", "600"))

_harness_pool: dict[str, object] = {}
_pool_lock = threading.Lock()
_ws_locks: dict[str, threading.Lock] = {}
_busy = False
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_job_threads: dict[str, threading.Thread] = {}
# 利贞 QQ 桥：一个常驻会话，跨消息保留上下文（同一个 harness 进程内）。
_chat_lock = threading.Lock()
_chat_harness = None
CHAT_SESSION = "lizhen-qq"
CHAT_WORKSPACE = _ROOT / "cache" / "lizhen_qq" / "workspace"
PERSONA_FILE = pathlib.Path(r"C:\Users\ACE_WAN——PROJECT\.dsh\AGENT.md")
_worker_cfg = {"workdir": str(_ROOT), "dsh_home": str(_ROOT / "cache" / "dsh-home"),
               "model": os.getenv("YHLZ_DSH_MODEL", "deepseek-v4-flash"),
               "mcp": os.getenv("YHLZ_DSH_MCP", "1").strip() != "0"}


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _mcp_patch_path(workspace: str | None = None) -> str | None:
    """Write the yhlz MCP overlay for the harness profile; None disables it.

    opencode.json used to give 利贞 the ledger/memory tools; on harness they
    arrive through the official mcp-client plugin, injected as a `--patch`
    overlay so no profile file is edited. The patch is plain JSON (valid YAML)
    with absolute paths baked in — no `!!js` evaluation needed.
    """
    if not _worker_cfg["mcp"]:
        return None
    python = _ROOT / ".venv" / "Scripts" / "python.exe"
    if not MCP_SERVER.exists() or not python.exists():
        _log("mcp overlay skipped: python/venv or server missing")
        return None
    entry = {
        "insert": [
            {
                "id": "mcp-yhlz",
                "name": "@deepseek-ai/dsh-mcp-client",
                "config": {
                    "serverName": "yhlz",
                    "transport": "stdio",
                    "command": str(python),
                    "args": ["-B", str(MCP_SERVER)],
                    "cwd": str(_ROOT),
                    "toolCallTimeoutMs": 120000,
                    "reconnect": {"enabled": True},
                },
            }
        ]
    }
    if workspace:
        entry["insert"].append({
            "id": "mcp-cmd", "name": "@deepseek-ai/dsh-mcp-client",
            "config": {"serverName": "cmd", "transport": "stdio", "command": str(python),
                       "args": ["-B", str(_TOOLS / "lizhen_cmd_mcp.py"), "--workspace", workspace],
                       "cwd": workspace, "toolCallTimeoutMs": 150000}})
    patch_path = MCP_PATCH
    if workspace:
        import hashlib
        patch_path = MCP_PATCH.with_name("harness_mcp_" + hashlib.sha256(workspace.encode()).hexdigest()[:12] + ".patch.yml")
    try:
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(
            "# generated by tools/dsh_worker.py — 利贞 harness overlay: yhlz MCP\n"
            + json.dumps([{"id": "terminal-pwsh", "disabled": True},
                                  {"id": "persistent-pwsh", "disabled": True},
                                  entry], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return str(patch_path)
    except Exception as exc:  # noqa: BLE001
        _log(f"mcp overlay write failed: {type(exc).__name__}")
        return None


def _make_harness(workspace: str):
    from backend.env_loader import ensure_env_loaded

    ensure_env_loaded()
    from deepseek_harness import DeepSeekHarness

    patches = tuple(p for p in (_mcp_patch_path(workspace),) if p)
    if not patches:
        raise RuntimeError("普通CMD和yhlz MCP不可用，拒绝启用利贞任务")
    harness = DeepSeekHarness(
        provider="deepseek-official",
        model=_worker_cfg["model"],
        max_tokens=49152,
        cwd=workspace,
        dsh_home=_worker_cfg["dsh_home"],
        profile="sdk-minimal",
        patches=patches,
        # A1 hardening (ledger 0450): never inherit a wider sandbox —
        # production runs as workspace-write unless explicitly overridden.
        env={"DSH_PERMISSION_MODE": os.getenv(
            "YHLZ_DSH_PERMISSION_MODE", "workspace-write"),
             "COMSPEC": os.getenv("COMSPEC", r"C:\Windows\System32\cmd.exe"),
             "SHELL": os.getenv("COMSPEC", r"C:\Windows\System32\cmd.exe")},
    )
    try:
        harness.start()
    except Exception:
        try:
            harness.close()
        except Exception:
            pass
        raise
    _log(f"harness started model={_worker_cfg['model']} cwd={workspace} "
         f"mcp={'on' if patches else 'off'}")
    return harness


def _harness_for(workspace: str):
    ws = str(pathlib.Path(workspace).resolve())
    with _pool_lock:
        harness = _harness_pool.get(ws)
        if harness is None:
            harness = _make_harness(ws)
            _harness_pool[ws] = harness
            while len(_harness_pool) > POOL_MAX:
                oldest = next(iter(_harness_pool))
                if oldest == ws:
                    break
                _dispose_locked(oldest)
        return harness


def _dispose_locked(ws: str) -> None:
    harness = _harness_pool.get(ws)
    if harness is None:
        return True
    try:
        harness.close()  # type: ignore[attr-defined]
        _harness_pool.pop(ws, None)
        _log(f"harness closed cwd={ws}")
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"harness close failed cwd={ws}: {type(exc).__name__}")
        return False


def _dispose(workspace: str) -> None:
    with _pool_lock:
        return _dispose_locked(str(pathlib.Path(workspace).resolve()))


def _harness_get():
    """Full-path accessor: the worker's default workspace harness."""
    return _harness_for(_worker_cfg["workdir"])


# --------------------------------------------------------------------------
# Full path (dev_runner): one active session, state.json contract
# --------------------------------------------------------------------------

def _chat_persona() -> str:
    try:
        text = PERSONA_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        text = ""
    return text[:2600]


def chat(text: str) -> dict:
    """One persistent 利贞 chat session for the QQ bridge."""
    global _chat_harness
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    if not _chat_lock.acquire(blocking=False):
        return {"ok": False, "error": "busy: 利贞正在回复上一条"}
    try:
        CHAT_WORKSPACE.mkdir(parents=True, exist_ok=True)
        h = _chat_harness
        if h is None:
            h = _make_harness(str(CHAT_WORKSPACE))
            _chat_harness = h
        persona = _chat_persona()
        prompt = ((persona + "\n\n" if persona else "")
                  + "【QQ 对话】\n" + text
                  + "\n\n直接以利贞的身份回复，不要输出工具/系统说明。")
        r = h.run(prompt, session_id=CHAT_SESSION)
        answer = str(getattr(r, "final_response", "") or "").strip()
        return {"ok": True, "answer": answer or "(无输出)",
                "session": CHAT_SESSION}
    except Exception as exc:  # noqa: BLE001
        _log(f"chat error {type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _chat_lock.release()


def _run_async(prompt: str, session: str, task: str) -> None:
    global _busy
    _busy = True
    try:
        h = _harness_get()
        r = h.run(prompt, session_id=session)
        text = (r.final_response or "").strip()
        status = dc.classify(text) if text else "error"
        dr._save({"status": status, "session": session, "task": task,
                  "text": text or "(无输出)", "backend": "dsh"})
        _log(f"done status={status} sid={session} text={text[:80]}")
    except Exception as exc:  # noqa: BLE001
        _log(f"run error {type(exc).__name__}: {exc}")
        dr._save({"status": "error", "session": session, "task": task,
                  "text": f"{type(exc).__name__}: {exc}", "backend": "dsh"})
    finally:
        saved = dr._load()
        if saved.get("status") != "awaiting":
            _dispose(_worker_cfg["workdir"])
            saved["session"] = ""
            dr._save(saved)
        _busy = False


def start(task: str) -> dict:
    if _busy:
        return {"ok": False, "error": "busy: 已有任务在跑"}
    sid = f"dev-{int(time.time() * 1000)}"
    dr._save({"status": "running", "session": "", "task": task,
              "text": "", "backend": "dsh"})
    threading.Thread(
        target=_run_async,
        args=(dc.build_start_prompt(task, harness=True), sid, task),
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
        args=(dc.build_answer_prompt(text, harness=True), sid,
              str(d.get("task") or "")),
        daemon=True, name="dsh-answer").start()
    return {"ok": True, "status": "running", "session": sid}


# --------------------------------------------------------------------------
# Job path (QQ Bridge Lite): one harness per workspace, job registry
# --------------------------------------------------------------------------

def _job_save(job: dict) -> None:
    job["updated_at"] = time.time()
    try:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = JOBS_DIR / f"{job['job_id']}.json.tmp"
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(JOBS_DIR / f"{job['job_id']}.json")
    except Exception as exc:  # noqa: BLE001
        _log(f"job state write failed {job.get('job_id')}: "
             f"{type(exc).__name__}")


def _job_get(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            return dict(job)
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if job.get("state") in ("running", "awaiting"):
        job["session"] = ""
        # The owner process is gone (restart) — the SDK session died with it.
        job["state"] = "error"
        job["error"] = "harness worker 重启/失联，任务已中断"
        _job_save(job)
    return job


def _job_update(job_id: str, **fields) -> dict:
    with _jobs_lock:
        job = _jobs.setdefault(job_id, {"job_id": job_id})
        job.update(fields)
        job["updated_at"] = time.time()
        snapshot = dict(job)
    _job_save(snapshot)
    return snapshot


def _job_touch(job_id: str) -> None:
    """Renew the client lease (called on every /job/state read)."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["lease"] = time.time()
        snapshot = dict(job)
    _job_save(snapshot)


def _sweep_leases() -> int:
    """Stop every running job whose client stopped polling. Returns the count."""
    now = time.time()
    with _jobs_lock:
        stale = [jid for jid, job in _jobs.items()
                 if job.get("state") == "running"
                 and now - float(job.get("lease")
                                 or job.get("updated_at") or now)
                 > LEASE_SECONDS]
    for job_id in stale:
        job = _job_get(job_id) or {}
        workspace = str(job.get("workspace") or "")
        _log(f"job lease expired id={job_id} ws={workspace} — stopping")
        _job_update(job_id, state="cancelled",
                    error=(f"客户端 {LEASE_SECONDS:.0f}s 未取状态"
                           "（桥/worker 已死），已停止"))
        if workspace:
            _dispose(workspace)
    return len(stale)


def _lease_watchdog() -> None:
    """Stop runs whose client stopped polling (dead bridge/worker)."""
    while True:
        time.sleep(30.0)
        try:
            _sweep_leases()
        except Exception as exc:  # noqa: BLE001
            _log(f"lease sweep failed: {type(exc).__name__}: {exc}")


def _ws_lock(workspace: str) -> threading.Lock:
    with _pool_lock:
        return _ws_locks.setdefault(workspace, threading.Lock())


def _run_job(job_id: str, workspace: str, prompt: str, task: str) -> None:
    lock = _ws_lock(workspace)
    with lock:
        terminal = True
        try:
            if (_job_get(job_id) or {}).get("state") == "cancelled":
                return
            harness = _harness_for(workspace)
            result = harness.run(prompt, session_id=job_id)
            if (_job_get(job_id) or {}).get("state") == "cancelled":
                return
            text = (result.final_response or "").strip()
            state = dc.classify(text) if text else "error"
            terminal = state != "awaiting"
            _job_update(job_id, state=state, text=text, session=job_id if not terminal else "",
                        workspace=workspace, task=task, error="" if text else "无输出")
        except Exception as exc:
            if (_job_get(job_id) or {}).get("state") != "cancelled":
                _job_update(job_id, state="error", session="", workspace=workspace,
                            task=task, error=f"{type(exc).__name__}: {exc}")
        finally:
            if terminal:
                cleaned = _dispose(workspace)
                fields = {"session": "", "cleanup_confirmed": bool(cleaned)}
                if not cleaned:
                    fields.update(state="error", error="执行线程清理未确认")
                _job_update(job_id, **fields)
            with _jobs_lock:
                _job_threads.pop(job_id, None)


def job_start(payload: dict) -> dict:
    job_id = str(payload.get("job_id") or "").strip()
    workspace = str(payload.get("workspace") or "").strip()
    task = str(payload.get("task") or "").strip()
    if not job_id or not workspace or not task:
        return {"ok": False, "error": "job_id/workspace/task 都必填"}
    existing = _job_get(job_id)
    if existing and existing.get("state") == "running":
        return {"ok": False, "error": f"job {job_id} 已在运行"}
    if not pathlib.Path(workspace).is_dir():
        return {"ok": False, "error": f"workspace 不存在：{workspace}"}
    _job_update(job_id, state="running", text="", error="", session=job_id,
                workspace=workspace, task=task, action="start",
                lease=time.time())
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, str(pathlib.Path(workspace).resolve()),
              dc.build_start_prompt(task, harness=True), task),
        daemon=True, name=f"dsh-job-{job_id}")
    with _jobs_lock:
        _job_threads[job_id] = thread
    thread.start()
    return {"ok": True, "state": "running", "session": job_id}


def job_answer(payload: dict) -> dict:
    job_id = str(payload.get("job_id") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not job_id or not text:
        return {"ok": False, "error": "job_id/text 都必填"}
    job = _job_get(job_id)
    if not job:
        return {"ok": False, "error": f"没有 job {job_id} 的记录"}
    if job.get("state") != "awaiting":
        return {"ok": False, "error": f"job {job_id} 不在等待答复状态"}
    workspace = str(job.get("workspace") or _worker_cfg["workdir"])
    task = str(job.get("task") or "")
    _job_update(job_id, state="running", text="", error="", action="answer",
                lease=time.time())
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, str(pathlib.Path(workspace).resolve()),
              dc.build_answer_prompt(text, harness=True), task),
        daemon=True, name=f"dsh-job-{job_id}")
    with _jobs_lock:
        _job_threads[job_id] = thread
    thread.start()
    return {"ok": True, "state": "running", "session": job_id}


def job_cancel(payload: dict) -> dict:
    job_id = str(payload.get("job_id") or "").strip()
    job = _job_get(job_id) if job_id else None
    if not job:
        return {"ok": False, "error": f"没有 job {job_id} 的记录"}
    workspace = str(job.get("workspace") or "")
    _job_update(job_id, state="cancelled", session="", error="已取消")
    cleanup = job_dispose({"workspace": workspace}) if workspace else {"ok": True}
    return {"ok": cleanup.get("ok", False), "state": "cancelled", "cleanup": cleanup}


def job_dispose(payload: dict) -> dict:
    workspace = str(payload.get("workspace") or "").strip()
    if not workspace:
        return {"ok": False, "error": "workspace 必填"}
    cleaned = _dispose(workspace)
    with _jobs_lock:
        active = [(jid,t) for jid,t in _job_threads.items()
                  if str((_jobs.get(jid) or {}).get("workspace")) == str(pathlib.Path(workspace).resolve())]
    for _, thread in active:
        if thread is not threading.current_thread(): thread.join(timeout=3)
    return {"ok": bool(cleaned) and not any(t.is_alive() for _,t in active),
            "cleanup_confirmed": bool(cleaned), "threads_alive": sum(t.is_alive() for _,t in active)}


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
        path, _, query = self.path.partition("?")
        if path == "/health":
            d = dr._load()
            with _jobs_lock:
                active = [j for j in _jobs.values()
                          if j.get("state") == "running"]
            self._send(200, {"status": "ok", "busy": _busy,
                             "task_status": d.get("status", ""),
                             "session": d.get("session", ""),
                             "backend": "dsh", "jobs_active": len(active),
                             "chat_busy": _chat_lock.locked(),
                             "harnesses": len(_harness_pool)})
        elif path == "/job/state":
            job_id = ""
            for part in query.split("&"):
                if part.startswith("job_id="):
                    job_id = part[len("job_id="):]
            job = _job_get(job_id) if job_id else None
            if job is None:
                self._send(404, {"error": f"没有 job {job_id} 的记录"})
                return
            _job_touch(job_id)
            self._send(200, job)
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
        elif p in ("/turn", "/chat"):
            res = chat(str(payload.get("text") or payload.get("task") or "").strip())
        elif p == "/job/start":
            res = job_start(payload)
        elif p == "/job/answer":
            res = job_answer(payload)
        elif p == "/job/cancel":
            res = job_cancel(payload)
        elif p == "/job/dispose":
            res = job_dispose(payload)
        else:
            self._send(404, {"error": "not found"})
            return
        self._send(200 if res.get("ok") else 409, res)


def _acquire_singleton() -> bool:
    """PID identity lock; kill(pid, 0) is unsafe on Windows consoles."""
    from backend.qq_bridge_lock import acquire_pid_lock, make_info, LockError
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        if LOCK.exists():
            raw = LOCK.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                import psutil
                try:
                    proc = psutil.Process(int(raw))
                    if any(str(arg).replace("\\", "/").lower().endswith("/dsh_worker.py") for arg in proc.cmdline()):
                        return False
                except psutil.NoSuchProcess:
                    pass
                LOCK.unlink(missing_ok=True)
        acquire_pid_lock(LOCK, make_info("harness", entry=str(pathlib.Path(__file__).resolve()), role="gateway"))
        return True
    except LockError:
        return False
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8347)
    ap.add_argument("--workdir", default=str(_ROOT))
    ap.add_argument("--dsh-home", default=str(_ROOT / "cache" / "dsh-home"))
    ap.add_argument("--model", default=os.getenv("YHLZ_DSH_MODEL",
                                                 "deepseek-v4-flash"))
    ap.add_argument("--no-mcp", action="store_true",
                    help="skip the yhlz MCP overlay (debug only)")
    a = ap.parse_args()
    if not _acquire_singleton():
        print("[dsh-worker] 已有实例在运行，退出", flush=True)
        return 1
    _worker_cfg["workdir"] = str(pathlib.Path(a.workdir).resolve())
    _worker_cfg["dsh_home"] = str(pathlib.Path(a.dsh_home).resolve())
    _worker_cfg["model"] = str(a.model)
    if a.no_mcp:
        _worker_cfg["mcp"] = False
    srv = ThreadingHTTPServer(("127.0.0.1", int(a.port)), _Handler)
    threading.Thread(target=_lease_watchdog, daemon=True,
                     name="dsh-lease").start()
    _log(f"listening 127.0.0.1:{a.port} workdir={_worker_cfg['workdir']} "
         f"mcp={'on' if _worker_cfg['mcp'] else 'off'} "
         f"lease={LEASE_SECONDS:.0f}s")
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
