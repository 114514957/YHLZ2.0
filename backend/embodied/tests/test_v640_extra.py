"""
YHLZ Embodied AI V6.4 - 认知集成补充测试 (V6.4 Extra)

覆盖 (专项补足):
    - 反思规则细节
    - 反事实边界
    - 经验对象边界
    - 网关增强细节
    - 快照细节
"""
import unittest

from backend.embodied.companion.experience import (
    MultimodalExperience,
    Provenance,
)
from backend.embodied.companion.perception import (
    ApprovalRule,
    CounterfactualCheck,
    MemoryGate,
    PerceptionStatsSnapshot,
    ReflectionEvaluator,
    ReflectionRules,
)


def make_candidate(**over):
    c = {
        "candidate_id": "mc_1",
        "source": "camera",
        "kind": "ocr",
        "summary": "用户屏幕显示重要任务清单",
        "confidence": 0.9,
        "occurrence_count": 1,
    }
    c.update(over)
    return c


def make_prov(**over):
    p = {
        "origin": "vision",
        "source_event": "pe_1",
        "verification_score": 0.9,
        "reflection_reason": "通过",
        "approved_by": "memory_gate",
    }
    p.update(over)
    return p


class TestRulesDetails(unittest.TestCase):
    """反思规则细节"""

    def setUp(self):
        self.rules = ReflectionRules()

    def test_credibility_screen(self):
        d = self.rules._credibility(make_candidate(source="screen",
                                                   confidence=1.0))
        self.assertGreaterEqual(d["score"], 0.8)

    def test_credibility_unknown(self):
        d = self.rules._credibility(make_candidate(source="weird",
                                                   confidence=0.5))
        self.assertLess(d["score"], 0.5)

    def test_consistency_clean(self):
        d = self.rules._consistency(make_candidate(), [])
        self.assertEqual(d["score"], 0.8)

    def test_consistency_keyword(self):
        d = self.rules._consistency(make_candidate(
            summary="任务取消",
        ), [])
        self.assertLess(d["score"], 0.5)

    def test_consistency_known_overlap(self):
        d = self.rules._consistency(
            make_candidate(),
            [{"trigger": "用户屏幕显示", "lesson": "l"}],
        )
        self.assertLess(d["score"], 0.5)

    def test_value_keyword_multi(self):
        d = self.rules._long_term_value(make_candidate(
            summary="重要目标任务计划",
        ))
        self.assertGreater(d["score"], 0.8)

    def test_value_no_keyword(self):
        d = self.rules._long_term_value(make_candidate(
            summary="x", confidence=0.0,
        ))
        self.assertEqual(d["score"], 0.4)

    def test_identity_no_keyword(self):
        d = self.rules._identity_impact(make_candidate(summary="x"))
        self.assertEqual(d["score"], 0.5)

    def test_risk_clean_low(self):
        d = self.rules._risk(make_candidate())
        self.assertEqual(d["score"], 0.2)

    def test_risk_payment(self):
        d = self.rules._risk(make_candidate(summary="授权支付"))
        self.assertEqual(d["score"], 0.5)

    def test_pattern_with_known(self):
        p = self.rules._find_pattern(
            make_candidate(),
            [{"trigger": "用户屏幕显示重要", "lesson": "l"}],
        )
        self.assertIn("相似", p)

    def test_pattern_empty_known(self):
        p = self.rules._find_pattern(make_candidate(), [])
        self.assertIn("无匹配", p)

    def test_value_hint_custom(self):
        h = self.rules._value_hint(make_candidate(summary="学习目标"))
        self.assertIn("建议保存", h)


class TestEvaluatorDetails(unittest.TestCase):
    """评估器细节"""

    def test_evaluate_known_experiences(self):
        e = ReflectionEvaluator()
        r = e.evaluate(make_candidate(), [
            {"trigger": "重要任务", "lesson": "l"},
        ])
        self.assertIn("评估", r["reason"])

    def test_stats_mode(self):
        e = ReflectionEvaluator()
        self.assertEqual(e.stats()["mode"], "rule_based")

    def test_audit_mode(self):
        e = ReflectionEvaluator()
        self.assertEqual(e.audit_report()["mode"], "rule_based")

    def test_recommendation_reason(self):
        e = ReflectionEvaluator()
        r = e.evaluate(make_candidate())
        self.assertTrue(r["recommendation_reason"])

    def test_dimensions_explainable(self):
        e = ReflectionEvaluator()
        r = e.evaluate(make_candidate())
        for d in r["dimensions"]:
            self.assertTrue(d["reason"])

    def test_contradiction_recommendation_reject(self):
        e = ReflectionEvaluator()
        r = e.evaluate(make_candidate(summary="任务失败取消"))
        self.assertEqual(r["recommendation"], "reject")
        self.assertIn("矛盾", r["recommendation_reason"])


class TestCounterfactualDetails(unittest.TestCase):
    """反事实细节"""

    def test_check_id_prefix(self):
        r = CounterfactualCheck().check(make_candidate())
        self.assertTrue(r["check_id"].startswith("cc_"))

    def test_stats_zero(self):
        st = CounterfactualCheck().stats()
        self.assertEqual(st["check_count"], 0)

    def test_disabled_stats(self):
        c = CounterfactualCheck(enabled=False)
        c.check(make_candidate())
        st = c.stats()
        self.assertEqual(st["check_count"], 1)  # 仍记录

    def test_score_holds_high(self):
        r = CounterfactualCheck().check(make_candidate(
            occurrence_count=3,
        ))
        self.assertEqual(r["score"], 0.9)

    def test_reason_explainable(self):
        r = CounterfactualCheck().check(make_candidate())
        self.assertTrue(r["reason"])

    def test_high_stake_words(self):
        from backend.embodied.companion.perception import (
            HIGH_STAKE_KEYWORDS,
        )
        self.assertIn("支付", HIGH_STAKE_KEYWORDS)
        self.assertIn("删除", HIGH_STAKE_KEYWORDS)

    def test_clear_empty(self):
        self.assertEqual(CounterfactualCheck().clear(), 0)


class TestExperienceDetails(unittest.TestCase):
    """经验对象细节"""

    def test_prov_id_unique(self):
        p1 = Provenance.create(**make_prov())
        p2 = Provenance.create(**make_prov())
        self.assertNotEqual(p1.provenance_id, p2.provenance_id)

    def test_prov_all_approvers(self):
        for a in ("memory_gate", "reflection", "user", "system"):
            p = Provenance.create(**{**make_prov(),
                                     "approved_by": a})
            ok, reason = p.validate()
            self.assertTrue(ok, a)

    def test_mexp_id_prefix(self):
        e = MultimodalExperience.create(
            source="vision", modalities=["vision"], meaning="m",
            confidence=0.9, provenance=make_prov(),
        )
        self.assertTrue(e.experience_id.startswith("mexp_"))

    def test_mexp_impact_kept(self):
        e = MultimodalExperience.create(
            source="vision", modalities=["vision"], meaning="m",
            confidence=0.9, impact="重要参考",
            provenance=make_prov(),
        )
        self.assertEqual(e.impact, "重要参考")

    def test_mexp_meaning_kept(self):
        e = MultimodalExperience.create(
            source="text", modalities=["text"], meaning="用户文本",
            confidence=0.9, provenance=make_prov(origin="text"),
        )
        self.assertEqual(e.meaning, "用户文本")

    def test_mexp_confidence_kept(self):
        e = MultimodalExperience.create(
            source="vision", modalities=["vision"], meaning="m",
            confidence=0.75, provenance=make_prov(),
        )
        self.assertEqual(e.confidence, 0.75)


class TestGateDetails(unittest.TestCase):
    """网关增强细节"""

    def test_gate_default_evaluator(self):
        g = MemoryGate()
        self.assertIsNotNone(g._evaluator)
        self.assertIsNotNone(g._counterfactual)

    def test_gate_inject_evaluator(self):
        e = ReflectionEvaluator()
        g = MemoryGate(evaluator=e)
        self.assertIs(g._evaluator, e)

    def test_gate_inject_counterfactual(self):
        c = CounterfactualCheck()
        g = MemoryGate(counterfactual=c)
        self.assertIs(g._counterfactual, c)

    def test_gate_steps_order(self):
        g = MemoryGate()
        r = g.process(make_candidate(), store_fn=lambda c: {})
        steps = [s["step"] for s in r["steps"]]
        self.assertEqual(steps[0], "candidate_validator")
        self.assertEqual(steps[1], "reflection_evaluation")
        self.assertEqual(steps[2], "counterfactual_check")
        self.assertEqual(steps[3], "approval")

    def test_gate_counterfactual_step_reason(self):
        g = MemoryGate()
        r = g.process(make_candidate(
            summary="任务", confidence=0.3,
        ), store_fn=lambda c: {})
        step = next((s for s in r["steps"]
                     if s["step"] == "counterfactual_check"), None)
        if step is not None:
            self.assertFalse(step["ok"])
        else:
            # 反思提前拒绝 (低价值) 同样不形成经验
            self.assertEqual(r["status"], "rejected")

    def test_approval_dimension_reflection_reason(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.7)
        dim = next(d for d in r["dimensions"]
                   if d["name"] == "reflection")
        self.assertIn("反思", dim["reason"])

    def test_approval_6dim_average(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.8)
        total = sum(d["score"] for d in r["dimensions"])
        self.assertAlmostEqual(r["final_score"], total / 6,
                               places=4)


class TestSnapshotDetails(unittest.TestCase):
    """快照细节"""

    def test_collect_all_sources(self):
        s = PerceptionStatsSnapshot()
        data = s.collect(
            perception_stats={"event_count": 1},
            gate_stats={"candidate_count": 1,
                        "approved_count": 1},
            evaluator_stats={"evaluated_count": 2},
            counterfactual_stats={"check_count": 1},
        )
        self.assertEqual(data["memory_gate"]["approved_count"], 1)
        self.assertEqual(data["reflection"]["evaluated_count"], 2)

    def test_collect_verification_kept(self):
        s = PerceptionStatsSnapshot()
        data = s.collect(perception_stats={
            "verification": {"approved_count": 1,
                             "rejected_count": 0},
        })
        self.assertEqual(
            data["perception"]["verification"]["approved_count"], 1,
        )

    def test_restore_returns_ok(self):
        s = PerceptionStatsSnapshot()
        ok, reason = s.restore({"perception": {}})
        self.assertTrue(ok)
        self.assertIn("已恢复", reason)

    def test_restore_empty_dict(self):
        s = PerceptionStatsSnapshot()
        ok, reason = s.restore({})
        self.assertTrue(ok)

    def test_clear_empty(self):
        s = PerceptionStatsSnapshot()
        self.assertEqual(s.clear(), 0)

    def test_stats_enabled(self):
        s = PerceptionStatsSnapshot(enabled=False)
        st = s.stats()
        self.assertFalse(st["enabled"])


if __name__ == "__main__":
    unittest.main()
