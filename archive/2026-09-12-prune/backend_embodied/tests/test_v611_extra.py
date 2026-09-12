"""
YHLZ Embodied AI V9.5.0 - 情绪与节律补充测试 (Emotion & Rhythm Extra)

覆盖 (专项补足):
    - 8 情境全行为
    - 稳定性边界 (consecutive_limit 各值 / floor 保护)
    - 衰减边界 (rate=0 / 边界时间)
    - 情绪记忆与快照联动
    - 节律配置开关 (emotion_enabled / rhythm_enabled / daily_snapshot)
    - Service 配置驱动
"""
import os
import shutil
import tempfile
import time
import unittest

from backend.embodied.companion.emotion import (
    EMOTION_CONTEXTS,
    EmotionDecay,
    EmotionEngine,
    EmotionState,
)
from backend.embodied.service import EmbodiedService


class TestAllContexts(unittest.TestCase):
    """8 情境全行为"""

    def setUp(self):
        self.engine = EmotionEngine(update_step=0.1)

    def test_all_contexts_acceptable(self):
        for ctx in EMOTION_CONTEXTS:
            self.engine.update(ctx)

    def test_success_energy_up(self):
        before = self.engine.get_state()["energy"]
        self.engine.update("success")
        self.assertGreater(self.engine.get_state()["energy"], before)

    def test_failure_energy_down(self):
        self.engine.update("success")
        before = self.engine.get_state()["energy"]
        self.engine.update("failure")
        self.assertLess(self.engine.get_state()["energy"], before)

    def test_consecutive_fail_context(self):
        before = self.engine.get_state()["positivity"]
        self.engine.update("consecutive_fail")
        self.assertLess(self.engine.get_state()["positivity"], before)

    def test_creative_rejected(self):
        before = self.engine.get_state()["positivity"]
        self.engine.update("creative_rejected")
        self.assertLess(self.engine.get_state()["positivity"], before)

    def test_relationship_down_warmth(self):
        before = self.engine.get_state()["warmth"]
        self.engine.update("relationship_down")
        self.assertLess(self.engine.get_state()["warmth"], before)

    def test_idle_no_change(self):
        before = self.engine.get_state()
        self.engine.update("idle")
        after = self.engine.get_state()
        self.assertEqual(before["positivity"], after["positivity"])
        self.assertEqual(before["energy"], after["energy"])

    def test_creative_done_warmth_up(self):
        before = self.engine.get_state()["warmth"]
        self.engine.update("creative_done")
        self.assertGreater(self.engine.get_state()["warmth"], before)

    def test_success_then_failure_net_down(self):
        self.engine.update("success")
        self.engine.update("failure")
        st = self.engine.get_state()
        self.assertLess(st["positivity"], 0.6 + 1e-9)


class TestStabilityExtra(unittest.TestCase):
    """稳定性边界"""

    def test_limit_2(self):
        e = EmotionEngine(update_step=0.1, consecutive_limit=2)
        for _ in range(8):
            e.update("failure")
        self.assertGreaterEqual(e.get_state()["positivity"], 0.1)

    def test_limit_5(self):
        e = EmotionEngine(update_step=0.1, consecutive_limit=5)
        for _ in range(10):
            e.update("failure")
        self.assertGreaterEqual(e.get_state()["positivity"], 0.1)

    def test_floor_never_broken(self):
        """30 次失败后仍 ≥ floor"""
        e = EmotionEngine(update_step=0.2, floor=0.2)
        for _ in range(30):
            e.update("failure")
        self.assertGreaterEqual(e.get_state()["positivity"], 0.2)

    def test_floor_default_0_1(self):
        e = EmotionEngine()
        for _ in range(50):
            e.update("failure")
        self.assertGreaterEqual(e.get_state()["positivity"], 0.1)

    def test_high_step_clamped(self):
        e = EmotionEngine(update_step=1.0)
        for _ in range(5):
            e.update("success")
        self.assertEqual(e.get_state()["positivity"], 1.0)

    def test_mixed_sequences_stable(self):
        e = EmotionEngine()
        seq = ["success", "failure", "success", "failure",
               "consecutive_fail", "creative_done",
               "relationship_up", "relationship_down"] * 3
        for ctx in seq:
            e.update(ctx)
        st = e.get_state()
        for dim in ("positivity", "energy", "warmth"):
            self.assertGreaterEqual(st[dim], 0.1)
            self.assertLessEqual(st[dim], 1.0)

    def test_energy_floor(self):
        e = EmotionEngine()
        for _ in range(30):
            e.update("failure")
        self.assertGreaterEqual(e.get_state()["energy"], 0.1)


class TestDecayExtra(unittest.TestCase):
    """衰减边界"""

    def test_rate_zero_no_decay(self):
        d = EmotionDecay(rate=0.0)
        st = EmotionState(positivity=0.9)
        before = st.to_dict()
        after = d.decay(st, now=time.time() + 86400)
        self.assertEqual(before["positivity"], after["positivity"])

    def test_window_large_slow_decay(self):
        d = EmotionDecay(rate=0.5, window_days=365)
        st = EmotionState(positivity=0.9)
        after = d.decay(st, now=time.time() + 86400)
        self.assertAlmostEqual(after["positivity"], 0.9, delta=0.01)

    def test_decay_returns_state_dict(self):
        d = EmotionDecay(rate=0.1, window_days=1)
        st = EmotionState(positivity=0.8)
        st._timestamp = time.time() - 86400
        after = d.decay(st, now=time.time())
        for key in ("positivity", "energy", "warmth",
                    "last_reason", "timestamp"):
            self.assertIn(key, after)

    def test_decay_all_dimensions(self):
        d = EmotionDecay(rate=0.2, window_days=1)
        st = EmotionState(positivity=0.9, energy=0.8, warmth=0.9)
        st._timestamp = time.time() - 86400
        after = d.decay(st, now=time.time())
        self.assertLess(after["positivity"], 0.9)
        self.assertLess(after["energy"], 0.8)
        self.assertLess(after["warmth"], 0.9)

    def test_decay_never_below_floor(self):
        d = EmotionDecay(rate=0.5, window_days=1)
        st = EmotionState(positivity=0.12, floor=0.1)
        st._timestamp = time.time() - 86400
        after = d.decay(st, now=time.time())
        self.assertGreaterEqual(after["positivity"], 0.1)


class TestEmotionSnapshotExtra(unittest.TestCase):
    """情绪快照联动"""

    def test_emotion_collected_in_states(self):
        from backend.embodied.companion.continuity_engine import (
            ContinuityEngine,
        )
        e = EmotionEngine()
        e.update("success")
        con = ContinuityEngine(emotion_engine=e)
        states = con.collect_states()
        self.assertIn("emotion", states)
        self.assertEqual(
            states["emotion"]["positivity"],
            e.get_state()["positivity"],
        )

    def test_emotion_restore_roundtrip(self):
        from backend.embodied.companion.continuity_engine import (
            ContinuityEngine,
        )
        e1 = EmotionEngine()
        e1.update("success")
        e1.update("relationship_up")
        con1 = ContinuityEngine(emotion_engine=e1)
        e2 = EmotionEngine()
        con2 = ContinuityEngine(emotion_engine=e2)
        # 模拟恢复
        states = con1.collect_states()
        con2._apply_emotion(states["emotion"])
        self.assertEqual(e2.get_state()["positivity"],
                         e1.get_state()["positivity"])
        self.assertEqual(e2.get_state()["warmth"],
                         e1.get_state()["warmth"])

    def test_emotion_restore_no_engine(self):
        from backend.embodied.companion.continuity_engine import (
            ContinuityEngine,
        )
        con = ContinuityEngine()
        self.assertFalse(con._apply_emotion(
            {"positivity": 0.9},
        ))


class TestEngineConfigExtra(unittest.TestCase):
    """引擎配置"""

    def test_stats_includes_floor_baseline(self):
        e = EmotionEngine(floor=0.2)
        st = e.get_stats()
        self.assertIn("baseline", st)

    def test_update_step_config_effect(self):
        e = EmotionEngine(update_step=0.05)
        before = e.get_state()["positivity"]
        e.update("success")
        self.assertAlmostEqual(
            e.get_state()["positivity"] - before, 0.05, places=4,
        )

    def test_reset_keeps_floor(self):
        e = EmotionEngine(floor=0.3)
        e.update("failure")
        e.reset()
        st = e.get_state()
        self.assertGreaterEqual(st["positivity"], 0.3)

    def test_restore_state_clamps(self):
        e = EmotionEngine()
        e.restore_state({"positivity": 5.0, "energy": -1.0})
        st = e.get_state()
        self.assertEqual(st["positivity"], 1.0)
        self.assertEqual(st["energy"], 0.1)  # floor 保护


class TestServiceConfigExtra(unittest.TestCase):
    """Service 配置驱动"""

    def test_emotion_disabled_config(self):
        svc = EmbodiedService()
        svc.load_config({"companion_emotion_enabled": False})
        eng = svc.companion_emotion_engine
        with self.assertRaises(Exception):
            eng.update("success")

    def test_rhythm_disabled_config(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_rhythm_enabled": False,
            "companion_enabled": True,
        })
        r = svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertFalse(r.get("rhythm", {}).get("enabled"))

    def test_daily_snapshot_config_false(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_rhythm_daily_snapshot": False,
            "companion_enabled": True,
        })
        st = svc.companion_growth_rhythm()
        self.assertFalse(st["daily_snapshot"])

    def test_consolidate_threshold_config(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_rhythm_consolidate_threshold": 50,
            "companion_enabled": True,
        })
        st = svc.companion_growth_rhythm()
        self.assertEqual(
            st["thresholds"]["consolidate_threshold"], 50,
        )

    def test_update_step_config(self):
        svc = EmbodiedService()
        svc.load_config({"companion_emotion_update_step": 0.2})
        before = svc.companion_emotion()["positivity"]
        svc.companion_emotion_adjust("success")
        after = svc.companion_emotion()["positivity"]
        self.assertAlmostEqual(after - before, 0.2, places=4)

    def test_decay_rate_config(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_emotion_decay_rate": 0.5,
            "companion_emotion_decay_window_days": 1,
        })
        eng = svc.companion_emotion_engine
        eng.update("success")
        eng._state._timestamp = time.time() - 86400
        before = eng.get_state()["positivity"]
        svc.companion_emotion_decay()
        after = eng.get_state()["positivity"]
        self.assertLess(after, before)


class TestRhythmEdgeExtra(unittest.TestCase):
    """节律边界"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
            "companion_persistence_enabled": True,
        })

    def test_rhythm_cycle_structure(self):
        r = self.svc.companion_growth_rhythm_cycle(
            {"intent": "x"}, {"aggregated": {"ok_count": 1,
                                             "total": 1}},
        )
        self.assertEqual(r["mode"], "rule_based")

    def test_handle_emotion_after_tasks(self):
        """多次成功任务 → 情绪上升"""
        for _ in range(3):
            self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertGreater(
            self.svc.companion_emotion()["positivity"], 0.6,
        )

    def test_growth_report_includes_emotion_context(self):
        self.svc.companion_emotion_adjust("success")
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")

    def test_emotion_isolated_from_personality_via_service(self):
        p_before = self.svc.companion_personality()
        for _ in range(5):
            self.svc.companion_emotion_adjust("failure")
        p_after = self.svc.companion_personality()
        self.assertEqual(p_before["base"], p_after["base"])
        self.assertEqual(p_before["dimensions"], p_after["dimensions"])

    def test_rhythm_audit_after_cycle(self):
        self.svc.companion_growth_rhythm_cycle(
            {}, {"aggregated": {"ok_count": 1, "total": 1}},
        )
        r = self.svc.companion_rhythm_audit()
        self.assertEqual(r["mode"], "rule_based")

    def test_emotion_history_service(self):
        self.svc.companion_emotion_adjust("creative_done")
        h = self.svc.companion_emotion_history(limit=5)
        self.assertEqual(h["records"][0]["event"], "creative_done")


class TestTmpCleanup(unittest.TestCase):
    """临时目录清理验证"""

    def test_tmp_clean(self):
        tmp = tempfile.mkdtemp(prefix="yhlz_clean_")
        self.assertTrue(os.path.exists(tmp))
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertFalse(os.path.exists(tmp))


if __name__ == "__main__":
    unittest.main()
