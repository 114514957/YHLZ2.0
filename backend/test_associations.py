"""Tests for PPR activation spreading (P5a-1)."""
import tempfile
import unittest
from pathlib import Path

from backend import associations as asc
from backend import entity_graph as eg


class AssociationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._db = eg.DB_PATH
        eg.DB_PATH = self.tmp / "eg.db"

    def tearDown(self):
        eg.DB_PATH = self._db

    def test_activation_spreads_multi_hop(self):
        eg.upsert([
            {"subject": "元亨", "object": "猫", "relation": "喜欢"},
            {"subject": "猫", "object": "深夜", "relation": "常在"},
            {"subject": "老爹", "object": "元亨", "relation": "创造"},
        ])
        names = [n for n, _ in asc.activate(["元亨"], top_k=6)]
        self.assertIn("猫", names)       # 1 跳
        self.assertTrue("深夜" in names or "老爹" in names)  # 2 跳可达

    def test_context_for_uses_spread(self):
        eg.upsert([{"subject": "量子计算", "object": "叠加态", "relation": "包含"}])
        old = asc._memories_mentioning
        asc._memories_mentioning = lambda name, limit=2: (
            ["关于叠加态的旧记忆"] if name == "叠加态" else [])
        try:
            out = asc.context_for("聊聊量子计算")
            self.assertIn("叠加态", out)
            self.assertIn("不要提及", out)
        finally:
            asc._memories_mentioning = old


if __name__ == "__main__":
    unittest.main()
