"""Tests for community summaries (P5a-2)."""
import tempfile
import unittest
from pathlib import Path

from backend import communities as cm
from backend import entity_graph as eg


class CommunityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._db = eg.DB_PATH
        self._cf = cm.COMM_FILE
        eg.DB_PATH = self.tmp / "eg.db"
        cm.COMM_FILE = self.tmp / "comm.json"

    def tearDown(self):
        eg.DB_PATH = self._db
        cm.COMM_FILE = self._cf

    def test_build_and_context(self):
        eg.upsert([
            {"subject": "元亨", "object": "老爹", "relation": "关系"},
            {"subject": "元亨", "object": "猫", "relation": "喜欢"},
            {"subject": "WebUI", "object": "daemon", "relation": "服务"},
            {"subject": "daemon", "object": "记忆", "relation": "承载"},
        ])

        async def fake(messages, tools):
            return {"content": "关于元亨与老爹、以及服务与记忆的主题"}

        data = cm.build(force=True, llm=fake)
        self.assertTrue(data["communities"])
        out = cm.context_for("帮我总结一下我最近的状态")
        self.assertIn("仅供理解", out)

    def test_context_empty_without_build(self):
        self.assertEqual(cm.context_for("总结一下"), "")


if __name__ == "__main__":
    unittest.main()
