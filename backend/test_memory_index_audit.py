"""Projection audit/rebuild tests; no embedding model is loaded."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.memory_index_audit import (
    audit, prune_vector_stale, rebuild_fts, rebuild_keyword, rebuild_vector,
)
from backend.target_kw_index import KeywordIndex
from backend.target_memory import L2Item, TargetMemoryService


class MemoryIndexAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "mem.db"
        self.kw = root / "kw.db"
        self.vec = root / "vec.db"
        self.mem = TargetMemoryService(db_path=self.db)
        self.mem.store_item(L2Item(
            id="a", tier="L2", type="preference", importance=8,
            summary="主人喜欢安静的夜间工作", content_hash="ha",
            keywords="安静 夜间", status="active", created_at=1,
        ))
        self.mem.store_item(L2Item(
            id="b", tier="L2", type="event", importance=5,
            summary="项目在周末完成了阶段验收", content_hash="hb",
            keywords="项目 周末", status="downgraded", created_at=2,
        ))
        self.mem.store_item(L2Item(
            id="old", tier="L2", type="event", importance=2,
            summary="旧条目", content_hash="ho", keywords="旧", status="archive", created_at=3,
        ))

    def tearDown(self):
        self.tmp.cleanup()

    def test_audit_reports_missing_and_stale_projections(self):
        con = sqlite3.connect(str(self.db))
        con.execute("DELETE FROM l2_fts")
        con.commit(); con.close()
        report = audit(self.db, kw_db_path=self.kw, vec_db_path=self.vec)
        self.assertFalse(report["ok"])
        self.assertEqual(report["fts"]["missing"], ["a", "b"])
        self.assertEqual(report["keyword"]["missing"], ["a", "b"])
        self.assertEqual(report["vector"]["missing"], ["a", "b"])

    def test_rebuild_fts_and_keyword_are_deterministic(self):
        self.assertTrue(rebuild_fts(self.db)["ok"])  # FTS is the only requested projection
        report = rebuild_keyword(self.db, kw_db_path=self.kw, clear_source=True)
        self.assertTrue(report["fts"]["missing"] == [])
        self.assertTrue(report["keyword"]["missing"] == [])
        self.assertEqual(report["keyword"]["stale"], [])
        self.assertEqual(report["authoritative"], 2)

    def test_vector_rebuild_is_blocked_without_explicit_model_permission(self):
        report = rebuild_vector(self.db, vec_db_path=self.vec, allow_model=False)
        self.assertFalse(report["vector_rebuild"]["attempted"])
        self.assertEqual(report["vector_rebuild"]["reason"], "model_not_allowed")

    def test_audit_detects_stale_archive_projection(self):
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO l2_fts(sid,keywords,summary) VALUES ('old','旧','旧条目')")
        con.commit(); con.close()
        report = audit(self.db)
        self.assertEqual(report["fts"]["stale"], ["old"])

    def test_vector_stale_prune_is_model_free_and_dry_run_by_default(self):
        con = sqlite3.connect(str(self.vec))
        con.execute("CREATE TABLE vec(id TEXT NOT NULL, scope TEXT NOT NULL, vec BLOB NOT NULL, text TEXT, PRIMARY KEY(id,scope))")
        con.execute("INSERT INTO vec VALUES ('old','l2',?,?)", (b"x", "旧条目"))
        con.execute("INSERT INTO vec VALUES ('a','l2',?,?)", (b"y", "主人喜欢安静的夜间工作"))
        con.commit(); con.close()
        dry = prune_vector_stale(self.db, vec_db_path=self.vec, scope="l2")
        self.assertFalse(dry["apply"])
        self.assertEqual(dry["deleted"], 0)
        self.assertEqual(dry["stale_before"], ["old"])
        applied = prune_vector_stale(self.db, vec_db_path=self.vec, scope="l2", apply=True)
        self.assertEqual(applied["deleted"], 1)
        self.assertEqual(applied["stale_after"], [])
        self.assertFalse(applied["model_loaded"])


if __name__ == "__main__":
    unittest.main()

