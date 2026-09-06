"""Target memory stabilization adapter tests (ledger 0196)."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.target_memory import L2Item, TargetMemoryService  # noqa: E402
from backend.target_stabilization import stabilize_report  # noqa: E402


class StabilizeAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.mem = TargetMemoryService(db_path=self.tmp / "mem.db")

    def _put(self, iid, typ, imp, summary, kw, created=None):
        self.mem.store_item(L2Item(
            id=iid, tier="L2", type=typ, importance=imp, summary=summary,
            content_hash="h", keywords=kw, status="active",
            created_at=created or time.time(),
        ))

    def test_report_finds_repeated_groups(self):
        kw = "同一主题关键词xyz"
        self._put("a1", "fact", 5, "用户喜欢晚上散步，走河边的路", kw)
        self._put("a2", "fact", 6, "用户喜欢晚上散步，走河边的路", kw)
        self._put("b1", "preference", 4, "完全不同的一件事：喝咖啡", "别主题abc")
        rep = stabilize_report(self.mem)
        self.assertEqual(rep["total"], 3)
        groups = rep["merge_groups"]
        self.assertTrue(any("a1" in str(g.get("primary")) or "a2" in str(g.get("primary"))
                        for g in groups))

    def test_report_readonly_no_l2_mutation(self):
        self._put("c1", "fact", 5, "独立条目内容别触发合并", "唯一词12345")
        before = sqlite3.connect(str(self.tmp / "mem.db")).execute(
            "SELECT COUNT(*) FROM l2_items").fetchone()[0]
        stabilize_report(self.mem)
        after = sqlite3.connect(str(self.tmp / "mem.db")).execute(
            "SELECT COUNT(*) FROM l2_items").fetchone()[0]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
