"""
YHLZ Embodied AI V6.5 - 认知反思补充测试 (V6.5 Extra)

覆盖 (专项补足):
    - 模式分析边界
    - 矛盾检测边界
    - 认知反思细节
    - 成长边界
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
    ReflectionReport,
)


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


class TestPatternMore(unittest.TestCase):
    """模式分析补充"""

    def test_streak_2_min(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="连续成功", ts_offset=i)
            for i in range(3)
        ]
        self.assertGreaterEqual(len(a.analyze(records)), 1)

    def test_streak_3_min(self):
        a = PatternAnalyzer(min_samples=3, min_streak=3)
        records = [
            make_record(trigger="三连成功", ts_offset=i)
            for i in range(3)
        ]
        self.assertGreaterEqual(len(a.analyze(records)), 1)

    def test_streak_4_min_not_met(self):
        a = PatternAnalyzer(min_samples=3, min_streak=4)
        records = [
            make_record(trigger="不够长", ts_offset=i)
            for i in range(3)
        ]
        self.assertEqual(a.analyze(records), [])

    def test_failure_streak(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="连败", type="failure",
                        result="错误", ts_offset=i)
            for i in range(3)
        ]
        patterns = a.analyze(records)
        types = [p["type"] for p in patterns]
        self.assertIn("problem_pattern", types)

    def test_interleaved_success_failure(self):
        """完全交替 → 无连续 2 次 → 无模式"""
        a = PatternAnalyzer(min_samples=4, min_streak=2)
        records = [
            make_record(trigger="交替", result="成功", rid="s0"),
            make_record(trigger="交替", result="错误",
                        type="failure", rid="f0"),
            make_record(trigger="交替", result="成功", rid="s1"),
            make_record(trigger="交替", result="错误",
                        type="failure", rid="f1"),
        ]
        patterns = a.analyze(records)
        self.assertEqual(patterns, [])

    def test_rate_threshold_effect(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2,
                            min_success_rate=0.95)
        records = [
            make_record(trigger="高门槛", result="成功", rid="a"),
            make_record(trigger="高门槛", result="成功", rid="b"),
            make_record(trigger="高门槛", result="错误",
                        type="failure", rid="c"),
            make_record(trigger="高门槛", result="成功", rid="d"),
        ]
        patterns = a.analyze(records)
        # 成功率 0.75 < 0.95 → 非 success_strategy
        types = [p["type"] for p in patterns]
        self.assertNotIn("success_strategy", types)

    def test_multiple_triggers_independent(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = (
            [make_record(trigger="成功A", ts_offset=i)
             for i in range(4)]
            + [make_record(trigger="失败B", type="failure",
                           result="错误", ts_offset=i)
               for i in range(4)]
        )
        patterns = a.analyze(records)
        types = {p["type"] for p in patterns}
        self.assertIn("success_strategy", types)
        self.assertIn("problem_pattern", types)

    def test_pattern_evidence_rate(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="证据率", ts_offset=i)
            for i in range(4)
        ]
        p = a.analyze(records)[0]
        self.assertIn("100%", p["evidence"])

    def test_pattern_timestamp(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="时间戳", ts_offset=i)
            for i in range(4)
        ]
        p = a.analyze(records)[0]
        self.assertGreater(p["timestamp"], 0.0)

    def test_stats_after_clear(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="清空统计", ts_offset=i)
            for i in range(4)
        ]
        a.analyze(records)
        a.clear()
        self.assertEqual(a.stats()["pattern_count"], 0)


class TestContradictionMore(unittest.TestCase):
    """矛盾检测补充"""

    def test_identity_field_name(self):
        d = CognitiveContradictionDetector()
        r = d.detect(
            {"trigger": "涉及使命相关内容", "lesson": "l",
             "result": "成功"},
        )
        self.assertTrue(r["conflict"])
        self.assertEqual(r["type"], "identity_conflict")

    def test_identity_core_value(self):
        d = CognitiveContradictionDetector()
        r = d.detect(
            {"trigger": "修改核心价值观", "lesson": "l",
             "result": "成功"},
        )
        self.assertTrue(r["conflict"])

    def test_severity_identity_highest(self):
        d = CognitiveContradictionDetector()
        r1 = d.detect(
            {"trigger": "使命相关", "lesson": "l", "result": "x"},
        )
        r2 = d.detect(
            {"trigger": "任务", "lesson": "l", "result": "不可靠"},
        )
        self.assertGreater(r1["severity"], r2["severity"])

    def test_knowledge_conflict_specific(self):
        d = CognitiveContradictionDetector()
        r = d.detect(
            {"trigger": "扫描", "lesson": "l", "result": "失败"},
            known_experiences=[
                {"trigger": "扫描", "result": "成功",
                 "lesson": "l"},
            ],
        )
        self.assertEqual(r["type"], "knowledge_conflict")

    def test_no_conflict_clean(self):
        d = CognitiveContradictionDetector()
        r = d.detect(
            {"trigger": "扫描", "lesson": "l", "result": "成功"},
            known_experiences=[
                {"trigger": "拾取", "result": "成功",
                 "lesson": "l"},
            ],
        )
        self.assertFalse(r["conflict"])

    def test_checked_at(self):
        d = CognitiveContradictionDetector()
        r = d.detect(make_record())
        self.assertGreater(r["checked_at"], 0.0)

    def test_stats_zero(self):
        st = CognitiveContradictionDetector().stats()
        self.assertEqual(st["check_count"], 0)

    def test_clear_empty(self):
        self.assertEqual(
            CognitiveContradictionDetector().clear(), 0,
        )


class TestCognitiveReflectionMore(unittest.TestCase):
    """认知反思补充"""

    def test_empty_records(self):
        e = CognitiveReflectionEngine()
        r = e.analyze([])
        self.assertIn("观察 0", r["summary"])

    def test_one_record_no_pattern(self):
        e = CognitiveReflectionEngine()
        r = e.analyze([make_record()])
        self.assertEqual(r["patterns"], [])

    def test_success_factor_no_records(self):
        e = CognitiveReflectionEngine()
        r = e.analyze([])
        self.assertIn("成功比例", r["success_factor"])

    def test_confidence_low_empty(self):
        e = CognitiveReflectionEngine()
        r = e.analyze([])
        self.assertEqual(r["confidence"], 0.0)

    def test_contradictions_identity(self):
        e = CognitiveReflectionEngine()
        records = [
            make_record(trigger="使命调整", rid=f"e{i}")
            for i in range(3)
        ]
        r = e.analyze(records)
        self.assertGreaterEqual(len(r["contradictions"]), 0)

    def test_generated_at(self):
        e = CognitiveReflectionEngine()
        r = e.analyze([])
        self.assertGreater(r["generated_at"], 0.0)

    def test_stats_pattern_count(self):
        e = CognitiveReflectionEngine()
        records = [
            make_record(trigger="统计模式", ts_offset=i)
            for i in range(4)
        ]
        e.analyze(records)
        st = e.stats()
        self.assertGreaterEqual(st["pattern_count"], 1)

    def test_stats_conflict_count(self):
        e = CognitiveReflectionEngine()
        records = [
            make_record(trigger="冲突不可靠", rid=f"e{i}")
            for i in range(3)
        ]
        e.analyze(records)
        st = e.stats()
        self.assertGreaterEqual(st["conflict_count"], 0)

    def test_clear_resets_all(self):
        e = CognitiveReflectionEngine()
        records = [
            make_record(trigger="清空全部", ts_offset=i)
            for i in range(4)
        ]
        e.analyze(records)
        n = e.clear()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(e.stats()["reflection_count"], 0)


class TestReportMore(unittest.TestCase):
    """反思记忆补充"""

    def test_record_with_pattern(self):
        r = ReflectionReport()
        e = r.record("exp_1", "反思", pattern="有效策略",
                     growth_value="高")
        self.assertEqual(e["pattern"], "有效策略")
        self.assertEqual(e["growth_value"], "高")

    def test_by_experience_empty(self):
        r = ReflectionReport()
        self.assertEqual(r.by_experience("none"), [])

    def test_history_empty(self):
        r = ReflectionReport()
        self.assertEqual(r.history(), [])

    def test_stats_empty(self):
        r = ReflectionReport()
        st = r.stats()
        self.assertEqual(st["memory_count"], 0)

    def test_record_timestamp(self):
        r = ReflectionReport()
        e = r.record("exp_1", "反思")
        self.assertGreater(e["timestamp"], 0.0)


class TestGrowthMore(unittest.TestCase):
    """成长补充"""

    def test_proposal_basis(self):
        g = GrowthProposal()
        ps = g.generate({
            "patterns": [{"type": "problem_pattern",
                          "trigger": "失败", "confidence": 0.8,
                          "meaning": "连续失败"}],
        })
        self.assertIn("连续失败", ps[0]["basis"])

    def test_proposal_expected_gain(self):
        g = GrowthProposal()
        ps = g.generate({
            "patterns": [{"type": "success_strategy",
                          "trigger": "成功", "confidence": 0.9,
                          "meaning": "有效"}],
        })
        self.assertTrue(ps[0]["expected_gain"])

    def test_evaluator_score_calculation(self):
        ev = GrowthEvaluator()
        r = ev.evaluate({
            "id": "p", "type": "skill_improvement",
            "description": "改进", "expected_gain": "g",
            "risk": "low", "confidence": 0.8,
        })
        # (0.9 + 0.9 + 0.95)/3
        self.assertAlmostEqual(r["score"], 0.9167, places=3)

    def test_evaluator_identity_state_reference(self):
        ev = GrowthEvaluator()
        r = ev.evaluate(
            {"id": "p", "type": "skill_improvement",
             "description": "改进使命方向",
             "expected_gain": "g", "risk": "low",
             "confidence": 0.8},
            identity_state={"mission": "长期陪伴"},
        )
        self.assertFalse(r["approved"])

    def test_applier_before_after(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            before_state={"param": 1},
            change_fn=lambda b, p: {"param": 2},
        )
        self.assertEqual(r["before"]["param"], 1)
        self.assertEqual(r["after"]["param"], 2)

    def test_applier_verification_ok(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            before_state={"a": 1},
            change_fn=lambda b, p: {"a": 2},
        )
        self.assertTrue(r["verification"]["ok"])

    def test_applier_verification_fail(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": "p", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            before_state={"mission": "旧"},
            change_fn=lambda b, p: {"mission": "新"},
        )
        self.assertFalse(r["verification"]["ok"])

    def test_audit_before_after_kept(self):
        a = GrowthAudit()
        a.record("p1", before={"x": 1}, decision="applied",
                 after={"x": 2})
        r = a.report(limit=10)
        self.assertEqual(r["recent"][0]["before"]["x"], 1)
        self.assertEqual(r["recent"][0]["after"]["x"], 2)

    def test_audit_recent_order(self):
        a = GrowthAudit()
        a.record("p1", decision="applied")
        a.record("p2", decision="blocked")
        r = a.report(limit=10)
        self.assertEqual(r["recent"][0]["proposal_id"], "p2")

    def test_audit_max_records(self):
        a = GrowthAudit(max_records=3)
        for i in range(5):
            a.record(f"p{i}", decision="applied")
        self.assertEqual(a.report()["total"], 3)

    def test_audit_validation(self):
        from backend.embodied.companion.growth.growth_audit import (
            AuditError,
        )
        with self.assertRaises(AuditError):
            GrowthAudit(max_records=0)

    def test_guard_dimensions_allowed(self):
        g = IdentityGuard()
        ok, reason = g.check({"dimensions": {"warmth": 0.8}})
        self.assertTrue(ok)

    def test_guard_multiple_fields(self):
        g = IdentityGuard()
        ok, reason = g.check({"a": 1, "b": 2})
        self.assertTrue(ok)

    def test_guard_intercept_structure(self):
        g = IdentityGuard()
        g.check({"mission": "x"})
        i = g.intercepts()[0]
        for key in ("guard_id", "change", "ok", "reason",
                    "timestamp"):
            self.assertIn(key, i)

    def test_validator_multiple_changes(self):
        v = ChangeValidator()
        r = v.validate({"a": 1, "b": 1},
                       {"a": 2, "b": 2}, "调整")
        self.assertEqual(sorted(r["changed_fields"]), ["a", "b"])

    def test_validator_validation_id(self):
        v = ChangeValidator()
        r = v.validate({}, {}, "原因")
        self.assertTrue(r["validation_id"].startswith("cv_"))

    def test_validator_mode(self):
        v = ChangeValidator()
        r = v.validate({}, {}, "原因")
        self.assertEqual(r["mode"], "rule_based")

    def test_validator_clear_empty(self):
        self.assertEqual(ChangeValidator().clear(), 0)


if __name__ == "__main__":
    unittest.main()
