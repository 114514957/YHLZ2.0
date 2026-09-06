"""R1/R2 vitality tests (ledger 0189): use-strengthens, weekly forget."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.target_memory import L2Item, TargetMemoryService  # noqa: E402


class MemoryVitalityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "m.db"
        self.svc = TargetMemoryService(db_path=self.db)
        self.svc.store_item(L2Item(
            id="t1", tier="L2", type="preference", importance=5,
            summary="测试条目：喜欢在雨天写诗", content_hash="h",
            keywords="雨天写诗", status="active",
            created_at=__import__("time").time(),
        ))

    def test_seven_day_decay_reaches_cold(self):
        # 0.5 after 7 no-use days must fall under the 0.22 downgrade hint
        b = TargetMemoryService.belief_step(0.5, 0.0, decay_days=7.0)
        self.assertLess(b, 0.22)
        self.assertGreater(b, 0.1)

    def test_recall_boosts_with_dedup(self):
        self.svc.observe_hit("t1", strength=0.0)
        before = sqlite3.connect(str(self.db)).execute(
            "SELECT belief FROM l2_items WHERE id='t1'").fetchone()[0]
        self.svc._boost_recalled([{"id": "t1"}])
        after1 = sqlite3.connect(str(self.db)).execute(
            "SELECT belief FROM l2_items WHERE id='t1'").fetchone()[0]
        self.svc._boost_recalled([{"id": "t1"}])  # within 30s -> skipped
        after2 = sqlite3.connect(str(self.db)).execute(
            "SELECT belief FROM l2_items WHERE id='t1'").fetchone()[0]
        self.assertGreater(after1, before)
        self.assertAlmostEqual(after1, after2, places=6)

    def test_upkeep_backfills_legacy_updated(self):
        # simulate legacy row with belief_updated=0
        con = sqlite3.connect(str(self.db))
        con.execute("UPDATE l2_items SET belief_updated=0 WHERE id='t1'")
        con.commit()
        con.close()
        self.svc.apply_belief_decay()
        con = sqlite3.connect(str(self.db))
        up = con.execute("SELECT belief_updated FROM l2_items WHERE id='t1'").fetchone()[0]
        con.close()
        self.assertGreater(up, 0)


if __name__ == "__main__":
    unittest.main()
