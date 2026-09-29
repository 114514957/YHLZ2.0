"""Tests for recall timing and memory health (Step 2)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.target_memory import L2Item, TargetMemoryService


class TestRecallTiming(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db = Path(self._tmp) / "test.db"
        self.svc = TargetMemoryService(db_path=self.db, l1_scope="test")
        item = L2Item(
            id="test-1", tier="L2", type="fact", importance=7,
            summary="测试事实：元亨喜欢喝茉莉花茶",
            content_hash="abc123", keywords="茉莉花茶 喜欢",
        )
        self.svc.store_item(item)

    def test_recall_timing_recorded(self):
        self.svc.recall("茉莉花茶", limit=3)
        t = self.svc.health()["last_recall_timing"]
        self.assertIn("keyword_ms", t)
        self.assertIn("total_ms", t)
        self.assertIsInstance(t["keyword_ms"], float)

    def test_recall_count_incremented(self):
        h0 = self.svc.health()["recall_count"]
        self.svc.recall("茉莉花茶", limit=3)
        h1 = self.svc.health()["recall_count"]
        self.assertEqual(h1, h0 + 1)

    def test_health_includes_timing(self):
        self.svc.recall("茉莉花茶", limit=3)
        h = self.svc.health()
        self.assertIn("last_recall_timing", h)
        self.assertIn("recall_count", h)
        self.assertIn("summary_provider_status", h)

    def test_health_includes_window_and_backlog(self):
        h = self.svc.health()
        self.assertIn("l1_window", h)
        self.assertIn("summary_backlog", h)
        self.assertIn("summary_pending", h)
        self.assertIn("l1_save_error", h)

    def test_semantic_timing_when_thin(self):
        """When keyword hits are thin, semantic path should be timed."""
        self.svc.recall("完全不相关的查询xyz123", limit=5)
        t = self.svc.health()["last_recall_timing"]
        # either keyword path or semantic path should have timing
        self.assertIn("total_ms", t)

    def test_provider_status_default(self):
        h = self.svc.health()
        self.assertIn("summary_provider_status", h)
        self.assertIsInstance(h["summary_provider_status"], str)


if __name__ == "__main__":
    unittest.main()
