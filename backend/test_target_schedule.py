"""Schedule cadence tests (ledger 0209)."""
import tempfile
import time
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backend.target_schedule as sc  # noqa: E402


def _st(y, m, d, hh, mm, wd):
    return time.struct_time((y, m, d, hh, mm, 0, wd, 1, -1))


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._f = sc.SCHED_FILE
        self._m = sc.MIRROR_FILE
        sc.SCHED_FILE = self.tmp / "sched.json"
        sc.MIRROR_FILE = self.tmp / "plan.md"

    def tearDown(self):
        sc.SCHED_FILE = self._f
        sc.MIRROR_FILE = self._m

    def test_add_list_delete(self):
        r = sc.add_plan("知识整合", "weekly", "10:00", ["跑主题总结", "整理知识库"],
                        weekday=6)
        self.assertIn("已加入", r)
        plans = sc._load()
        self.assertEqual(len(plans), 3)  # 2 defaults + 1
        pid = plans[-1]["id"]
        txt = sc.list_plans()
        self.assertIn("知识整合", txt)
        self.assertIn("已删除", sc.delete_plan(pid))
        self.assertEqual(len(sc._load()), 2)

    def test_is_due_daily(self):
        p = {"cadence": {"type": "daily", "time": "13:00"}}
        self.assertFalse(sc.is_due(p, _st(2026, 9, 7, 12, 0, 0), ""))
        self.assertTrue(sc.is_due(p, _st(2026, 9, 7, 14, 0, 0), ""))
        self.assertFalse(sc.is_due(p, _st(2026, 9, 7, 14, 0, 0),
                                  "2026-09-07 13:01"))

    def test_is_due_weekly(self):
        # sunday (wd=6) weekly 09:00
        p = {"cadence": {"type": "weekly", "time": "09:00", "weekday": 6}}
        self.assertTrue(sc.is_due(p, _st(2026, 9, 6, 10, 0, 6), ""))   # sunday
        self.assertFalse(sc.is_due(p, _st(2026, 9, 7, 10, 0, 0), ""))  # monday no
        self.assertFalse(sc.is_due(p, _st(2026, 9, 6, 10, 0, 6),
                                   "2026-09-06 09:05"))  # ran this very week -> not due
        # ran previous week (8/30 sunday) -> new week -> due
        self.assertTrue(sc.is_due(p, _st(2026, 9, 6, 10, 0, 6),
                                  "2026-08-30 09:05"))

    def test_is_due_monthly(self):
        p = {"cadence": {"type": "monthly", "time": "10:00", "day": 7}}
        self.assertTrue(sc.is_due(p, _st(2026, 9, 7, 11, 0, 0), ""))
        self.assertFalse(sc.is_due(p, _st(2026, 9, 8, 11, 0, 0), ""))
        self.assertFalse(sc.is_due(p, _st(2026, 9, 7, 11, 0, 0),
                                   "2026-09-07 10:01"))
        self.assertTrue(sc.is_due(p, _st(2026, 10, 7, 11, 0, 0),
                                  "2026-09-07 10:01"))  # new month -> due

    def test_mark_run(self):
        sc.add_plan("x", "daily", "08:00", ["s"])
        plans = sc._load()
        pid = plans[-1]["id"]
        sc.mark_run(pid, time.localtime())
        plans = sc._load()
        self.assertTrue(plans[-1]["last_run"])


if __name__ == "__main__":
    unittest.main()
