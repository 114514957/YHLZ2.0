"""
YHLZ Personality Engine V3.4 - Logger 单元测试

覆盖:
    - log_start / log_success / log_fail / log_exception
    - query 过滤 / 最新优先
    - stats 性能指标 (load_latency / switch_latency / consistency_score / profile_count)
    - clear / count / save_to_file
"""
import os
import tempfile
import unittest

from backend.personality.logger import PersonalityLogEntry, PersonalityLogger


class TestPersonalityLogger(unittest.TestCase):

    def setUp(self):
        self.plog = PersonalityLogger(enable_logging=False)

    def test_log_start(self):
        e = self.plog.log_start(store="memory", action="switch")
        self.assertEqual(e.event, "start")
        self.assertEqual(e.action, "switch")
        self.assertEqual(self.plog.count(), 1)

    def test_log_success(self):
        e = self.plog.log_success(
            store="memory", action="save", profile_id="p1",
            profile_name="人格", latency_ms=2.5, consistency=0.9,
        )
        self.assertEqual(e.event, "success")
        self.assertEqual(e.status, "ok")
        self.assertEqual(e.consistency, 0.9)

    def test_log_fail(self):
        e = self.plog.log_fail(
            store="memory", action="save", status="denied",
            error="无权限", latency_ms=1.0,
        )
        self.assertEqual(e.event, "fail")
        self.assertEqual(e.status, "denied")
        self.assertEqual(e.error, "无权限")

    def test_log_exception(self):
        e = self.plog.log_exception(store="memory", action="save", error="异常")
        self.assertEqual(e.event, "exception")

    def test_query_filters(self):
        self.plog.log_success(store="memory", action="save", profile_id="a")
        self.plog.log_fail(store="sqlite", action="save", status="error", error="e")
        self.plog.log_success(store="memory", action="switch", profile_id="b")
        self.assertEqual(len(self.plog.query(action="save")), 2)
        self.assertEqual(len(self.plog.query(store="memory")), 2)
        self.assertEqual(len(self.plog.query(status="ok")), 2)
        self.assertEqual(len(self.plog.query(event="fail")), 1)

    def test_query_newest_first(self):
        self.plog.log_success(store="memory", action="save", profile_id="first")
        self.plog.log_success(store="memory", action="save", profile_id="second")
        entries = self.plog.query(action="save")
        self.assertEqual(entries[0].profile_id, "second")

    def test_query_limit(self):
        for i in range(5):
            self.plog.log_success(store="memory", action="save", profile_id=f"p{i}")
        self.assertEqual(len(self.plog.query(limit=2)), 2)

    def test_stats_empty(self):
        st = self.plog.stats()
        self.assertEqual(st["total"], 0)
        self.assertEqual(st["success_rate"], 0.0)

    def test_stats_metrics(self):
        self.plog.log_success(store="memory", action="load", latency_ms=3.0)
        self.plog.log_success(store="memory", action="load", latency_ms=1.0)
        self.plog.log_success(store="memory", action="switch", latency_ms=4.0)
        self.plog.log_success(store="memory", action="save", profile_id="p1")
        self.plog.log_success(store="memory", action="assess", consistency=0.85)
        self.plog.log_fail(store="memory", action="save", status="denied", error="x")
        st = self.plog.stats()
        self.assertEqual(st["total"], 6)
        self.assertEqual(st["fail"], 1)
        self.assertEqual(st["load_latency_ms"], 2.0)
        self.assertEqual(st["switch_latency_ms"], 4.0)
        self.assertEqual(st["consistency_score"], 0.85)
        self.assertEqual(st["profile_count"], 1)
        self.assertEqual(st["load_count"], 2)
        self.assertEqual(st["switch_count"], 1)

    def test_clear(self):
        self.plog.log_success(store="memory", action="save")
        self.plog.log_success(store="memory", action="save")
        n = self.plog.clear()
        self.assertEqual(n, 2)
        self.assertEqual(self.plog.count(), 0)

    def test_max_entries(self):
        plog = PersonalityLogger(max_entries=5, enable_logging=False)
        for i in range(10):
            plog.log_success(store="memory", action="save", profile_id=f"p{i}")
        self.assertEqual(plog.count(), 5)

    def test_save_to_file(self):
        self.plog.log_success(store="memory", action="save", profile_id="p1")
        tmp = tempfile.mkdtemp(prefix="yhlz_personality_log_")
        path = os.path.join(tmp, "log.jsonl")
        n = self.plog.save_to_file(path)
        self.assertEqual(n, 1)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            line = f.readline().strip()
        self.assertIn('"profile_id": "p1"', line)


class TestPersonalityLogEntry(unittest.TestCase):

    def test_to_dict(self):
        e = PersonalityLogEntry(
            event="success", store="memory", action="save",
            profile_id="p1", profile_name="人格", latency_ms=2.0,
            status="ok", consistency=0.9, error=None,
        )
        d = e.to_dict()
        self.assertEqual(d["profile_id"], "p1")
        self.assertEqual(d["consistency"], 0.9)
        self.assertEqual(d["status"], "ok")


if __name__ == "__main__":
    unittest.main()
