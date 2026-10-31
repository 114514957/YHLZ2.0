"""P3 evidence matrix: job lifecycle, owner gate, git scope, recovery (offline).

Uses a temporary git repo, bare remote, fake agent and the real worker/runner
processes. No harness gateway, no QQ, no YHLZ services (the fake agent rides
the stub seam ``YHLZ_QQ_DEV_AGENT_CMD``).

Usage:
    .venv\\Scripts\\python.exe tools\\qq_bridge_p3_matrix.py --out artifacts\\qq_lite\\p3_<id>
"""
from __future__ import annotations

import argparse
import asyncio
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

FAKE_AGENT = str((_ROOT / "tools" / "qq_dev_fake_agent.py").resolve())


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def make_fixture(base: pathlib.Path) -> dict:
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "p3@test.local")
    _git(repo, "config", "user.name", "P3 Test")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    bare = base / "bare.git"
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
    _git(repo, "remote", "add", "origin", str(bare))
    state = base / "state"
    ws_root = base / "ws"
    state.mkdir(parents=True, exist_ok=True)
    ws_root.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "YHLZ_QQ_PROFILE": "lite",
        "YHLZ_QQ_STATE_DIR": str(state),
        "YHLZ_QQ_DEV_DB": str(state / "dev_jobs.db"),
        "YHLZ_QQ_DEV_WORKSPACE": str(ws_root),
        "YHLZ_QQ_DEV_TARGET": str(repo),
        "YHLZ_QQ_DEV_AGENT_CMD": json.dumps([sys.executable, FAKE_AGENT]),
        "YHLZ_QQ_DEV_TIMEOUT": "60",
        "FAKE_AGENT_MODE": "auto",
        "FAKE_AGENT_FILES": '["a.txt","b.txt"]',
    })
    os.environ.pop("FAKE_AGENT_STDERR_MB", None)
    return {"repo": repo, "bare": bare, "state": state, "ws_root": ws_root,
            "db": state / "dev_jobs.db"}


def _runner():
    import qq_dev_runner as mod

    return mod


def wait_state(con, job_id, states, timeout=40.0):
    end = time.time() + timeout
    while time.time() < end:
        job = jobs.get(con, job_id)
        if job and job["state"] in states:
            return job
        time.sleep(0.25)
    return jobs.get(con, job_id)


def case_job_lifecycle(base: pathlib.Path) -> dict:
    fx = make_fixture(base)
    mod = _runner()
    con = jobs.connect(fx["db"])
    r = mod.start("实现功能 X", owner="2258374446", channel="qq_p2258374446")
    job_id = r.get("job_id", "")
    job = wait_state(con, job_id, ("awaiting_owner", "completed", "failed"))
    ask_ok = bool(job and job["state"] == "awaiting_owner"
                  and "[QUESTION]" in (job.get("question") or ""))
    mod.answer("按方案 A 执行", owner="2258374446", channel="qq_p2258374446")
    job = wait_state(con, job_id, ("completed", "failed"))
    done_ok = bool(job and job["state"] == "completed"
                   and "[DONE]" in (job.get("report") or "")
                   and set(job.get("changed_files") or []) >= {"a.txt", "b.txt"}
                   and job.get("confirmed_snapshot"))
    updates = mod.pending_reports()
    versioned = any(u["job_id"] == job_id and u["result_version"] >= 2
                    for u in updates)
    again = mod.pending_reports()
    no_replay = not any(u["job_id"] == job_id for u in again)
    return {"pass": all((ask_ok, done_ok, versioned, no_replay)),
            "job_id": job_id, "ask_ok": ask_ok, "done_ok": done_ok,
            "result_versioned_once": versioned, "no_replay": no_replay,
            "changed_files": job.get("changed_files") if job else None,
            "session_id": job.get("session_id") if job else ""}


def case_owner_matrix(base: pathlib.Path) -> dict:
    fx = make_fixture(base)
    os.environ["FAKE_AGENT_MODE"] = "ask"
    import qq_bot as qq

    class Stub:
        def __init__(self):
            self.starts = []
            self.answers = []

        def start(self, task, *, owner, channel):
            self.starts.append((task, owner, channel))
            return {"status": "accepted", "text": "[利贞] stub 已开工"}

        def awaiting_job(self, owner, channel=None):
            return self.awaiting.pop(0) if self.awaiting else None

        awaiting = []

        def answer(self, text, *, owner, channel, job_id=None):
            self.answers.append((job_id, text))
            return {"status": "accepted", "text": "[利贞] stub 答复"}

        def status_text(self):
            return "[利贞] 状态=idle（stub）"

    stub = Stub()
    qq._lite_dev = stub
    old_turn = qq._daemon_turn
    qq._daemon_turn = lambda *a, **k: "ok"
    bridge = qq.QQBridge("unused", "3655185302", pathlib.Path("unused"),
                         masters={"2258374446"})
    bridge.log = lambda msg: None
    bridge._say = _AsyncMock()
    bridge._daemon_ok = lambda: True   # offline: fake daemon for chat path

    def event(mid, sender, text, group=None):
        return {"post_type": "message",
                "message_type": "group" if group else "private",
                "user_id": sender, "group_id": group, "message_id": mid,
                "message": [{"type": "text", "data": {"text": text}}]}

    async def scenario():
        await bridge.handle(None, event(1, "10086", "#dev 偷偷改代码"))
        await bridge.handle(None, event(2, "10086", "#dev 群里也试", group="999"))
        non_owner_ok = len(stub.starts) == 0
        await bridge.handle(None, event(3, "2258374446", "#dev 正常任务"))
        owner_ok = len(stub.starts) == 1
        stub.awaiting = [{"job_id": "jobX", "state": "awaiting_owner"}]
        await bridge.handle(None, event(4, "2258374446", "我的答复"))
        reply_ok = stub.answers == [("jobX", "我的答复")]
        return non_owner_ok, owner_ok, reply_ok

    try:
        non_owner_ok, owner_ok, reply_ok = asyncio.run(scenario())
    finally:
        qq._daemon_turn = old_turn
    return {"pass": all((non_owner_ok, owner_ok, reply_ok)),
            "non_owner_started": not non_owner_ok,
            "owner_started": owner_ok, "awaiting_answer_routed": reply_ok,
            "starts": stub.starts}


def _AsyncMock():
    from unittest.mock import AsyncMock

    return AsyncMock()


def case_git_scope(base: pathlib.Path) -> dict:
    fx = make_fixture(base)
    os.environ["FAKE_AGENT_MODE"] = "done"
    mod = _runner()
    con = jobs.connect(fx["db"])
    r = mod.start("写两个文件", owner="2258374446", channel="qq_p2258374446")
    job_id = r["job_id"]
    job = wait_state(con, job_id, ("completed", "failed"))
    files_ok = bool(job and set(job.get("changed_files") or []) >= {"a.txt",
                                                                    "b.txt"})
    ws = pathlib.Path(job["workspace"])
    (ws / "external.txt").write_text("other agent\n", encoding="utf-8")
    refused = mod.commit(job_id)
    external_blocked = ("外部改动" in (refused.get("text") or "")
                        or refused.get("status") == "error")
    (ws / "external.txt").unlink(missing_ok=True)
    committed = mod.commit(job_id)
    commit_ok = committed.get("status") == "ok"
    show = _git(ws, "show", "--name-only", "--pretty=format:", "HEAD")
    committed_files = sorted(set(
        line.strip() for line in (show.stdout or "").splitlines()
        if line.strip()))
    scope_ok = committed_files == ["a.txt", "b.txt"]
    pushed = mod.push(job_id)
    bare_has_branch = False
    if job:
        rc = _git(fx["bare"], "rev-parse", "--verify",
                  f"refs/heads/{job.get('branch')}")
        bare_has_branch = rc.returncode == 0
    os.environ["FAKE_AGENT_MODE"] = "auto"
    return {"pass": all((files_ok, external_blocked, commit_ok, scope_ok,
                         pushed.get("status") == "ok", bare_has_branch)),
            "job_id": job_id, "files_ok": files_ok,
            "external_blocked": external_blocked, "commit_ok": commit_ok,
            "committed_files": committed_files, "push_ok":
                pushed.get("status") == "ok", "bare_has_branch": bare_has_branch}


def case_recovery_and_cancel(base: pathlib.Path) -> dict:
    fx = make_fixture(base)
    os.environ["FAKE_AGENT_MODE"] = "sleep"
    os.environ["YHLZ_QQ_DEV_TIMEOUT"] = "120"
    mod = _runner()
    con = jobs.connect(fx["db"])
    r = mod.start("长任务", owner="2258374446", channel="qq_p2258374446")
    job_id = r["job_id"]
    job = wait_state(con, job_id, ("running",))
    running = bool(job and job["state"] == "running" and int(job.get("pid") or 0))
    alive_recover = mod.recover()
    still_running = jobs.get(con, job_id)["state"] == "running"
    cancelled = mod.cancel(job_id)
    job = jobs.get(con, job_id)
    cancel_ok = job["state"] == "interrupted"
    dead = jobs.create(con, owner_id="2258374446", channel="qq_p1",
                       target_project=str(fx["repo"]), workspace=str(fx["repo"]),
                       shared_workspace=True, branch="main", backend="dsh",
                       task="ghost", base_head="", base_status="")
    jobs.update(con, dead["job_id"], state="running", pid=999999,
                pid_create_time=1.0)
    ghost_recovered = mod.recover()
    ghost_state = jobs.get(con, dead["job_id"])["state"]
    os.environ["FAKE_AGENT_MODE"] = "auto"
    os.environ["YHLZ_QQ_DEV_TIMEOUT"] = "60"
    return {"pass": all((running, alive_recover == 0, still_running,
                         cancel_ok, ghost_recovered >= 1,
                         ghost_state == "interrupted")),
            "job_id": job_id, "worker_running": running,
            "recover_kept_alive_job": alive_recover == 0,
            "cancel_interrupted": cancel_ok,
            "ghost_recovered": ghost_recovered,
            "ghost_state": ghost_state}


def case_stderr_drain(base: pathlib.Path) -> dict:
    fx = make_fixture(base)
    os.environ["FAKE_AGENT_MODE"] = "done"
    os.environ["FAKE_AGENT_STDERR_MB"] = "2"
    mod = _runner()
    con = jobs.connect(fx["db"])
    r = mod.start("stderr 排空", owner="2258374446", channel="qq_p2258374446")
    job_id = r["job_id"]
    job = wait_state(con, job_id, ("completed", "failed"), timeout=60)
    log_ok = False
    if job:
        try:
            log_ok = "fake-stderr-tail" in pathlib.Path(job["log_path"]).read_text(
                encoding="utf-8", errors="replace")
        except Exception:
            log_ok = False
    os.environ.pop("FAKE_AGENT_STDERR_MB", None)
    os.environ["FAKE_AGENT_MODE"] = "auto"
    return {"pass": bool(job and job["state"] == "completed" and log_ok),
            "state": job["state"] if job else "",
            "stderr_drained": log_ok}


def case_timeout_kill(base: pathlib.Path) -> dict:
    fx = make_fixture(base)
    os.environ["FAKE_AGENT_MODE"] = "sleep"
    os.environ["YHLZ_QQ_DEV_TIMEOUT"] = "2"
    mod = _runner()
    con = jobs.connect(fx["db"])
    r = mod.start("超时任务", owner="2258374446", channel="qq_p2258374446")
    job_id = r["job_id"]
    job = wait_state(con, job_id, ("failed", "completed"), timeout=40)
    ok = bool(job and job["state"] == "failed"
              and "超时" in (job.get("error") or ""))
    os.environ["YHLZ_QQ_DEV_TIMEOUT"] = "60"
    os.environ["FAKE_AGENT_MODE"] = "auto"
    return {"pass": ok, "state": job["state"] if job else "",
            "error": job.get("error") if job else ""}


def main() -> int:
    ap = argparse.ArgumentParser()
    run_id = time.strftime("p3_%Y%m%dT%H%M%S")
    ap.add_argument("--out", default=str(_ROOT / "artifacts" / "qq_lite" / run_id))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    for name, fn in (("job_lifecycle", case_job_lifecycle),
                     ("owner_matrix", case_owner_matrix),
                     ("git_scope", case_git_scope),
                     ("recovery_and_cancel", case_recovery_and_cancel),
                     ("stderr_drain", case_stderr_drain),
                     ("timeout_kill", case_timeout_kill)):
        try:
            cases[name] = fn(out / name)
        except Exception as exc:  # noqa: BLE001
            import traceback

            cases[name] = {"pass": False,
                           "error": f"{type(exc).__name__}: {exc}",
                           "trace": traceback.format_exc()[-800:]}
    report = {"run_id": out.name,
              "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "profile": "lite", "pass": all(c.get("pass") for c in cases.values()),
              "cases": cases}
    (out / "owner_matrix.json").write_text(
        json.dumps({"run_id": out.name, "case": cases.get("owner_matrix")},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "git_scope.json").write_text(
        json.dumps({"run_id": out.name, "case": cases.get("git_scope")},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "job_recovery.json").write_text(
        json.dumps({"run_id": out.name,
                    "case": cases.get("recovery_and_cancel")},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "p3_matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[p3] out={out} pass={report['pass']}")
    for name, case in cases.items():
        print(f"[p3] {name} = {case.get('pass')}")
        if not case.get("pass") and case.get("error"):
            print(f"[p3]   error: {case['error']}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
