"""
单元测试: logger.py - 视觉日志系统
覆盖: log_start/success/fail/exception / query / stats / clear / save_to_file
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.vision.logger import VisionLogEntry, VisionLogger


class TestVisionLogger(unittest.TestCase):

    def setUp(self):
        self.logger = VisionLogger(max_entries=100, enable_logging=False)

    def test_log_start(self):
        entry = self.logger.log_start(source="screen", adapter="ScreenAdapter")
        self.assertEqual(entry.source, "screen")
        self.assertEqual(entry.event, "start")
        self.assertEqual(self.logger.count(), 1)

    def test_log_success(self):
        entry = self.logger.log_success(
            source="mock", adapter="MockAdapter",
            frame_id="abc123", latency_ms=15.5,
        )
        self.assertEqual(entry.event, "success")
        self.assertEqual(entry.frame_id, "abc123")
        self.assertEqual(entry.status, "ok")
        self.assertEqual(entry.latency_ms, 15.5)

    def test_log_fail(self):
        entry = self.logger.log_fail(
            source="camera", adapter="CameraAdapter",
            status="no_device", error="无摄像头",
            latency_ms=2.0,
        )
        self.assertEqual(entry.event, "fail")
        self.assertEqual(entry.status, "no_device")
        self.assertEqual(entry.error, "无摄像头")

    def test_log_exception(self):
        entry = self.logger.log_exception(
            source="screen", adapter="ScreenAdapter",
            error="OpenCV error",
        )
        self.assertEqual(entry.event, "exception")
        self.assertEqual(entry.error, "OpenCV error")

    def test_query_by_source(self):
        self.logger.log_success(source="screen", adapter="A", frame_id="1", latency_ms=1)
        self.logger.log_success(source="camera", adapter="B", frame_id="2", latency_ms=2)
        self.logger.log_success(source="screen", adapter="A", frame_id="3", latency_ms=3)
        result = self.logger.query(source="screen", limit=10)
        self.assertEqual(len(result), 2)
        for e in result:
            self.assertEqual(e.source, "screen")

    def test_query_by_event(self):
        self.logger.log_start(source="screen", adapter="A")
        self.logger.log_success(source="screen", adapter="A", frame_id="1", latency_ms=1)
        self.logger.log_fail(source="screen", adapter="A", status="error", error="x")
        result = self.logger.query(event="fail", limit=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].event, "fail")

    def test_query_limit(self):
        for i in range(10):
            self.logger.log_success(source="s", adapter="a", frame_id=str(i), latency_ms=1)
        result = self.logger.query(limit=5)
        self.assertEqual(len(result), 5)

    def test_query_returns_newest_first(self):
        self.logger.log_success(source="s", adapter="a", frame_id="old", latency_ms=1)
        self.logger.log_success(source="s", adapter="a", frame_id="new", latency_ms=1)
        result = self.logger.query(limit=10)
        self.assertEqual(result[0].frame_id, "new")
        self.assertEqual(result[1].frame_id, "old")

    def test_stats_empty(self):
        s = self.logger.stats()
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["success_rate"], 0.0)

    def test_stats_with_entries(self):
        self.logger.log_success(source="s", adapter="a", frame_id="1", latency_ms=10)
        self.logger.log_success(source="s", adapter="a", frame_id="2", latency_ms=20)
        self.logger.log_fail(source="s", adapter="a", status="error", error="x")
        s = self.logger.stats()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["success"], 2)
        self.assertEqual(s["fail"], 1)
        self.assertAlmostEqual(s["success_rate"], 66.67, places=1)
        self.assertEqual(s["avg_latency_ms"], 15.0)

    def test_clear(self):
        self.logger.log_start(source="s", adapter="a")
        self.logger.log_success(source="s", adapter="a", frame_id="1", latency_ms=1)
        n = self.logger.clear()
        self.assertEqual(n, 2)
        self.assertEqual(self.logger.count(), 0)

    def test_max_entries_bound(self):
        """超过 max_entries 时旧条目被丢弃"""
        small = VisionLogger(max_entries=3, enable_logging=False)
        for i in range(10):
            small.log_start(source="s", adapter="a")
        self.assertEqual(small.count(), 3)

    def test_save_to_file(self):
        self.logger.log_success(source="s", adapter="a", frame_id="1", latency_ms=1)
        self.logger.log_fail(source="s", adapter="a", status="error", error="x")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            n = self.logger.save_to_file(path)
            self.assertEqual(n, 2)
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)
        finally:
            os.unlink(path)

    def test_log_entry_to_dict(self):
        e = VisionLogEntry(source="screen", adapter="A", event="success", latency_ms=10.5)
        d = e.to_dict()
        self.assertEqual(d["source"], "screen")
        self.assertEqual(d["latency_ms"], 10.5)
        self.assertEqual(d["event"], "success")


if __name__ == "__main__":
    unittest.main(verbosity=2)
