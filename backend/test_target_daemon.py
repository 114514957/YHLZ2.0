"""Daemon tests (0168): health + /turn with a fake LLM (no network)."""

import json
import unittest
import urllib.request

from backend.target_daemon import DaemonRuntime, make_server


class _FakeLLM:
    async def __call__(self, messages, tools):
        return {"content": "daemon 测试回复", "tool_calls": []}


def _factory():
    from backend.target_entry import ConversationSession
    from backend.target_memory import TargetMemoryService
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    from backend.target_kw_index import KeywordIndex

    kw = KeywordIndex(tmp / "kw.db")
    mem = TargetMemoryService(db_path=tmp / "mem.db", kw_index=kw)
    return ConversationSession(memory=mem, llm_turn=_FakeLLM())


class TestDaemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rt = DaemonRuntime(session_factory=_factory)
        cls.srv = make_server(0, "127.0.0.1", cls.rt)
        import threading

        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}",
                                    timeout=10) as r:
            return json.loads(r.read())

    def _post(self, text):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/turn",
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def test_health(self):
        h = self._get("/health")
        self.assertEqual(h["status"], "ok")
        self.assertEqual(h["provider"], "dual-rail")

    def test_turn(self):
        out = self._post("你好")
        self.assertEqual(out["answer"], "daemon 测试回复")
        self.assertIn("iterations", out)


if __name__ == "__main__":
    unittest.main()
