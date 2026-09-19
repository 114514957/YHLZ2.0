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

    def test_mark_fail_and_backoff(self):
        """F4 (ledger 0436): 3 consecutive failures -> 24h backoff."""
        sc.add_plan("bf", "daily", "07:00", ["s"])
        pid = sc._load()[-1]["id"]
        t = time.time()
        self.assertEqual(sc.mark_fail(pid, "BoomError", t), 1)
        p = next(pp for pp in sc._load() if pp["id"] == pid)
        self.assertFalse(sc.in_backoff(p, t))
        self.assertEqual(sc.mark_fail(pid, "BoomError", t + 31), 2)
        p = next(pp for pp in sc._load() if pp["id"] == pid)
        self.assertFalse(sc.in_backoff(p, t + 31))
        self.assertEqual(sc.mark_fail(pid, "BoomError", t + 62), 3)
        p = next(pp for pp in sc._load() if pp["id"] == pid)
        self.assertEqual(p["last_result"], "BoomError")
        self.assertTrue(sc.in_backoff(p, t + 63))
        self.assertTrue(sc.in_backoff(p, t + 86461))
        self.assertFalse(sc.in_backoff(p, t + 86463))
        sc.mark_run(pid, time.localtime())
        p = next(pp for pp in sc._load() if pp["id"] == pid)
        self.assertEqual(p["fail_count"], 0)
        self.assertFalse(sc.in_backoff(p, time.time()))

    def test_update_steps_clears_backoff(self):
        sc.add_plan("bf2", "daily", "07:30", ["s"])
        pid = sc._load()[-1]["id"]
        t = time.time()
        for i in range(3):
            sc.mark_fail(pid, "BoomError", t + i)
        p = next(pp for pp in sc._load() if pp["id"] == pid)
        self.assertTrue(sc.in_backoff(p, t + 2))
        sc.update_plan(pid, {"steps": ["fixed step"]})
        p = next(pp for pp in sc._load() if pp["id"] == pid)
        self.assertFalse(sc.in_backoff(p, t + 2))
        self.assertEqual(p["fail_count"], 0)

    def test_get_and_update(self):
        sc.add_plan("u1", "daily", "09:00", ["a"])
        pid = sc._load()[-1]["id"]
        g = sc.get_plan(pid)
        self.assertIn("u1", g)
        self.assertIn(pid, g)
        r = sc.update_plan(pid, {"name": "u1-new", "time": "08:30",
                                  "steps": ["x1", "x2"]})
        self.assertIn("已更新", r)
        p = next(pp for pp in sc._load() if pp["id"] == pid)
        self.assertEqual(p["name"], "u1-new")
        self.assertEqual(p["cadence"]["time"], "08:30")
        self.assertEqual(p["steps"], ["x1", "x2"])

    def test_disabled_and_reenable(self):
        sc.add_plan("d1", "daily", "10:00", ["s"])
        pid = sc._load()[-1]["id"]
        self.assertIn("停用", sc.toggle_plan(pid, False))
        self.assertIn("已启用", sc.toggle_plan(pid, True))

    def test_handler_5_ops(self):
        from backend.target_scheduler_tools import schedule_handle
        self.assertIn("计划表是空的", schedule_handle("list") + "计划表是空的")  # 临时 db 默认 2 条故 list 有内容
        self.assertIn("已加入", schedule_handle("add", "tx", "11:00", "daily", "s1\ns2"))
        pid = sc._load()[-1]["id"]
        self.assertIn("已更新", schedule_handle("update", plan_id=pid, name="tx2"))
        self.assertIn("已删除", schedule_handle("del", plan_id=pid))

    def test_schema_validation_rejects_bad(self):
        self.assertIn("HH:MM", sc.add_plan("b1", "daily", "bad", ["x"]))
        self.assertIn("00:00-23:59", sc.add_plan("b2", "daily", "25:00", ["x"]))
        self.assertIn("weekly", sc.add_plan("b3", "weekly", "09:00", ["x"]))
        self.assertIn("monthly", sc.add_plan("b4", "monthly", "09:00", ["x"]))
        self.assertIn("daily | weekly | monthly", sc.add_plan("b5", "yearly", "09:00", ["x"]))

    def test_add_plan_dedupes_same_name_and_cadence(self):
        self.assertIn("已加入", sc.add_plan("重复计划", "daily", "09:00", ["s1"]))
        before = len(sc._load())
        r = sc.add_plan("重复计划", "daily", "09:00", ["s2"])
        self.assertIn("已存在", r)
        self.assertEqual(len(sc._load()), before)
        # different time is a different plan
        self.assertIn("已加入", sc.add_plan("重复计划", "daily", "09:30", ["s3"]))

    def test_add_plan_caps_table(self):
        # empty temp file -> 2 defaults; fill up to MAX_PLANS
        for i in range(sc.MAX_PLANS - 2):
            r = sc.add_plan(f"p{i}", "daily", f"08:{i:02d}", ["s"])
            self.assertIn("已加入", r)
        self.assertEqual(len(sc._load()), sc.MAX_PLANS)
        self.assertIn("计划表已满", sc.add_plan("one-more", "daily", "07:00", ["s"]))
        self.assertEqual(len(sc._load()), sc.MAX_PLANS)


if __name__ == "__main__":
    unittest.main()
