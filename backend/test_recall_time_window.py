"""W3 (ledger 1174): time-window recall — parsing, filtering, explicit errors."""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import target_scheduler_tools as tst  # noqa: E402
from backend.target_memory import TargetMemoryService  # noqa: E402


def _seed(db: pathlib.Path) -> None:
    con = sqlite3.connect(db)
    try:
        now = time.time()
        day = 86400.0
        rows = [
            ("m_old", "preference", 8, "老爹喜欢喝冰美式", "咖啡 喜欢", now - 40 * day),
            ("m_new", "preference", 8, "老爹喜欢喝冰美式（最近）", "咖啡 喜欢", now - 2 * day),
        ]
        for iid, typ, imp, summary, kw, ts in rows:
            con.execute(
                "INSERT INTO l2_items (id,tier,type,importance,summary,content_hash,"
                "keywords,status,evidence_ref,created_at,version,access_count,"
                "last_accessed,belief,evidence_count,belief_updated,salience,"
                "valid_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, "L2", typ, imp, summary, iid, kw, "active", "", ts, 1,
                 0, 0, 0.5, 1, ts, 0.5, ts))
        con.commit()
    finally:
        con.close()
    # keyword mirror so recall() has a lexical path
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS l2_fts USING fts5(sid, keywords, summary)")
        for iid, kw, summary in (("m_old", "咖啡 喜欢", "老爹喜欢喝冰美式"),
                                 ("m_new", "咖啡 喜欢", "老爹喜欢喝冰美式（最近）")):
            con.execute("INSERT INTO l2_fts(sid,keywords,summary) VALUES (?,?,?)",
                        (iid, kw, summary))
        con.commit()
    finally:
        con.close()


class TimeWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="w3-"))
        self.db = self.tmp / "memstore.db"
        self.svc = TargetMemoryService(db_path=self.db, l1_scope="w3")
        _seed(self.db)

    def test_parse_day_start_and_end(self):
        start = tst._parse_day("2026-11-01", end=False)
        end = tst._parse_day("2026-11-01", end=True)
        self.assertAlmostEqual(end - start, 86399, delta=1)

    def test_parse_day_rejects_garbage(self):
        with self.assertRaises(ValueError):
            tst._parse_day("上个月", end=False)
        with self.assertRaises(ValueError):
            tst._parse_day("2026-13-40", end=False)

    def test_filter_keeps_only_window(self):
        items = [{"id": "m_old"}, {"id": "m_new"}]
        now = time.time()
        kept = self.svc._filter_time_range(items, now - 5 * 86400, now)
        self.assertEqual([i["id"] for i in kept], ["m_new"])

    def test_open_ended_window(self):
        items = [{"id": "m_old"}, {"id": "m_new"}]
        kept = self.svc._filter_time_range(items, 0.0, time.time() - 10 * 86400)
        self.assertEqual([i["id"] for i in kept], ["m_old"])

    def test_unknown_id_dropped(self):
        kept = self.svc._filter_time_range([{"id": "nope"}], 0.0, 0.0)
        self.assertEqual(kept, [])

    def test_handler_raises_on_bad_date(self):
        with self.assertRaises(ValueError):
            tst._recall_handler({"query": "咖啡", "time_start": "上周"})

    def test_handler_rejects_inverted_window(self):
        with self.assertRaises(ValueError):
            tst._recall_handler({"query": "咖啡", "time_start": "2026-11-10",
                                 "time_end": "2026-11-01"})


if __name__ == "__main__":
    unittest.main()
