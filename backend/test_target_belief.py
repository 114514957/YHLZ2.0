"""Belief (bayes-style) + retrieval confidence tests (M2)."""

import tempfile
import unittest
from pathlib import Path

from backend.target_kw_index import KeywordIndex
from backend.target_memory import TargetMemoryService


class TestBeliefUpdate(unittest.TestCase):
    def test_step_hit_raises(self):
        b = TargetMemoryService.belief_step(0.5, 0.3)
        self.assertGreater(b, 0.5)

    def test_step_contradiction_lowers(self):
        b = TargetMemoryService.belief_step(0.5, -0.5)
        self.assertLess(b, 0.5)

    def test_decay_lowers_over_time(self):
        b = TargetMemoryService.belief_step(0.8, 0.0, decay_days=90)
        self.assertLess(b, 0.8)

    def test_clamped(self):
        self.assertLessEqual(TargetMemoryService.belief_step(0.99, 1.0), 0.99)
        self.assertGreaterEqual(TargetMemoryService.belief_step(0.01, -1.0), 0.01)


class TestBeliefIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.kw = KeywordIndex(self.tmp / "kw.db")
        self.mem = TargetMemoryService(db_path=self.tmp / "mem.db", kw_index=self.kw)

    def _add(self, summary="用户喜欢在深夜思考问题") -> str:
        from backend.target_memory import L2Item

        item = L2Item(
            id="mem_testbelief",
            tier="L2", type="preference", importance=6, summary=summary,
            content_hash="h", keywords="深夜 思考",
            evidence_ref="test", created_at=0,
        )
        self.mem.store_item(item)
        return item.id

    def test_hit_then_contradiction(self):
        iid = self._add()
        b1 = self.mem.observe_hit(iid, strength=0.4)
        r1 = self.mem.belief_report(iid)
        self.assertGreater(r1["belief"], 0.5)
        b2 = self.mem.observe_contradiction(iid)
        self.assertLess(b2, b1)
        r2 = self.mem.belief_report(iid)
        self.assertEqual(r2["evidence_count"], 2)
        self.assertFalse(r2["downgrade_hint"])

    def test_many_contradictions_hint(self):
        iid = self._add()
        for _ in range(6):
            self.mem.observe_contradiction(iid)
        rep = self.mem.belief_report(iid)
        self.assertTrue(rep["downgrade_hint"])
        row = self.mem.recall("深夜")
        self.assertTrue(row)  # never deleted

    def test_decay_all(self):
        self._add()
        n = self.mem.apply_belief_decay(now=time.time() + 200 * 86400)
        self.assertGreaterEqual(n, 1)

    def test_apply_downgrades_flags_low_belief(self):
        iid = self._add()
        for _ in range(8):
            self.mem.observe_contradiction(iid)
        n = self.mem.apply_belief_downgrades()
        self.assertGreaterEqual(n, 1)
        rep = self.mem.belief_report(iid)
        self.assertEqual(rep["status"], "downgraded")
        rows = self.mem.recall("深夜")
        self.assertTrue(rows)  # downgraded still recallable; never deleted

    def test_belief_survives_store_and_reload(self):
        iid = self._add()
        self.mem.observe_hit(iid, 0.3)
        mem2 = TargetMemoryService(db_path=self.tmp / "mem.db")
        rep = mem2.belief_report(iid)
        self.assertGreater(rep["belief"], 0.5)


import time  # noqa: E402


if __name__ == "__main__":
    unittest.main()
