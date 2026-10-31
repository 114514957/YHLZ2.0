"""Crash/conflict tests for recoverable L3 persona versions."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.persona_versions import PersonaConflict, PersonaVersions
from backend.target_memory import L2Item, TargetMemoryService


class PersonaVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "mem.db"
        self.foundation = root / "cognition.md"
        self.foundation.write_text("# 根基\n", encoding="utf-8")
        self.mem = TargetMemoryService(db_path=self.db)
        self.mem.store_item(L2Item(
            id="source-a", tier="L2", type="preference", importance=8,
            summary="主人偏好可追溯的记忆", content_hash="ha", keywords="偏好",
            status="active", evidence_ref="turn:1", created_at=1,
        ))
        self.versions = PersonaVersions(self.db, self.foundation)

    def tearDown(self):
        self.tmp.cleanup()

    def _status(self):
        con = sqlite3.connect(str(self.db))
        try:
            return con.execute("SELECT status,evidence_ref FROM l2_items WHERE id='source-a'").fetchone()
        finally:
            con.close()

    def test_apply_archives_source_and_records_version(self):
        before = self.foundation.read_text(encoding="utf-8")
        cid = self.versions.apply(1, before + "\n## v1\n", ["source-a"], ["claim-1"], expected_before=before)
        self.assertEqual(self.versions.list()[0]["state"], "applied")
        self.assertEqual(self._status(), ("archive", "persona:consolidated:v1"))
        self.assertIn("v1", self.foundation.read_text(encoding="utf-8"))
        self.assertTrue(cid.startswith("persona_"))

    def test_external_foundation_conflict_does_not_archive_source(self):
        before = self.foundation.read_text(encoding="utf-8")
        with self.assertRaises(PersonaConflict):
            self.versions.apply(1, before + "x", ["source-a"], ["claim-1"], expected_before="wrong")
        self.assertEqual(self._status(), ("active", "turn:1"))
        self.assertEqual(self.versions.list(), [])

    def test_source_conflict_does_not_apply(self):
        before = self.foundation.read_text(encoding="utf-8")
        con = sqlite3.connect(str(self.db))
        con.execute("UPDATE l2_items SET status='cold' WHERE id='source-a'")
        con.commit(); con.close()
        with self.assertRaises(PersonaConflict):
            self.versions.apply(1, before + "x", ["source-a"], ["claim-1"], expected_before=before)
        self.assertEqual(self.foundation.read_text(encoding="utf-8"), before)

    def test_prepared_intent_recovery_rolls_forward(self):
        before = self.foundation.read_text(encoding="utf-8")
        after = before + "\n## v1\n"
        with self.versions._transaction() as con:
            source = self.versions._source(con, "source-a")
            self.versions._prepare(
                con, "prepared-1", 1, "apply", "", before, after,
                [{"before": source, "after": dict(source, status="archive", evidence_ref="persona:consolidated:v1")}],
                ["claim-1"], "test",
            )
        self.assertEqual(self.versions.recover("prepared-1"), "applied")
        self.assertEqual(self._status(), ("archive", "persona:consolidated:v1"))

    def test_revert_keeps_history_and_restores_source(self):
        before = self.foundation.read_text(encoding="utf-8")
        cid = self.versions.apply(1, before + "\n## v1\n", ["source-a"], ["claim-1"], expected_before=before)
        rid = self.versions.revert(cid, reason="owner correction")
        rows = self.versions.list()
        self.assertEqual([r["state"] for r in rows], ["reverted", "applied"])
        self.assertEqual(self._status(), ("active", "turn:1"))
        self.assertEqual(self.foundation.read_text(encoding="utf-8"), before)
        self.assertTrue(rid.startswith("persona_"))

    def test_revert_rejects_external_edit(self):
        before = self.foundation.read_text(encoding="utf-8")
        cid = self.versions.apply(1, before + "\n## v1\n", ["source-a"], ["claim-1"], expected_before=before)
        self.foundation.write_text("external", encoding="utf-8")
        with self.assertRaises(PersonaConflict):
            self.versions.revert(cid, reason="owner correction")
        self.assertEqual(self._status(), ("archive", "persona:consolidated:v1"))

    def test_version_cannot_be_reused_after_revert(self):
        before = self.foundation.read_text(encoding="utf-8")
        cid = self.versions.apply(1, before + "\n## v1\n", ["source-a"], ["claim-1"], expected_before=before)
        self.versions.revert(cid, reason="owner correction")
        now = self.foundation.read_text(encoding="utf-8")
        with self.assertRaises(PersonaConflict):
            self.versions.apply(1, now + "again", ["source-a"], ["claim-2"], expected_before=now)


if __name__ == "__main__":
    unittest.main()
