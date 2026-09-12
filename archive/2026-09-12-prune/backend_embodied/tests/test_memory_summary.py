"""
YHLZ Embodied AI V4.2 - 具身经验摘要单元测试 (Embodied Long-term Memory)

覆盖:
    - summary(): 行动统计 / 成功率
    - failure_patterns: 高频失败模式 (按 cause 聚合 + 示例)
    - success_trends: 成功率趋势 (时间桶)
    - cause_stats: 因果统计
    - top_failures: 失败示例
    - 空记忆 / 全成功 / 全失败边界
    - 跨进程持久化: load_or_init / save + load (embodied_memory_path 语义)
"""
import os
import tempfile
import unittest

from backend.embodied.world_model import EnvironmentMemory


class TestSummaryBasics(unittest.TestCase):

    def setUp(self):
        self.mem = EnvironmentMemory(max_entries=100)

    def test_empty_memory_summary(self):
        s = self.mem.summary()
        self.assertEqual(s.total_actions, 0)
        self.assertEqual(s.success_rate, 0.0)
        self.assertEqual(s.failure_patterns, [])
        self.assertEqual(s.cause_stats, {})

    def test_all_success(self):
        for i in range(10):
            self.mem.record_action(
                feedback={"action_id": f"a{i}", "result": "success"},
                analysis={"success": True, "cause": None},
            )
        s = self.mem.summary()
        self.assertEqual(s.total_actions, 10)
        self.assertEqual(s.success_count, 10)
        self.assertEqual(s.success_rate, 1.0)
        self.assertEqual(s.failure_patterns, [])

    def test_all_failure(self):
        for i in range(4):
            self.mem.record_action(
                feedback={"action_id": f"a{i}", "result": "failure"},
                analysis={"success": False, "cause": "position_mismatch"},
            )
        s = self.mem.summary()
        self.assertEqual(s.total_actions, 4)
        self.assertEqual(s.success_rate, 0.0)
        self.assertEqual(s.failure_patterns[0]["cause"], "position_mismatch")
        self.assertEqual(s.failure_patterns[0]["count"], 4)

    def test_mixed_rate(self):
        for i in range(3):
            self.mem.record_action(feedback={"result": "success"}, analysis={})
        self.mem.record_action(feedback={"result": "failure"}, analysis={})
        s = self.mem.summary()
        self.assertEqual(s.total_actions, 4)
        self.assertEqual(s.success_count, 3)
        self.assertAlmostEqual(s.success_rate, 0.75)


class TestSummaryPatterns(unittest.TestCase):

    def setUp(self):
        self.mem = EnvironmentMemory(max_entries=100)

    def test_failure_patterns_sorted_by_count(self):
        self.mem.record_action(
            feedback={"action_id": "a1", "result": "failure", "error": "越界"},
            analysis={"cause": "boundary_limit"},
        )
        self.mem.record_action(
            feedback={"action_id": "a2", "result": "failure", "error": "越界"},
            analysis={"cause": "boundary_limit"},
        )
        self.mem.record_action(
            feedback={"action_id": "a3", "result": "failure", "error": "不在"},
            analysis={"cause": "position_mismatch"},
        )
        s = self.mem.summary()
        self.assertEqual(s.failure_patterns[0]["cause"], "boundary_limit")
        self.assertEqual(s.failure_patterns[0]["count"], 2)
        self.assertEqual(len(s.failure_patterns), 2)

    def test_failure_pattern_example(self):
        self.mem.record_action(
            feedback={"action_id": "a1", "result": "failure", "error": "对象不存在: ghost"},
            analysis={"cause": "object_missing", "failure_reason": "对象不存在"},
        )
        s = self.mem.summary()
        pattern = s.failure_patterns[0]
        self.assertEqual(pattern["cause"], "object_missing")
        self.assertTrue(pattern["example"])

    def test_cause_stats(self):
        self.mem.record_action(
            feedback={"result": "success"}, analysis={"cause": None},
        )
        self.mem.record_action(
            feedback={"result": "failure"}, analysis={"cause": "boundary_limit"},
        )
        self.mem.record_action(
            feedback={"result": "failure"}, analysis={"cause": "boundary_limit"},
        )
        s = self.mem.summary()
        self.assertEqual(s.cause_stats["boundary_limit"], 2)
        self.assertIn("no_cause", s.cause_stats)

    def test_top_failures(self):
        for i in range(8):
            self.mem.record_action(
                feedback={"action_id": f"f{i}", "result": "failure"},
                analysis={"cause": "unknown", "failure_reason": f"err{i}"},
            )
        s = self.mem.summary(top_failures=3)
        self.assertEqual(len(s.top_failures), 3)
        self.assertEqual(s.top_failures[0]["action_id"], "f7")


class TestSummaryTrends(unittest.TestCase):

    def setUp(self):
        self.mem = EnvironmentMemory(max_entries=100)

    def test_trend_buckets(self):
        # 前 5 次成功, 后 5 次失败 → 两个桶
        for i in range(5):
            self.mem.record_action(
                feedback={"action_id": f"s{i}", "result": "success"}, analysis={},
            )
        for i in range(5):
            self.mem.record_action(
                feedback={"action_id": f"f{i}", "result": "failure"}, analysis={},
            )
        s = self.mem.summary(trend_bucket_size=5)
        self.assertEqual(len(s.success_trends), 2)
        oldest, newest = s.success_trends[0], s.success_trends[1]
        self.assertEqual(oldest["success_rate"], 1.0)
        self.assertEqual(newest["success_rate"], 0.0)

    def test_trend_single_bucket(self):
        self.mem.record_action(feedback={"result": "success"}, analysis={})
        self.mem.record_action(feedback={"result": "success"}, analysis={})
        s = self.mem.summary(trend_bucket_size=10)
        self.assertEqual(len(s.success_trends), 1)
        self.assertEqual(s.success_trends[0]["success_rate"], 1.0)

    def test_trend_bucket_size_zero_guard(self):
        self.mem.record_action(feedback={"result": "success"}, analysis={})
        s = self.mem.summary(trend_bucket_size=0)
        self.assertEqual(len(s.success_trends), 1)


class TestCrossProcessPersistence(unittest.TestCase):
    """V4.2: embodied_memory_path 跨进程加载语义"""

    def _tmp_path(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        return path

    def test_save_then_load_new_instance(self):
        path = self._tmp_path()
        try:
            mem1 = EnvironmentMemory()
            mem1.record_action(
                feedback={"action_id": "x1", "result": "failure"},
                analysis={"cause": "position_mismatch"},
            )
            mem1.save_to_file(path)

            mem2 = EnvironmentMemory()
            mem2.load_or_init(path)
            self.assertEqual(mem2.count(), 1)
            s = mem2.summary()
            self.assertEqual(s.failure_patterns[0]["cause"], "position_mismatch")
        finally:
            os.remove(path)

    def test_load_or_init_missing_path_silent(self):
        mem = EnvironmentMemory()
        mem.load_or_init("nonexistent_embodied_memory.jsonl")  # 不应抛异常
        self.assertEqual(mem.count(), 0)

    def test_load_or_init_none_path(self):
        mem = EnvironmentMemory()
        mem.load_or_init(None)
        mem.load_or_init("")
        self.assertEqual(mem.count(), 0)

    def test_load_or_init_appends(self):
        path = self._tmp_path()
        try:
            mem1 = EnvironmentMemory()
            mem1.record_action(feedback={"result": "success"}, analysis={})
            mem1.save_to_file(path)

            mem2 = EnvironmentMemory()
            mem2.record_action(feedback={"result": "failure"}, analysis={})
            mem2.load_or_init(path)
            s = mem2.summary()
            self.assertEqual(s.total_actions, 2)
            self.assertEqual(s.success_rate, 0.5)
        finally:
            os.remove(path)

    def test_cross_process_trend_preserved(self):
        path = self._tmp_path()
        try:
            mem1 = EnvironmentMemory()
            for i in range(6):
                mem1.record_action(feedback={"result": "success"}, analysis={})
            mem1.save_to_file(path)

            mem2 = EnvironmentMemory()
            mem2.load_or_init(path)
            s = mem2.summary(trend_bucket_size=3)
            self.assertEqual(s.total_actions, 6)
            self.assertEqual(len(s.success_trends), 2)
        finally:
            os.remove(path)


class TestSummarySerialization(unittest.TestCase):

    def test_summary_to_dict(self):
        mem = EnvironmentMemory()
        mem.record_action(
            feedback={"result": "failure"}, analysis={"cause": "x"},
        )
        s = mem.summary()
        d = s.to_dict()
        self.assertIn("total_actions", d)
        self.assertIn("success_rate", d)
        self.assertIn("failure_patterns", d)
        self.assertIn("success_trends", d)
        self.assertIn("cause_stats", d)
        self.assertIn("top_failures", d)

    def test_summary_roundtrip(self):
        mem = EnvironmentMemory()
        mem.record_action(feedback={"result": "success"}, analysis={})
        s = mem.summary()
        d = s.to_dict()
        restored = s.__class__.from_dict(d) if hasattr(s.__class__, "from_dict") else s
        self.assertEqual(restored.total_actions, s.total_actions)
        self.assertEqual(restored.success_rate, s.success_rate)


if __name__ == "__main__":
    unittest.main()
