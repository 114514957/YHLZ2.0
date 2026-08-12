"""
单元测试: logger.py - 感知日志系统
覆盖: log_start/success/fail/exception / query / stats / clear / save_to_file
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.logger import PerceptionLogger, PerceptionLogEntry


class TestPerceptionLogger(unittest.TestCase):

    def setUp(self):
        self.logger = PerceptionLogger(max_entries=100, enable_logging=False)

    def test_log_start(self):
        entry = self.logger.log_start(source="ocr", adapter="OCRAdapter", provider="mock")
        self.assertEqual(entry.source, "ocr")
        self.assertEqual(entry.event, "start")
        self.assertEqual(entry.adapter, "OCRAdapter")
        self.assertEqual(self.logger.count(), 1)

    def test_log_success(self):
        entry = self.logger.log_success(
            source="ocr",
            adapter="OCRAdapter",
            result_id="r1",
            latency_ms=12.5,
            provider="mock",
            text_count=3,
            confidence=0.9,
        )
        self.assertEqual(entry.event, "success")
        self.assertEqual(entry.latency_ms, 12.5)
        self.assertEqual(entry.text_count, 3)
        self.assertEqual(entry.confidence, 0.9)
        self.assertEqual(entry.status, "ok")

    def test_log_fail(self):
        entry = self.logger.log_fail(
            source="ocr",
            adapter="OCRAdapter",
            status="denied",
            error="权限不足",
            latency_ms=1.0,
        )
        self.assertEqual(entry.event, "fail")
        self.assertEqual(entry.status, "denied")
        self.assertEqual(entry.error, "权限不足")

    def test_log_exception(self):
        entry = self.logger.log_exception(
            source="detection",
            adapter="DetectionAdapter",
            error="boom",
            provider="yolo",
        )
        self.assertEqual(entry.event, "exception")
        self.assertEqual(entry.error, "boom")

    def test_query_by_source(self):
        self.logger.log_start(source="ocr", adapter="A")
        self.logger.log_start(source="detection", adapter="B")
        entries = self.logger.query(source="ocr", limit=10)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].source, "ocr")

    def test_query_by_event(self):
        self.logger.log_start(source="ocr", adapter="A")
        self.logger.log_success(
            source="ocr", adapter="A", result_id="r1", latency_ms=10.0
        )
        success_entries = self.logger.query(event="success", limit=10)
        self.assertEqual(len(success_entries), 1)
        self.assertEqual(success_entries[0].result_id, "r1")

    def test_query_limit(self):
        for i in range(10):
            self.logger.log_start(source="ocr", adapter=f"A{i}")
        entries = self.logger.query(limit=5)
        self.assertEqual(len(entries), 5)
        # 最新的在前, 第一个应该是 A9
        self.assertEqual(entries[0].adapter, "A9")

    def test_stats_empty(self):
        stats = self.logger.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["success_rate"], 0.0)

    def test_stats_with_entries(self):
        self.logger.log_success(
            source="ocr", adapter="A", result_id="r1", latency_ms=10.0,
            object_count=2, text_count=3,
        )
        self.logger.log_fail(source="ocr", adapter="A", status="error", error="x")
        stats = self.logger.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(stats["fail"], 1)
        self.assertEqual(stats["total_objects"], 2)
        self.assertEqual(stats["total_texts"], 3)
        self.assertEqual(stats["avg_latency_ms"], 10.0)
        self.assertEqual(stats["success_rate"], 50.0)

    def test_clear(self):
        self.logger.log_start(source="ocr", adapter="A")
        n = self.logger.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.logger.count(), 0)

    def test_max_entries_ring_buffer(self):
        logger = PerceptionLogger(max_entries=3, enable_logging=False)
        for i in range(5):
            logger.log_start(source="ocr", adapter=f"A{i}")
        self.assertEqual(logger.count(), 3)
        # 应保留最后 3 条
        entries = logger.query(limit=10)
        self.assertEqual(entries[0].adapter, "A4")

    def test_save_to_file(self):
        self.logger.log_start(source="ocr", adapter="A")
        self.logger.log_success(
            source="ocr", adapter="A", result_id="r1", latency_ms=5.0
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            path = f.name
        try:
            n = self.logger.save_to_file(path)
            self.assertEqual(n, 2)
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)
            import json
            entry = json.loads(lines[0])
            self.assertEqual(entry["source"], "ocr")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_log_entry_to_dict(self):
        entry = PerceptionLogEntry(
            source="ocr", adapter="A", provider="mock",
            event="success", latency_ms=12.5, result_id="r1",
            object_count=2, text_count=1, confidence=0.8,
        )
        d = entry.to_dict()
        self.assertEqual(d["source"], "ocr")
        self.assertEqual(d["provider"], "mock")
        self.assertEqual(d["latency_ms"], 12.5)
        self.assertEqual(d["object_count"], 2)
        self.assertEqual(d["confidence"], 0.8)


if __name__ == "__main__":
    unittest.main()
