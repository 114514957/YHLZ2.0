"""Salience-modulated decay (design v1 §1.1): high salience forgets slower."""
import asyncio
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from backend.target_memory import L2Item, TargetMemoryService


def _mk(iid, sal, summary):
    return L2Item(id=iid, tier="t", type="fact", importance=5, summary=summary,
                  content_hash="h" + iid, keywords="k", created_at=0.0,
                  salience=sal)


class SalienceTest(unittest.TestCase):
    def test_high_salience_decays_slower(self):
        tmp = Path(tempfile.mkdtemp())
        svc = TargetMemoryService(db_path=tmp / "m.db")
        asyncio.run(svc.adjudicate_async([_mk("a", 0.0, "低显著"),
                                          _mk("b", 1.0, "高显著")]))
        old = time.time() - 40 * 86400
        con = sqlite3.connect(str(tmp / "m.db"))
        con.execute("UPDATE l2_items SET belief=1.0, belief_updated=?", (old,))
        con.commit()
        con.close()
        svc.apply_belief_decay(now=time.time())
        con = sqlite3.connect(str(tmp / "m.db"))
        a = con.execute("SELECT belief FROM l2_items WHERE id='a'").fetchone()[0]
        b = con.execute("SELECT belief FROM l2_items WHERE id='b'").fetchone()[0]
        con.close()
        self.assertGreater(b, a)  # 高显著保留更多信念（忘得更慢）


if __name__ == "__main__":
    unittest.main()
