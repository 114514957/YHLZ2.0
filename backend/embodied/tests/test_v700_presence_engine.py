"""
YHLZ Embodied AI V7.0 - 存在表达引擎单元测试 (Presence Engine)

覆盖:
    - 状态机更新 (映射 → 有限幅 → 守护 → 输出)
    - 强度有限幅 (防剧烈震荡)
    - 身份守护 (表达不触身份)
    - 连续性/审计/快照恢复
    - Boundary Test (表达不改变身份)
"""
import threading
import unittest

from backend.embodied.companion.emotion import EmotionEngine
from backend.embodied.companion.embodied_presence import (
    PRESENCE_OUTPUT_FIELDS,
    PRESENCE_PROTECTED_FIELDS,
    PresenceEngine,
    PresenceEngineError,
    PresenceMapper,
    PresenceMemory,
    PresenceState,
)


class TestPresenceEngine(unittest.TestCase):
    """表达引擎"""

    def setUp(self):
        self.emotion = EmotionEngine()
        self.engine = PresenceEngine(emotion=self.emotion)

    def test_update_success(self):
        r = self.engine.update("success")
        self.assertEqual(r["expression"], "高兴")
        self.assertEqual(r["interaction_mode"], "playful")
        self.assertEqual(r["mode"], "rule_based")

    def test_update_failure(self):
        r = self.engine.update("failure")
        self.assertEqual(r["expression"], "关切")
        self.assertEqual(r["interaction_mode"], "supportive")

    def test_update_deep_task(self):
        r = self.engine.update("deep_task")
        self.assertEqual(r["expression"], "思考")
        self.assertEqual(r["posture"], "专注")

    def test_update_idle(self):
        r = self.engine.update("idle")
        self.assertEqual(r["expression"], "平静")

    def test_state_reflects_update(self):
        self.engine.update("success")
        state = self.engine.state()
        self.assertEqual(state["expression"], "高兴")
        self.assertIn("last_reason", state)

    def test_intensity_limited_step(self):
        # 0.3 → 0.7 需要多步 (step 0.15): 0.3→0.45→0.6
        self.engine.update("success")
        r = self.engine.update("success")
        self.assertLessEqual(r["intensity"], 0.6)

    def test_intensity_approaches_target(self):
        for _ in range(10):
            self.engine.update("success")
        state = self.engine.state()
        self.assertLessEqual(state["intensity"], 0.7)
        self.assertGreaterEqual(state["intensity"], 0.55)

    def test_intensity_never_exceeds_1(self):
        for _ in range(30):
            self.engine.update("success")
        self.assertLessEqual(self.engine.state()["intensity"],
                             1.0)

    def test_intensity_never_below_0(self):
        for _ in range(30):
            self.engine.update("failure")
        self.assertGreaterEqual(
            self.engine.state()["intensity"], 0.0)

    def test_interpreter_read_only(self):
        before = self.engine.state()
        r = self.engine.interpreter("success")
        self.assertEqual(r["expression"], "高兴")
        after = self.engine.state()
        self.assertEqual(before["expression"],
                         after["expression"])

    def test_update_records_memory(self):
        self.engine.update("success")
        self.engine.update("failure")
        self.assertEqual(
            self.engine.memory_stats()["record_count"], 2)

    def test_update_audited(self):
        self.engine.update("success")
        audit = self.engine.audit_report()
        self.assertEqual(audit["total"], 1)
        self.assertEqual(audit["recent"][0]["context"],
                         "success")

    def test_audit_has_guard_ok(self):
        self.engine.update("success")
        entry = self.engine.audit_report()["recent"][0]
        self.assertTrue(entry["guard_ok"])
        self.assertIn("applied", entry)

    def test_continuity(self):
        self.engine.update("success")
        self.engine.update("success")
        c = self.engine.continuity()
        self.assertEqual(c["preferred_mode"], "playful")

    def test_history(self):
        self.engine.update("success")
        h = self.engine.history()
        self.assertEqual(len(h["records"]), 1)

    def test_update_count(self):
        self.engine.update("idle")
        self.engine.update("idle")
        self.assertEqual(self.engine.stats()["update_count"],
                         2)

    def test_emotion_engine_linked(self):
        # 情绪引擎联动: 表达读取情绪状态
        self.emotion.update("success")
        self.engine.update("idle")
        state = self.engine.state()
        self.assertEqual(state["expression"], "高兴")

    def test_disabled_engine(self):
        engine = PresenceEngine(enabled=False)
        r = engine.update("success")
        self.assertEqual(r["expression"], "平静")
        self.assertEqual(r["reason"], "presence_enabled_false")

    def test_invalid_intensity_step(self):
        with self.assertRaises(PresenceEngineError):
            PresenceEngine(intensity_step=0)

    def test_stats_structure(self):
        stats = self.engine.stats()
        for key in ("enabled", "update_count",
                    "guard_block_count", "state", "mapper",
                    "memory", "intensity_step"):
            self.assertIn(key, stats)

    def test_restore_state(self):
        self.engine.update("success")
        self.engine.restore_state(
            {"expression": "平静", "posture": "待机",
             "intensity": 0.3, "interaction_mode": "neutral"},
        )
        state = self.engine.state()
        self.assertEqual(state["expression"], "平静")

    def test_clear(self):
        self.engine.update("success")
        n = self.engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(self.engine.stats()[
            "update_count"], 0)


class TestIdentityGuard(unittest.TestCase):
    """身份守护 (Boundary Test)"""

    def setUp(self):
        self.emotion = EmotionEngine()
        self.engine = PresenceEngine(emotion=self.emotion)

    def test_guard_check_pass(self):
        ok, reason = self.engine._guard_check({
            "expression": "高兴", "posture": "回应",
            "intensity": 0.7, "interaction_mode": "playful",
            "reason": "任务成功",
        })
        self.assertTrue(ok)

    def test_guard_check_identity_field(self):
        ok, reason = self.engine._guard_check({
            "expression": "高兴", "mission": "新使命",
        })
        self.assertFalse(ok)

    def test_guard_check_modify_signal(self):
        ok, reason = self.engine._guard_check({
            "expression": "高兴",
            "reason": "建议修改人格",
        })
        self.assertFalse(ok)

    def test_output_only_whitelist(self):
        self.engine.update("success")
        state = self.engine.state()
        for key in state:
            if key in ("last_reason", "reason", "mode"):
                continue
            self.assertIn(key, PRESENCE_OUTPUT_FIELDS)

    def test_protected_fields_constant(self):
        self.assertIn("mission", PRESENCE_PROTECTED_FIELDS)
        self.assertIn("core_value",
                      PRESENCE_PROTECTED_FIELDS)
        self.assertIn("base_personality",
                      PRESENCE_PROTECTED_FIELDS)
        self.assertIn("人格", PRESENCE_PROTECTED_FIELDS)

    def test_guard_block_count_zero(self):
        self.engine.update("success")
        self.assertEqual(
            self.engine.stats()["guard_block_count"], 0)

    def test_boundary_identity_stable(self):
        """Boundary Test: 表达模拟不会改变身份"""
        before = self.emotion.get_state()
        self.engine.update("failure")
        self.engine.update("success")
        self.engine.update("deep_task")
        after = self.emotion.get_state()
        # 情绪引擎不被表达修改 (表达是只读输入方)
        self.assertEqual(before, after)


class TestContinuity(unittest.TestCase):
    """Continuity Test: 长期互动表达一致性"""

    def test_long_term_consistency(self):
        engine = PresenceEngine(emotion=EmotionEngine())
        # 一周内的多次互动
        for i in range(20):
            engine.update("success" if i % 2 == 0
                          else "failure")
        c = engine.continuity(window_days=7)
        self.assertGreater(c["total"], 0)
        self.assertGreaterEqual(c["rhythm_stability"], 0.0)
        self.assertLessEqual(c["rhythm_stability"], 1.0)
        self.assertIn(c["preferred_mode"],
                      ["playful", "supportive"])

    def test_preference_learned(self):
        engine = PresenceEngine(emotion=EmotionEngine())
        for _ in range(10):
            engine.update("success")
        c = engine.continuity()
        self.assertEqual(c["preferred_mode"], "playful")
        self.assertEqual(c["preferred_expression"], "高兴")

    def test_state_continuous_after_restore(self):
        engine = PresenceEngine(emotion=EmotionEngine())
        engine.update("success")
        snap = engine.state()
        engine2 = PresenceEngine(emotion=EmotionEngine())
        engine2.restore_state(snap)
        self.assertEqual(engine2.state()["expression"], "高兴")


class TestRecovery(unittest.TestCase):
    """Recovery Test: 云端失败后的本地降级能力"""

    def test_emotion_failure_tolerated(self):
        class BoomEmotion:
            def get_state(self):
                raise RuntimeError("boom")

        engine = PresenceEngine(emotion=BoomEmotion())
        r = engine.update("success")
        # 情绪读取失败 → 仍可输出 (默认中性映射)
        self.assertEqual(r["expression"], "高兴")
        self.assertEqual(r["mode"], "rule_based")

    def test_personality_fn_failure_tolerated(self):
        def boom():
            raise RuntimeError("boom")

        engine = PresenceEngine(
            emotion=EmotionEngine(),
            personality_fn=boom,
        )
        r = engine.update("idle")
        self.assertIn("expression", r)

    def test_mapper_always_available(self):
        engine = PresenceEngine()  # 无注入
        r = engine.update("idle")
        self.assertEqual(r["expression"], "平静")


class TestThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_update(self):
        engine = PresenceEngine(emotion=EmotionEngine())
        errors = []

        def work():
            try:
                for _ in range(20):
                    engine.update("success")
                    engine.update("failure")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(engine.stats()["update_count"], 160)

    def test_concurrent_interpreter(self):
        engine = PresenceEngine()
        errors = []

        def work():
            try:
                for _ in range(20):
                    engine.interpreter("idle")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
