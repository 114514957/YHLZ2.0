"""M1 acceptance (ledger 0317): Profile/Episodic 分层 + 双时态失效。

Sample set (中文) exercising the M1 contract on an isolated temp db.
"""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from backend.target_memory import L2Item, TargetMemoryService


class TestM1Acceptance(unittest.TestCase):
    def setUp(self):
        self.svc = TargetMemoryService(db_path=Path(tempfile.mkdtemp()) / "m.db")
        self.now = time.time()

    def _item(self, iid, summary, kind="episodic", protected=0, imp=5,
              conf=0.5, kw=""):
        return L2Item(id=iid, tier="L2",
                      type=("preference" if kind == "profile" else "fact"),
                      importance=imp, summary=summary, content_hash=iid,
                      keywords=kw or summary[:20], kind=kind,
                      protected=protected, confidence=conf,
                      created_at=self.now)

    def test_profile_precise_read(self):
        self.svc.store_item(self._item("p1", "老爹不吃香菜", kind="profile",
                                       protected=1, conf=0.9))
        self.svc.store_item(self._item("e1", "今天聊了天气"))
        self.assertEqual([r["summary"] for r in self.svc.profile_get("香菜")],
                         ["老爹不吃香菜"])
        self.assertEqual(self.svc.profile_get("天气"), [])

    def test_protected_and_profile_not_decayed(self):
        self.svc.store_item(self._item("p1", "老爹的生日是X", kind="profile",
                                       protected=1))
        self.svc.store_item(self._item("e1", "一个普通事件"))
        con = sqlite3.connect(str(self.svc.db_path))
        con.execute("UPDATE l2_items SET belief_updated=?",
                    (self.now - 60 * 86400,))
        con.commit()
        before = {i: b for i, b in con.execute(
            "SELECT id, belief FROM l2_items")}
        con.close()
        self.svc.apply_belief_decay()
        con = sqlite3.connect(str(self.svc.db_path))
        after = {i: b for i, b in con.execute(
            "SELECT id, belief FROM l2_items")}
        con.close()
        self.assertAlmostEqual(after["p1"], before["p1"], places=9)  # untouched
        self.assertLess(after["e1"], before["e1"])                   # decayed

    def test_supersede_preserves_history(self):
        self.svc.store_item(self._item("e1", "老爹在A公司"))
        self.svc.store_item(self._item("e2", "老爹在B公司"))
        self.assertTrue(self.svc.supersede("e1", "e2"))
        con = sqlite3.connect(str(self.svc.db_path))
        r = con.execute("SELECT invalid_at, superseded_by FROM l2_items "
                        "WHERE id='e1'").fetchone()
        cnt = con.execute("SELECT count(*) FROM l2_items").fetchone()[0]
        con.close()
        self.assertGreater(r[0], 0)         # old invalidated (soft)
        self.assertEqual(r[1], "e2")
        self.assertEqual(cnt, 2)            # history NOT deleted

    def test_cross_restart_persistence(self):
        self.svc.store_item(self._item("p1", "我叫老爹", kind="profile",
                                       protected=1))
        self.svc.append_turn(role="user", text="你好")
        svc2 = TargetMemoryService(db_path=self.svc.db_path)
        self.assertEqual([r["summary"] for r in svc2.profile_get("老爹")],
                         ["我叫老爹"])
        self.assertEqual(len(svc2._turns), 1)

    def test_marker_upgrade_to_profile(self):
        from backend.target_scheduler_tools import _looks_like_profile
        self.assertTrue(_looks_like_profile("记住我不吃香菜"))
        self.assertFalse(_looks_like_profile("今天天气不错"))


if __name__ == "__main__":
    unittest.main()
