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
        cls.rt = DaemonRuntime(session_factory=_factory)
        cls.srv = make_server(0, "127.0.0.1", cls.rt)
        import threading

        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

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
