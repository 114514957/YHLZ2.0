"""
YHLZ Embodied AI V8.0 - 规则引擎单元测试 (Rule Engine)

覆盖:
    - 组合治理评估 (优先级依次检查)
    - 跨层冲突仲裁 (固定优先级)
    - Identity/Safety/Constitution/Growth/Intelligence
"""
import unittest

from backend.embodied.companion.constitution import (
    GOVERNANCE_PRIORITIES,
    GrowthPolicy,
    IdentityRules,
    IntelligencePolicy,
    Principles,
    RuleEngine,
    SafetyPolicy,
)


class TestRuleEngine(unittest.TestCase):
    """规则引擎"""

    def setUp(self):
        self.engine = RuleEngine(
            principles=Principles(),
            identity_rules=IdentityRules(),
            safety=SafetyPolicy(),
            growth=GrowthPolicy(),
            intelligence=IntelligencePolicy(),
        )

    def ctx(self, **over):
        base = {
            "module": "test",
            "action_text": "正常行为",
            "change": {},
        }
        base.update(over)
        return base

    def test_safe_allow(self):
        r = self.engine.evaluate(self.ctx())
        self.assertEqual(r["decision"], "allow")
        self.assertEqual(r["priority"], "constitution")

    def test_identity_block(self):
        r = self.engine.evaluate(self.ctx(
            change={"mission": "x"},
        ))
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "identity")

    def test_safety_block(self):
        r = self.engine.evaluate(self.ctx(
            action_text="非法操作",
        ))
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "safety")

    def test_principles_block(self):
        r = self.engine.evaluate(self.ctx(
            action_text="我拥有意识",
        ))
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "constitution")

    def test_growth_review(self):
        r = self.engine.evaluate(self.ctx(
            growth_proposal={
                "type": "skill_improvement",
                "description": "修改使命",
                "risk": "low",
            },
        ))
        self.assertEqual(r["decision"], "review")
        self.assertEqual(r["priority"], "growth")

    def test_growth_ok(self):
        r = self.engine.evaluate(self.ctx(
            growth_proposal={
                "type": "skill_improvement",
                "description": "改进技能",
                "risk": "low",
            },
        ))
        self.assertEqual(r["decision"], "allow")

    def test_cloud_block(self):
        r = self.engine.evaluate(self.ctx(
            cloud_result={
                "provider": "cloud",
                "content": "修改人格",
                "temporary": True,
            },
        ))
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "intelligence")

    def test_cloud_ok(self):
        r = self.engine.evaluate(self.ctx(
            cloud_result={
                "provider": "cloud",
                "content": "推理结果",
                "temporary": True,
            },
        ))
        self.assertEqual(r["decision"], "allow")

    def test_checked_rules(self):
        r = self.engine.evaluate(self.ctx())
        self.assertIn("identity_rules", r["checked_rules"])
        self.assertIn("safety_policy", r["checked_rules"])
        self.assertIn("principles", r["checked_rules"])

    def test_reasons_list(self):
        r = self.engine.evaluate(self.ctx())
        self.assertGreaterEqual(len(r["reasons"]), 1)

    def test_module_context(self):
        r = self.engine.evaluate(self.ctx(module="growth"))
        self.assertEqual(r["context"]["module"], "growth")

    def test_disabled(self):
        engine = RuleEngine(enabled=False)
        r = engine.evaluate(self.ctx(change={"mission": "x"}))
        self.assertEqual(r["decision"], "allow")
        matched = [
            x for x in r["reasons"] if "停用" in x
        ]
        self.assertGreaterEqual(len(matched), 1)


class TestArbitration(unittest.TestCase):
    """冲突仲裁"""

    def setUp(self):
        self.engine = RuleEngine(
            principles=Principles(),
            identity_rules=IdentityRules(),
        )

    def test_identity_wins(self):
        r = self.engine.arbitrate({
            "layers": ["expression", "intelligence",
                       "identity"],
            "description": "表达 vs 调度 vs 身份",
        })
        self.assertEqual(r["winner"], "identity")
        self.assertEqual(r["priority"], 0)

    def test_safety_over_growth(self):
        r = self.engine.arbitrate({
            "layers": ["growth", "safety"],
            "description": "成长 vs 安全",
        })
        self.assertEqual(r["winner"], "safety")

    def test_constitution_over_expression(self):
        r = self.engine.arbitrate({
            "layers": ["expression", "constitution"],
            "description": "表达 vs 宪法",
        })
        self.assertEqual(r["winner"], "constitution")

    def test_growth_over_intelligence(self):
        r = self.engine.arbitrate({
            "layers": ["intelligence", "growth"],
            "description": "调度 vs 成长",
        })
        self.assertEqual(r["winner"], "growth")

    def test_identity_risk_boosts(self):
        r = self.engine.arbitrate({
            "layers": ["expression"],
            "identity_risk": True,
        })
        self.assertEqual(r["winner"], "identity")

    def test_safety_risk_boosts(self):
        r = self.engine.arbitrate({
            "layers": ["expression", "growth"],
            "safety_risk": True,
        })
        self.assertEqual(r["winner"], "safety")

    def test_empty_layers_default(self):
        r = self.engine.arbitrate({"layers": []})
        self.assertEqual(r["winner"], "constitution")

    def test_unknown_layer_skipped(self):
        r = self.engine.arbitrate({
            "layers": ["bogus", "expression"],
        })
        self.assertEqual(r["winner"], "expression")

    def test_priority_name(self):
        r = self.engine.arbitrate({
            "layers": ["identity"],
        })
        self.assertEqual(r["priority_name"], "identity")

    def test_reason_explainable(self):
        r = self.engine.arbitrate({
            "layers": ["expression", "identity"],
            "description": "测试冲突",
        })
        self.assertIn("优先级最高", r["reason"])

    def test_priorities_constant(self):
        self.assertEqual(GOVERNANCE_PRIORITIES[0], "identity")
        self.assertEqual(GOVERNANCE_PRIORITIES[-1],
                         "expression")


class TestEngineStats(unittest.TestCase):
    """引擎统计"""

    def setUp(self):
        self.engine = RuleEngine(
            principles=Principles(),
            identity_rules=IdentityRules(),
        )

    def test_evaluate_count(self):
        self.engine.evaluate({"action_text": "正常"})
        self.engine.evaluate({"action_text": "修改使命",
                              "change": {"mission": "x"}})
        stats = self.engine.stats()
        self.assertEqual(stats["evaluate_count"], 2)
        self.assertEqual(stats["decisions"]["block"], 1)

    def test_arbitrate_count(self):
        self.engine.arbitrate({"layers": ["identity"]})
        self.assertEqual(self.engine.stats()[
            "arbitrate_count"], 1)

    def test_clear(self):
        self.engine.evaluate({"action_text": "正常"})
        n = self.engine.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.engine.stats()[
            "evaluate_count"], 0)

    def test_mode(self):
        self.assertEqual(self.engine.stats()["mode"],
                         "rule_based")


if __name__ == "__main__":
    unittest.main()
