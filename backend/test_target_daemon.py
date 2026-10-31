"""Daemon tests (0168/0169): health, /turn, multi-channel isolation,
OpenAI-compatible endpoint, public convergence clause."""

import json
import unittest
import urllib.request

from backend.target_daemon import DaemonRuntime, make_server


class _FakeLLM:
    async def __call__(self, messages, tools):
        last_user = next((m for m in reversed(messages)
                          if m.get("role") == "user"), None)
        system = next((m.get("content", "") for m in messages
                       if m.get("role") == "system"), "")
        public = "公共频道" in system
        return {"content": f"reply:{public}:{str(last_user.get('content'))[:8]}",
                "tool_calls": []}


def _factory(channel: str = "private"):
    import tempfile
    from pathlib import Path

    from backend.target_entry import ConversationSession
    from backend.target_kw_index import KeywordIndex
    from backend.target_memory import TargetMemoryService

    tmp = Path(tempfile.mkdtemp())
    kw = KeywordIndex(tmp / "kw.db")
    mem = TargetMemoryService(db_path=tmp / "mem.db", kw_index=kw)
    return ConversationSession(memory=mem, llm_turn=_FakeLLM(), channel=channel)


class TestDaemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib as _pl
        import tempfile as _tf

        import backend.target_entry as _te
        # isolate session storage: tests must NEVER write into cache/sessions
        # (a previous leak polluted the real console session with fake answers
        #  that the live model then imitated — ledger 0316)
        cls._sess_dir = _te.SESSIONS_DIR
        _te.SESSIONS_DIR = _pl.Path(_tf.mkdtemp()) / "sessions"
        # B4 (ledger 0437): turns now check the schedule — isolate it so tests
        # never mark_run / nudge against the real data/yuanheng_schedule.json
        import backend.target_schedule as _ts

        cls._sched_file, cls._sched_mirror = _ts.SCHED_FILE, _ts.MIRROR_FILE
        _tmpd = _pl.Path(_tf.mkdtemp())
        _ts.SCHED_FILE = _tmpd / "sched.json"
        _ts.MIRROR_FILE = _tmpd / "plan.md"
        from backend import notify_guard as _ng

        cls._ng_state = _ng.STATE_FILE
        _ng.STATE_FILE = _tmpd / "notify_guard.json"
        cls.rt = DaemonRuntime(session_factory=_factory)
        cls.srv = make_server(0, "127.0.0.1", cls.rt)
        import threading

        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        import backend.target_entry as _te
        import backend.target_schedule as _ts
        from backend import notify_guard as _ng

        _te.SESSIONS_DIR = cls._sess_dir
        _ts.SCHED_FILE, _ts.MIRROR_FILE = cls._sched_file, cls._sched_mirror
        _ng.STATE_FILE = cls._ng_state

    def _post(self, path, obj):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(obj).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def test_health(self):
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/health", timeout=10) as r:
            h = json.loads(r.read())
        self.assertEqual(h["status"], "ok")

    def test_health_never_touches_memory_db(self):
        """F3 regression (ledger 0436): even a broken/slow session.status()
        (busy SQLite) must not fail /health — that bug made the watchdog
        believe a live daemon was down and respawn it in a loop."""
        s = self.rt._session("console")
        orig = s.status
        s.status = lambda: (_ for _ in ()).throw(RuntimeError("db busy"))
        try:
            h = self.rt.health()
        finally:
            s.status = orig
        self.assertEqual(h["status"], "ok")

    def test_sing_status_route(self):
        """ledger 0457: daemon exposes /sing/status for the workbench module."""
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/sing/status", timeout=10) as r:
            st = json.loads(r.read())
        self.assertTrue(st["ok"])
        self.assertIn(st["status"], ("idle", "running", "done", "error"))

    def test_official_ui_status_route(self):
        """0792: daemon exposes /official-ui/status for the launch entrance."""
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/official-ui/status",
                timeout=10) as r:
            st = json.loads(r.read())
        self.assertTrue(st["ok"])
        self.assertIn(st["status"],
                      ("idle", "starting", "running", "error"))
        self.assertIn("url", st)

    def test_autonomy_route_exposes_decisions(self):
        """0496: 自主 tick / 通知拦截的决策可从 daemon 审计（只读）。"""
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/autonomy", timeout=10) as r:
            d = json.loads(r.read())
        self.assertIn("items", d)
        self.assertIn("decisions", d)
        self.assertIsInstance(d["items"], list)

    def test_tts_endpoint_returns_wav(self):
        """A4b (ledger 0454): /tts synthesizes via _synth and returns WAV."""
        import backend.console_server as cs

        old = cs._synth
        cs._synth = lambda m, t, s="Vivian": ([0.0] * 2400, 24000)
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/tts",
                data=json.dumps({"text": "你好", "model": "clone"}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                ctype = r.headers.get("Content-Type")
        finally:
            cs._synth = old
        self.assertEqual(ctype, "audio/wav")
        self.assertEqual(data[:4], b"RIFF")
        self.assertGreater(len(data), 44)

    def test_songs_route(self):
        """ledger 0460: /songs lists the finished-song library."""
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/songs", timeout=10) as r:
            out = json.loads(r.read())
        self.assertTrue(out["ok"])
        self.assertIsInstance(out["items"], list)

    def test_turn_blocked_during_sing(self):
        """ledger 0459: chat turns are refused while the SVC window runs."""
        from backend import gpu_lock

        self.assertTrue(gpu_lock.acquire_sing())
        self.assertTrue(gpu_lock.enter_window())
        try:
            out = self.rt.turn("你在吗")
        finally:
            gpu_lock.release_sing()
        self.assertTrue(out.get("busy"))
        self.assertIn("唱歌", out["answer"])

    def test_talk_route_blocked_during_sing(self):
        from backend import gpu_lock

        self.assertTrue(gpu_lock.acquire_sing())
        self.assertTrue(gpu_lock.enter_window())
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/talk",
                data=json.dumps({"text": "hi"}).encode(),
                headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
        finally:
            gpu_lock.release_sing()

    def test_turn_triggers_idle_schedule_check(self):
        """B4 (ledger 0437): a finished turn immediately checks due plans."""
        calls = []
        orig = self.rt._run_due_plans
        self.rt._run_due_plans = lambda: calls.append(1)
        try:
            self._post("/turn", {"text": "B4触发", "source": "console", "channel": "console"})
        finally:
            self.rt._run_due_plans = orig
        self.assertGreaterEqual(len(calls), 1)

    def test_run_due_plans_is_non_reentrant(self):
        """B4: nested call (plan nudge -> turn -> check) must not deadlock."""
        sched = self.rt._run_due_plans
        got = self.rt._sched_lock.acquire(blocking=False)
        self.assertTrue(got)
        try:
            sched()  # must return immediately while the lock is held
        finally:
            self.rt._sched_lock.release()

    def test_turn_explicit_console_private(self):
        out = self._post("/turn", {"text": "你好", "source": "console", "channel": "console"})
        self.assertIn("reply:False:", out["answer"])

    def test_channel_isolation_and_public(self):
        a1 = self._post("/turn", {"text": "群A问", "channel": "qq_g123456", "source": "qq_bridge"})
        self.assertIn("reply:True:", a1["answer"])  # public convergence applied
        b1 = self._post("/turn", {"text": "群B问", "channel": "qq_g654321", "source": "qq_bridge"})
        # different channel context; histories independent
        self.assertNotIn("群A", b1["answer"])

    def test_openai_endpoint(self):
        out = self._post("/v1/chat/completions", {
            "model": "yhlz",
            "user": "grp-c",
            "messages": [{"role": "user", "content": "几点啦"}],
        })
        self.assertEqual(out["object"], "chat.completion")
        self.assertIn("reply:", out["choices"][0]["message"]["content"])


class TestAutonomyTickLog(unittest.TestCase):
    """0496: 自主 tick 决策日志（时间/驱动值/选题/是否推送/原因），有界、倒序可读。"""

    def setUp(self):
        import pathlib as _pl
        import tempfile as _tf

        import backend.target_daemon as _td

        self.tmp = _pl.Path(_tf.mkdtemp())
        self._old = _td.AUTONOMY_LOG_FILE
        _td.AUTONOMY_LOG_FILE = self.tmp / "autonomy_ticks.json"
        self.td = _td

    def tearDown(self):
        self.td.AUTONOMY_LOG_FILE = self._old

    def test_roundtrip_newest_first(self):
        self.td.log_autonomy_tick({"time": "t1", "answer_head": "A",
                                   "pushed": False, "reason": "too_short"})
        self.td.log_autonomy_tick({"time": "t2", "answer_head": "B",
                                   "pushed": True, "reason": "ok"})
        rows = self.td.read_autonomy_ticks(10)
        self.assertEqual([r["time"] for r in rows], ["t2", "t1"])
        self.assertTrue(rows[0]["pushed"])
        self.assertEqual(rows[1]["reason"], "too_short")

    def test_bounded(self):
        for i in range(self.td.AUTONOMY_LOG_KEEP + 5):
            self.td.log_autonomy_tick({"time": f"t{i}", "pushed": False,
                                       "reason": "too_short"})
        self.assertEqual(len(self.td.read_autonomy_ticks(999)),
                         self.td.AUTONOMY_LOG_KEEP)

    def test_missing_file_reads_empty(self):
        self.assertEqual(self.td.read_autonomy_ticks(), [])


if __name__ == "__main__":
    unittest.main()
