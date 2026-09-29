"""Tests for memory governance (Step 3: approve/reject/correct/invalidate)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.target_memory import L2Item, TargetMemoryService


class TestMemoryGovernance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db = Path(self._tmp) / "test.db"
        self.svc = TargetMemoryService(db_path=self.db, l1_scope="test")

    def _store(self, iid: str, summary: str, status: str = "active"):
        item = L2Item(
            id=iid, tier="L2", type="fact", importance=7,
            summary=summary, content_hash=iid[:16], keywords="test",
            status=status,
        )
        self.svc.store_item(item)

    def test_approve_pending(self):
        self._store("a1", "候选事实", status="pending")
        ok = self.svc.approve("a1", approved_by="owner")
        self.assertTrue(ok)
        items = self.svc.list_by_status("active", limit=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "owner")

    def test_reject_candidate(self):
        self._store("r1", "待拒绝", status="candidate")
        ok = self.svc.reject("r1")
        self.assertTrue(ok)
        items = self.svc.list_by_status("archive", limit=5)
        self.assertEqual(len(items), 1)

    def test_reject_active_not_allowed(self):
        self._store("r2", "已激活", status="active")
        ok = self.svc.reject("r2")
        self.assertFalse(ok)  # only pending/candidate can be rejected

    def test_correct_fact(self):
        self._store("old1", "元亨喜欢喝茉莉花茶")
        new_id = self.svc.correct(
            "old1", "元亨喜欢喝普洱茶",
            speaker="老爹", channel="console",
        )
        self.assertTrue(new_id.startswith("corr_"))
        # old is superseded
        items = self.svc.list_by_status("active", limit=5)
        summaries = [i["summary"] for i in items]
        self.assertIn("元亨喜欢喝普洱茶", summaries)
        # old is soft-invalidated
        old_items = self.svc.list_by_status("archive", limit=5)
        self.assertEqual(len(old_items), 1)
        self.assertEqual(old_items[0]["superseded_by"], new_id)

    def test_invalidate(self):
        self._store("inv1", "过时信息")
        ok = self.svc.invalidate("inv1", reason="time to forget")
        self.assertTrue(ok)
        items = self.svc.list_by_status("archive", limit=5)
        self.assertEqual(len(items), 1)
        self.assertGreater(items[0]["invalid_at"], 0)

    def test_invalidate_twice_no_effect(self):
        self._store("inv2", "双重失效")
        self.assertTrue(self.svc.invalidate("inv2"))
        self.assertFalse(self.svc.invalidate("inv2"))  # already invalidated

    def test_list_by_status(self):
        self._store("s1", "活跃项", status="active")
        self._store("s2", "待处理", status="pending")
        self._store("s3", "已拒绝", status="archive")
        act = self.svc.list_by_status("active", limit=5)
        pend = self.svc.list_by_status("pending", limit=5)
        arch = self.svc.list_by_status("archive", limit=5)
        self.assertEqual(len(act), 1)
        self.assertEqual(len(pend), 1)
        self.assertEqual(len(arch), 1)

    def test_correction_preserves_provenance(self):
        self._store("old2", "旧偏好")
        new_id = self.svc.correct(
            "old2", "新偏好",
            speaker="老爹", channel="console",
            evidence_ref="ledger:0518",
        )
        items = self.svc.list_by_status("active", limit=5)
        self.assertEqual(items[0]["source"], "老爹")
        self.assertEqual(items[0]["evidence_ref"], "ledger:0518")

    def test_correction_never_deletes(self):
        self._store("old3", "要被纠正的")
        self.svc.correct("old3", "纠正后的内容")
        # old3 still exists (just invalidated)
        h = self.svc.health()
        self.assertGreaterEqual(h["l2_items"], 2)  # old + new


if __name__ == "__main__":
    unittest.main()
