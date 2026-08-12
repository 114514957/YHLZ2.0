"""
YHLZ Vision Memory V1.0 - 日志系统单元测试

覆盖:
    - 各事件记录 (start/save/query/delete/fail/exception)
    - 查询过滤
    - 统计 + 性能指标 (save_latency / query_latency / memory_count / hit_rate)
    - clear / count / save_to_file
"""
import os
import tempfile
import unittest

from backend.vision.memory.logger import MemoryLogger


class TestMemoryLogger(unittest.TestCase):

    def setUp(self):
        self.mlog = MemoryLogger(max_entries=100, enable_logging=False)

    def test_log_start(self):
        e = self.mlog.log_start(store="sqlite", action="save")
        self.assertEqual(e.event, "start")
        self.assertEqual(e.action, "save")

    def test_log_save(self):
        e = self.mlog.log_save(store="sqlite", memory_id="m1", latency_ms=5.5)
        self.assertEqual(e.event, "save")
        self.assertEqual(e.action, "save")
        self.assertEqual(e.memory_id, "m1")
        self.assertEqual(e.status, "ok")
        self.assertEqual(e.count, 1)

    def test_log_query(self):
        e = self.mlog.log_query(store="sqlite", latency_ms=3.2, hit_count=2)
        self.assertEqual(e.event, "query")
        self.assertTrue(e.hit)
        self.assertEqual(e.count, 2)
        e2 = self.mlog.log_query(store="sqlite", latency_ms=1.0, hit_count=0)
        self.assertFalse(e2.hit)

    def test_log_delete(self):
        e = self.mlog.log_delete(
            store="sqlite", action="delete", memory_id="m1",
            latency_ms=2.0, status="ok", count=1,
        )
        self.assertEqual(e.event, "delete")
        e2 = self.mlog.log_delete(
            store="sqlite", action="clear", memory_id="",
            latency_ms=2.0, status="ok", count=5,
        )
        self.assertEqual(e2.count, 5)

    def test_log_fail(self):
        e = self.mlog.log_fail(
            store="memory", action="save", status="denied", error="无权限",
        )
        self.assertEqual(e.event, "fail")
        self.assertEqual(e.status, "denied")

    def test_log_exception(self):
        e = self.mlog.log_exception(store="sqlite", action="save", error="异常")
        self.assertEqual(e.event, "exception")

    def test_query_filter(self):
        self.mlog.log_save(store="sqlite", memory_id="a", latency_ms=1.0)
        self.mlog.log_save(store="memory", memory_id="b", latency_ms=1.0)
        self.mlog.log_query(store="sqlite", latency_ms=1.0, hit_count=1)
        self.assertEqual(len(self.mlog.query(event="save")), 2)
        self.assertEqual(len(self.mlog.query(event="save", store="sqlite")), 1)
        self.assertEqual(len(self.mlog.query(action="query")), 1)
        self.assertEqual(len(self.mlog.query(status="denied")), 0)

    def test_newest_first(self):
        self.mlog.log_save(store="s", memory_id="1", latency_ms=1.0)
        self.mlog.log_save(store="s", memory_id="2", latency_ms=1.0)
        entries = self.mlog.query(event="save")
        self.assertEqual(entries[0].memory_id, "2")

    def test_limit(self):
        for i in range(10):
            self.mlog.log_save(store="s", memory_id=str(i), latency_ms=1.0)
        self.assertEqual(len(self.mlog.query(event="save", limit=3)), 3)

    def test_stats_empty(self):
        stats = self.mlog.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["save_latency_ms"], 0.0)
        self.assertEqual(stats["query_latency_ms"], 0.0)
        self.assertEqual(stats["hit_rate"], 0.0)

    def test_stats_metrics(self):
        self.mlog.log_save(store="s", memory_id="1", latency_ms=10.0)
        self.mlog.log_save(store="s", memory_id="2", latency_ms=20.0)
        self.mlog.log_query(store="s", latency_ms=5.0, hit_count=2)
        self.mlog.log_query(store="s", latency_ms=15.0, hit_count=0)
        self.mlog.log_fail(store="s", action="save", status="denied", error="无权限")
        stats = self.mlog.stats()
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["save_count"], 2)
        self.assertEqual(stats["query_count"], 2)
        self.assertEqual(stats["memory_count"], 2)
        self.assertEqual(stats["save_latency_ms"], 15.0)
        self.assertEqual(stats["query_latency_ms"], 10.0)
        self.assertEqual(stats["hit_rate"], 50.0)
        self.assertEqual(stats["fail"], 1)

    def test_clear(self):
        self.mlog.log_save(store="s", memory_id="1", latency_ms=1.0)
        n = self.mlog.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.mlog.count(), 0)

    def test_save_to_file(self):
        self.mlog.log_save(store="s", memory_id="1", latency_ms=1.0)
        self.mlog.log_query(store="s", latency_ms=1.0, hit_count=1)
        tmp = tempfile.mktemp(suffix=".jsonl")
        try:
            n = self.mlog.save_to_file(tmp)
            self.assertEqual(n, 2)
            with open(tmp, "r", encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_max_entries(self):
        mlog = MemoryLogger(max_entries=5, enable_logging=False)
        for i in range(10):
            mlog.log_save(store="s", memory_id=str(i), latency_ms=1.0)
        self.assertEqual(mlog.count(), 5)


if __name__ == "__main__":
    unittest.main()
