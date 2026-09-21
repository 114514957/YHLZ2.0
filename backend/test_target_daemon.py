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

    def test_turn_triggers_idle_schedule_check(self):
        """B4 (ledger 0437): a finished turn immediately checks due plans."""
        calls = []
        orig = self.rt._run_due_plans
        self.rt._run_due_plans = lambda: calls.append(1)
        try:
            self._post("/turn", {"text": "B4触发"})
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

    def test_turn_default_private(self):
        out = self._post("/turn", {"text": "你好"})
        self.assertIn("reply:False:", out["answer"])

    def test_channel_isolation_and_public(self):
        a1 = self._post("/turn", {"text": "群A问", "channel": "grp-a"})
        self.assertIn("reply:True:", a1["answer"])  # public convergence applied
        b1 = self._post("/turn", {"text": "群B问", "channel": "grp-b"})
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


if __name__ == "__main__":
    unittest.main()
