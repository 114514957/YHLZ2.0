"""
YHLZ Embodied AI V6.4 - 反思评估单元测试 (Reflection Evaluation)

覆盖 (memory_gate/reflection/):
    - 反思规则: 5 维 (可信度/一致性/价值/身份/风险)
    - 评估器: 评分/模式/矛盾/建议 (Advisor)
    - 反事实验证: 高风险单一来源拒绝
    - 反思审计
"""
import unittest

from backend.embodied.companion.perception import (
    CONTRADICTION_KEYWORDS,
    CounterfactualCheck,
    CounterfactualError,
    HIGH_STAKE_KEYWORDS,
    ReflectionAudit,
    ReflectionEvaluator,
    ReflectionRules,
    ReflectionRulesError,
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


class TestReflectionRules(unittest.TestCase):
    """反思规则"""

    def setUp(self):
        self.rules = ReflectionRules()

    def test_evaluate_structure(self):
        r = self.rules.evaluate(make_candidate())
        for key in ("reflection_score", "pattern", "contradiction",
                    "value_hint", "reason", "dimensions", "mode"):
            self.assertIn(key, r)

    def test_five_dimensions(self):
        r = self.rules.evaluate(make_candidate())
        names = {d["name"] for d in r["dimensions"]}
        self.assertEqual(names, {"credibility", "consistency",
                                 "long_term_value",
                                 "identity_impact", "risk"})

    def test_score_range(self):
        r = self.rules.evaluate(make_candidate())
        self.assertGreaterEqual(r["reflection_score"], 0.0)
        self.assertLessEqual(r["reflection_score"], 1.0)

    def test_high_value_high_score(self):
        r = self.rules.evaluate(make_candidate())
        self.assertGreaterEqual(r["reflection_score"], 0.5)

    def test_low_value_low_score(self):
        r = self.rules.evaluate(make_candidate(
            source="mock", summary="x", confidence=0.2,
        ))
        self.assertLess(r["reflection_score"], 0.5)

    def test_contradiction_detected(self):
        r = self.rules.evaluate(make_candidate(
            summary="支付确认失败",
        ))
        self.assertTrue(r["contradiction"])

    def test_contradiction_empty_clean(self):
        r = self.rules.evaluate(make_candidate())
        self.assertEqual(r["contradiction"], "")

    def test_consistency_with_known(self):
        r = self.rules.evaluate(
            make_candidate(),
            known_experiences=[
                {"trigger": "重要任务", "lesson": "l"},
            ],
        )
        self.assertIn("相似", r["pattern"])

    def test_no_pattern(self):
        r = self.rules.evaluate(make_candidate())
        self.assertIn("无匹配模式", r["pattern"])

    def test_value_hint_positive(self):
        r = self.rules.evaluate(make_candidate())
        self.assertIn("建议保存", r["value_hint"])

    def test_value_hint_caution(self):
        r = self.rules.evaluate(make_candidate(summary="x"))
        self.assertIn("谨慎", r["value_hint"])

    def test_credibility_camera(self):
        d = self.rules._credibility(make_candidate())
        self.assertGreater(d["score"], 0.8)

    def test_credibility_mock(self):
        d = self.rules._credibility(make_candidate(source="mock",
                                                   confidence=0.5))
        self.assertEqual(d["score"], 0.5)

    def test_risk_detected(self):
        d = self.rules._risk(make_candidate(summary="删除数据"))
        self.assertEqual(d["score"], 0.5)

    def test_risk_clean(self):
        d = self.rules._risk(make_candidate())
        self.assertEqual(d["score"], 0.2)

    def test_identity_keyword(self):
        d = self.rules._identity_impact(make_candidate(
            summary="身份价值观",
        ))
        self.assertGreater(d["score"], 0.5)

    def test_threshold_validation(self):
        with self.assertRaises(ReflectionRulesError):
            ReflectionRules(threshold=1.5)

    def test_threshold_getter(self):
        self.assertEqual(ReflectionRules(threshold=0.7).threshold(),
                         0.7)

    def test_stats(self):
        st = self.rules.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertEqual(len(st["dimensions"]), 5)

    def test_keywords_nonempty(self):
        self.assertTrue(CONTRADICTION_KEYWORDS)
        self.assertTrue(HIGH_STAKE_KEYWORDS)


class TestReflectionEvaluator(unittest.TestCase):
    """反思评估器"""

    def setUp(self):
        self.evaluator = ReflectionEvaluator()

    def test_evaluate_structure(self):
        r = self.evaluator.evaluate(make_candidate())
        for key in ("evaluation_id", "reflection_score", "pattern",
                    "contradiction", "value_hint", "reason",
                    "recommendation", "dimensions", "mode"):
            self.assertIn(key, r)

    def test_eval_id_prefix(self):
        r = self.evaluator.evaluate(make_candidate())
        self.assertTrue(r["evaluation_id"].startswith("refe_"))

    def test_high_value_approve(self):
        r = self.evaluator.evaluate(make_candidate())
        self.assertEqual(r["recommendation"], "approve")

    def test_low_value_reject(self):
        r = self.evaluator.evaluate(make_candidate(
            source="mock", summary="x", confidence=0.2,
        ))
        self.assertEqual(r["recommendation"], "reject")

    def test_contradiction_reject(self):
        r = self.evaluator.evaluate(make_candidate(
            summary="支付确认失败",
        ))
        self.assertEqual(r["recommendation"], "reject")

    def test_invalid_candidate(self):
        with self.assertRaises(Exception):
            self.evaluator.evaluate(None)

    def test_disabled_neutral(self):
        e = ReflectionEvaluator(enabled=False)
        r = e.evaluate(make_candidate())
        self.assertEqual(r["recommendation"], "neutral")
        self.assertEqual(r["reflection_score"], 0.5)

    def test_stats(self):
        self.evaluator.evaluate(make_candidate())
        self.evaluator.evaluate(make_candidate(
            source="mock", summary="x", confidence=0.2,
        ))
        st = self.evaluator.stats()
        self.assertEqual(st["evaluated_count"], 2)
        self.assertEqual(st["by_recommendation"]["approve"], 1)
        self.assertEqual(st["by_recommendation"]["reject"], 1)

    def test_stats_avg(self):
        self.evaluator.evaluate(make_candidate())
        st = self.evaluator.stats()
        self.assertGreaterEqual(st["avg_reflection_score"], 0.0)

    def test_audit_recorded(self):
        self.evaluator.evaluate(make_candidate())
        r = self.evaluator.audit_report()
        self.assertGreaterEqual(r["by_action"].get(
            "evaluate", 0), 1)

    def test_clear(self):
        self.evaluator.evaluate(make_candidate())
        n = self.evaluator.clear()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(self.evaluator.stats()[
            "evaluated_count"], 0)

    def test_mode(self):
        r = self.evaluator.evaluate(make_candidate())
        self.assertEqual(r["mode"], "rule_based")


class TestCounterfactual(unittest.TestCase):
    """反事实验证"""

    def setUp(self):
        self.checker = CounterfactualCheck()

    def test_check_structure(self):
        r = self.checker.check(make_candidate())
        for key in ("check_id", "status", "reason", "score",
                    "mode"):
            self.assertIn(key, r)

    def test_high_confidence_holds(self):
        r = self.checker.check(make_candidate())
        self.assertEqual(r["status"], "holds")

    def test_high_stake_single_fails(self):
        """'支付成功' 仅一次 → 反事实不成立"""
        r = self.checker.check(make_candidate(
            summary="支付成功",
        ))
        self.assertEqual(r["status"], "fails")
        self.assertIn("高风险", r["reason"])

    def test_high_stake_repeated_holds(self):
        r = self.checker.check(make_candidate(
            summary="支付成功", occurrence_count=3,
        ))
        self.assertEqual(r["status"], "holds")

    def test_low_conf_no_repeat_fails(self):
        r = self.checker.check(make_candidate(
            confidence=0.3,
        ))
        self.assertEqual(r["status"], "fails")

    def test_disabled_neutral(self):
        c = CounterfactualCheck(enabled=False)
        r = c.check(make_candidate())
        self.assertEqual(r["status"], "neutral")

    def test_stats(self):
        self.checker.check(make_candidate())
        self.checker.check(make_candidate(summary="支付成功"))
        st = self.checker.stats()
        self.assertEqual(st["check_count"], 2)
        self.assertEqual(st["holds_count"], 1)
        self.assertEqual(st["fails_count"], 1)

    def test_clear(self):
        self.checker.check(make_candidate())
        self.assertEqual(self.checker.clear(), 1)

    def test_min_conf_validation(self):
        with self.assertRaises(CounterfactualError):
            CounterfactualCheck(min_confidence=1.5)

    def test_min_occurrences_validation(self):
        with self.assertRaises(CounterfactualError):
            CounterfactualCheck(min_occurrences=1)

    def test_score_values(self):
        r1 = self.checker.check(make_candidate())
        self.assertGreaterEqual(r1["score"], 0.7)
        r2 = self.checker.check(make_candidate(summary="支付成功"))
        self.assertLessEqual(r2["score"], 0.3)

    def test_mode(self):
        r = self.checker.check(make_candidate())
        self.assertEqual(r["mode"], "rule_based")


class TestReflectionAudit(unittest.TestCase):
    """反思审计"""

    def test_record(self):
        a = ReflectionAudit()
        e = a.record(action="evaluate", detail="approve")
        self.assertTrue(e["audit_id"].startswith("refa_"))

    def test_actions_whitelist(self):
        from backend.embodied.companion.perception import (
            REFLECTION_AUDIT_ACTIONS,
        )
        self.assertIn("evaluate", REFLECTION_AUDIT_ACTIONS)
        self.assertIn("counterfactual",
                      REFLECTION_AUDIT_ACTIONS)

    def test_record_invalid(self):
        a = ReflectionAudit()
        from backend.embodied.companion.perception.memory_gate.reflection.reflection_audit import (
            AuditError,
        )
        with self.assertRaises(AuditError):
            a.record(action="hack")

    def test_report(self):
        a = ReflectionAudit()
        a.record(action="evaluate")
        r = a.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["by_action"]["evaluate"], 1)

    def test_clear(self):
        a = ReflectionAudit()
        a.record(action="evaluate")
        self.assertEqual(a.clear(), 1)


if __name__ == "__main__":
    unittest.main()
