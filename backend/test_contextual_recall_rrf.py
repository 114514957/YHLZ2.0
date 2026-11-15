"""W2 integration: contextual_recall ranks a multi-channel hit first with RRF on."""
from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.target_memory import TargetMemoryService  # noqa: E402


def _seed(db: pathlib.Path) -> None:
    con = sqlite3.connect(db)
    try:
        now = time.time()
        rows = [
            # id, type, importance, summary, keywords
            ("m_both", "preference", 8, "老爹喜欢喝冰美式，不加糖", "咖啡 喜欢 冰美式"),
            ("m_one", "preference", 8, "老爹喜欢喝冰美式，不加糖（另一条）", "咖啡 喜欢"),
            ("m_other", "preference", 8, "周末去爬山要带够水", "爬山 运动"),
        ]
        for iid, typ, imp, summary, kw in rows:
            con.execute(
                "INSERT INTO l2_items (id,tier,type,importance,summary,content_hash,"
                "keywords,status,evidence_ref,created_at,version,access_count,"
                "last_accessed,belief,evidence_count,belief_updated,salience,"
                "valid_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, "L2", typ, imp, summary, iid, kw, "active", "", now, 1,
                 0, 0, 0.5, 1, now, 0.5, now))
        con.commit()
    finally:
        con.close()


class ContextualRecallRrfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="w2-"))
        self.db = self.tmp / "memstore.db"
        self.svc = TargetMemoryService(db_path=self.db, l1_scope="w2")
        _seed(self.db)

    def _recall(self, mode: str) -> list[dict]:
        # 2nd channel: no keyword index in a fresh temp DB, so stand in for BM25.
        self.svc.bm25_search = lambda q, limit=8: [{
            "id": "m_one", "type": "preference", "importance": 8,
            "status": "active", "summary": "老爹喜欢喝冰美式，不加糖（另一条）"}]
        with mock.patch.dict(os.environ, {"YHLZ_RRF": mode}):
            return self.svc.contextual_recall("老爹喜欢喝什么咖啡", limit=5)

    def test_rrf_fuses_two_channels(self):
        hits = self._recall("on")
        self.assertTrue(hits, "expected at least one hit")
        ids = [h["id"] for h in hits]
        self.assertIn("m_both", ids)
        self.assertIn("m_one", ids)
        multi = [h for h in hits if len(h.get("_channels") or []) >= 2]
        self.assertTrue(multi, "m_one appears in two channels and should be marked")

    def test_off_keeps_legacy_scores(self):
        hits = self._recall("off")
        self.assertTrue(hits)
        self.assertTrue(all("_channels" not in h for h in hits))
        self.assertEqual(hits[0]["id"], "m_both")   # legacy constant score order


if __name__ == "__main__":
    unittest.main()
