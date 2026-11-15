"""W4 (ledger 1174): freeze/revive hysteresis and its effect on ranking."""
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

from backend import memory_lifecycle as lc  # noqa: E402
from backend.target_memory import TargetMemoryService  # noqa: E402


class LifecyclePureTests(unittest.TestCase):
    def test_freeze_below_threshold(self):
        with mock.patch.dict(os.environ, {"YHLZ_L2_FREEZE": "0.10", "YHLZ_L2_REVIVE": "0.15"}):
            self.assertEqual(lc.next_state("", 0.05), lc.FROZEN)
            self.assertEqual(lc.next_state("", 0.30), lc.ACTIVE)

    def test_hysteresis_stays_frozen_between_thresholds(self):
        with mock.patch.dict(os.environ, {"YHLZ_L2_FREEZE": "0.10", "YHLZ_L2_REVIVE": "0.15"}):
            self.assertEqual(lc.next_state(lc.FROZEN, 0.12), lc.FROZEN)   # not revived yet
            self.assertEqual(lc.next_state(lc.FROZEN, 0.16), lc.ACTIVE)   # revived above 0.15

    def test_rank_factor(self):
        self.assertAlmostEqual(lc.rank_factor(lc.FROZEN), 0.5)
        self.assertAlmostEqual(lc.rank_factor(""), 1.0)

    def test_half_life_matches_belief_lambda(self):
        self.assertAlmostEqual(lc.half_life_days(), 5.545, places=2)

    def test_switch_off(self):
        with mock.patch.dict(os.environ, {"YHLZ_L2_STRENGTH": "off"}):
            self.assertFalse(lc.enabled())


class LifecycleDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="w4-"))
        self.db = self.tmp / "memstore.db"
        self.svc = TargetMemoryService(db_path=self.db, l1_scope="w4")
        con = sqlite3.connect(self.db)
        now = time.time()
        for iid, belief in (("m_dead", 0.04), ("m_mid", 0.12), ("m_alive", 0.80)):
            con.execute(
                "INSERT INTO l2_items (id,tier,type,importance,summary,content_hash,"
                "keywords,status,evidence_ref,created_at,version,access_count,"
                "last_accessed,belief,evidence_count,belief_updated,salience,valid_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, "L2", "preference", 8, f"summary {iid}", iid, "关键词", "active",
                 "", now, 1, 0, 0, belief, 1, now, 0.5, now))
        con.commit()
        con.close()

    def test_migration_adds_lifecycle_column(self):
        con = sqlite3.connect(self.db)
        cols = {r[1] for r in con.execute("PRAGMA table_info(l2_items)")}
        con.close()
        self.assertIn("lifecycle", cols)

    def test_apply_lifecycle_freezes_low_belief(self):
        with mock.patch.dict(os.environ, {"YHLZ_L2_STRENGTH": "on"}):
            res = self.svc.apply_lifecycle()
        self.assertTrue(res["enabled"])
        self.assertGreaterEqual(res["frozen"], 1)
        con = sqlite3.connect(self.db)
        states = dict(con.execute("SELECT id, COALESCE(lifecycle,'') FROM l2_items"))
        con.close()
        self.assertEqual(states["m_dead"], "frozen")
        self.assertEqual(states["m_alive"], "")

    def test_apply_lifecycle_disabled(self):
        with mock.patch.dict(os.environ, {"YHLZ_L2_STRENGTH": "off"}):
            res = self.svc.apply_lifecycle()
        self.assertFalse(res["enabled"])

    def test_health_reports_frozen(self):
        with mock.patch.dict(os.environ, {"YHLZ_L2_STRENGTH": "on"}):
            self.svc.apply_lifecycle()
        self.assertGreaterEqual(self.svc.health()["l2_frozen"], 1)


if __name__ == "__main__":
    unittest.main()
