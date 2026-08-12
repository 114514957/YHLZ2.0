"""
YHLZ Embodied AI V6.5 - 认知反思补充测试 2 (V6.5 Extra2)

覆盖 (专项补足至 ≥400):
    - Service 组合场景
    - 单元边界矩阵
"""
import time
import unittest

from backend.embodied.companion.growth import (
    GrowthApplier,
    GrowthAudit,
    GrowthEvaluator,
    GrowthProposal,
)
from backend.embodied.companion.identity import (
    ChangeValidator,
    IdentityGuard,
)
from backend.embodied.companion.reflection import (
    CognitiveContradictionDetector,
    CognitiveReflectionEngine,
    PatternAnalyzer,
)
from backend.embodied.service import EmbodiedService


def make_record(trigger="生成工程Prompt", type="improvement",
                result="成功", rid=None, ts_offset=0):
    return {
        "id": rid or f"exp_{trigger}_{ts_offset}",
        "type": type,
        "trigger": trigger,
        "lesson": "l",
        "result": result,
        "timestamp": time.time() - ts_offset * 86400,
    }


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


def seed(svc, sn=4, fn=3):
    for _ in range(sn):
        svc.companion_experience.store_from_event(
            success=True, trigger="生成工程Prompt",
            source="t", action="a", result="成功",
        )
    for _ in range(fn):
        svc.companion_experience.store_from_event(
            success=False, trigger="拾取物体",
            source="t", action="a", result="位置不匹配",
        )


class TestServiceCombos(unittest.TestCase):
    """Service 组合"""

    def test_reflect_then_generate(self):
        svc = setup_service()
        seed(svc)
        r = svc.companion_reflection_analyze()
        g = svc.companion_growth_generate()
        self.assertGreaterEqual(g["proposal_count"], 1)

    def test_generate_then_evaluate_all(self):
        svc = setup_service()
        seed(svc)
        g = svc.companion_growth_generate()
        for p in g["proposals"]:
            ev = svc.companion_growth_evaluate(p)
            self.assertIn("approved", ev)

    def test_full_controlled_flow(self):
        """反思 → 建议 → 评估 → 受控应用 → 审计"""
        svc = setup_service()
        seed(svc)
        g = svc.companion_growth_generate()
        if g["proposals"]:
            p = g["proposals"][0]
            ev = svc.companion_growth_evaluate(p)
            r = svc.companion_growth_apply(
                p, ev, changes={"note": "优化记录"},
            )
            self.assertIn(r["status"], ("applied", "blocked",
                                        "pending_confirm"))
        au = svc.companion_growth_audit()
        self.assertIn("by_decision", au)

    def test_contradiction_with_seed(self):
        svc = setup_service()
        seed(svc)
        r = svc.companion_contradiction_check()
        self.assertIn("conflict", r)

    def test_pattern_after_seed(self):
        svc = setup_service()
        seed(svc)
        r = svc.companion_pattern_detect()
        types = set(r["stats"]["by_type"].keys())
        self.assertIn("success_strategy", types)

    def test_handle_after_reflection(self):
        svc = setup_service()
        seed(svc)
        svc.companion_reflection_analyze()
        r = svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_emotion_after_reflection(self):
        svc = setup_service()
        seed(svc)
        before = svc.companion_emotion()
        svc.companion_reflection_analyze()
        after = svc.companion_emotion()
        # 反思不直接改情绪 (经 Meaning)
        self.assertEqual(before["positivity"],
                         after["positivity"])

    def test_expression_after_growth(self):
        svc = setup_service()
        r = svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_growth_stats_empty(self):
        svc = setup_service()
        st = svc.companion_growth_stats()
        self.assertEqual(st["proposal"]["proposal_count"], 0)
        self.assertEqual(st["applier"]["apply_count"], 0)

    def test_growth_stats_after_flow(self):
        svc = setup_service()
        seed(svc)
        svc.companion_reflection_analyze()
        svc.companion_growth_generate()
        st = svc.companion_growth_stats()
        self.assertGreaterEqual(st["reflection"][
            "reflection_count"], 1)
        self.assertGreaterEqual(st["proposal"][
            "proposal_count"], 1)

    def test_identity_guard_stats_after_block(self):
        svc = setup_service()
        svc.companion_growth_apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            changes={"mission": "新"},
        )
        st = svc.companion_growth_stats()
        self.assertGreaterEqual(
            st["identity_guard"]["intercept_count"], 1,
        )

    def test_version(self):
        self.assertEqual(setup_service().companion.status()[
            "version"], "9.5.0")


class TestPatternMatrix(unittest.TestCase):
    """模式矩阵"""

    def test_success_rates_varied(self):
        """不同成功率对应不同模式"""
        a = PatternAnalyzer(min_samples=4, min_streak=2,
                            min_success_rate=0.7)
        # 75% 成功率 + 连续 3 成功
        records = [
            make_record(trigger="率75", result="成功", rid="a"),
            make_record(trigger="率75", result="成功", rid="b"),
            make_record(trigger="率75", result="成功", rid="c"),
            make_record(trigger="率75", result="错误",
                        type="failure", rid="d"),
        ]
        types = [p["type"] for p in a.analyze(records)]
        self.assertIn("success_strategy", types)

    def test_50_rate_no_strategy(self):
        a = PatternAnalyzer(min_samples=4, min_streak=2,
                            min_success_rate=0.7)
        records = [
            make_record(trigger="率50", result="成功", rid="a"),
            make_record(trigger="率50", result="错误",
                        type="failure", rid="b"),
            make_record(trigger="率50", result="成功", rid="c"),
            make_record(trigger="率50", result="错误",
                        type="failure", rid="d"),
        ]
        types = [p["type"] for p in a.analyze(records)]
        self.assertNotIn("success_strategy", types)

    def test_three_groups(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = (
            [make_record(trigger="组A", ts_offset=i)
             for i in range(3)]
            + [make_record(trigger="组B", type="failure",
                           result="错误", ts_offset=i)
               for i in range(3)]
            + [make_record(trigger="组C", ts_offset=i)
               for i in range(3)]
        )
        patterns = a.analyze(records)
        self.assertGreaterEqual(len(patterns), 2)

    def test_large_samples_high_conf(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="大样本", ts_offset=i)
            for i in range(20)
        ]
        p = a.analyze(records)[0]
        self.assertGreaterEqual(p["confidence"], 0.9)

    def test_two_records_no_pattern(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="两条", result="成功", rid="a"),
            make_record(trigger="两条", result="成功", rid="b"),
        ]
        self.assertEqual(a.analyze(records), [])

    def test_failure_result_variant(self):
        """不同失败结果文本"""
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="失败变体", type="failure",
                        result="超时", rid="a"),
            make_record(trigger="失败变体", type="failure",
                        result="超时", rid="b"),
            make_record(trigger="失败变体", type="failure",
                        result="超时", rid="c"),
        ]
        types = [p["type"] for p in a.analyze(records)]
        self.assertIn("problem_pattern", types)


class TestEvaluatorMatrix(unittest.TestCase):
    """评估矩阵"""

    def test_all_risks(self):
        ev = GrowthEvaluator()
        for risk in ("low", "medium", "high"):
            r = ev.evaluate({
                "id": "p", "type": "skill_improvement",
                "description": "改进", "expected_gain": "g",
                "risk": risk, "confidence": 0.8,
            })
            self.assertIn("approved", r, risk)

    def test_high_risk_rejected(self):
        ev = GrowthEvaluator()
        r = ev.evaluate({
            "id": "p", "type": "skill_improvement",
            "description": "改进", "expected_gain": "g",
            "risk": "high", "confidence": 0.8,
        })
        self.assertFalse(r["approved"])

    def test_all_protected_fields(self):
        ev = GrowthEvaluator()
        for desc in ("修改使命", "修改价值观", "修改人格",
                     "修改安全规则", "修改权限"):
            r = ev.evaluate({
                "id": "p", "type": "skill_improvement",
                "description": desc, "expected_gain": "g",
                "risk": "low", "confidence": 0.8,
            })
            self.assertFalse(r["approved"], desc)

    def test_safety_words(self):
        ev = GrowthEvaluator()
        for desc in ("绕过安全", "关闭权限", "自我修改核心",
                     "修改安全规则"):
            r = ev.evaluate({
                "id": "p", "type": "skill_improvement",
                "description": desc, "expected_gain": "g",
                "risk": "low", "confidence": 0.8,
            })
            self.assertFalse(r["approved"], desc)

    def test_check_reasons(self):
        ev = GrowthEvaluator()
        r = ev.evaluate({
            "id": "p", "type": "skill_improvement",
            "description": "改进", "expected_gain": "g",
            "risk": "low", "confidence": 0.8,
        })
        for c in r["checks"]:
            self.assertTrue(c["reason"])

    def test_evaluator_mode(self):
        ev = GrowthEvaluator()
        r = ev.evaluate({
            "id": "p", "type": "skill_improvement",
            "description": "改进", "expected_gain": "g",
            "risk": "low", "confidence": 0.8,
        })
        self.assertEqual(r["mode"], "rule_based")


class TestApplierMatrix(unittest.TestCase):
    """应用矩阵"""

    def test_no_changes_applied(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            before_state={"a": 1},
            change_fn=lambda b, p: {},
        )
        self.assertEqual(r["status"], "applied")
        self.assertEqual(r["after"]["a"], 1)

    def test_multi_field_changes(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            before_state={"a": 1, "b": 1},
            change_fn=lambda b, p: {"a": 2, "b": 2},
        )
        self.assertEqual(r["after"], {"a": 2, "b": 2})

    def test_apply_id_prefix(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": False, "reason": "x"},
            before_state={},
        )
        self.assertTrue(r["apply_id"].startswith("ga_"))

    def test_mode(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": False, "reason": "x"},
            before_state={},
        )
        self.assertEqual(r["mode"], "rule_based")

    def test_applied_at(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            before_state={},
            change_fn=lambda b, p: {},
        )
        self.assertGreater(r["applied_at"], 0.0)

    def test_stats_after_apply(self):
        a = GrowthApplier()
        a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            before_state={},
            change_fn=lambda b, p: {},
        )
        st = a.stats()
        self.assertEqual(st["applied_count"], 1)

    def test_stats_blocked(self):
        a = GrowthApplier()
        a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": False, "reason": "x"},
            before_state={},
        )
        st = a.stats()
        self.assertGreaterEqual(st["blocked_count"], 1)


class TestGuardMatrix(unittest.TestCase):
    """守护矩阵"""

    def test_all_protected_blocked(self):
        g = IdentityGuard()
        for field in ("mission", "core_value",
                      "base_personality", "safety_rules",
                      "permission"):
            ok, reason = g.check({field: "x"})
            self.assertFalse(ok, field)

    def test_expression_fields_allowed(self):
        g = IdentityGuard()
        for field in ("dimensions", "communication_style",
                      "note", "param"):
            ok, reason = g.check({field: "x"})
            self.assertTrue(ok, field)

    def test_multi_protected(self):
        g = IdentityGuard()
        ok, reason = g.check({"mission": "x", "core_value": "y"})
        self.assertFalse(ok)

    def test_guard_mode(self):
        g = IdentityGuard()
        self.assertEqual(g.stats()["mode"], "rule_based")

    def test_intercepts_empty(self):
        g = IdentityGuard()
        self.assertEqual(g.intercepts(), [])

    def test_clear_empty(self):
        self.assertEqual(IdentityGuard().clear(), 0)


class TestValidatorMatrix(unittest.TestCase):
    """验证矩阵"""

    def test_same_state_no_change(self):
        v = ChangeValidator()
        r = v.validate({"a": 1}, {"a": 1}, "原因")
        self.assertEqual(r["changed_fields"], [])

    def test_whitespace_reason(self):
        v = ChangeValidator()
        r = v.validate({"a": 1}, {"a": 2}, "   ")
        self.assertFalse(r["ok"])

    def test_unicode_changes(self):
        v = ChangeValidator()
        r = v.validate({"名称": "旧"}, {"名称": "新"}, "改名")
        self.assertEqual(r["changed_fields"], ["名称"])

    def test_validation_id_unique(self):
        v = ChangeValidator()
        r1 = v.validate({}, {}, "原因")
        r2 = v.validate({}, {}, "原因")
        self.assertNotEqual(r1["validation_id"],
                            r2["validation_id"])

    def test_stats_zero(self):
        st = ChangeValidator().stats()
        self.assertEqual(st["validation_count"], 0)

    def test_max_changes_validation(self):
        from backend.embodied.companion.identity.change_validator import (
            ValidatorError as VE,
        )
        with self.assertRaises(VE):
            ChangeValidator(max_changes=0)


class TestReportEdge(unittest.TestCase):
    """反思记忆边界"""

    def test_reflection_memory_roundtrip(self):
        from backend.embodied.companion.reflection import (
            ReflectionReport,
        )
        r = ReflectionReport()
        e = r.record("exp_9", "理解", pattern="模式",
                     growth_value="高价值")
        out = r.by_experience("exp_9")
        self.assertEqual(out[0]["growth_value"], "高价值")


if __name__ == "__main__":
    unittest.main()
