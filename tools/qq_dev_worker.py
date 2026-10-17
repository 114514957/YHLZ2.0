"""QQ dev worker (P3): one independent process per job execution.

Drains stdout and stderr concurrently (no pipe deadlock), enforces the total
timeout with an independent timer that kills the owned process tree, records
process ownership, and persists the result into the profile job DB. The
bridge never re-runs a job: a dead worker's running job becomes interrupted.

Executor (ledger 0797): 利贞 runs on **harness**. This process is a thin
client of the resident gateway (`tools/dsh_worker.py`): it posts
`/job/start` or `/job/answer` and polls `/job/state`. The harness instance
must outlive this process, which is exactly why the gateway owns it (the SDK
has no cross-process session resume). Backends are harness-only; the retired
opencode argv builder survives solely as the offline stub seam
(`YHLZ_QQ_DEV_AGENT_CMD`, used by the P3 evidence matrix).

Usage (spawned by qq_dev_runner, not by hand):
    python tools/qq_dev_worker.py --db <dev_jobs.db> --job <job_id> --action start
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

import dev_contract as dc  # noqa: E402
import harness_gateway as gw  # noqa: E402
from backend import qq_dev_git as githelp  # noqa: E402
from backend import qq_dev_jobs as jobs  # noqa: E402
from backend.qq_bridge_lock import make_info  # noqa: E402

MODEL = os.getenv("YHLZ_DEV_MODEL", "").strip()
AGENT = os.getenv("YHLZ_DEV_AGENT", "yhlz-dev").strip()
DEFAULT_TIMEOUT = float(os.getenv("YHLZ_QQ_DEV_TIMEOUT", "1800"))
HARNESS_BACKEND = "dsh"

# Kept for callers/tests that import the prompt contract from here.
START_PROMPT = dc.START_PROMPT
ANSWER_PROMPT = dc.ANSWER_PROMPT


def _opencode_exe() -> str:
    """Legacy (retired 2026-10-13, ledger 0797): opencode executor is unused."""
    cand = shutil.which("opencode")
    if cand:
        p = pathlib.Path(cand)
        exe = p.parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if exe.exists():
            return str(exe)
        if p.suffix.lower() == ".exe":
            return str(p)
    for c in (
        pathlib.Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules"
        / "opencode-ai" / "bin" / "opencode.exe",
        pathlib.Path(os.environ.get("ProgramFiles", "")) / "nodejs"
        / "node_modules" / "opencode-ai" / "bin" / "opencode.exe",
    ):
        if c.exists():
            return str(c)
    raise FileNotFoundError("找不到利贞(opencode)可执行文件")


def _agent(prompt: str, session: str, workspace: str) -> tuple[list[str], str | None]:
    """Legacy (retired) opencode argv builder. Test override: YHLZ_QQ_DEV_AGENT_CMD."""
    raw = os.getenv("YHLZ_QQ_DEV_AGENT_CMD", "").strip()
    if raw:
        argv = json.loads(raw)
        return [str(x) for x in argv], prompt
    cmd = [_opencode_exe(), "run", prompt, "--dir", workspace, "--format",
           "json"]
    if MODEL:
        cmd += ["-m", MODEL]
    if AGENT:
        cmd += ["--agent", AGENT]
    if session:
        cmd += ["--session", session]
    return cmd, None


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        import psutil

        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        parent.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _backend_of(job: dict, logf) -> str:
    """Harness-only (ledger 0797):任何历史/环境里的 opencode 都改走 harness。"""
    raw = str(job.get("backend") or "").strip().lower()
    if raw and raw != HARNESS_BACKEND:
        logf.write(f"[backend] {raw} 已退役 → 本次用 harness 执行\n")
    return HARNESS_BACKEND


def _agent_stub() -> str:
    """Offline stub hook for the P3 evidence matrix (never set by the bridge).

    When ``YHLZ_QQ_DEV_AGENT_CMD`` is present the job runs the stub argv
    instead of the harness gateway, so matrix/soak runs stay offline. The
    retired opencode argv builder survives only for this test seam.
    """
    return os.getenv("YHLZ_QQ_DEV_AGENT_CMD", "").strip()


def _harness_execute(job: dict, action: str, timeout: float, logf) -> dict:
    """Run one round on the resident harness gateway. Returns an exec result."""
    job_id = str(job["job_id"])
    workspace = str(job["workspace"])
    if not gw.ensure(wait_s=90.0):
        return {"state": "error", "text": "", "session": "",
                "error": "harness 网关不可用（venv-dsh 缺失或启动失败）",
                "timed_out": False}
    logf.write(f"[harness] {action} job={job_id} ws={workspace}\n")

    def progress(state: dict) -> None:
        logf.write(f"[harness] state={state.get('state')} "
                   f"updated={state.get('updated_at')}\n")

    try:
        result = gw.run_job(
            job_id, workspace, action, task=str(job.get("task") or ""),
            text=str(job.get("answer") or ""), timeout=timeout, on_progress=progress)
    except Exception as exc:
        result = {"state": "error", "text": "", "session": "",
                  "error": f"harness 调用失败: {type(exc).__name__}", "timed_out": False}
    if result.get("state") != "awaiting" or not result.get("text"):
        try:
            cleaned = gw.post("/job/dispose", {"workspace": workspace}, timeout=30.0)
            if not cleaned.get("ok"):
                raise RuntimeError("cleanup unconfirmed")
        except Exception:
            result["state"] = "error"
            result["error"] = str(result.get("error") or "") + "；执行线程清理未确认"
        result["session"] = ""
    return result



def _classify(text: str) -> str:  # legacy helper kept for callers/tests
    return dc.classify(text)


def run_job(db_path: str, job_id: str, action: str) -> int:
    con = jobs.connect(db_path)
    job = jobs.get(con, job_id)
    if not job:
        return 2
    workspace = job["workspace"]
    session = job.get("session_id") or ""
    info = make_info(os.getenv("YHLZ_QQ_PROFILE", "lite"),
                     entry=str(pathlib.Path(__file__).resolve()),
                     role="dev_worker")
    jobs.update(con, job_id, state="running", error="",
                execution_id=info["instance_id"], pid=info["pid"],
                pid_create_time=info["create_time"])

    log_path = pathlib.Path(job["log_path"]) if job.get("log_path") else \
        pathlib.Path(db_path).parent / f"{job_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    jobs.update(con, job_id, log_path=str(log_path))

    logf = log_path.open("a", encoding="utf-8", buffering=1)
    logf.write(f"\n=== worker {time.strftime('%Y-%m-%d %H:%M:%S')} "
               f"action={action} pid={os.getpid()} ===\n")
    log_lock = threading.Lock()

    backend = _backend_of(job, logf)
    logf.write(f"[backend] {backend}\n")
    if backend == HARNESS_BACKEND and not _agent_stub():
        result = _harness_execute(job, action, DEFAULT_TIMEOUT, logf)
        logf.close()
        return _finish(con, job, job_id, workspace, result, logf=None)

    # ── offline stub executor (P3 matrix/soak only; the bridge never sets it) ──
    logf.write("[executor] stub (YHLZ_QQ_DEV_AGENT_CMD)\n")
    prompt = (dc.ANSWER_PROMPT.format(answer=job.get("answer") or "")
              if action == "answer"
              else dc.START_PROMPT.format(task=job.get("task") or ""))
    try:
        argv, stdin_text = _agent(prompt, session, workspace)
    except Exception as exc:  # noqa: BLE001
        jobs.update(con, job_id, state="failed",
                    error=f"agent 不可用: {type(exc).__name__}")
        jobs.bump_result(con, job_id)
        logf.write(f"agent unavailable: {exc}\n")
        logf.close()
        return 1

    texts: list[str] = []
    sid = session
    err_tail: list[str] = []
    timed_out = threading.Event()

    try:
        proc = subprocess.Popen(
            argv, cwd=workspace, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001
        jobs.update(con, job_id, state="failed",
                    error=f"启动失败: {type(exc).__name__}")
        jobs.bump_result(con, job_id)
        logf.write(f"spawn failed: {exc}\n")
        logf.close()
        return 1

    timeout = DEFAULT_TIMEOUT
    timer = threading.Timer(timeout, lambda: (timed_out.set(), _kill_tree(proc)))
    timer.daemon = True
    timer.start()

    def drain(stream, sink) -> None:
        try:
            for line in stream:
                with log_lock:
                    logf.write(line if line.endswith("\n") else line + "\n")
                sink(line)
        except Exception:
            pass

    def on_stdout(line: str) -> None:
        nonlocal sid
        line = line.strip()
        if not line:
            return
        if line.startswith("{"):
            try:
                ev = json.loads(line)
            except Exception:
                return
            if ev.get("sessionID"):
                sid = str(ev["sessionID"])
            if ev.get("type") == "text":
                t = (ev.get("part") or {}).get("text", "")
                if t:
                    texts.append(str(t))
            elif ev.get("type") == "error":
                err_tail.append(
                    json.dumps(ev.get("error", {}), ensure_ascii=False)[:300])
            return
        texts.append(line)

    def on_stderr(line: str) -> None:
        line = line.strip()
        if line:
            err_tail.append(line[:300])

    t_out = threading.Thread(target=drain, args=(proc.stdout, on_stdout),
                             daemon=True)
    t_err = threading.Thread(target=drain, args=(proc.stderr, on_stderr),
                             daemon=True)
    t_out.start()
    t_err.start()
    try:
        if proc.stdin is not None:
            try:
                if stdin_text is not None:
                    proc.stdin.write(stdin_text)
            finally:
                # CLI 在 stdin 为管道且未关闭时会等待 EOF；必须立刻关闭。
                proc.stdin.close()
        rc = proc.wait()
    finally:
        timer.cancel()
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        try:
            logf.close()
        except Exception:
            pass

    text = "".join(texts).strip()
    return _finish(con, job, job_id, workspace,
                   {"state": "error" if timed_out.is_set() else
                    (dc.classify(text) if text else "error"),
                    "text": text, "session": sid,
                    "error": f"超时 {timeout:.0f}s" if timed_out.is_set() else
                    ("" if text else (err_tail[-1] if err_tail
                                      else f"无输出 rc={rc}")),
                    "timed_out": timed_out.is_set()},
                   logf=None)


def _finish(con, job: dict, job_id: str, workspace: str, result: dict,
            logf=None) -> int:
    """Map one executor result onto the job DB contract (never fakes success)."""
    text = str(result.get("text") or "").strip()
    state_name = str(result.get("state") or "")
    error = str(result.get("error") or "")
    if result.get("timed_out"):
        state, error = "failed", error or "超时"
    elif state_name == "cancelled":
        state, error = "interrupted", error or "已取消"
    elif state_name == "error" or not text:
        state, error = "failed", error or "无输出"
    elif state_name == "awaiting":
        state, error = "awaiting_owner", ""
    else:
        state, error = "completed", ""
    files = githelp.changed_files(workspace)
    fields: dict = {"state": state, "session_id": str(result.get("session") or "") if state == "awaiting_owner" else "",
                    "pid": 0, "pid_create_time": 0.0,
                    "changed_files": files, "error": error[:300]}
    if state == "awaiting_owner":
        fields["question"] = text
    else:
        fields["report"] = text
    if state == "completed":
        snap = githelp.snapshot(workspace, job.get("base_head") or "")
        fields["confirmed_snapshot"] = snap.get("hash", "")
    jobs.update(con, job_id, **fields)
    jobs.bump_result(con, job_id)
    return 0 if state in ("completed", "awaiting_owner") else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--action", choices=("start", "answer"), default="start")
    a = ap.parse_args()
    return run_job(a.db, a.job, a.action)


if __name__ == "__main__":
    raise SystemExit(main())
