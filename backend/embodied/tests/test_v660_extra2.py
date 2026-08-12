"""
YHLZ Embodied AI V6.6 - 自主成长成熟化补充测试 (V6.6 Extra2)

覆盖 (生成式批量 + 边界):
    - 反思情绪: 多模式组合 / 连续调整 / 风险组合
    - 成长闭环: 决策矩阵 / 边界触发 / 空容错
    - 成长趋势: 组合输入 / 权重贡献 / 容错
"""
import time
import unittest

from backend.embodied.companion.emotion import EmotionEngine
from backend.embodied.companion.growth import (
    CycleError,
    GrowthCycleEngine,
    GrowthTrendAnalysis,
)
from backend.embodied.companion.reflection import (
    ReflectionEmotionIntegrator,
)


def _report(patterns=None, contradictions=None,
            confidence=0.8):
    return {
        "report_id": "cr_gen2",
        "confidence": confidence,
        "patterns": patterns or [],
        "contradictions": contradictions or [],
    }


def _pat(ptype, conf=0.8):
    return {"type": ptype, "trigger": "t",
            "confidence": conf, "meaning": "m"}


def _stats(**over):
    data = {
        "reflection": {"reflection_count": 10},
        "proposal": {"proposal_count": 8},
        "evaluator": {"evaluation_count": 8,
                      "approved_count": 6},
        "applier": {"applied_count": 3},
        "identity_guard": {"intercept_count": 1,
                           "approval_count": 2},
        "experience": {"total": 40},
        "verification": {"confirmed": 20, "rejected": 2},
        "period_days": 30,
    }
    data.update(over)
    return data


class TestCombinedPatterns(unittest.TestCase):
    """多模式组合"""

    def setUp(self):
        self.integrator = ReflectionEmotionIntegrator()

    def test_success_plus_repetition(self):
        r = self.integrator.analyze(_report(patterns=[
            _pat("success_strategy", 0.9),
            _pat("repetition", 0.7),
        ]))
        self.assertEqual(r["emotion_context"], "success")

    def test_problem_plus_success_low(self):
        r = self.integrator.analyze(_report(patterns=[
            _pat("success_strategy", 0.5),
            _pat("problem_pattern", 0.95),
        ]))
        self.assertEqual(r["emotion_context"], "failure")

    def test_three_patterns_top_conf(self):
        r = self.integrator.analyze(_report(patterns=[
            _pat("repetition", 0.6),
            _pat("success_strategy", 0.8),
            _pat("problem_pattern", 0.7),
        ]))
        self.assertEqual(r["emotion_context"], "success")

    def test_problem_with_identity_conflict(self):
        r = self.integrator.analyze(_report(
            patterns=[_pat("problem_pattern")],
            contradictions=[{"conflict_type":
                             "identity_conflict"}],
        ))
        self.assertEqual(r["risk_level"], "high")
        self.assertLess(r["growth_value"], 0.35)

    def test_success_with_medium_conflict(self):
        r = self.integrator.analyze(_report(
            patterns=[_pat("success_strategy")],
            contradictions=[{"conflict_type":
                             "knowledge_conflict"}],
        ))
        self.assertEqual(r["growth_value"], 0.7)
        self.assertEqual(r["emotion_context"], "success")

    def test_no_pattern_medium_conflict(self):
        r = self.integrator.analyze(_report(
            contradictions=[{"conflict_type":
                             "knowledge_conflict"}],
        ))
        self.assertEqual(r["growth_value"], 0.45)
        self.assertEqual(r["emotion_analysis"]["state"],
                         "cautious")


class TestRepeatedAdjustments(unittest.TestCase):
    """连续调整稳定性"""

    def test_mixed_repeated_adjust(self):
        emotion = EmotionEngine()
        integrator = ReflectionEmotionIntegrator(
            emotion=emotion,
        )
        seq = ["success_strategy", "problem_pattern",
               "repetition", "problem_pattern",
               "success_strategy"]
        for ptype in seq:
            integrator.adjust(_report(
                patterns=[_pat(ptype)],
            ))
        state = emotion.get_state()
        for dim in ("positivity", "energy", "warmth"):
            self.assertGreaterEqual(state[dim], 0.0)
            self.assertLessEqual(state[dim], 1.0)

    def test_ten_successes_limited(self):
        emotion = EmotionEngine()
        integrator = ReflectionEmotionIntegrator(
            emotion=emotion,
        )
        for _ in range(10):
            integrator.adjust(_report(
                patterns=[_pat("success_strategy")],
            ))
        self.assertLessEqual(
            emotion.get_state()["positivity"], 1.0)

    def test_stats_reflect_all_contexts(self):
        emotion = EmotionEngine()
        integrator = ReflectionEmotionIntegrator(
            emotion=emotion,
        )
        integrator.adjust(_report(
            patterns=[_pat("success_strategy")],
        ))
        integrator.adjust(_report(
            patterns=[_pat("problem_pattern")],
        ))
        integrator.adjust(_report())
        dist = integrator.stats()["context_distribution"]
        self.assertEqual(dist, {"success": 1, "failure": 1})


class TestCycleDecisionMatrix(unittest.TestCase):
    """决策矩阵"""

    def setUp(self):
        from backend.embodied.companion.growth import (
            GrowthEvaluator,
            GrowthProposal,
        )
        from backend.embodied.companion.reflection import (
            CognitiveReflectionEngine,
        )
        self.engine = GrowthCycleEngine(
            reflection=CognitiveReflectionEngine(),
            proposal=GrowthProposal(),
            evaluator=GrowthEvaluator(),
            records_fn=lambda: [
                {"id": f"{trig}{i}", "type": "failure",
                 "trigger": trig, "result": "错误"}
                for trig in ("t1", "t2", "t3")
                for i in range(4)
            ],
        )
        self.engine.run(trigger="manual")

    def test_all_pending_approve(self):
        items = self.engine.pending()["items"]
        for item in items:
            r = self.engine.decide(item["pending_id"],
                                   "approve")
            self.assertFalse(r["applied"])
        stats = self.engine.stats()
        self.assertEqual(stats["pending_decisions"][
            "approve"], len(items))

    def test_all_pending_reject(self):
        items = self.engine.pending()["items"]
        for item in items:
            r = self.engine.decide(item["pending_id"],
                                   "reject")
            self.assertEqual(r["decision"], "reject")
        stats = self.engine.stats()
        self.assertEqual(stats["pending_decisions"][
            "reject"], len(items))

    def test_mixed_decisions(self):
        items = self.engine.pending()["items"]
        for i, item in enumerate(items):
            self.engine.decide(
                item["pending_id"],
                "approve" if i % 2 == 0 else "reject",
            )
        stats = self.engine.stats()
        self.assertGreater(stats["pending_decisions"][
            "approve"], 0)
        self.assertGreater(stats["pending_decisions"][
            "reject"], 0)

    def test_decide_twice_allowed(self):
        items = self.engine.pending()["items"]
        pid = items[0]["pending_id"]
        self.engine.decide(pid, "approve")
        self.engine.decide(pid, "reject")
        item = next(i for i in self.engine.pending()["items"]
                    if i["pending_id"] == pid)
        self.assertEqual(item["decision"], "reject")

    def test_pending_still_listed_after_approve(self):
        items = self.engine.pending()["items"]
        pid = items[0]["pending_id"]
        self.engine.decide(pid, "approve")
        ids = [i["pending_id"]
               for i in self.engine.pending()["items"]]
        self.assertIn(pid, ids)

    def test_evaluation_status_in_pending(self):
        item = self.engine.pending()["items"][0]
        self.assertIn("approved",
                      item["evaluation"])
        self.assertIn("score",
                      item["evaluation"])


class TestCycleBoundaries(unittest.TestCase):
    """边界触发"""

    def test_time_exact_boundary(self):
        engine = GrowthCycleEngine(cycle_days=1,
                                   records_fn=lambda: [])
        now = time.time()
        engine._last_run = now - 86400
        self.assertTrue(
            engine.check(experience_count=0,
                         now=now)["triggered"])

    def test_time_just_below(self):
        engine = GrowthCycleEngine(cycle_days=1,
                                   records_fn=lambda: [])
        now = time.time()
        engine._last_run = now - 86399.0
        self.assertFalse(
            engine.check(experience_count=0,
                         now=now)["triggered"])

    def test_event_exact_boundary(self):
        engine = GrowthCycleEngine(min_experience_delta=5,
                                   records_fn=lambda: [])
        engine._last_experience_count = 5
        self.assertTrue(
            engine.check(experience_count=10)["triggered"])

    def test_event_just_below(self):
        engine = GrowthCycleEngine(min_experience_delta=5,
                                   records_fn=lambda: [])
        engine._last_experience_count = 6
        self.assertFalse(
            engine.check(experience_count=10)["triggered"])

    def test_manual_overrides_disabled_check(self):
        engine = GrowthCycleEngine(enabled=False)
        r = engine.run(trigger="manual")
        self.assertIsNone(r["cycle"])

    def test_empty_records_manual(self):
        engine = GrowthCycleEngine(records_fn=lambda: [])
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")
        self.assertEqual(r["cycle"]["experience_count"], 0)

    def test_auto_after_manual_no_trigger(self):
        engine = GrowthCycleEngine(
            records_fn=lambda: [{"id": "x",
                                 "type": "failure",
                                 "result": "错误"}] * 6,
        )
        engine.run(trigger="manual")
        r = engine.run(trigger="auto")
        self.assertIsNone(r["cycle"])


class TestCycleTolerance(unittest.TestCase):
    """容错与空输入"""

    def test_records_fn_returns_none(self):
        engine = GrowthCycleEngine(records_fn=lambda: None)
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")
        self.assertEqual(r["cycle"]["experience_count"], 0)

    def test_records_fn_returns_dict(self):
        engine = GrowthCycleEngine(records_fn=lambda: {"x": 1})
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")

    def test_run_with_no_proposals(self):
        engine = GrowthCycleEngine(
            proposal=None,
            records_fn=lambda: [],
        )
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")
        self.assertEqual(r["pending_count"], 0)

    def test_cycle_after_clear(self):
        engine = GrowthCycleEngine(records_fn=lambda: [])
        engine.run(trigger="manual")
        engine.clear()
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")

    def test_check_negative_delta(self):
        engine = GrowthCycleEngine()
        engine._last_experience_count = 100
        r = engine.check(experience_count=10)
        self.assertFalse(r["triggered"])


class TestTrendCombinations(unittest.TestCase):
    """趋势组合输入"""

    def setUp(self):
        self.analysis = GrowthTrendAnalysis()

    def test_full_growth_stats(self):
        r = self.analysis.analyze(_stats(
            reflection={"reflection_count": 50},
            proposal={"proposal_count": 40},
            evaluator={"evaluation_count": 40,
                       "approved_count": 36},
            applier={"apply_count": 12,
                     "applied_count": 12},
            identity_guard={"intercept_count": 2,
                            "approval_count": 5,
                            "attempt_count": 7},
            experience={"total": 150, "confirmed": 80},
            verification={"confirmed": 80,
                          "rejected": 3},
            period_days=30,
        ))
        self.assertEqual(len(r["analysis"]), 9)
        self.assertGreaterEqual(r["growth_score"], 0.6)

    def test_none_input_tolerated(self):
        r = self.analysis.analyze(None)
        self.assertEqual(len(r["analysis"]), 9)
        self.assertEqual(r["growth_score"], 0.1)

    def test_null_section_tolerated(self):
        r = self.analysis.analyze({
            "reflection": None,
            "evaluator": None,
            "applier": None,
            "experience": None,
            "verification": None,
        })
        self.assertEqual(len(r["analysis"]), 9)

    def test_guard_attempts_fallback(self):
        r = self.analysis.analyze(_stats(
            identity_guard={"intercept_count": 3,
                            "approval_count": 0},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "identity_change_attempt")
        self.assertEqual(m["value"], 3)

    def test_guard_block_value(self):
        r = self.analysis.analyze(_stats(
            identity_guard={"intercept_count": 4},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "identity_guard_block")
        self.assertEqual(m["value"], 4)


class TestTrendWeights(unittest.TestCase):
    """权重贡献"""

    def test_identity_base_weight(self):
        r = self.analysis_empty()
        self.assertEqual(r["growth_score"], 0.1)

    def analysis_empty(self):
        return GrowthTrendAnalysis().analyze({
            "reflection": {"reflection_count": 0},
            "evaluator": {"evaluation_count": 0,
                          "approved_count": 0},
            "applier": {"applied_count": 0},
            "experience": {"total": 0},
            "verification": {"confirmed": 0,
                             "rejected": 0},
            "period_days": 30,
        })

    def test_reflection_full_weight(self):
        r = GrowthTrendAnalysis().analyze(_stats(
            reflection={"reflection_count": 100},
            evaluator={"evaluation_count": 0,
                       "approved_count": 0},
            applier={"applied_count": 0},
            experience={"total": 0},
            verification={"confirmed": 0, "rejected": 0},
            period_days=30,
        ))
        self.assertAlmostEqual(r["growth_score"],
                               0.3, places=4)

    def test_approval_full_weight(self):
        r = GrowthTrendAnalysis().analyze(_stats(
            reflection={"reflection_count": 0},
            evaluator={"evaluation_count": 10,
                       "approved_count": 10},
            applier={"applied_count": 0},
            experience={"total": 0},
            verification={"confirmed": 0, "rejected": 0},
            period_days=30,
        ))
        self.assertAlmostEqual(r["growth_score"],
                               0.35, places=4)

    def test_applied_full_weight(self):
        r = GrowthTrendAnalysis().analyze(_stats(
            reflection={"reflection_count": 0},
            evaluator={"evaluation_count": 0,
                       "approved_count": 0},
            applier={"applied_count": 30},
            experience={"total": 0},
            verification={"confirmed": 0, "rejected": 0},
            period_days=30,
        ))
        self.assertAlmostEqual(r["growth_score"],
                               0.25, places=4)

    def test_experience_full_weight(self):
        r = GrowthTrendAnalysis().analyze(_stats(
            reflection={"reflection_count": 0},
            evaluator={"evaluation_count": 0,
                       "approved_count": 0},
            applier={"applied_count": 0},
            experience={"total": 500},
            verification={"confirmed": 0, "rejected": 0},
            period_days=30,
        ))
        self.assertAlmostEqual(r["growth_score"],
                               0.25, places=4)

    def test_quality_full_weight(self):
        r = GrowthTrendAnalysis().analyze(_stats(
            reflection={"reflection_count": 0},
            evaluator={"evaluation_count": 0,
                       "approved_count": 0},
            applier={"applied_count": 0},
            experience={"total": 0},
            verification={"confirmed": 50, "rejected": 0},
            period_days=30,
        ))
        self.assertAlmostEqual(r["growth_score"],
                               0.25, places=4)


class TestEmotionEdgeInputs(unittest.TestCase):
    """情绪边界输入"""

    def setUp(self):
        self.integrator = ReflectionEmotionIntegrator()

    def test_none_report(self):
        r = self.integrator.analyze(None)
        self.assertEqual(r["emotion_context"], "idle")
        self.assertEqual(r["risk_level"], "low")

    def test_empty_patterns_list(self):
        r = self.integrator.analyze(_report(patterns=[]))
        self.assertEqual(r["emotion_context"], "idle")

    def test_pattern_missing_type(self):
        r = self.integrator.analyze(_report(patterns=[
            {"confidence": 0.9},
        ]))
        self.assertEqual(r["emotion_context"], "idle")

    def test_pattern_empty_type(self):
        r = self.integrator.analyze(_report(patterns=[
            {"type": "", "confidence": 0.9},
        ]))
        self.assertEqual(r["emotion_context"], "idle")

    def test_contradictions_empty(self):
        r = self.integrator.analyze(_report(
            contradictions=[],
        ))
        self.assertEqual(r["risk_level"], "low")

    def test_negative_growth_value_floor(self):
        r = self.integrator.analyze(_report(
            patterns=[_pat("problem_pattern")],
            contradictions=[{"conflict_type":
                             "value_conflict"}],
        ))
        self.assertGreaterEqual(r["growth_value"], 0.0)


class TestGeneratedDecideMatrix(unittest.TestCase):
    """生成式: 决策组合"""
    pass

# (pending 数, 决策序列) 长度校验
_DECIDE_CASES = [
    (1, ["approve"]),
    (2, ["approve", "reject"]),
    (3, ["reject", "reject", "approve"]),
    (3, ["approve", "approve", "reject"]),
]


def _make_decide(total, seq):
    def test(self):
        from backend.embodied.companion.growth import (
            GrowthEvaluator,
            GrowthProposal,
        )
        from backend.embodied.companion.reflection import (
            CognitiveReflectionEngine,
        )
        engine = GrowthCycleEngine(
            reflection=CognitiveReflectionEngine(),
            proposal=GrowthProposal(),
            evaluator=GrowthEvaluator(),
            records_fn=lambda: [
                {"id": f"{trig}{i}", "type": "failure",
                 "trigger": trig, "result": "错误"}
                for trig in ("t1", "t2", "t3")
                for i in range(4)
            ],
        )
        engine.run(trigger="manual")
        items = engine.pending()["items"][:total]
        for item, decision in zip(items, seq):
            r = engine.decide(item["pending_id"], decision)
            self.assertFalse(r["applied"])
        stats = engine.stats()
        self.assertEqual(
            stats["pending_decisions"]["approve"],
            seq.count("approve"))
        self.assertEqual(
            stats["pending_decisions"]["reject"],
            seq.count("reject"))
    test.__name__ = f"test_decide_seq_{len(_DECIDE_CASES)}"
    return test


for _i, (_total, _seq) in enumerate(_DECIDE_CASES):
    fn = _make_decide(_total, _seq)
    fn.__name__ = f"test_decide_seq_{_i}"
    fn.__doc__ = f"决策序列 {_seq}"
    setattr(TestGeneratedDecideMatrix, fn.__name__, fn)


class TestGeneratedRiskCombos(unittest.TestCase):
    """生成式: 模式×矛盾风险组合"""
    pass

# (pattern_type, conflict_type, 期望 risk)
_RISK_COMBOS = [
    ("success_strategy", None, "low"),
    ("success_strategy", "identity_conflict", "high"),
    ("problem_pattern", "knowledge_conflict", "medium"),
    ("repetition", "value_conflict", "high"),
    (None, "identity_conflict", "high"),
    (None, None, "low"),
    ("unknown_type", "knowledge_conflict", "medium"),
]


for _i, (_ptype, _ctype, _risk) in enumerate(_RISK_COMBOS):
    def _make(ptype=_ptype, ctype=_ctype, risk=_risk):
        def test(self):
            conflicts = []
            if ctype:
                conflicts.append({"conflict_type": ctype})
            patterns = [_pat(ptype)] if ptype else []
            r = ReflectionEmotionIntegrator().analyze(
                _report(patterns=patterns,
                        contradictions=conflicts),
            )
            self.assertEqual(r["risk_level"], risk)
        test.__name__ = f"test_risk_combo_{_i}"
        test.__doc__ = f"风险组合 {_ptype}/{_ctype}"
        return test
    setattr(TestGeneratedRiskCombos,
            _make().__name__, _make())


class TestGeneratedInvalidInputs(unittest.TestCase):
    """生成式: 非法输入容错"""
    pass

# (报告 dict, 期望不抛异常)
_INVALID_REPORTS = [
    None,
    {},
    {"patterns": "not-a-list"},
    {"patterns": [123]},
    {"contradictions": "not-a-list"},
    {"patterns": [None]},
    {"confidence": "high"},
]


for _i, _bad in enumerate(_INVALID_REPORTS):
    def _make(bad=_bad):
        def test(self):
            r = ReflectionEmotionIntegrator().analyze(bad)
            self.assertIn("result_id", r)
            self.assertIn("emotion_context", r)
        test.__name__ = f"test_invalid_report_{_i}"
        test.__doc__ = f"非法报告 {_i}"
        return test
    setattr(TestGeneratedInvalidInputs,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
