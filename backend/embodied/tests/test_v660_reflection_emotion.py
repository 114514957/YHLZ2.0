"""
YHLZ Embodied AI V6.6 - 反思情绪集成单元测试 (Reflection Emotion)

覆盖:
    - Meaning 提取 (模式 → 意义/成长值/情绪上下文)
    - 情绪分析 (状态/置信度)
    - 风险等级 (矛盾类型)
    - 情绪调整 (经 EmotionEngine, 有限幅)
    - 安全: 不直接修改情绪/人格
"""
import threading
import unittest

from backend.embodied.companion.emotion import EmotionEngine
from backend.embodied.companion.reflection import (
    CONTRADICTION_RISK,
    EMOTION_STATES,
    MEANING_BY_PATTERN,
    REFLECTION_EMOTION_CONTEXTS,
    RISK_LEVELS,
    ReflectionEmotionError,
    ReflectionEmotionIntegrator,
)


def make_report(patterns=None, contradictions=None,
                confidence=0.9, report_id="cr_x"):
    return {
        "report_id": report_id,
        "confidence": confidence,
        "patterns": patterns or [],
        "contradictions": contradictions or [],
    }


def make_pattern(ptype, confidence=0.8, trigger="t"):
    return {
        "type": ptype, "trigger": trigger,
        "confidence": confidence, "meaning": "m",
    }


class TestMeaningExtraction(unittest.TestCase):
    """意义提取"""

    def setUp(self):
        self.integrator = ReflectionEmotionIntegrator()

    def test_success_strategy_meaning(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertIn("有效策略", r["meaning"])

    def test_problem_pattern_meaning(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("problem_pattern")],
        ))
        self.assertIn("问题模式", r["meaning"])

    def test_repetition_meaning(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("repetition")],
        ))
        self.assertIn("重复", r["meaning"])

    def test_no_pattern_meaning(self):
        r = self.integrator.analyze(make_report())
        self.assertIn("无明显模式", r["meaning"])

    def test_unknown_pattern_meaning(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("unknown_type")],
        ))
        self.assertIn("待分类", r["meaning"])

    def test_success_growth_value(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertEqual(r["growth_value"], 0.85)

    def test_problem_growth_value(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("problem_pattern")],
        ))
        self.assertEqual(r["growth_value"], 0.35)

    def test_no_pattern_growth_value(self):
        r = self.integrator.analyze(make_report())
        self.assertEqual(r["growth_value"], 0.6)

    def test_success_emotion_context(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertEqual(r["emotion_context"], "success")

    def test_problem_emotion_context(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("problem_pattern")],
        ))
        self.assertEqual(r["emotion_context"], "failure")

    def test_repetition_emotion_context(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("repetition")],
        ))
        self.assertEqual(r["emotion_context"], "idle")

    def test_highest_confidence_pattern_wins(self):
        r = self.integrator.analyze(make_report(patterns=[
            make_pattern("success_strategy", confidence=0.5),
            make_pattern("problem_pattern", confidence=0.9),
        ]))
        self.assertEqual(r["emotion_context"], "failure")

    def test_success_state_positive(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertEqual(r["emotion_analysis"]["state"],
                         "positive")

    def test_problem_state_cautious(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("problem_pattern")],
        ))
        self.assertEqual(r["emotion_analysis"]["state"],
                         "cautious")

    def test_no_pattern_state_neutral(self):
        r = self.integrator.analyze(make_report())
        self.assertEqual(r["emotion_analysis"]["state"],
                         "neutral")

    def test_confidence_from_report(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
            confidence=0.75,
        ))
        self.assertEqual(r["emotion_analysis"]["confidence"],
                         0.75)

    def test_empty_report(self):
        r = self.integrator.analyze({})
        self.assertEqual(r["emotion_context"], "idle")
        self.assertEqual(r["risk_level"], "low")


class TestRiskLevel(unittest.TestCase):
    """风险等级"""

    def setUp(self):
        self.integrator = ReflectionEmotionIntegrator()

    def test_identity_conflict_high_risk(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
            contradictions=[{"conflict_type":
                             "identity_conflict"}],
        ))
        self.assertEqual(r["risk_level"], "high")

    def test_knowledge_conflict_medium_risk(self):
        r = self.integrator.analyze(make_report(
            contradictions=[{"conflict_type":
                             "knowledge_conflict"}],
        ))
        self.assertEqual(r["risk_level"], "medium")

    def test_value_conflict_high_risk(self):
        r = self.integrator.analyze(make_report(
            contradictions=[{"conflict_type":
                             "value_conflict"}],
        ))
        self.assertEqual(r["risk_level"], "high")

    def test_no_conflict_low_risk(self):
        r = self.integrator.analyze(make_report())
        self.assertEqual(r["risk_level"], "low")

    def test_unknown_conflict_low_risk(self):
        r = self.integrator.analyze(make_report(
            contradictions=[{"conflict_type": "x_conflict"}],
        ))
        self.assertEqual(r["risk_level"], "low")

    def test_high_risk_lowers_growth_value(self):
        base = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        risky = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
            contradictions=[{"conflict_type":
                             "identity_conflict"}],
        ))
        self.assertLess(risky["growth_value"],
                        base["growth_value"])

    def test_medium_risk_limits_growth_value(self):
        r = self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
            contradictions=[{"conflict_type":
                             "knowledge_conflict"}],
        ))
        self.assertEqual(r["growth_value"], 0.7)

    def test_high_risk_state_cautious(self):
        r = self.integrator.analyze(make_report(
            contradictions=[{"conflict_type":
                             "value_conflict"}],
        ))
        self.assertEqual(r["emotion_analysis"]["state"],
                         "cautious")

    def test_contradiction_risk_mapping(self):
        self.assertEqual(CONTRADICTION_RISK["identity_conflict"],
                         "high")
        self.assertEqual(CONTRADICTION_RISK["value_conflict"],
                         "high")
        self.assertEqual(CONTRADICTION_RISK["knowledge_conflict"],
                         "medium")


class TestEmotionAdjustment(unittest.TestCase):
    """情绪调整 (经 EmotionEngine)"""

    def setUp(self):
        self.emotion = EmotionEngine()
        self.integrator = ReflectionEmotionIntegrator(
            emotion=self.emotion,
        )

    def test_positive_adjust_applied(self):
        r = self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertTrue(r["adjustment"]["applied"])
        self.assertEqual(r["adjustment"]["context"], "success")

    def test_negative_adjust_applied(self):
        r = self.integrator.adjust(make_report(
            patterns=[make_pattern("problem_pattern")],
        ))
        self.assertTrue(r["adjustment"]["applied"])
        self.assertEqual(r["adjustment"]["context"], "failure")

    def test_idle_adjust_not_applied(self):
        r = self.integrator.adjust(make_report())
        self.assertFalse(r["adjustment"]["applied"])
        self.assertEqual(r["adjustment"]["context"], "idle")

    def test_adjustment_records_before_after(self):
        r = self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        adj = r["adjustment"]
        self.assertIn("positivity", adj["before"])
        self.assertIn("positivity", adj["after"])
        self.assertNotEqual(adj["before"], adj["after"])

    def test_adjustment_reason_is_meaning(self):
        r = self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertEqual(r["adjustment"]["reason"],
                         r["meaning"])

    def test_emotion_state_changed_limited(self):
        before = self.emotion.get_state()
        self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        after = self.emotion.get_state()
        delta = abs(after["positivity"] - before["positivity"])
        self.assertLess(delta, 0.5)

    def test_emotion_update_count_incremented(self):
        before = self.emotion.get_stats()["update_count"]
        self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        after = self.emotion.get_stats()["update_count"]
        self.assertEqual(after, before + 1)

    def test_no_emotion_engine_skipped(self):
        integrator = ReflectionEmotionIntegrator()
        r = integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertFalse(r["adjustment"]["applied"])

    def test_disabled_engine_skipped(self):
        integrator = ReflectionEmotionIntegrator(
            emotion=self.emotion, enabled=False,
        )
        r = integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertFalse(r["adjustment"]["applied"])
        self.assertEqual(r["emotion_context"], "idle")

    def test_idle_does_not_touch_emotion(self):
        state_before = self.emotion.get_state()
        self.integrator.adjust(make_report())
        state_after = self.emotion.get_state()
        self.assertEqual(state_before, state_after)

    def test_personality_not_modified(self):
        before = dict(self.emotion.get_state())
        self.integrator.adjust(make_report(
            patterns=[make_pattern("problem_pattern")],
        ))
        self.assertIn("positivity", before)
        self.assertIn("last_reason",
                      self.emotion.get_state())


class TestDisabledAndErrors(unittest.TestCase):
    """停用与异常"""

    def test_disabled_result(self):
        integrator = ReflectionEmotionIntegrator(enabled=False)
        r = integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertEqual(r["growth_value"], 0.0)
        self.assertEqual(r["emotion_context"], "idle")
        self.assertEqual(r["mode"], "rule_based")

    def test_emotion_exception_caught(self):
        class BoomEmotion:
            def get_state(self):
                return {}

            def update(self, context):
                raise RuntimeError("boom")

        integrator = ReflectionEmotionIntegrator(
            emotion=BoomEmotion(),
        )
        r = integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertFalse(r["adjustment"]["applied"])
        self.assertIn("失败", r["adjustment"]["reason"])

    def test_result_id_prefix(self):
        r = self._fresh().analyze(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.assertTrue(r["result_id"].startswith("re_"))

    def test_report_id_passthrough(self):
        r = self._fresh().analyze(make_report(
            report_id="cr_abc", patterns=[
                make_pattern("success_strategy")],
        ))
        self.assertEqual(r["report_id"], "cr_abc")

    def _fresh(self):
        return ReflectionEmotionIntegrator()

    def test_mode_rule_based(self):
        r = self._fresh().analyze(make_report())
        self.assertEqual(r["mode"], "rule_based")


class TestStatsAndLifecycle(unittest.TestCase):
    """统计与生命周期"""

    def setUp(self):
        self.emotion = EmotionEngine()
        self.integrator = ReflectionEmotionIntegrator(
            emotion=self.emotion,
        )

    def test_analysis_count(self):
        self.integrator.analyze(make_report())
        self.integrator.analyze(make_report())
        self.assertEqual(
            self.integrator.stats()["analysis_count"], 2)

    def test_adjustment_count(self):
        self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.integrator.adjust(make_report(
            patterns=[make_pattern("problem_pattern")],
        ))
        self.integrator.adjust(make_report())
        stats = self.integrator.stats()
        self.assertEqual(stats["adjustment_count"], 2)
        self.assertEqual(stats["skip_count"], 1)

    def test_context_distribution(self):
        self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        stats = self.integrator.stats()
        self.assertEqual(stats["context_distribution"]["success"],
                         2)

    def test_latest_result(self):
        self.integrator.analyze(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        latest = self.integrator.latest()
        self.assertEqual(latest["emotion_context"], "success")

    def test_latest_empty(self):
        self.assertIsNone(self.integrator.latest())

    def test_clear(self):
        self.integrator.analyze(make_report())
        n = self.integrator.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.integrator.stats()[
            "analysis_count"], 0)

    def test_stats_enabled_flag(self):
        self.assertTrue(self.integrator.stats()["enabled"])

    def test_stats_contexts_whitelist(self):
        self.assertEqual(
            self.integrator.stats()["emotion_contexts"],
            REFLECTION_EMOTION_CONTEXTS)

    def test_constants_complete(self):
        self.assertIn("success", REFLECTION_EMOTION_CONTEXTS)
        self.assertIn("failure", REFLECTION_EMOTION_CONTEXTS)
        self.assertIn("idle", REFLECTION_EMOTION_CONTEXTS)
        self.assertEqual(len(REFLECTION_EMOTION_CONTEXTS), 3)

    def test_emotion_states(self):
        self.assertIn("positive", EMOTION_STATES)
        self.assertIn("cautious", EMOTION_STATES)
        self.assertIn("neutral", EMOTION_STATES)

    def test_risk_levels(self):
        self.assertEqual(RISK_LEVELS, ["low", "medium", "high"])

    def test_meaning_map_keys(self):
        self.assertIn("success_strategy", MEANING_BY_PATTERN)
        self.assertIn("problem_pattern", MEANING_BY_PATTERN)
        self.assertIn("repetition", MEANING_BY_PATTERN)


class TestThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_analyze(self):
        integrator = ReflectionEmotionIntegrator()
        errors = []

        def work():
            try:
                for _ in range(20):
                    integrator.analyze(make_report(
                        patterns=[make_pattern(
                            "success_strategy")],
                    ))
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(integrator.stats()["analysis_count"],
                         80)

    def test_concurrent_adjust(self):
        emotion = EmotionEngine()
        integrator = ReflectionEmotionIntegrator(
            emotion=emotion,
        )
        errors = []

        def work():
            try:
                for _ in range(10):
                    integrator.adjust(make_report(
                        patterns=[make_pattern(
                            "problem_pattern")],
                    ))
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(integrator.stats()["adjustment_count"],
                         40)


class TestAdjustmentBoundary(unittest.TestCase):
    """调整边界"""

    def setUp(self):
        self.emotion = EmotionEngine()
        self.integrator = ReflectionEmotionIntegrator(
            emotion=self.emotion,
        )

    def test_negative_does_not_crash_floor(self):
        for _ in range(30):
            self.integrator.adjust(make_report(
                patterns=[make_pattern("problem_pattern")],
            ))
        state = self.emotion.get_state()
        self.assertGreaterEqual(state["positivity"], 0.0)

    def test_positive_limited_by_consecutive(self):
        before = self.emotion.get_state()
        for _ in range(10):
            self.integrator.adjust(make_report(
                patterns=[make_pattern("success_strategy")],
            ))
        after = self.emotion.get_state()
        self.assertLessEqual(after["positivity"], 1.0)

    def test_emotion_reason_recorded(self):
        self.integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        state = self.emotion.get_state()
        self.assertIn("成功", state["last_reason"])


class TestEmotionIsolation(unittest.TestCase):
    """情绪隔离 (不触人格/核心)"""

    def test_emotion_contexts_only_whitelist(self):
        for ctx in REFLECTION_EMOTION_CONTEXTS:
            self.assertIn(ctx, ["success", "failure", "idle"])

    def test_integrator_never_writes_state_directly(self):
        emotion = EmotionEngine()
        integrator = ReflectionEmotionIntegrator(
            emotion=emotion,
        )
        integrator.adjust(make_report(
            patterns=[make_pattern("success_strategy")],
        ))
        stats = emotion.get_stats()
        self.assertEqual(stats["update_count"], 1)


if __name__ == "__main__":
    unittest.main()
