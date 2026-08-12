"""
YHLZ Embodied AI V5.9 - 价值评估器单元测试 (Value Evaluator)

覆盖 (value_evaluator.py):
    - 5 维评估: Impact / Frequency / Benefit / Feasibility / Risk
    - 加权价值分 (VALUE_WEIGHTS)
    - 决策: create / defer / reject (阈值)
    - 可解释: 每维 reason / decision_reason
    - 查询 / 统计 / 异常
"""
import unittest

from backend.embodied.companion.creative import (
    DECISIONS,
    VALUE_WEIGHTS,
    EvaluationError,
    ValueEvaluator,
)


def make_opportunity(opp_id="opp_1", source_type="repetition",
                     trigger="重复需求", evidence=None,
                     confidence=0.8):
    """构造机会候选"""
    if evidence is None:
        evidence = [f"exp_{i}" for i in range(3)]
    return {
        "opportunity_id": opp_id,
        "problem": f"{trigger}问题",
        "current_state": "手动处理",
        "desired_state": "自动处理",
        "gap": "缺乏自动化",
        "source_type": source_type,
        "trigger": trigger,
        "evidence": evidence,
        "confidence": confidence,
        "created_at": 1000.0,
    }


def make_experience(trigger="重复需求", type="improvement",
                    result="成功", value=0.8, rid="exp_0"):
    """构造经历"""
    return {
        "id": rid, "type": type, "trigger": trigger,
        "lesson": "l", "result": result, "value": value,
    }


class TestEvaluatorInit(unittest.TestCase):
    """初始化与参数校验"""

    def test_default_init(self):
        v = ValueEvaluator()
        self.assertIsNotNone(v)

    def test_create_threshold_validation_high(self):
        with self.assertRaises(EvaluationError):
            ValueEvaluator(create_threshold=1.5)

    def test_create_threshold_validation_low(self):
        with self.assertRaises(EvaluationError):
            ValueEvaluator(create_threshold=-0.1)

    def test_defer_threshold_validation(self):
        with self.assertRaises(EvaluationError):
            ValueEvaluator(defer_threshold=1.5)

    def test_defer_must_be_less_than_create(self):
        with self.assertRaises(EvaluationError):
            ValueEvaluator(create_threshold=0.4, defer_threshold=0.6)

    def test_decisions_whitelist(self):
        self.assertEqual(set(DECISIONS), {"create", "defer", "reject"})

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(VALUE_WEIGHTS.values()), 1.0, places=6)

    def test_weights_keys(self):
        for key in ("impact", "frequency", "benefit",
                    "feasibility", "risk"):
            self.assertIn(key, VALUE_WEIGHTS)


class TestEvaluateStructure(unittest.TestCase):
    """评估结果结构"""

    def setUp(self):
        self.evaluator = ValueEvaluator()
        self.opp = make_opportunity()

    def test_evaluate_structure(self):
        r = self.evaluator.evaluate(self.opp)
        for key in ("evaluation_id", "opportunity_id", "value_score",
                    "impact", "frequency", "benefit", "feasibility",
                    "risk", "dimensions", "decision", "decision_reason",
                    "mode", "evaluated_at"):
            self.assertIn(key, r)

    def test_eval_id_prefix(self):
        r = self.evaluator.evaluate(self.opp)
        self.assertTrue(r["evaluation_id"].startswith("eval_"))

    def test_mode_rule_based(self):
        r = self.evaluator.evaluate(self.opp)
        self.assertEqual(r["mode"], "rule_based")

    def test_score_range(self):
        r = self.evaluator.evaluate(self.opp)
        self.assertGreaterEqual(r["value_score"], 0.0)
        self.assertLessEqual(r["value_score"], 1.0)

    def test_decision_in_whitelist(self):
        r = self.evaluator.evaluate(self.opp)
        self.assertIn(r["decision"], DECISIONS)

    def test_dimensions_five(self):
        r = self.evaluator.evaluate(self.opp)
        self.assertEqual(len(r["dimensions"]), 5)

    def test_dimension_names(self):
        r = self.evaluator.evaluate(self.opp)
        names = {d["name"] for d in r["dimensions"]}
        self.assertEqual(names, {"impact", "frequency", "benefit",
                                 "feasibility", "risk"})

    def test_dimension_reason_explainable(self):
        r = self.evaluator.evaluate(self.opp)
        for d in r["dimensions"]:
            self.assertTrue(d["reason"])

    def test_levels_valid(self):
        r = self.evaluator.evaluate(self.opp)
        for d in r["dimensions"]:
            self.assertIn(d["level"], ("high", "medium", "low"))

    def test_missing_opportunity_id(self):
        with self.assertRaises(EvaluationError):
            self.evaluator.evaluate({})

    def test_none_opportunity(self):
        with self.assertRaises(EvaluationError):
            self.evaluator.evaluate(None)


class TestDimensionScoring(unittest.TestCase):
    """维度评分规则"""

    def setUp(self):
        self.evaluator = ValueEvaluator()

    def test_impact_high_with_many_evidence(self):
        opp = make_opportunity(
            evidence=[f"e{i}" for i in range(4)],
            source_type="failure",
        )
        r = self.evaluator.evaluate(opp)
        self.assertEqual(r["impact"], "high")

    def test_impact_low_with_one_evidence(self):
        opp = make_opportunity(evidence=[], source_type="pattern")
        r = self.evaluator.evaluate(opp)
        self.assertEqual(r["impact"], "low")

    def test_frequency_high_five_evidence(self):
        opp = make_opportunity(evidence=[f"e{i}" for i in range(5)])
        r = self.evaluator.evaluate(opp)
        self.assertEqual(r["frequency"], "high")

    def test_frequency_medium_three_evidence(self):
        opp = make_opportunity(evidence=[f"e{i}" for i in range(3)])
        r = self.evaluator.evaluate(opp)
        self.assertEqual(r["frequency"], "medium")

    def test_frequency_low_one_evidence(self):
        opp = make_opportunity(evidence=["e0"])
        r = self.evaluator.evaluate(opp)
        self.assertEqual(r["frequency"], "low")

    def test_benefit_high_trust(self):
        opp = make_opportunity()
        r = self.evaluator.evaluate(
            opp, relationship={"trust": 0.9},
        )
        self.assertEqual(r["benefit"], "high")

    def test_benefit_low_trust(self):
        opp = make_opportunity()
        r = self.evaluator.evaluate(
            opp, relationship={"trust": 0.1},
        )
        self.assertEqual(r["benefit"], "low")

    def test_benefit_relationship_bonus(self):
        opp = make_opportunity(source_type="relationship")
        r = self.evaluator.evaluate(
            opp, relationship={"trust": 0.5},
        )
        self.assertGreaterEqual(r["benefit"], "medium")

    def test_feasibility_high_success_rate(self):
        opp = make_opportunity()
        exps = [
            make_experience(result="成功", rid=f"e{i}")
            for i in range(8)
        ]
        r = self.evaluator.evaluate(opp, confirmed_experiences=exps)
        self.assertEqual(r["feasibility"], "high")

    def test_feasibility_low_failure_rate(self):
        opp = make_opportunity()
        exps = [
            make_experience(type="failure", result="错误", rid=f"e{i}")
            for i in range(8)
        ]
        r = self.evaluator.evaluate(opp, confirmed_experiences=exps)
        self.assertEqual(r["feasibility"], "low")

    def test_feasibility_no_experience_medium(self):
        opp = make_opportunity()
        r = self.evaluator.evaluate(opp, confirmed_experiences=[])
        self.assertEqual(r["feasibility"], "medium")

    def test_risk_high_failure_ratio(self):
        opp = make_opportunity()
        exps = (
            [make_experience(type="failure", rid=f"f{i}")
             for i in range(5)]
            + [make_experience(rid=f"s{i}") for i in range(5)]
        )
        r = self.evaluator.evaluate(opp, confirmed_experiences=exps)
        self.assertEqual(r["risk"], "high")

    def test_risk_low_no_failures(self):
        opp = make_opportunity()
        exps = [
            make_experience(rid=f"e{i}") for i in range(5)
        ]
        r = self.evaluator.evaluate(opp, confirmed_experiences=exps)
        self.assertEqual(r["risk"], "low")

    def test_risk_no_experience_low(self):
        opp = make_opportunity()
        r = self.evaluator.evaluate(opp, confirmed_experiences=[])
        self.assertEqual(r["risk"], "low")


class TestDecisionRules(unittest.TestCase):
    """决策规则"""

    def test_create_high_value(self):
        v = ValueEvaluator(create_threshold=0.3, defer_threshold=0.2)
        opp = make_opportunity(
            evidence=[f"e{i}" for i in range(6)],
            confidence=0.95,
        )
        r = v.evaluate(opp)
        self.assertEqual(r["decision"], "create")

    def test_reject_low_value(self):
        v = ValueEvaluator(create_threshold=0.9, defer_threshold=0.6)
        opp = make_opportunity(evidence=["e0"], confidence=0.3)
        r = v.evaluate(opp)
        self.assertEqual(r["decision"], "reject")

    def test_defer_middle(self):
        v = ValueEvaluator(create_threshold=0.8, defer_threshold=0.3)
        opp = make_opportunity(evidence=["e0"], confidence=0.5)
        r = v.evaluate(opp)
        self.assertEqual(r["decision"], "defer")

    def test_decision_reason_contains_score(self):
        v = ValueEvaluator(create_threshold=0.9)
        opp = make_opportunity(evidence=["e0"], confidence=0.4)
        r = v.evaluate(opp)
        self.assertIn("0.", r["decision_reason"])

    def test_decision_reason_create(self):
        v = ValueEvaluator(create_threshold=0.2, defer_threshold=0.1)
        opp = make_opportunity()
        r = v.evaluate(opp)
        self.assertIn("值得", r["decision_reason"])

    def test_decision_reason_reject(self):
        v = ValueEvaluator(create_threshold=0.99, defer_threshold=0.98)
        opp = make_opportunity(evidence=["e0"], confidence=0.2)
        r = v.evaluate(opp)
        self.assertIn("不值得", r["decision_reason"])


class TestValueScore(unittest.TestCase):
    """价值分计算"""

    def test_high_success_rate_raises_score(self):
        v = ValueEvaluator()
        opp = make_opportunity(
            evidence=[f"e{i}" for i in range(5)],
        )
        exps_ok = [
            make_experience(result="成功", rid=f"e{i}")
            for i in range(10)
        ]
        r_ok = v.evaluate(opp, confirmed_experiences=exps_ok)
        v2 = ValueEvaluator()
        exps_fail = [
            make_experience(type="failure", result="错误", rid=f"e{i}")
            for i in range(10)
        ]
        r_fail = v2.evaluate(opp, confirmed_experiences=exps_fail)
        self.assertGreater(r_ok["value_score"], r_fail["value_score"])

    def test_more_evidence_raises_score(self):
        v = ValueEvaluator()
        opp_low = make_opportunity(evidence=["e0"])
        opp_high = make_opportunity(
            evidence=[f"e{i}" for i in range(6)],
        )
        r_low = v.evaluate(opp_low)
        r_high = v.evaluate(opp_high)
        self.assertGreater(r_high["value_score"], r_low["value_score"])

    def test_risk_inverted_in_score(self):
        """风险维度以 (1-risk) 参与评分"""
        v = ValueEvaluator()
        opp = make_opportunity()
        exps_risk = [
            make_experience(type="failure", rid=f"f{i}")
            for i in range(8)
        ]
        r = v.evaluate(opp, confirmed_experiences=exps_risk)
        risk_dim = next(
            d for d in r["dimensions"] if d["name"] == "risk"
        )
        self.assertGreaterEqual(risk_dim["score"], 0.0)


class TestQueryAndStats(unittest.TestCase):
    """查询与统计"""

    def setUp(self):
        self.evaluator = ValueEvaluator()
        self.opp = make_opportunity()
        self.result = self.evaluator.evaluate(self.opp)

    def test_get_by_id(self):
        r = self.evaluator.get(self.result["evaluation_id"])
        self.assertEqual(r["opportunity_id"], "opp_1")

    def test_get_missing(self):
        self.assertIsNone(self.evaluator.get("eval_nonexist"))

    def test_by_opportunity(self):
        results = self.evaluator.by_opportunity("opp_1")
        self.assertEqual(len(results), 1)

    def test_by_opportunity_none(self):
        self.assertEqual(
            self.evaluator.by_opportunity("opp_none"), [],
        )

    def test_stats_structure(self):
        st = self.evaluator.stats()
        for key in ("mode", "evaluation_count", "avg_value_score",
                    "by_decision", "by_risk", "create_count",
                    "defer_count", "reject_count"):
            self.assertIn(key, st)

    def test_stats_counts(self):
        st = self.evaluator.stats()
        self.assertEqual(st["evaluation_count"], 1)
        self.assertEqual(st["create_count"]
                         + st["defer_count"] + st["reject_count"], 1)

    def test_clear(self):
        self.evaluator.clear()
        self.assertEqual(self.evaluator.stats()["evaluation_count"], 0)

    def test_multiple_evaluations_counted(self):
        self.evaluator.evaluate(self.opp)
        self.assertEqual(self.evaluator.stats()["evaluation_count"], 2)

    def test_avg_score(self):
        v = ValueEvaluator()
        v.evaluate(make_opportunity(opp_id="a", evidence=["e0"]))
        v.evaluate(make_opportunity(opp_id="b",
                                    evidence=[f"e{i}" for i in range(5)]))
        st = v.stats()
        self.assertGreaterEqual(st["avg_value_score"], 0.0)
        self.assertLessEqual(st["avg_value_score"], 1.0)


class TestEdgeCases(unittest.TestCase):
    """边界情况"""

    def test_empty_evidence(self):
        v = ValueEvaluator()
        opp = make_opportunity(evidence=[])
        r = v.evaluate(opp)
        self.assertEqual(r["frequency"], "low")

    def test_zero_conf_opportunity(self):
        v = ValueEvaluator(create_threshold=0.9)
        opp = make_opportunity(confidence=0.0, evidence=["e0"])
        r = v.evaluate(opp)
        self.assertIn(r["decision"], DECISIONS)

    def test_evaluate_does_not_mutate_input(self):
        v = ValueEvaluator()
        opp = make_opportunity()
        before = dict(opp)
        v.evaluate(opp)
        self.assertEqual(opp, before)

    def test_no_relationship_default(self):
        v = ValueEvaluator()
        opp = make_opportunity()
        r = v.evaluate(opp, relationship=None)
        self.assertIn(r["benefit"], ("high", "medium", "low"))

    def test_no_experiences_default(self):
        v = ValueEvaluator()
        opp = make_opportunity()
        r = v.evaluate(opp, confirmed_experiences=None)
        self.assertEqual(r["feasibility"], "medium")


if __name__ == "__main__":
    unittest.main()
