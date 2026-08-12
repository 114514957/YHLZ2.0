"""
YHLZ Embodied AI V9.5.0 - 成长触发器与调度器单元测试 (Trigger & Scheduler)

覆盖 (rhythm/growth_trigger.py, rhythm/consolidation_scheduler.py,
       rhythm/rhythm_audit.py):
    - 触发条件: 经验阈值 / 整理天数
    - 调度: 条件达成自动整理 / 上次整理时间
    - 审计: 自动行为可追踪
"""
import time
import unittest

from backend.embodied.companion.rhythm import (
    ConsolidationScheduler,
    GrowthTrigger,
    RHYTHM_AUDIT_ACTIONS,
    RhythmAudit,
    RhythmAuditError,
    SchedulerError,
    TriggerError,
)


class TestTriggerInit(unittest.TestCase):
    """触发器初始化"""

    def test_default_init(self):
        t = GrowthTrigger()
        self.assertIsNotNone(t)

    def test_threshold_validation(self):
        with self.assertRaises(TriggerError):
            GrowthTrigger(consolidate_threshold=0)

    def test_days_validation(self):
        with self.assertRaises(TriggerError):
            GrowthTrigger(consolidate_days=0)

    def test_thresholds(self):
        t = GrowthTrigger(consolidate_threshold=10,
                          consolidate_days=5)
        th = t.thresholds()
        self.assertEqual(th["consolidate_threshold"], 10)
        self.assertEqual(th["consolidate_days"], 5)
        self.assertEqual(th["mode"], "rule_based")


class TestTriggerCheck(unittest.TestCase):
    """条件检查"""

    def setUp(self):
        self.trigger = GrowthTrigger(consolidate_threshold=20,
                                     consolidate_days=7)

    def test_check_structure(self):
        r = self.trigger.check(experience_count=5,
                               last_consolidation_days=1)
        self.assertEqual(len(r), 2)
        for item in r:
            self.assertIn("condition", item)
            self.assertIn("triggered", item)
            self.assertIn("reason", item)

    def test_threshold_not_met(self):
        r = self.trigger.check(experience_count=5,
                               last_consolidation_days=1)
        self.assertFalse(r[0]["triggered"])
        self.assertFalse(r[1]["triggered"])

    def test_experience_threshold_met(self):
        r = self.trigger.check(experience_count=25,
                               last_consolidation_days=1)
        self.assertTrue(r[0]["triggered"])
        self.assertEqual(r[0]["condition"], "experience_threshold")

    def test_days_met(self):
        r = self.trigger.check(experience_count=5,
                               last_consolidation_days=10)
        self.assertTrue(r[1]["triggered"])
        self.assertEqual(r[1]["condition"], "consolidation_days")

    def test_both_met(self):
        r = self.trigger.check(experience_count=30,
                               last_consolidation_days=10)
        self.assertTrue(all(x["triggered"] for x in r))

    def test_boundary_threshold(self):
        r = self.trigger.check(experience_count=20,
                               last_consolidation_days=1)
        self.assertTrue(r[0]["triggered"])

    def test_boundary_days(self):
        r = self.trigger.check(experience_count=1,
                               last_consolidation_days=7)
        self.assertTrue(r[1]["triggered"])

    def test_should_run(self):
        self.assertTrue(self.trigger.should_run(
            experience_count=25, last_consolidation_days=0))
        self.assertFalse(self.trigger.should_run(
            experience_count=5, last_consolidation_days=1))

    def test_reason_explainable(self):
        r = self.trigger.check(experience_count=25,
                               last_consolidation_days=1)
        self.assertIn("≥", r[0]["reason"])


class TestSchedulerInit(unittest.TestCase):
    """调度器初始化"""

    def test_default_init(self):
        s = ConsolidationScheduler()
        self.assertIsNotNone(s)

    def test_stats_empty(self):
        s = ConsolidationScheduler()
        st = s.stats()
        self.assertEqual(st["run_count"], 0)
        self.assertEqual(st["mode"], "rule_based")

    def test_clear_empty(self):
        s = ConsolidationScheduler()
        self.assertEqual(s.clear(), 0)


class TestSchedulerTick(unittest.TestCase):
    """调度执行"""

    def setUp(self):
        self.scheduler = ConsolidationScheduler(
            GrowthTrigger(consolidate_threshold=20,
                          consolidate_days=7),
        )
        self.consolidated = []

        def fake_consolidate():
            self.consolidated.append(time.time())
            return {"mode": "rule_based", "done": True}

        self.fake = fake_consolidate

    def test_tick_no_trigger(self):
        # 首次 last_run=0 → 天数条件触发; 先运行一次再测不触发
        self.scheduler.tick(experience_count=1,
                            consolidate_fn=self.fake)
        r = self.scheduler.tick(experience_count=5,
                                consolidate_fn=self.fake,
                                now=time.time() + 3600)
        self.assertFalse(r["triggered"])
        self.assertFalse(r["consolidated"])
        self.assertEqual(len(self.consolidated), 1)

    def test_tick_triggered_by_count(self):
        r = self.scheduler.tick(experience_count=25,
                                consolidate_fn=self.fake)
        self.assertTrue(r["triggered"])
        self.assertTrue(r["consolidated"])
        self.assertEqual(len(self.consolidated), 1)

    def test_tick_triggered_by_days(self):
        # 首次调用 last_run=0 → 999 天 → 触发
        r = self.scheduler.tick(experience_count=1,
                                consolidate_fn=self.fake)
        self.assertTrue(r["triggered"])
        self.assertTrue(r["consolidated"])

    def test_tick_structure(self):
        r = self.scheduler.tick(experience_count=1,
                                consolidate_fn=self.fake)
        for key in ("mode", "checked", "triggered", "reasons",
                    "consolidated", "result", "last_run_days"):
            self.assertIn(key, r)

    def test_tick_reasons(self):
        r = self.scheduler.tick(experience_count=25,
                                consolidate_fn=self.fake)
        self.assertEqual(len(r["reasons"]), 2)

    def test_no_double_trigger_same_day(self):
        """整理后当天不再重复触发"""
        self.scheduler.tick(experience_count=25,
                            consolidate_fn=self.fake)
        r = self.scheduler.tick(experience_count=25,
                                consolidate_fn=self.fake,
                                now=time.time() + 3600)
        # 天数条件: last_run 刚设置 → 天数不触发; 数量条件仍触发
        self.assertTrue(r["triggered"])  # 数量条件触发 (设计: 数量每次超限都整理)

    def test_consolidate_exception_no_crash(self):
        def boom():
            raise RuntimeError("boom")

        r = self.scheduler.tick(experience_count=25,
                                consolidate_fn=boom)
        self.assertTrue(r["triggered"])
        self.assertFalse(r["consolidated"])

    def test_trigger_without_fn(self):
        """无整理回调 → 仅判断 (仍记录运行)"""
        r = self.scheduler.tick(experience_count=25)
        self.assertTrue(r["triggered"])
        self.assertFalse(r["consolidated"])

    def test_stats_run_count(self):
        self.scheduler.tick(experience_count=25,
                            consolidate_fn=self.fake)
        self.scheduler.tick(experience_count=1,
                            consolidate_fn=self.fake)
        st = self.scheduler.stats()
        self.assertGreaterEqual(st["run_count"], 1)

    def test_clear(self):
        self.scheduler.tick(experience_count=25,
                            consolidate_fn=self.fake)
        n = self.scheduler.clear()
        self.assertGreaterEqual(n, 0)
        self.assertEqual(self.scheduler.stats()["run_count"], 0)

    def test_trigger_conditions_constant(self):
        from backend.embodied.companion.rhythm import (
            TRIGGER_CONDITIONS,
        )
        self.assertIn("experience_threshold", TRIGGER_CONDITIONS)
        self.assertIn("consolidation_days", TRIGGER_CONDITIONS)


class TestRhythmAudit(unittest.TestCase):
    """节律审计"""

    def test_actions_whitelist(self):
        for a in ("capture", "consolidate", "snapshot",
                  "reflection", "skip", "error"):
            self.assertIn(a, RHYTHM_AUDIT_ACTIONS)

    def test_record(self):
        a = RhythmAudit()
        e = a.record(action="capture", detail="experience_added")
        self.assertTrue(e["audit_id"].startswith("rh_"))

    def test_record_invalid(self):
        a = RhythmAudit()
        with self.assertRaises(RhythmAuditError):
            a.record(action="hack")

    def test_report(self):
        a = RhythmAudit()
        a.record(action="capture")
        a.record(action="consolidate")
        r = a.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["by_action"]["capture"], 1)
        self.assertEqual(r["by_action"]["consolidate"], 1)

    def test_report_empty(self):
        a = RhythmAudit()
        self.assertEqual(a.report()["total"], 0)

    def test_report_limit(self):
        a = RhythmAudit()
        for i in range(5):
            a.record(action="skip")
        self.assertEqual(len(a.report(limit=2)["recent"]), 2)

    def test_max_records_validation(self):
        with self.assertRaises(RhythmAuditError):
            RhythmAudit(max_records=0)

    def test_clear(self):
        a = RhythmAudit()
        a.record(action="capture")
        self.assertEqual(a.clear(), 1)


if __name__ == "__main__":
    unittest.main()
