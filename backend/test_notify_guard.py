"""F5 notify dedupe/rate-limit tests (ledger 0436) + fail-closed 决策日志 (0496)."""
import json
import tempfile
import unittest
from pathlib import Path

from backend import notify_guard as ng


class NotifyGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _allow(self, kind, text, now, cooldown=3600, max_per_day=4):
        return ng.allow(kind, text, cooldown=cooldown, max_per_day=max_per_day,
                        now=now, state_file=self.tmp / "g.json")

    def test_duplicate_within_cooldown_blocked(self):
        t = 1_700_000_000.0
        self.assertTrue(self._allow("task", "完成：导出 QQ", t))
        self.assertFalse(self._allow("task", "完成：导出 QQ", t + 60))
        # whitespace-normalized near-duplicates count as the same notice
        self.assertFalse(self._allow("task", "完成： 导出　QQ", t + 60))
        self.assertTrue(self._allow("task", "另一件事", t + 61))

    def test_cooldown_expiry(self):
        t = 1_700_000_000.0
        self.assertTrue(self._allow("task", "X", t))
        self.assertFalse(self._allow("task", "X", t + 3599))
        self.assertTrue(self._allow("task", "X", t + 3601))

    def test_daily_cap(self):
        t = 1_700_000_000.0
        for i in range(3):
            self.assertTrue(self._allow("autonomy", f"想法{i}", t + i))
        self.assertFalse(self._allow("autonomy", "第四", t + 4, max_per_day=3))
        self.assertTrue(self._allow("autonomy", "明天", t + 86400))


class NotifyGuardFailClosedTest(unittest.TestCase):
    """0496: 坏掉的守卫必须丢通知（fail-closed），不能再 fail-open 刷屏。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # 用一个"文件"当父目录 → 状态文件与决策日志都写不进去
        self.blocker = self.tmp / "blocked"
        self.blocker.write_text("not a dir", encoding="utf-8")
        self.bad = self.blocker / "g.json"

    def test_fail_closed_on_bad_state_path(self):
        self.assertFalse(ng.allow("x", "y", now=1.0, state_file=self.bad))

    def test_fail_closed_reports_guard_error(self):
        ok, reason = ng.allow_ex("x", "y", now=1.0, state_file=self.bad)
        self.assertFalse(ok)
        self.assertEqual(reason, "guard_error")

    def test_corrupt_state_self_heals_not_guard_error(self):
        """状态文件只是内容坏了 → 当空账本，仍放行（否则一次坏文件永久静音）。"""
        p = self.tmp / "corrupt.json"
        p.write_text("{ not json", encoding="utf-8")
        ok, reason = ng.allow_ex("task", "X", now=1.0, state_file=p)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")


class NotifyGuardDecisionLogTest(unittest.TestCase):
    """0496: 每次决策留痕（供自主 tick / 工作台审计）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "g.json"

    def _ex(self, kind, text, now, cooldown=3600, max_per_day=4):
        return ng.allow_ex(kind, text, cooldown=cooldown, max_per_day=max_per_day,
                           now=now, state_file=self.state)

    def test_reasons_ok_duplicate_daily_cap(self):
        t = 1_700_000_000.0
        self.assertEqual(self._ex("task", "A", t), (True, "ok"))
        self.assertEqual(self._ex("task", "A", t + 1), (False, "duplicate"))
        self.assertEqual(self._ex("autonomy", "B", t, max_per_day=1), (True, "ok"))
        self.assertEqual(self._ex("autonomy", "C", t + 1, max_per_day=1),
                         (False, "daily_cap"))

    def test_log_records_every_decision_newest_first(self):
        t = 1_700_000_000.0
        self._ex("task", "A", t)
        self._ex("task", "A", t + 1)
        rows = ng.recent(limit=10, state_file=self.state)
        self.assertEqual([r["decision"] for r in rows], ["drop", "allow"])
        self.assertEqual([r["reason"] for r in rows], ["duplicate", "ok"])
        self.assertEqual(rows[0]["kind"], "task")
        self.assertTrue(rows[0]["time"])

    def test_log_is_bounded(self):
        t = 1_700_000_000.0
        for i in range(ng._MAX_DECISIONS + 15):
            self._ex("task", f"n{i}", t + i, cooldown=0.0)
        raw = json.loads((self.tmp / "notify_guard_decisions.json")
                         .read_text(encoding="utf-8"))
        self.assertEqual(len(raw), ng._MAX_DECISIONS)

    def test_recent_empty_when_no_log(self):
        self.assertEqual(ng.recent(state_file=self.tmp / "nope.json"), [])


if __name__ == "__main__":
    unittest.main()