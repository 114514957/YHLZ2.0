"""
YHLZ Vision Action V1.0 - Logger 单元测试

覆盖:
    - log_start / log_success / log_fail / log_cancel / log_exception
    - query 过滤 / 最新优先
    - stats 指标: action_count / success_rate / approval_rate / execution_latency / failure_rate
    - clear / count / save_to_file
"""
import os
import tempfile
import unittest

from backend.action.logger import ActionLogEntry, ActionLogger


class TestActionLogger(unittest.TestCase):

    def setUp(self):
        self.alog = ActionLogger(enable_logging=False)

    def test_log_start(self):
        e = self.alog.log_start(action_id="a1", action_type="check")
        self.assertEqual(e.event, "start")
        self.assertEqual(e.action_type, "check")
        self.assertEqual(self.alog.count(), 1)

    def test_log_success(self):
        e = self.alog.log_success(action_id="a1", action_type="check", status="ok", latency_ms=2.5)
        self.assertEqual(e.event, "success")
        self.assertEqual(e.status, "ok")
        self.assertEqual(e.latency_ms, 2.5)

    def test_log_fail(self):
        e = self.alog.log_fail(action_id="a1", action_type="check", status="denied", error="无权限")
        self.assertEqual(e.event, "fail")
        self.assertEqual(e.status, "denied")
        self.assertEqual(e.error, "无权限")

    def test_log_cancel(self):
        e = self.alog.log_cancel(action_id="a1", action_type="check")
        self.assertEqual(e.event, "cancel")
        self.assertEqual(e.status, "cancelled")

    def test_log_exception(self):
        e = self.alog.log_exception(action_id="a1", action_type="check", error="异常")
        self.assertEqual(e.event, "exception")

    def test_query_filters(self):
        self.alog.log_success(action_id="a1", action_type="check", status="ok")
        self.alog.log_fail(action_id="a2", action_type="check", status="denied", error="x")
        self.alog.log_success(action_id="a3", action_type="report", status="ok")
        self.assertEqual(len(self.alog.query(action_type="check")), 2)
        self.assertEqual(len(self.alog.query(status="ok")), 2)
        self.assertEqual(len(self.alog.query(event="fail")), 1)

    def test_query_newest_first(self):
        self.alog.log_success(action_id="first", action_type="check", status="ok")
        self.alog.log_success(action_id="second", action_type="check", status="ok")
        entries = self.alog.query(action_type="check")
        self.assertEqual(entries[0].action_id, "second")

    def test_query_limit(self):
        for i in range(5):
            self.alog.log_success(action_id=f"a{i}", action_type="check", status="ok")
        self.assertEqual(len(self.alog.query(limit=2)), 2)

    def test_stats_empty(self):
        st = self.alog.stats()
        self.assertEqual(st["total"], 0)
        self.assertEqual(st["action_count"], 0)
        self.assertEqual(st["success_rate"], 0.0)

    def test_stats_metrics(self):
        # 4 次成功 ok
        for i in range(4):
            self.alog.log_success(action_id=f"ok{i}", action_type="check",
                                  status="ok", latency_ms=2.0)
        # 1 次 denied
        self.alog.log_fail(action_id="d1", action_type="check", status="denied", error="x")
        # 1 次 error
        self.alog.log_fail(action_id="e1", action_type="check", status="error", error="y")
        # 1 次 start + 1 次 cancel (不计入 attempts)
        self.alog.log_start(action_id="s1", action_type="check")
        self.alog.log_cancel(action_id="c1", action_type="check")

        st = self.alog.stats()
        self.assertEqual(st["action_count"], 6)          # 4 ok + 1 denied + 1 error
        self.assertEqual(st["ok_count"], 4)
        self.assertEqual(st["denied_count"], 1)
        self.assertEqual(st["success_rate"], round(4 / 6, 4))
        self.assertEqual(st["approval_rate"], round(5 / 6, 4))
        self.assertEqual(st["failure_rate"], round(2 / 6, 4))
        self.assertEqual(st["execution_latency_ms"], 2.0)
        self.assertEqual(st["cancel_count"], 1)

    def test_stats_only_start_events(self):
        self.alog.log_start(action_id="a1", action_type="check")
        st = self.alog.stats()
        self.assertEqual(st["action_count"], 0)

    def test_clear(self):
        self.alog.log_success(action_id="a1", action_type="check", status="ok")
        self.alog.log_success(action_id="a2", action_type="check", status="ok")
        n = self.alog.clear()
        self.assertEqual(n, 2)
        self.assertEqual(self.alog.count(), 0)

    def test_max_entries(self):
        alog = ActionLogger(max_entries=5, enable_logging=False)
        for i in range(10):
            alog.log_success(action_id=f"a{i}", action_type="check", status="ok")
        self.assertEqual(alog.count(), 5)

    def test_save_to_file(self):
        self.alog.log_success(action_id="a1", action_type="check", status="ok")
        tmp = tempfile.mkdtemp(prefix="yhlz_action_log_")
        path = os.path.join(tmp, "log.jsonl")
        n = self.alog.save_to_file(path)
        self.assertEqual(n, 1)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            line = f.readline().strip()
        self.assertIn('"action_id": "a1"', line)


class TestActionLogEntry(unittest.TestCase):

    def test_to_dict(self):
        e = ActionLogEntry(
            event="success", action_id="a1", action_type="check",
            status="ok", risk_level="low", latency_ms=2.0,
        )
        d = e.to_dict()
        self.assertEqual(d["action_id"], "a1")
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["risk_level"], "low")


if __name__ == "__main__":
    unittest.main()
