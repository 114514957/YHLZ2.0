"""
YHLZ Embodied AI V4.1 - 具身日志系统单元测试

覆盖:
    - 目标事件 (start / success / fail)
    - 观察事件
    - 动作事件 (start / success / fail)
    - 异常 / 取消事件
    - 查询 (按事件 / 类型 / 状态过滤)
    - 统计指标 (目标成功率 / 动作成功率 / 平均耗时 / 异常数)
    - JSONL 落盘 / 清空 / 上限
"""
import os
import tempfile
import unittest

from backend.embodied.logger import EmbodiedLogEntry, EmbodiedLogger


class TestLoggerEvents(unittest.TestCase):

    def setUp(self):
        self.elog = EmbodiedLogger(max_entries=100, enable_logging=False)

    def test_goal_start(self):
        e = self.elog.log_goal_start(goal_id="g1", intent="扫描")
        self.assertEqual(e.event, "goal_start")
        self.assertEqual(e.goal_id, "g1")

    def test_goal_success(self):
        e = self.elog.log_goal_success(goal_id="g1", iterations=2, latency_ms=5.0)
        self.assertEqual(e.event, "goal_success")
        self.assertEqual(e.status, "ok")
        self.assertEqual(e.metadata["iterations"], 2)

    def test_goal_fail(self):
        e = self.elog.log_goal_fail(goal_id="g1", status="denied", error="被拒绝")
        self.assertEqual(e.event, "goal_fail")
        self.assertEqual(e.error, "被拒绝")

    def test_observe(self):
        e = self.elog.log_observe(environment="mock", objects=4, latency_ms=1.0)
        self.assertEqual(e.event, "observe")
        self.assertEqual(e.metadata["objects"], 4)

    def test_action_start(self):
        e = self.elog.log_action_start(action_id="a1", action_type="scan")
        self.assertEqual(e.event, "action_start")

    def test_action_success(self):
        e = self.elog.log_action_success(
            action_id="a1", action_type="move", latency_ms=2.5,
        )
        self.assertEqual(e.event, "action_success")
        self.assertEqual(e.latency_ms, 2.5)

    def test_action_fail(self):
        e = self.elog.log_action_fail(
            action_id="a1", action_type="pick", status="error", error="越界",
        )
        self.assertEqual(e.event, "action_fail")
        self.assertEqual(e.error, "越界")

    def test_exception(self):
        e = self.elog.log_exception(error="boom", action_type="move")
        self.assertEqual(e.event, "exception")

    def test_cancel(self):
        e = self.elog.log_cancel(action_id="a1")
        self.assertEqual(e.event, "cancel")
        self.assertEqual(e.status, "cancelled")


class TestLoggerQuery(unittest.TestCase):

    def setUp(self):
        self.elog = EmbodiedLogger(enable_logging=False)
        self.elog.log_action_success(action_id="a1", action_type="scan")
        self.elog.log_action_fail(action_id="a2", action_type="pick", status="error", error="x")
        self.elog.log_goal_success(goal_id="g1", iterations=1)
        self.elog.log_observe(environment="mock", objects=4)

    def test_query_all_latest_first(self):
        events = [e.event for e in self.elog.query()]
        self.assertEqual(events, ["observe", "goal_success", "action_fail", "action_success"])

    def test_query_by_event(self):
        events = self.elog.query(event="action_success")
        self.assertEqual(len(events), 1)

    def test_query_by_action_type(self):
        events = self.elog.query(action_type="pick")
        self.assertEqual(len(events), 1)

    def test_query_by_status(self):
        events = self.elog.query(status="error")
        self.assertEqual(len(events), 1)

    def test_query_limit(self):
        self.assertEqual(len(self.elog.query(limit=2)), 2)

    def test_query_dicts(self):
        d = self.elog.query_dicts(event="observe")
        self.assertEqual(d[0]["event"], "observe")
        self.assertEqual(d[0]["metadata"]["environment"], "mock")

    def test_entry_to_dict(self):
        e = EmbodiedLogEntry(event="test", goal_id="g1")
        d = e.to_dict()
        self.assertEqual(d["event"], "test")
        self.assertIn("latency_ms", d)


class TestLoggerStats(unittest.TestCase):

    def test_empty_stats(self):
        st = EmbodiedLogger(enable_logging=False).stats()
        self.assertEqual(st["total"], 0)
        self.assertEqual(st["goal_success_rate"], 0.0)
        self.assertEqual(st["action_success_rate"], 0.0)

    def test_stats_mixed(self):
        elog = EmbodiedLogger(enable_logging=False)
        elog.log_goal_success(goal_id="g1", iterations=2, latency_ms=10.0)
        elog.log_goal_fail(goal_id="g2", status="error", error="x")
        elog.log_action_success(action_id="a1", action_type="scan", latency_ms=2.0)
        elog.log_action_success(action_id="a2", action_type="scan", latency_ms=4.0)
        elog.log_action_fail(action_id="a3", action_type="pick", status="error", error="x", latency_ms=6.0)
        elog.log_observe(environment="mock", objects=4)
        elog.log_exception(error="boom")
        st = elog.stats()
        self.assertEqual(st["goal_count"], 2)
        self.assertEqual(st["goal_success_rate"], 0.5)
        self.assertEqual(st["action_count"], 3)
        self.assertEqual(st["action_success_rate"], round(2 / 3, 4))
        self.assertEqual(st["avg_action_latency_ms"], 4.0)
        self.assertEqual(st["observe_count"], 1)
        self.assertEqual(st["exception_count"], 1)

    def test_clear(self):
        elog = EmbodiedLogger(enable_logging=False)
        elog.log_observe(environment="mock", objects=1)
        n = elog.clear()
        self.assertEqual(n, 1)
        self.assertEqual(elog.count(), 0)

    def test_max_entries_cap(self):
        elog = EmbodiedLogger(max_entries=3, enable_logging=False)
        for i in range(5):
            elog.log_observe(environment="mock", objects=i)
        self.assertEqual(elog.count(), 3)

    def test_save_to_file(self):
        elog = EmbodiedLogger(enable_logging=False)
        elog.log_action_success(action_id="a1", action_type="scan")
        path = os.path.join(tempfile.gettempdir(), "embodied_log_test.jsonl")
        n = elog.save_to_file(path)
        self.assertEqual(n, 1)
        self.assertGreater(os.path.getsize(path), 0)
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
