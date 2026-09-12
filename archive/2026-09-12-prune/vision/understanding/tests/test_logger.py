"""
单元测试: logger.py - UnderstandingLogger
覆盖: 全生命周期日志 / 查询 / 统计 / 清空 / 落盘
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.logger import (
    UnderstandingLogEntry,
    UnderstandingLogger,
)


class TestUnderstandingLogEntry(unittest.TestCase):

    def test_fields(self):
        entry = UnderstandingLogEntry(
            source="describe",
            adapter="VLMAdapter",
            provider="mock",
            event="success",
            latency_ms=12.5,
            result_id="r1",
            status="ok",
            scene_type="desktop",
            subject_count=2,
            confidence=0.9,
        )
        self.assertEqual(entry.source, "describe")
        self.assertEqual(entry.scene_type, "desktop")
        self.assertEqual(entry.subject_count, 2)

    def test_to_dict(self):
        entry = UnderstandingLogEntry(event="start", source="qa")
        d = entry.to_dict()
        self.assertEqual(d["event"], "start")
        self.assertEqual(d["source"], "qa")
        self.assertIn("timestamp", d)


class TestUnderstandingLogger(unittest.TestCase):

    def setUp(self):
        self.ulog = UnderstandingLogger(max_entries=100, enable_logging=False)

    def test_log_start(self):
        entry = self.ulog.log_start(source="describe", adapter="VLMAdapter")
        self.assertEqual(entry.event, "start")
        self.assertEqual(self.ulog.count(), 1)

    def test_log_success(self):
        self.ulog.log_success(
            source="describe",
            adapter="VLMAdapter",
            result_id="r1",
            latency_ms=10.0,
            provider="mock",
            scene_type="desktop",
            subject_count=3,
            confidence=0.9,
        )
        entries = self.ulog.query(event="success")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].latency_ms, 10.0)
        self.assertEqual(entries[0].scene_type, "desktop")
        self.assertEqual(entries[0].subject_count, 3)

    def test_log_fail(self):
        self.ulog.log_fail(
            source="qa",
            adapter="VLMAdapter",
            status="denied",
            error="权限拒绝",
            latency_ms=5.0,
        )
        entries = self.ulog.query(event="fail")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].status, "denied")
        self.assertEqual(entries[0].error, "权限拒绝")

    def test_log_exception(self):
        self.ulog.log_exception(source="vlm", adapter="VLMAdapter", error="boom")
        entries = self.ulog.query(event="exception")
        self.assertEqual(len(entries), 1)

    def test_query_filters(self):
        self.ulog.log_start(source="describe", adapter="A")
        self.ulog.log_start(source="qa", adapter="A")
        self.ulog.log_start(source="describe", adapter="B")
        self.assertEqual(len(self.ulog.query(source="describe")), 2)
        self.assertEqual(len(self.ulog.query(source="qa")), 1)
        self.assertEqual(len(self.ulog.query(adapter="B")), 1)
        self.assertEqual(len(self.ulog.query(source="describe", adapter="B")), 1)
        self.assertEqual(len(self.ulog.query(source="vlm")), 0)

    def test_query_limit(self):
        for _ in range(10):
            self.ulog.log_start(source="describe", adapter="A")
        entries = self.ulog.query(limit=3)
        self.assertEqual(len(entries), 3)

    def test_stats_empty(self):
        stats = self.ulog.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["success_rate"], 0.0)

    def test_stats_with_data(self):
        self.ulog.log_start(source="describe", adapter="A")
        self.ulog.log_success(
            source="describe", adapter="A", result_id="r1",
            latency_ms=10.0, scene_type="desktop", subject_count=2,
        )
        self.ulog.log_success(
            source="describe", adapter="A", result_id="r2",
            latency_ms=20.0, scene_type="web", subject_count=1,
        )
        self.ulog.log_fail(source="qa", adapter="A", status="denied", error="x")
        stats = self.ulog.stats()
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["success"], 2)
        self.assertEqual(stats["fail"], 1)
        self.assertEqual(stats["exception"], 0)
        self.assertEqual(stats["success_rate"], 50.0)
        self.assertEqual(stats["avg_latency_ms"], 15.0)
        self.assertEqual(stats["total_subjects"], 3)

    def test_clear(self):
        self.ulog.log_start(source="describe", adapter="A")
        self.ulog.log_success(
            source="describe", adapter="A", result_id="r1", latency_ms=1.0,
        )
        n = self.ulog.clear()
        self.assertEqual(n, 2)
        self.assertEqual(self.ulog.count(), 0)

    def test_save_to_file(self):
        self.ulog.log_start(source="describe", adapter="A")
        self.ulog.log_success(
            source="describe", adapter="A", result_id="r1",
            latency_ms=1.0, scene_type="desktop",
        )
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            n = self.ulog.save_to_file(path)
            self.assertEqual(n, 2)
            lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            import json
            first = json.loads(lines[0])
            self.assertIn("event", first)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_ring_buffer_cap(self):
        ulog = UnderstandingLogger(max_entries=5, enable_logging=False)
        for i in range(10):
            ulog.log_start(source="describe", adapter="A")
        self.assertEqual(ulog.count(), 5)

    def test_metadata_in_entry(self):
        entry = self.ulog.log_start(
            source="describe", adapter="A", metadata={"frame_id": "f1"}
        )
        self.assertEqual(entry.metadata["frame_id"], "f1")


if __name__ == "__main__":
    unittest.main()
