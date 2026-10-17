"""Harness gateway client (ledger 0797): the one door to 利贞's dsh daemon.

Both dev paths talk to the same resident worker (`tools/dsh_worker.py`):

* Full  — `tools/dev_runner.py`: `/start` + `/answer`, state in
  `cache/dev/state.json` (unchanged contract since ledger 0446).
* Lite  — `tools/qq_dev_worker.py`: `/job/start` + `/job/answer` +
  `/job/state`, one harness instance per job workspace.

This module only speaks HTTP and (when needed) spawns the worker; every
execution detail lives in the worker. Import-cheap: no heavy deps.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://127.0.0.1:8347"
DEFAULT_PY = _ROOT / "venv-dsh" / "Scripts" / "python.exe"
WORKER = _ROOT / "tools" / "dsh_worker.py"
TERMINAL_STATES = ("awaiting", "done", "error", "cancelled")


def worker_url() -> str:
    from backend.env_loader import ensure_env_loaded
    ensure_env_loaded()
    return os.getenv("YHLZ_DSH_WORKER", "").strip() or DEFAULT_URL


def dsh_python() -> pathlib.Path:
    from backend.env_loader import ensure_env_loaded
    ensure_env_loaded()
    raw = os.getenv("YHLZ_DSH_PYTHON", "").strip()
    return pathlib.Path(raw) if raw else DEFAULT_PY


def get(path: str, *, url: str | None = None, timeout: float = 30.0) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open((url or worker_url()) + path,
                                timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path: str, obj: dict, *, url: str | None = None,
         timeout: float = 30.0) -> dict:
    req = urllib.request.Request(
        (url or worker_url()) + path, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # worker answers 409 with a reason
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            raise


def healthy(*, url: str | None = None, timeout: float = 2.0) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open((url or worker_url()) + "/health",
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def spawn(*, py: pathlib.Path | None = None, workdir: str | None = None,
          url: str | None = None) -> bool:
    """Start the resident worker process (idempotent at the OS level via lock)."""
    exe = py or dsh_python()
    if not pathlib.Path(exe).exists():
        return False
    port = (url or worker_url()).rsplit(":", 1)[-1].strip("/")
    cmd = [str(exe), "-B", str(WORKER), "--port", port or "8347"]
    if workdir:
        cmd += ["--workdir", str(workdir)]
    try:
        subprocess.Popen(cmd, cwd=str(_ROOT), close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def ensure(*, url: str | None = None, py: pathlib.Path | None = None,
           workdir: str | None = None, wait_s: float = 60.0) -> bool:
    """True when the resident worker answers /health (spawning it if needed)."""
    u = url or worker_url()
    if healthy(url=u):
        return True
    if not spawn(py=py, workdir=workdir, url=u):
        return False
    end = time.time() + float(wait_s)
    while time.time() < end:
        if healthy(url=u):
            return True
        time.sleep(1.0)
    return False


def job_state(job_id: str, *, url: str | None = None) -> dict:
    return get(f"/job/state?job_id={job_id}", url=url)


def run_job(job_id: str, workspace: str, action: str, *, task: str = "",
            text: str = "", timeout: float = 1800.0, poll: float = 2.0,
            url: str | None = None,
            on_progress=None) -> dict:
    """Drive one harness job to a terminal state.

    ``action`` is ``start`` (needs ``task``) or ``answer`` (needs ``text``).
    Returns ``{ok, state, text, session, error, timed_out}``; ``state`` is one
    of ``awaiting`` / ``done`` / ``error`` / ``cancelled``.
    """
    u = url or worker_url()
    payload = ({"job_id": job_id, "workspace": str(workspace), "task": task}
               if action == "start" else
               {"job_id": job_id, "text": text})
    res = post(f"/job/{action}", payload, url=u, timeout=60.0)
    if not res.get("ok"):
        return {"ok": False, "state": "error", "text": "", "session": "",
                "error": str(res.get("error") or "worker rejected"),
                "timed_out": False}
    deadline = time.time() + float(timeout)
    last: dict = {}
    while time.time() < deadline:
        try:
            last = job_state(job_id, url=u)
        except Exception as exc:  # noqa: BLE001
            last = {"state": "error",
                    "error": f"worker 失联：{type(exc).__name__}"}
            return {"ok": False, "state": "error", "text": "", "session": "",
                    "error": last["error"], "timed_out": False}
        state = str(last.get("state") or "")
        if state in TERMINAL_STATES:
            if on_progress is not None:
                on_progress(last)
            return {"ok": state in ("awaiting", "done"),
                    "state": state,
                    "text": str(last.get("text") or ""),
                    "session": str(last.get("session") or ""),
                    "error": str(last.get("error") or ""),
                    "timed_out": False}
        if on_progress is not None:
            on_progress(last)
        time.sleep(poll)
    try:
        post("/job/cancel", {"job_id": job_id}, url=u, timeout=30.0)
    except Exception:
        pass
    return {"ok": False, "state": "error",
            "text": str(last.get("text") or ""),
            "session": str(last.get("session") or ""),
            "error": f"超时 {timeout:.0f}s", "timed_out": True}
