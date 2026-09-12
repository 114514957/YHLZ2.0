"""
YHLZ Embodied AI V9.5.0 - 情绪记忆与边界补充测试 (Emotion Memory & Edge)

覆盖 (专项补足至 ≥250):
    - EmotionMemory 完整行为
    - EmotionAudit 环形上限
    - EmotionState 自定义基线 / floor
    - Scheduler 边界
    - Service 情绪全情境
    - 快照兼容细节
"""
import os
import shutil
import tempfile
import time
import unittest

from backend.embodied.companion.emotion import (
    EMOTION_BASELINE,
    EmotionAudit,
    EmotionMemory,
    EmotionState,
)
from backend.embodied.companion.rhythm import (
    ConsolidationScheduler,
    GrowthTrigger,
)
from backend.embodied.service import EmbodiedService


class TestMemoryDetailed(unittest.TestCase):
    """情绪记忆细节"""

    def test_memory_id_unique(self):
        m = EmotionMemory()
        e1 = m.record("success", {}, {}, "")
        e2 = m.record("success", {}, {}, "")
        self.assertNotEqual(e1["memory_id"], e2["memory_id"])

    def test_memory_keeps_impact(self):
        m = EmotionMemory()
        e = m.record("success", {"p": 0.5}, {"p": 0.6}, "原因",
                     impact={"p": 0.1})
        self.assertEqual(e["impact"]["p"], 0.1)

    def test_memory_by_event_empty(self):
        m = EmotionMemory()
        self.assertEqual(m.by_event("failure"), [])

    def test_memory_timestamp(self):
        m = EmotionMemory()
        e = m.record("success", {}, {}, "")
        self.assertGreater(e["timestamp"], 0.0)

    def test_memory_limit_recent_only(self):
        m = EmotionMemory(max_records=3)
        for i in range(5):
            m.record("success", {}, {}, f"e{i}")
        h = m.history()
        self.assertEqual(len(h), 3)
        self.assertEqual(h[0]["reason"], "e4")

    def test_memory_stats_empty(self):
        m = EmotionMemory()
        st = m.stats()
        self.assertEqual(st["total"], 0)
        self.assertEqual(st["by_event"], {})

    def test_memory_stats_by_event(self):
        m = EmotionMemory()
        m.record("decay", {}, {}, "")
        m.record("decay", {}, {}, "")
        st = m.stats()
        self.assertEqual(st["by_event"]["decay"], 2)


class TestAuditDetailed(unittest.TestCase):
    """情绪审计细节"""

    def test_audit_ring_capacity(self):
        a = EmotionAudit(max_records=4)
        for i in range(10):
            a.record(action="update", detail=f"d{i}")
        r = a.report()
        self.assertEqual(r["total"], 4)
        self.assertEqual(r["recent"][0]["detail"], "d9")

    def test_audit_recent_order(self):
        a = EmotionAudit()
        a.record(action="update", detail="first")
        a.record(action="decay", detail="second")
        r = a.report(limit=10)
        self.assertEqual(r["recent"][0]["detail"], "second")

    def test_audit_by_action_counts(self):
        a = EmotionAudit()
        a.record(action="update")
        a.record(action="update")
        a.record(action="restore")
        r = a.report()
        self.assertEqual(r["by_action"]["update"], 2)
        self.assertEqual(r["by_action"]["restore"], 1)

    def test_audit_max_records_zero(self):
        from backend.embodied.companion.emotion import AuditError
        with self.assertRaises(AuditError):
            EmotionAudit(max_records=0)


class TestStateDetailed(unittest.TestCase):
    """情绪状态细节"""

    def test_custom_baseline(self):
        st = EmotionState(baseline={"positivity": 0.3})
        self.assertEqual(st.get("positivity"), 0.3)
        self.assertEqual(st.baseline()["positivity"], 0.3)

    def test_custom_baseline_partial(self):
        st = EmotionState(baseline={"warmth": 0.8})
        self.assertEqual(st.get("positivity"),
                         EMOTION_BASELINE["positivity"])
        self.assertEqual(st.get("warmth"), 0.8)

    def test_floor_validation(self):
        with self.assertRaises(Exception):
            EmotionState(floor=1.0)

    def test_floor_validation_negative(self):
        with self.assertRaises(Exception):
            EmotionState(floor=-0.1)

    def test_apply_floor_respected(self):
        st = EmotionState(positivity=0.1, floor=0.1)
        st.apply({"positivity": -0.5}, reason="x")
        self.assertEqual(st.get("positivity"), 0.1)

    def test_distance_from_baseline_custom(self):
        st = EmotionState(positivity=0.9, baseline={"positivity": 0.5})
        self.assertGreater(st.distance_from_baseline(), 0.0)

    def test_apply_multiple_dims(self):
        st = EmotionState()
        st.apply({"positivity": 0.1, "warmth": 0.2}, reason="x")
        self.assertAlmostEqual(st.get("positivity"), 0.7, places=4)
        self.assertAlmostEqual(st.get("warmth"), 0.8, places=4)

    def test_apply_negative_floor_zero(self):
        st = EmotionState(positivity=0.5, floor=0.0)
        st.apply({"positivity": -1.0}, reason="x")
        self.assertEqual(st.get("positivity"), 0.0)


class TestSchedulerDetailed(unittest.TestCase):
    """调度器细节"""

    def test_trigger_config(self):
        t = GrowthTrigger(consolidate_threshold=5,
                          consolidate_days=2)
        self.assertTrue(t.should_run(experience_count=5,
                                     last_consolidation_days=0))
        self.assertTrue(t.should_run(experience_count=0,
                                     last_consolidation_days=2))

    def test_scheduler_result_kept(self):
        s = ConsolidationScheduler(GrowthTrigger(
            consolidate_threshold=1, consolidate_days=1))
        r = s.tick(experience_count=5,
                   consolidate_fn=lambda: {"done": True})
        self.assertTrue(r["consolidated"])
        self.assertEqual(r["result"]["done"], True)

    def test_scheduler_no_consolidate_fn(self):
        s = ConsolidationScheduler(GrowthTrigger(
            consolidate_threshold=1, consolidate_days=1))
        r = s.tick(experience_count=5)
        self.assertTrue(r["triggered"])
        self.assertIsNone(r["result"])

    def test_scheduler_history_recorded(self):
        s = ConsolidationScheduler(GrowthTrigger(
            consolidate_threshold=1, consolidate_days=1))
        s.tick(experience_count=5, consolidate_fn=lambda: {})
        st = s.stats()
        self.assertGreaterEqual(len(st["history"]), 1)

    def test_scheduler_last_run_days(self):
        s = ConsolidationScheduler(GrowthTrigger(
            consolidate_threshold=1, consolidate_days=1))
        now = time.time()
        r = s.tick(experience_count=5, consolidate_fn=lambda: {},
                   now=now)
        self.assertGreaterEqual(r["last_run_days"], 0.0)


class TestServiceAllContexts(unittest.TestCase):
    """Service 全情境"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"companion_enabled": True})

    def test_adjust_success(self):
        self.svc.companion_emotion_adjust("success")
        self.assertIn("positivity", self.svc.companion_emotion())

    def test_adjust_creative_done(self):
        self.svc.companion_emotion_adjust("creative_done")
        self.assertGreater(self.svc.companion_emotion()["warmth"], 0.6)

    def test_adjust_relationship_down(self):
        self.svc.companion_emotion_adjust("relationship_down")
        self.assertLess(self.svc.companion_emotion()["warmth"], 0.6)

    def test_adjust_idle_no_change(self):
        before = self.svc.companion_emotion()
        self.svc.companion_emotion_adjust("idle")
        after = self.svc.companion_emotion()
        self.assertEqual(before["positivity"], after["positivity"])

    def test_emotion_state_bounded(self):
        for _ in range(10):
            self.svc.companion_emotion_adjust("success")
        st = self.svc.companion_emotion()
        self.assertLessEqual(st["positivity"], 1.0)
        self.assertGreaterEqual(st["positivity"], 0.0)

    def test_emotion_stats_reason_distribution(self):
        eng = self.svc.companion_emotion_engine
        eng.update("success")
        eng.update("failure")
        st = eng.get_stats()
        self.assertEqual(st["reason_distribution"]["success"], 1)
        self.assertEqual(st["reason_distribution"]["failure"], 1)

    def test_emotion_audit_service_mode(self):
        r = self.svc.companion_emotion_audit()
        self.assertEqual(r["mode"], "rule_based")


class TestSnapshotCompatibility(unittest.TestCase):
    """快照兼容细节"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_cmp_")
        self.path = os.path.join(self.tmp, "s.jsonl")
        self.svc = EmbodiedService()
        self.svc.load_config({
            "companion_enabled": True,
            "companion_persistence_enabled": True,
        })

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_with_emotion_then_load(self):
        self.svc.companion_emotion_adjust("success")
        self.svc.companion_persistence_save(self.path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(self.path)
        self.assertIn("emotion", res["activated"])

    def test_restore_emotion_last_reason(self):
        self.svc.companion_emotion_adjust("creative_done")
        self.svc.companion_persistence_save(self.path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        svc2.companion_persistence_load(self.path)
        st = svc2.companion_emotion()
        self.assertIn("快照恢复", st["last_reason"])

    def test_persistence_disabled_but_emotion_works(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_persistence_enabled": False,
            "companion_emotion_enabled": True,
        })
        before = svc.companion_emotion()["positivity"]
        svc.companion_emotion_adjust("success")
        self.assertGreater(svc.companion_emotion()["positivity"],
                           before)


class TestRhythmFullCycle(unittest.TestCase):
    """节律完整循环"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "companion_enabled": True,
            "companion_persistence_enabled": True,
        })

    def test_full_cycle_after_handles(self):
        for i in range(3):
            self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        st = self.svc.companion_growth_rhythm()
        self.assertGreaterEqual(st["capture_count"], 1)

    def test_emotion_after_handle_failure(self):
        self.svc.companion_handle({"text": "不存在的无效请求xyz"})
        st = self.svc.companion_emotion()
        self.assertGreaterEqual(st["positivity"], 0.0)

    def test_rhythm_stats_mode(self):
        st = self.svc.companion_growth_rhythm()
        self.assertEqual(st["mode"], "rule_based")

    def test_rhythm_auto_reflection_config(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_rhythm_auto_reflection": False,
            "companion_enabled": True,
        })
        st = svc.companion_growth_rhythm()
        self.assertFalse(st["auto_reflection"])

    def test_rhythm_consolidate_days_config(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_rhythm_consolidate_days": 14,
            "companion_enabled": True,
        })
        st = svc.companion_growth_rhythm()
        self.assertEqual(
            st["thresholds"]["consolidate_days"], 14,
        )


if __name__ == "__main__":
    unittest.main()
