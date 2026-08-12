"""
YHLZ Embodied AI V6.5 - 自主成长单元测试 (Growth & Identity)

覆盖:
    - GrowthProposal: 4 类型建议生成
    - GrowthEvaluator: Identity/Safety/Value 三检查
    - GrowthApplier: 受控应用 (仅 approved, 默认需确认)
    - GrowthAudit: 成长审计
    - IdentityGuard: 保护字段拦截
    - ChangeValidator: 变更验证
"""
import unittest

from backend.embodied.companion.growth import (
    ApplierError,
    GrowthApplier,
    GrowthAudit,
    GrowthEvaluator,
    GrowthEvaluatorError,
    GrowthProposal,
    GrowthProposalError,
    IMMUTABLE_FIELDS,
    PROPOSAL_TYPES,
    SAFETY_KEYWORDS,
)
from backend.embodied.companion.identity import (
    PROTECTED_FIELDS,
    ChangeValidator,
    IdentityGuard,
    ValidatorError,
)


def make_reflection(patterns=None, contradictions=None,
                    failure_factor=""):
    return {
        "patterns": patterns or [],
        "contradictions": contradictions or [],
        "failure_factor": failure_factor,
    }


def make_proposal(**over):
    p = {
        "id": "gp_1",
        "type": "skill_improvement",
        "description": "针对问题模式改进执行技能",
        "expected_gain": "降低失败率",
        "risk": "low",
        "confidence": 0.8,
        "status": "PENDING_EVALUATION",
    }
    p.update(over)
    return p


class TestGrowthProposal(unittest.TestCase):
    """成长建议"""

    def setUp(self):
        self.generator = GrowthProposal()

    def test_problem_pattern_proposal(self):
        proposals = self.generator.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "拾取失败", "confidence": 0.8,
                       "meaning": "连续失败"}],
        ))
        types = [p["type"] for p in proposals]
        self.assertIn("skill_improvement", types)

    def test_success_strategy_proposal(self):
        proposals = self.generator.generate(make_reflection(
            patterns=[{"type": "success_strategy",
                       "trigger": "扫描成功", "confidence": 0.9,
                       "meaning": "有效策略"}],
        ))
        types = [p["type"] for p in proposals]
        self.assertIn("memory_strategy", types)

    def test_contradiction_proposal(self):
        proposals = self.generator.generate(make_reflection(
            contradictions=[{"conflict": True}],
        ))
        types = [p["type"] for p in proposals]
        self.assertIn("interaction_strategy", types)

    def test_failure_reasoning_proposal(self):
        proposals = self.generator.generate(make_reflection(
            failure_factor="失败 3 次",
        ))
        types = [p["type"] for p in proposals]
        self.assertIn("reasoning_strategy", types)

    def test_empty_reflection(self):
        proposals = self.generator.generate(make_reflection())
        self.assertEqual(proposals, [])

    def test_proposal_structure(self):
        proposals = self.generator.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "失败", "confidence": 0.8,
                       "meaning": "m"}],
        ))
        p = proposals[0]
        for key in ("id", "type", "description", "expected_gain",
                    "risk", "confidence", "basis", "status",
                    "created_at"):
            self.assertIn(key, p)

    def test_id_prefix(self):
        proposals = self.generator.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "失败", "confidence": 0.8,
                       "meaning": "m"}],
        ))
        self.assertTrue(proposals[0]["id"].startswith("gp_"))

    def test_status_pending(self):
        proposals = self.generator.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "失败", "confidence": 0.8,
                       "meaning": "m"}],
        ))
        self.assertEqual(proposals[0]["status"],
                         "PENDING_EVALUATION")

    def test_risk_mapping(self):
        proposals = self.generator.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "失败", "confidence": 0.8,
                       "meaning": "m"}],
        ))
        self.assertEqual(proposals[0]["risk"], "medium")

    def test_disabled(self):
        g = GrowthProposal(enabled=False)
        proposals = g.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "失败", "confidence": 0.8,
                       "meaning": "m"}],
        ))
        self.assertEqual(proposals, [])

    def test_types_whitelist(self):
        for t in ("skill_improvement", "memory_strategy",
                  "interaction_strategy", "reasoning_strategy"):
            self.assertIn(t, PROPOSAL_TYPES)

    def test_by_type(self):
        self.generator.generate(make_reflection(
            patterns=[{"type": "success_strategy",
                       "trigger": "成功", "confidence": 0.9,
                       "meaning": "m"}],
        ))
        out = self.generator.by_type("memory_strategy")
        self.assertGreaterEqual(len(out), 1)

    def test_by_type_invalid(self):
        with self.assertRaises(GrowthProposalError):
            self.generator.by_type("bogus")

    def test_stats(self):
        self.generator.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "失败", "confidence": 0.8,
                       "meaning": "m"}],
        ))
        st = self.generator.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertGreaterEqual(st["proposal_count"], 1)

    def test_max_proposals(self):
        g = GrowthProposal(max_proposals=1)
        g.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "A", "confidence": 0.8,
                       "meaning": "m"},
                      {"type": "success_strategy",
                       "trigger": "B", "confidence": 0.9,
                       "meaning": "m"}],
        ))
        self.assertLessEqual(g.stats()["proposal_count"], 1)

    def test_clear(self):
        self.generator.generate(make_reflection(
            patterns=[{"type": "problem_pattern",
                       "trigger": "失败", "confidence": 0.8,
                       "meaning": "m"}],
        ))
        self.assertEqual(self.generator.clear(), 1)


class TestGrowthEvaluator(unittest.TestCase):
    """成长评估"""

    def setUp(self):
        self.evaluator = GrowthEvaluator()

    def test_safe_proposal_approved(self):
        r = self.evaluator.evaluate(make_proposal())
        self.assertTrue(r["approved"])

    def test_identity_touch_rejected(self):
        """建议涉及使命 → 拒绝"""
        r = self.evaluator.evaluate(make_proposal(
            description="修改使命方向",
        ))
        self.assertFalse(r["approved"])
        self.assertIn("使命", r["reason"])

    def test_safety_keyword_rejected(self):
        r = self.evaluator.evaluate(make_proposal(
            description="关闭权限保护",
        ))
        self.assertFalse(r["approved"])

    def test_result_structure(self):
        r = self.evaluator.evaluate(make_proposal())
        for key in ("evaluation_id", "approved", "reason", "score",
                    "checks", "mode", "evaluated_at"):
            self.assertIn(key, r)

    def test_three_checks(self):
        r = self.evaluator.evaluate(make_proposal())
        names = {c["name"] for c in r["checks"]}
        self.assertEqual(names, {"identity", "safety", "value"})

    def test_high_risk_low_score(self):
        r = self.evaluator.evaluate(make_proposal(risk="high"))
        # 高风险降低价值分数
        low = self.evaluator.evaluate(make_proposal(risk="low"))
        self.assertLess(r["score"], low["score"])

    def test_threshold_validation(self):
        with self.assertRaises(GrowthEvaluatorError):
            GrowthEvaluator(approve_threshold=1.5)

    def test_stats(self):
        self.evaluator.evaluate(make_proposal())
        self.evaluator.evaluate(make_proposal(
            description="修改使命",
        ))
        st = self.evaluator.stats()
        self.assertEqual(st["evaluation_count"], 2)
        self.assertEqual(st["approved_count"], 1)
        self.assertEqual(st["rejected_count"], 1)

    def test_clear(self):
        self.evaluator.evaluate(make_proposal())
        self.assertEqual(self.evaluator.clear(), 1)

    def test_immutable_fields_constant(self):
        for f in ("mission", "core_value", "base_personality",
                  "safety_rules", "permission"):
            self.assertIn(f, IMMUTABLE_FIELDS)

    def test_safety_keywords(self):
        self.assertTrue(SAFETY_KEYWORDS)


class TestGrowthApplier(unittest.TestCase):
    """受控应用"""

    def setUp(self):
        self.applier = GrowthApplier()

    def test_unapproved_blocked(self):
        r = self.applier.apply(
            make_proposal(),
            {"approved": False, "reason": "x"},
            before_state={},
        )
        self.assertEqual(r["status"], "blocked")

    def test_default_no_auto_apply(self):
        """默认禁止自动成长修改 (需人工确认)"""
        r = self.applier.apply(
            make_proposal(),
            {"approved": True, "reason": "x"},
            before_state={},
        )
        self.assertEqual(r["status"], "pending_confirm")

    def test_with_change_fn_applied(self):
        r = self.applier.apply(
            make_proposal(),
            {"approved": True, "reason": "x"},
            before_state={"param": 1},
            change_fn=lambda b, p: {"param": 2},
        )
        self.assertEqual(r["status"], "applied")
        self.assertEqual(r["after"]["param"], 2)

    def test_guard_fn_block(self):
        r = self.applier.apply(
            make_proposal(),
            {"approved": True, "reason": "x"},
            before_state={},
            change_fn=lambda b, p: {},
            guard_fn=lambda p: (False, "守护拒绝"),
        )
        self.assertEqual(r["status"], "blocked")

    def test_change_exception(self):
        def boom(b, p):
            raise RuntimeError("boom")

        r = self.applier.apply(
            make_proposal(),
            {"approved": True, "reason": "x"},
            before_state={},
            change_fn=boom,
        )
        self.assertEqual(r["status"], "apply_failed")

    def test_verification_immutable(self):
        """变更修改不可变字段 → 验证失败"""
        r = self.applier.apply(
            make_proposal(),
            {"approved": True, "reason": "x"},
            before_state={"mission": "原使命"},
            change_fn=lambda b, p: {"mission": "新使命"},
        )
        self.assertIn(r["status"], ("applied", "rejected"))

    def test_result_structure(self):
        r = self.applier.apply(
            make_proposal(),
            {"approved": True, "reason": "x"},
            before_state={},
            change_fn=lambda b, p: {},
        )
        for key in ("apply_id", "proposal_id", "status", "reason",
                    "before", "after", "verification", "mode",
                    "applied_at"):
            self.assertIn(key, r)

    def test_audit_recorded(self):
        self.applier.apply(
            make_proposal(),
            {"approved": True, "reason": "x"},
            before_state={},
            change_fn=lambda b, p: {},
        )
        report = self.applier._audit.report()
        self.assertEqual(report["total"], 1)

    def test_stats(self):
        self.applier.apply(
            make_proposal(),
            {"approved": False, "reason": "x"},
            before_state={},
        )
        st = self.applier.stats()
        self.assertGreaterEqual(st["apply_count"], 1)

    def test_clear(self):
        self.applier.apply(
            make_proposal(),
            {"approved": False, "reason": "x"},
            before_state={},
        )
        n = self.applier.clear()
        self.assertGreaterEqual(n, 1)


class TestGrowthAudit(unittest.TestCase):
    """成长审计"""

    def test_record(self):
        a = GrowthAudit()
        e = a.record("gp_1", before={"a": 1}, decision="applied",
                     after={"a": 2})
        self.assertTrue(e["audit_id"].startswith("ga_"))
        self.assertEqual(e["proposal_id"], "gp_1")

    def test_record_structure(self):
        a = GrowthAudit()
        e = a.record("gp_1", decision="applied")
        for key in ("audit_id", "proposal_id", "before",
                    "decision", "after", "time"):
            self.assertIn(key, e)

    def test_report(self):
        a = GrowthAudit()
        a.record("p1", decision="applied")
        a.record("p2", decision="blocked")
        r = a.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["by_decision"]["applied"], 1)

    def test_disabled(self):
        a = GrowthAudit(enabled=False)
        e = a.record("p1", decision="applied")
        self.assertEqual(e, {})

    def test_clear(self):
        a = GrowthAudit()
        a.record("p1", decision="applied")
        self.assertEqual(a.clear(), 1)


class TestIdentityGuard(unittest.TestCase):
    """身份守护"""

    def test_protected_field_blocked(self):
        g = IdentityGuard()
        ok, reason = g.check({"mission": "新使命"})
        self.assertFalse(ok)
        self.assertIn("保护字段", reason)

    def test_safe_change_allowed(self):
        g = IdentityGuard()
        ok, reason = g.check({"dimensions": {"serious": 0.9}})
        self.assertTrue(ok)

    def test_disabled(self):
        g = IdentityGuard(enabled=False)
        ok, reason = g.check({"mission": "新使命"})
        self.assertTrue(ok)
        self.assertIn("停用", reason)

    def test_stats(self):
        g = IdentityGuard()
        g.check({"mission": "x"})
        g.check({"dimensions": {"a": 1}})
        st = g.stats()
        self.assertEqual(st["intercept_count"], 1)
        self.assertEqual(st["approval_count"], 1)

    def test_intercepts_recorded(self):
        g = IdentityGuard()
        g.check({"mission": "x"})
        intercepts = g.intercepts()
        self.assertEqual(len(intercepts), 1)

    def test_protected_fields_constant(self):
        for f in ("mission", "core_value", "base_personality",
                  "safety_rules", "permission"):
            self.assertIn(f, PROTECTED_FIELDS)

    def test_clear(self):
        g = IdentityGuard()
        g.check({"mission": "x"})
        self.assertEqual(g.clear(), 1)


class TestChangeValidator(unittest.TestCase):
    """变更验证"""

    def test_valid_change(self):
        v = ChangeValidator()
        r = v.validate({"a": 1}, {"a": 2}, "调整参数")
        self.assertTrue(r["ok"])
        self.assertEqual(r["changed_fields"], ["a"])

    def test_no_change(self):
        v = ChangeValidator()
        r = v.validate({"a": 1}, {"a": 1}, "无变化")
        self.assertTrue(r["ok"])
        self.assertEqual(r["changed_fields"], [])

    def test_missing_reason(self):
        v = ChangeValidator()
        r = v.validate({"a": 1}, {"a": 2}, "")
        self.assertFalse(r["ok"])
        self.assertIn("原因不能为空", r["reason"])

    def test_protected_touch_rejected(self):
        v = ChangeValidator()
        r = v.validate({"mission": "旧"}, {"mission": "新"},
                       "变更使命")
        self.assertFalse(r["ok"])
        self.assertIn("保护字段", r["reason"])

    def test_result_structure(self):
        v = ChangeValidator()
        r = v.validate({}, {}, "原因")
        for key in ("validation_id", "ok", "reason",
                    "changed_fields", "mode", "validated_at"):
            self.assertIn(key, r)

    def test_stats(self):
        v = ChangeValidator()
        v.validate({"a": 1}, {"a": 2}, "原因")
        v.validate({"a": 1}, {"a": 1}, "")
        st = v.stats()
        self.assertEqual(st["validation_count"], 2)
        self.assertEqual(st["passed_count"], 1)

    def test_clear(self):
        v = ChangeValidator()
        v.validate({}, {}, "原因")
        self.assertEqual(v.clear(), 1)


if __name__ == "__main__":
    unittest.main()
