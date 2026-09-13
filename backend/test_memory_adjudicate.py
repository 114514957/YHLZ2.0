"""M2 acceptance: evidence-based adjudicator (ledger 0318)."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.memory_adjudicate import (
    ACTION_CANDIDATE, ACTION_MERGE, ACTION_SUPERSEDE, ACTION_UNCERTAIN, resolve,
)
from backend.target_memory import L2Item, TargetMemoryService


def _it(summary, source="群聊", created=1.0, protected=0, conf=0.5):
    return SimpleNamespace(summary=summary, source=source, confidence=conf,
                           protected=protected, created_at=created,
                           evidence_count=0, belief=0.5)


class TestAdjudicate(unittest.TestCase):
    def test_protected_never_superseded(self):
        v = resolve(_it("老爹不吃香菜", "老爹", 2.0),
                    _it("老爹吃香菜", "群聊", 1.0, protected=1))
        self.assertEqual(v.action, ACTION_UNCERTAIN)

    def test_negation_trusted_supersede(self):
        v = resolve(_it("更正：老爹现在不吃香菜了", "老爹", 2.0),
                    _it("老爹吃香菜", "群聊", 1.0))
        self.assertEqual(v.action, ACTION_SUPERSEDE)

    def test_thin_evidence_candidate(self):
        v = resolve(_it("老爹在B公司", "群聊", 2.0),
                    _it("老爹在A公司", "群聊", 1.0))
        self.assertEqual(v.action, ACTION_CANDIDATE)

    def test_merge_same_wording(self):
        v = resolve(_it("老爹喜欢猫", "x", 2.0),
                    _it("老爹喜欢猫。", "y", 1.0))
        self.assertEqual(v.action, ACTION_MERGE)


class TestAutoSupersede(unittest.TestCase):
    def test_store_triggers_soft_invalidate(self):
        svc = TargetMemoryService(db_path=Path(tempfile.mkdtemp()) / "m.db")
        now = time.time()
        svc.store_item(L2Item(id="o1", tier="L2", type="fact", importance=5,
                              summary="老爹在A公司", content_hash="a",
                              keywords="老爹 A公司", source="群聊",
                              created_at=now - 100))
        svc.store_item(L2Item(id="n1", tier="L2", type="fact", importance=5,
                              summary="更正：老爹现在在B公司", content_hash="b",
                              keywords="老爹 B公司", source="老爹",
                              created_at=now))
        con = sqlite3.connect(str(svc.db_path))
        r = con.execute("SELECT invalid_at, superseded_by FROM l2_items "
                        "WHERE id='o1'").fetchone()
        cnt = con.execute("SELECT count(*) FROM l2_items").fetchone()[0]
        con.close()
        self.assertGreater(r[0], 0)      # old soft-invalidated
        self.assertEqual(r[1], "n1")
        self.assertEqual(cnt, 2)         # history preserved


if __name__ == "__main__":
    unittest.main()
