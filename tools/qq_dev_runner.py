"""QQ Bridge Lite dev runner (P3): persistent jobs, owned workers, scope commits.

Profile-scoped; never touches cache/dev/state.json. Worktrees default to the
profile state dir; ``YHLZ_QQ_DEV_WORKSPACE=main`` opts into the shared main
workspace (recorded as shared_workspace=true, scope commits still enforced).

Executor (ledger 0797): 利贞 跑在 harness 上——本 runner 只负责 job 台账与
工作树，真正的执行由 `tools/qq_dev_worker.py` 转交常驻网关
（`tools/dsh_worker.py`）。后端固定 harness；opencode 已退役。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

from backend import qq_dev_git as githelp  # noqa: E402
from backend import qq_dev_jobs as jobs  # noqa: E402
from backend.qq_bridge_lock import (  # noqa: E402
    make_info, pid_alive, terminate_owned,
)
from backend.qq_bridge_state import path as _bridge_path  # noqa: E402
from backend.qq_bridge_state import state_dir as _state_dir  # noqa: E402

import harness_gateway as gw  # noqa: E402

WORKER = str((_ROOT / "tools" / "qq_dev_worker.py").resolve())
HARNESS_BACKEND = "dsh"
RETIRED_BACKENDS = ("opencode",)
DEFAULT_BACKEND = HARNESS_BACKEND


def _db_path() -> pathlib.Path:
    env = os.getenv("YHLZ_QQ_DEV_DB", "").strip()
    if env:
        return pathlib.Path(env)
    return _bridge_path("dev_jobs.db",
                        _ROOT / "cache" / "dev" / "dev_jobs_lite.db")


def _ws_root() -> str:
    return os.getenv("YHLZ_QQ_DEV_WORKSPACE", "").strip()


def _target() -> str:
    return os.getenv("YHLZ_QQ_DEV_TARGET", "").strip() or str(_ROOT)


def _backend_file() -> pathlib.Path:
    return _state_dir() / "dev_backend.txt"


def _backend() -> str:
    """Harness-only (ledger 0797): 历史文件/环境里的 opencode 一律改走 harness。"""
    return HARNESS_BACKEND


def set_backend(name: str) -> str:
    b = str(name or "").strip().lower()
    if b in RETIRED_BACKENDS:
        return ("[利贞] opencode 后端已退役（ledger 0797）：利贞现在只跑 harness，"
                "无需切换。")
    if b and b != HARNESS_BACKEND:
        return f"用法：#backend（只读）——利贞固定跑 harness，当前：{_backend()}"
    return f"[利贞] 后端固定 harness（{_backend()}），opencode 已退役。"


def backend_status() -> str:
    return "[利贞] 当前后端：harness（dsh）——唯一后端；opencode 已退役（#backend 只读）"


def _store():
    return jobs.connect(_db_path())


def _spawn_worker(job_id: str, action: str) -> None:
    env = dict(os.environ)
    env.setdefault("YHLZ_QQ_PROFILE", os.getenv("YHLZ_QQ_PROFILE", "lite"))
    cmd = [sys.executable, WORKER, "--db", str(_db_path()), "--job", job_id,
           "--action", action]
    subprocess.Popen(cmd, cwd=str(_ROOT), env=env,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True)


def recover() -> int:
    """Bridge restart: dead workers' jobs become interrupted (never re-run)."""
    con = _store()
    count = 0
    for job in jobs.running_jobs(con):
        pid = int(job.get("pid") or 0)
        if pid and pid_alive(pid):
            continue
        files = githelp.changed_files(job.get("workspace") or "")
        jobs.update(con, job["job_id"], state="interrupted",
                    changed_files=files or (job.get("changed_files") or []),
                    error="worker 消失，标记 interrupted，不自动重做")
        jobs.bump_result(con, job["job_id"])
        count += 1
    return count


def start(task: str, *, owner: str, channel: str) -> dict:
    task = str(task or "").strip()
    if not task:
        return {"status": "error", "text": "用法：#dev <任务>"}
    con = _store()
    act = jobs.active(con)
    if act:
        return {"status": "busy", "job_id": act["job_id"],
                "text": (f"[利贞] 已有任务 {act['job_id']} 状态={act['state']}，"
                         "先处理或 #cancel <job_id>")}
    backend = _backend()
    ws_env = _ws_root()
    shared = ws_env.lower() == "main" or \
        os.getenv("YHLZ_QQ_DEV_SHARED", "").strip() in ("1", "true", "yes")
    target = _target()
    job = jobs.create(con, owner_id=str(owner), channel=str(channel),
                      target_project=target, workspace="", shared_workspace=shared,
                      branch="", backend=backend, task=task,
                      base_head="", base_status="")
    job_id = job["job_id"]
    if shared:
        workspace = pathlib.Path(target)
        branch = githelp.branch_of(target)
    else:
        root = pathlib.Path(ws_env) if ws_env else _state_dir() / "dev_workspace"
        workspace = root / job_id
        branch = f"codex/qq-dev-{job_id}"
        ok, out = githelp.worktree_add(target, workspace, branch, "HEAD")
        if not ok:
            jobs.update(con, job_id, state="failed", error=out[:300])
            jobs.bump_result(con, job_id)
            return {"status": "error", "job_id": job_id,
                    "text": f"[利贞] 工作树创建失败：{out[:200]}"}
    base_head = githelp.head_of(workspace)
    base_files = githelp.changed_files(workspace)
    jobs.update(con, job_id, workspace=str(workspace), branch=branch,
                base_head=base_head, base_status="\n".join(base_files))
    try:
        _spawn_worker(job_id, "start")
    except Exception as exc:  # noqa: BLE001
        jobs.update(con, job_id, state="failed",
                    error=f"worker 启动失败: {type(exc).__name__}")
        jobs.bump_result(con, job_id)
        return {"status": "error", "job_id": job_id,
                "text": f"[利贞] worker 启动失败：{type(exc).__name__}"}
    return {
        "status": "accepted", "job_id": job_id,
        "text": (f"[利贞] 已开工：{task[:60]}\njob={job_id} 后端={backend} "
                 f"分支={branch}"
                 + ("（共享工作树，提交仍按范围）" if shared else "")),
    }


def awaiting_job(owner: str, channel: str | None = None) -> dict | None:
    return jobs.awaiting(_store(), owner_id=str(owner), channel=channel)


def answer(text: str, *, owner: str, channel: str, job_id: str | None = None):
    con = _store()
    job = jobs.get(con, job_id) if job_id else jobs.awaiting(
        con, owner_id=str(owner), channel=channel)
    if not job:
        return {"status": "error", "text": "没有等待答复的开发任务"}
    if str(job.get("owner_id")) != str(owner):
        return {"status": "error", "text": "只有该任务主人能答复"}
    if channel and str(job.get("channel")) != "monitor" \
            and str(job.get("channel")) != str(channel) and not job_id:
        return {"status": "error", "text": "请使用 #answer <job_id> <答复> 跨会话回答"}
    if job.get("state") != "awaiting_owner":
        return {"status": "error",
                "text": f"任务 {job['job_id']} 状态={job.get('state')}，不接受答复"}
    jobs.update(con, job["job_id"], answer=str(text), state="running")
    _spawn_worker(job["job_id"], "answer")
    return {"status": "accepted", "job_id": job["job_id"],
            "text": f"[利贞] 收到答复，继续…（job={job['job_id']}）"}


def report_text(job: dict) -> tuple[str, str]:
    """(status, text) for the QQ report of one job version."""
    state = str(job.get("state"))
    if state == "awaiting_owner":
        return "awaiting", (f"job={job['job_id']} 分支={job.get('branch')}\n"
                            f"{job.get('question') or ''}")
    if state == "completed":
        files = job.get("changed_files") or []
        snap = job.get("confirmed_snapshot") or ""
        diff = githelp.diffstat(job.get("workspace") or "",
                                job.get("base_head") or "")
        text = (f"job={job['job_id']} 分支={job.get('branch')}\n"
                f"文件清单({len(files)}): {', '.join(files[:20])}\n"
                f"diff: {diff or '（无差异统计）'}\n"
                f"快照: {snap}")
        return "done", text
    if state == "interrupted":
        return "error", (f"job={job['job_id']} 已中断（worker 消失/被取消），"
                         "改动保留在工作树，不自动重做")
    return "error", f"job={job['job_id']} 失败：{job.get('error') or '未知错误'}"


def status_text() -> str:
    con = _store()
    act = jobs.active(con)
    job = act or jobs.latest(con)
    if not job:
        return "[利贞] 状态=idle 暂无开发任务"
    return (f"[利贞] 状态={job.get('state')} job={job['job_id']} "
            f"任务={str(job.get('task') or '')[:60]}")


def pending_reports() -> list[dict]:
    con = _store()
    updates = jobs.pending_reports(con)
    for job in updates:
        jobs.mark_reported(con, job["job_id"], job["result_version"])
    return updates


def resolve_job(job_id: str | None = None) -> dict | None:
    con = _store()
    return jobs.get(con, job_id) if job_id else (jobs.active(con) or jobs.latest(con))


def confirm_snapshot(job_id: str) -> dict:
    job = resolve_job(job_id)
    if not job:
        return {"status": "error", "text": "没有开发任务"}
    snap = githelp.snapshot(job.get("workspace") or "",
                            job.get("base_head") or "")
    external = githelp.external_changes(job, snap)
    if job.get("state") != "completed":
        return {"status": "error",
                "text": f"job={job['job_id']} 状态={job.get('state')}，不能提交"}
    if snap.get("hash") != (job.get("confirmed_snapshot") or ""):
        return {"status": "error",
                "text": (f"job={job['job_id']} 快照已变化，原确认失效；"
                         "请等新回报后再 #y")}
    if external:
        return {"status": "error",
                "text": f"job={job['job_id']} 发现外部改动，暂停提交：{external[:5]}"}
    if snap.get("head") != (job.get("base_head") or ""):
        return {"status": "error",
                "text": f"job={job['job_id']} 基线 HEAD 已变化，暂停提交"}
    return {"status": "ok", "job": job, "snapshot": snap}


def commit(job_id: str | None = None, message: str = "") -> dict:
    checked = confirm_snapshot(job_id)
    if checked.get("status") != "ok":
        return checked
    job = checked["job"]
    files = [str(p) for p in job.get("changed_files") or []]
    msg = str(message or "").strip() or \
        ("chore(remote-dev): " + str(job.get("task") or "")[:40]).strip()
    result = githelp.add_and_commit(job.get("workspace") or "", files, msg)
    if not result.get("ok"):
        return {"status": "error", "text": result.get("out") or "提交失败"}
    con = _store()
    jobs.update(con, job["job_id"], commit_message=msg,
                commit_hash=result.get("hash") or "")
    return {"status": "ok",
            "text": (f"[利贞] 已提交 {result.get('hash', '')[:12]} "
                     f"（{len(files)} 个文件）")}


def push(job_id: str | None = None) -> dict:
    job = resolve_job(job_id)
    if not job:
        return {"status": "error", "text": "没有开发任务"}
    if not job.get("commit_hash"):
        return {"status": "error",
                "text": f"job={job['job_id']} 还没有提交，先 #y"}
    result = githelp.push(job.get("workspace") or "", job.get("branch") or "")
    if not result.get("ok"):
        return {"status": "error", "text": result.get("out") or "推送失败"}
    con = _store()
    jobs.update(con, job["job_id"], pushed=1)
    return {"status": "ok",
            "text": f"[利贞] 已推送 {job.get('branch')}：{result.get('out', '')[:160]}"}


def detach(job_id: str | None = None) -> dict:
    """退出任务模式：等待答复的任务直接结束（改动保留，不自动重做）；
    执行中的任务必须用 #cancel 明确取消；已完成/已结束的只做退出确认。"""
    job = resolve_job(job_id)
    if not job:
        return {"status": "error", "text": "当前没有开发任务"}
    state = str(job.get("state"))
    if state == "awaiting_owner":
        con = _store()
        jobs.update(con, job["job_id"], state="interrupted",
                    error="主人退出任务模式，改动保留")
        jobs.bump_result(con, job["job_id"])
        return {"status": "ok",
                "text": (f"[利贞] 已退出任务模式（job={job['job_id']}），"
                         "改动保留、不提交、不自动重做")}
    if state in ("accepted", "running"):
        return {"status": "error",
                "text": (f"job={job['job_id']} 正在执行；需要停止请用 "
                         "#cancel，或等它完成")}
    return {"status": "ok",
            "text": (f"[利贞] 已退出任务模式（job={job['job_id']} "
                     f"状态={state}）；如需提交仍可 #y")}


def cancel(job_id: str | None = None) -> dict:
    job = resolve_job(job_id)
    if not job:
        return {"status": "error", "text": "没有开发任务"}
    pid = int(job.get("pid") or 0)
    if pid:
        info = make_info(os.getenv("YHLZ_QQ_PROFILE", "lite"),
                         entry=WORKER, role="dev_worker")
        info["pid"] = pid
        info["create_time"] = float(job.get("pid_create_time") or 0)
        terminate_owned(info, entry=WORKER)
    try:
        # harness 运行在常驻网关里，不在 worker pid 名下：必须让它停手。
        gw.post("/job/cancel", {"job_id": job["job_id"]}, timeout=30.0)
    except Exception:
        pass
    con = _store()
    files = githelp.changed_files(job.get("workspace") or "")
    jobs.update(con, job["job_id"], state="interrupted",
                changed_files=files or (job.get("changed_files") or []),
                error="用户取消", session_id="", pid=0, pid_create_time=0.0)
    jobs.bump_result(con, job["job_id"])
    return {"status": "ok",
            "text": f"[利贞] 已取消 job={job['job_id']}；已改文件清单已保存，不自动重做"}
