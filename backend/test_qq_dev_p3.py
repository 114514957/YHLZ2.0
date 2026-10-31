"""P3 offline tests: job store, git scope, owner gate, memory gate, recovery.

No harness/opencode process, no QQ, no network. Run:
    .venv\\Scripts\\python.exe -m unittest backend.test_qq_dev_p3
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from unittest.mock import AsyncMock

from backend import qq_dev_git as githelp
from backend import qq_dev_jobs as jobs

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools"))


def _git(repo, *args):
    return subprocess.run(["git", "-c", "core.quotepath=false", "-C",
                           str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def make_repo(base: pathlib.Path) -> pathlib.Path:
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "p3@test.local")
    _git(repo, "config", "user.name", "P3 Test")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    return repo


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.con = jobs.connect(self.tmp / "dev_jobs.db")

    def _create(self, **kw):
        args = dict(owner_id="2258374446", channel="qq_p2258374446",
                    target_project="repo", workspace="ws",
                    shared_workspace=False, branch="codex/x", backend="dsh",
                    task="t", base_head="h", base_status="")
        args.update(kw)
        return jobs.create(self.con, **args)

    def test_state_flow_and_active(self):
        job = self._create()
        self.assertEqual(job["state"], "accepted")
        self.assertEqual(jobs.active(self.con)["job_id"], job["job_id"])
        jobs.update(self.con, job["job_id"], state="awaiting_owner",
                    question="q?")
        self.assertEqual(jobs.awaiting(self.con, owner_id="2258374446",
                                       channel="qq_p2258374446")["job_id"],
                         job["job_id"])
        jobs.update(self.con, job["job_id"], state="completed",
                    report="done")
        self.assertIsNone(jobs.active(self.con))

    def test_pending_reports_version_once(self):
        job = self._create()
        jobs.update(self.con, job["job_id"], state="completed", report="r")
        jobs.bump_result(self.con, job["job_id"])
        first = jobs.pending_reports(self.con)
        self.assertEqual([j["job_id"] for j in first], [job["job_id"]])
        jobs.mark_reported(self.con, job["job_id"], first[0]["result_version"])
        self.assertEqual(jobs.pending_reports(self.con), [])


class GitScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp)

    def test_changed_files_and_scope_commit(self):
        (self.repo / "base.txt").write_text("changed\n", encoding="utf-8")
        (self.repo / "extra.txt").write_text("extra\n", encoding="utf-8")
        files = githelp.changed_files(self.repo)
        self.assertEqual(files, ["base.txt", "extra.txt"])
        result = githelp.add_and_commit(self.repo, ["base.txt"], "only base")
        self.assertTrue(result["ok"], result)
        show = _git(self.repo, "show", "--name-only", "--pretty=format:", "HEAD")
        names = [ln.strip() for ln in (show.stdout or "").splitlines()
                 if ln.strip()]
        self.assertEqual(names, ["base.txt"])
        self.assertEqual(githelp.changed_files(self.repo), ["extra.txt"])

    def test_cjk_filename_scope(self):
        name = "真机冒烟_20261006.md"
        target = self.repo / name
        target.write_text("x\n", encoding="utf-8")
        files = githelp.changed_files(self.repo)
        self.assertIn(name, files)
        result = githelp.add_and_commit(self.repo, [name], "cjk")
        self.assertTrue(result["ok"], result)
        show = _git(self.repo, "show", "--name-only", "--pretty=format:",
                    "HEAD")
        names = [ln.strip() for ln in (show.stdout or "").splitlines()
                 if ln.strip()]
        self.assertEqual(names, [name])

    def test_external_change_detection(self):
        job = {"workspace": str(self.repo), "base_head":
               githelp.head_of(self.repo), "changed_files": ["base.txt"]}
        (self.repo / "base.txt").write_text("changed\n", encoding="utf-8")
        self.assertEqual(githelp.external_changes(job), [])
        (self.repo / "other.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(githelp.external_changes(job), ["other.txt"])

    def test_commit_fails_without_files(self):
        result = githelp.add_and_commit(self.repo, [], "nothing")
        self.assertFalse(result["ok"])

    def test_worktree_and_push(self):
        bare = self.tmp / "bare.git"
        subprocess.run(["git", "init", "--bare", str(bare)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
        _git(self.repo, "remote", "add", "origin", str(bare))
        ws = self.tmp / "ws" / "job1"
        ok, out = githelp.worktree_add(str(self.repo), ws,
                                       "codex/qq-dev-job1", "HEAD")
        self.assertTrue(ok, out)
        (ws / "new.txt").write_text("new\n", encoding="utf-8")
        result = githelp.add_and_commit(ws, ["new.txt"], "add new")
        self.assertTrue(result["ok"], result)
        pushed = githelp.push(ws, "codex/qq-dev-job1")
        self.assertTrue(pushed["ok"], pushed)
        rc = _git(bare, "rev-parse", "--verify",
                  "refs/heads/codex/qq-dev-job1")
        self.assertEqual(rc.returncode, 0)
        self.assertFalse(githelp.push(ws, "")["ok"])


class OwnerGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import qq_bot as qq

        self.qq = qq
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.stub = mock.Mock()
        self.stub.start.return_value = {"status": "accepted", "text": "ok"}
        self.stub.awaiting_job.return_value = None
        self.stub.answer.return_value = {"status": "accepted", "text": "ok"}
        self._env = mock.patch.dict(os.environ, {
            "YHLZ_QQ_PROFILE": "lite",
            "YHLZ_QQ_STATE_DIR": str(self.tmp),
            "YHLZ_QQ_DEV_DB": str(self.tmp / "dev_jobs.db"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        self._lite = mock.patch.object(qq, "_lite_dev", self.stub)
        self._lite.start()
        self.addCleanup(self._lite.stop)
        self._turn = mock.patch.object(qq, "_daemon_turn",
                                       return_value="chat-ok")
        self._turn.start()
        self.addCleanup(self._turn.stop)
        self.bridge = qq.QQBridge("unused", "3655185302",
                                  pathlib.Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = mock.Mock()
        self.bridge._say = AsyncMock()

    def event(self, mid, sender, text, group=None):
        return {"post_type": "message",
                "message_type": "group" if group else "private",
                "user_id": sender, "group_id": group, "message_id": mid,
                "message": [{"type": "text", "data": {"text": text}}]}

    async def test_non_owner_dev_is_chat_only(self):
        await self.bridge.handle(None, self.event(1, "10086", "#dev 改代码"))
        await self.bridge.handle(None, self.event(2, "10086", "#dev x",
                                                  group="999"))
        self.stub.start.assert_not_called()
        self.stub.answer.assert_not_called()

    async def test_owner_dev_starts_and_answer_routes(self):
        await self.bridge.handle(None,
                                 self.event(3, "2258374446", "#dev 正常任务"))
        self.stub.start.assert_called_once()
        kwargs = self.stub.start.call_args.kwargs
        self.assertEqual(kwargs["owner"], "2258374446")
        self.assertEqual(kwargs["channel"], "qq_p2258374446")
        self.stub.awaiting_job.return_value = {"job_id": "jobX",
                                               "state": "awaiting_owner"}
        await self.bridge.handle(None, self.event(4, "2258374446", "答复内容"))
        self.stub.answer.assert_called_once()
        self.assertEqual(self.stub.answer.call_args.kwargs["job_id"], "jobX")

    async def test_owner_plain_chat_without_awaiting_goes_to_chat(self):
        await self.bridge.handle(None, self.event(5, "2258374446", "随便聊聊"))
        self.stub.answer.assert_not_called()


class MemoryGateTests(unittest.IsolatedAsyncioTestCase):
    async def _report_and_check(self, profile: str):
        import qq_bot as qq

        bridge = qq.QQBridge("unused", "3655185302", pathlib.Path("unused"),
                             masters={"2258374446"})
        bridge._say = AsyncMock()
        with mock.patch.object(qq, "_bridge_profile", return_value=profile), \
                mock.patch("backend.target_scheduler_tools.memory_save") as save, \
                mock.patch("backend.target_memory.TargetMemoryService") as svc:
            svc.return_value = object()
            await bridge._dev_report(None, {}, "done", "报告", hint=True)
            return save

    async def test_lite_does_not_write_main_memory(self):
        save = await self._report_and_check("lite")
        save.assert_not_called()

    async def test_full_still_writes_memory(self):
        save = await self._report_and_check("full")
        save.assert_called_once()


class RecoveryTests(unittest.TestCase):
    def test_dead_worker_marked_interrupted(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        db = tmp / "dev_jobs.db"
        con = jobs.connect(db)
        job = jobs.create(con, owner_id="2258374446", channel="qq_p1",
                          target_project="repo", workspace=str(tmp),
                          shared_workspace=True, branch="main",
                          backend="dsh", task="t", base_head="",
                          base_status="")
        jobs.update(con, job["job_id"], state="running", pid=999999,
                    pid_create_time=1.0)
        import qq_dev_runner as runner

        with mock.patch.dict(os.environ, {"YHLZ_QQ_DEV_DB": str(db)}):
            self.assertEqual(runner.recover(), 1)
        self.assertEqual(jobs.get(con, job["job_id"])["state"], "interrupted")


class ServiceDevEnvTests(unittest.TestCase):
    def test_dev_env_defaults(self):
        import qq_bridge_service as svc

        tmp = pathlib.Path(tempfile.mkdtemp())
        keys = ("YHLZ_QQ_DEV_DB", "YHLZ_QQ_DEV_WORKSPACE",
                "YHLZ_QQ_DEV_TARGET", "YHLZ_QQ_DEV_BACKEND",
                "YHLZ_QQ_DEV_TIMEOUT")
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in keys:
                os.environ.pop(key, None)
            svc._apply_dev_env({"dev_backend": "dsh",
                                "dev_workspace": ""}, tmp)
            self.assertEqual(os.environ["YHLZ_QQ_DEV_DB"],
                             str(tmp / "dev_jobs.db"))
            self.assertEqual(os.environ["YHLZ_QQ_DEV_WORKSPACE"],
                             str(tmp / "dev_workspace"))
            self.assertEqual(os.environ["YHLZ_QQ_DEV_BACKEND"], "dsh")


class DetachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.db = self.tmp / "dev_jobs.db"
        con = jobs.connect(self.db)
        self.job = jobs.create(con, owner_id="2258374446",
                               channel="qq_p2258374446",
                               target_project="repo", workspace=str(self.tmp),
                               shared_workspace=True, branch="main",
                               backend="dsh", task="t", base_head="",
                               base_status="")
        self.env = mock.patch.dict(os.environ, {"YHLZ_QQ_DEV_DB": str(self.db)})
        self.env.start()
        self.addCleanup(self.env.stop)
        import qq_dev_runner as runner

        self.runner = runner

    def test_detach_awaiting_becomes_interrupted(self):
        con = jobs.connect(self.db)
        jobs.update(con, self.job["job_id"], state="awaiting_owner",
                    question="q?")
        result = self.runner.detach(self.job["job_id"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(jobs.get(con, self.job["job_id"])["state"],
                         "interrupted")

    def test_detach_running_is_refused(self):
        con = jobs.connect(self.db)
        jobs.update(con, self.job["job_id"], state="running", pid=999999)
        result = self.runner.detach(self.job["job_id"])
        self.assertEqual(result["status"], "error")
        self.assertIn("#cancel", result["text"])
        self.assertEqual(jobs.get(con, self.job["job_id"])["state"], "running")

    def test_detach_completed_is_ack(self):
        con = jobs.connect(self.db)
        jobs.update(con, self.job["job_id"], state="completed", report="done")
        result = self.runner.detach(self.job["job_id"])
        self.assertEqual(result["status"], "ok")


class CommandRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import qq_bot as qq

        self.qq = qq
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {
            "YHLZ_QQ_PROFILE": "lite",
            "YHLZ_QQ_STATE_DIR": str(self.tmp),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.stub = mock.Mock()
        self.stub.start.return_value = {"status": "accepted", "text": "开工"}
        self.stub.detach.return_value = {"status": "ok", "text": "已退出"}
        self._lite = mock.patch.object(qq, "_lite_dev", self.stub)
        self._lite.start()
        self.addCleanup(self._lite.stop)
        self.bridge = qq.QQBridge("unused", "3655185302",
                                  pathlib.Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = mock.Mock()
        self.bridge._say = AsyncMock()

    def event(self, mid, text):
        return {"post_type": "message", "message_type": "private",
                "user_id": "2258374446", "message_id": mid,
                "message": [{"type": "text", "data": {"text": text}}]}

    async def test_task_dispatch_alias(self):
        await self.bridge.handle(None, self.event(1, "#任务派发 写个测试"))
        self.stub.start.assert_called_once()
        self.assertEqual(self.stub.start.call_args.args[0], "写个测试")

    async def test_exit_task_mode(self):
        await self.bridge.handle(None, self.event(2, "#退出任务"))
        self.stub.detach.assert_called_once()

    async def test_task_bar_help(self):
        await self.bridge.handle(None, self.event(3, "#任务栏"))
        texts = [str(c.args[2]) for c in self.bridge._say.await_args_list]
        self.assertTrue(any("#任务派发" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
