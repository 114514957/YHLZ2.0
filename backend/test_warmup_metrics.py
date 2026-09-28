"""Tests for persistent warmup metrics (Phase9 step 2)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tts_qwen_process import QwenProcessWorker


class TestWarmupMetrics(unittest.TestCase):
    def _make_provider(self):
        p = QwenProcessWorker.__new__(QwenProcessWorker)
        p._lock = MagicMock()
        p._process = MagicMock()
        p._process.is_alive.return_value = True
        p._process.pid = 12345
        p._connection = MagicMock()
        p.worker_id = "test-worker"
        p.config = MagicMock()
        p.config.provider_id = "qwen3-faster-customvoice"
        p._started_at = 100.0
        p._ready_at = 117.3
        p._turn_count = 0
        p._stopping = False
        p._last_error_code = None
        p._last_error_detail = ""
        p._sessions = {}
        p._last_metrics = {}
        return p

    def test_cold_start_metrics(self):
        p = self._make_provider()
        h = p.health()
        self.assertEqual(h["model_load_ms"], 17300.0)
        self.assertFalse(h["is_warm"])
        self.assertEqual(h["turn_count"], 0)

    def test_hot_after_first_turn(self):
        p = self._make_provider()
        p._turn_count = 1
        h = p.health()
        self.assertTrue(h["is_warm"])
        self.assertEqual(h["turn_count"], 1)

    def test_ready_at_in_health(self):
        p = self._make_provider()
        h = p.health()
        self.assertEqual(h["ready_at"], 117.3)

    def test_metrics_include_warmup(self):
        p = self._make_provider()
        m = p.metrics()
        self.assertEqual(m["model_load_ms"], 17300.0)
        self.assertFalse(m["is_warm"])

    def test_no_ready_at(self):
        p = self._make_provider()
        p._ready_at = None
        h = p.health()
        self.assertIsNone(h["model_load_ms"])

    def test_no_started_at(self):
        p = self._make_provider()
        p._started_at = None
        h = p.health()
        self.assertIsNone(h["model_load_ms"])


if __name__ == "__main__":
    unittest.main()
