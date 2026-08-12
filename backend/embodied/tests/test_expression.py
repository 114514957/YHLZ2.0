"""
YHLZ Embodied AI V6.2 - 表达层单元测试 (Expression Layer)

覆盖 (expression/):
    - 规则表: 高积极/低能量/高温度/高信任/任务失败
    - 上下文聚合
    - 引擎: 生成建议/置信度/统计/审计
    - 隔离: 表达不改人格
"""
import unittest

from backend.embodied.companion.expression import (
    EXPRESSION_RULES,
    EXPRESSION_STYLES,
    EXPRESSION_TONES,
    ExpressionAudit,
    ExpressionContext,
    ExpressionEngine,
    ExpressionEngineError,
    ExpressionRules,
    RulesError,
)


class TestRules(unittest.TestCase):
    """规则表"""

    def setUp(self):
        self.rules = ExpressionRules(threshold=0.7)

    def test_styles_whitelist(self):
        for s in ("more_positive", "reduce_intensity", "personal",
                  "friendly", "patient", "neutral"):
            self.assertIn(s, EXPRESSION_STYLES)

    def test_tones_whitelist(self):
        for t in ("warm", "calm", "cheerful", "gentle", "neutral"):
            self.assertIn(t, EXPRESSION_TONES)

    def test_high_positivity_hit(self):
        hits = self.rules.match({
            "emotion": {"positivity": 0.9},
        })
        self.assertIn("high_positivity", [h["rule"] for h in hits])

    def test_low_positivity_no_hit(self):
        hits = self.rules.match({
            "emotion": {"positivity": 0.3},
        })
        self.assertNotIn("high_positivity",
                         [h["rule"] for h in hits])

    def test_low_energy_hit(self):
        hits = self.rules.match({
            "emotion": {"energy": 0.2},
        })
        self.assertIn("low_energy", [h["rule"] for h in hits])

    def test_high_warmth_hit(self):
        hits = self.rules.match({
            "emotion": {"warmth": 0.8},
        })
        self.assertIn("high_warmth", [h["rule"] for h in hits])

    def test_high_trust_hit(self):
        hits = self.rules.match({
            "relationship": {"trust": 0.9},
        })
        self.assertIn("high_trust", [h["rule"] for h in hits])

    def test_task_failure_hit(self):
        hits = self.rules.match({
            "task": {"result": "failure"},
        })
        self.assertIn("task_failure", [h["rule"] for h in hits])

    def test_no_context_no_hit(self):
        hits = self.rules.match({})
        self.assertEqual(hits, [])

    def test_multiple_hits(self):
        hits = self.rules.match({
            "emotion": {"positivity": 0.9, "warmth": 0.8},
            "relationship": {"trust": 0.9},
        })
        self.assertGreaterEqual(len(hits), 2)

    def test_hit_reason_explainable(self):
        hits = self.rules.match({"emotion": {"positivity": 0.9}})
        self.assertTrue(hits[0]["reason"])

    def test_threshold_validation(self):
        with self.assertRaises(RulesError):
            ExpressionRules(threshold=1.5)

    def test_rules_snapshot(self):
        r = self.rules.rules()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(len(r["rules"]), 5)

    def test_rules_constant(self):
        self.assertIn("high_positivity", EXPRESSION_RULES)

    def test_threshold_getter(self):
        self.assertEqual(self.rules.threshold(), 0.7)

    def test_boundary_threshold(self):
        r = ExpressionRules(threshold=0.5)
        hits = r.match({"emotion": {"positivity": 0.5}})
        self.assertIn("high_positivity", [h["rule"] for h in hits])


class TestContext(unittest.TestCase):
    """上下文聚合"""

    def test_build(self):
        ctx = ExpressionContext()
        c = ctx.build(emotion={"positivity": 0.9},
                      relationship={"trust": 0.8},
                      task={"result": "ok"},
                      conversation={"turns": 5})
        self.assertEqual(c["emotion"]["positivity"], 0.9)
        self.assertEqual(c["relationship"]["trust"], 0.8)
        self.assertEqual(c["task"]["result"], "ok")

    def test_build_none_inputs(self):
        ctx = ExpressionContext()
        c = ctx.build()
        for key in ("emotion", "relationship", "task",
                    "conversation", "built_at"):
            self.assertIn(key, c)
        self.assertEqual(c["emotion"], {})

    def test_build_does_not_mutate_input(self):
        ctx = ExpressionContext()
        emotion = {"positivity": 0.9}
        ctx.build(emotion=emotion)
        self.assertEqual(emotion, {"positivity": 0.9})

    def test_neutral(self):
        c = ExpressionContext.neutral()
        self.assertEqual(c["emotion"], {})
        self.assertEqual(c["relationship"], {})

    def test_latest(self):
        ctx = ExpressionContext()
        ctx.build(emotion={"positivity": 0.5})
        latest = ctx.latest()
        self.assertEqual(latest["emotion"]["positivity"], 0.5)

    def test_latest_empty_neutral(self):
        ctx = ExpressionContext()
        self.assertEqual(ctx.latest()["emotion"], {})

    def test_clear(self):
        ctx = ExpressionContext()
        ctx.build(emotion={"positivity": 0.5})
        self.assertEqual(ctx.clear(), 1)
        self.assertEqual(ctx.latest()["emotion"], {})


class TestEngine(unittest.TestCase):
    """表达引擎"""

    def setUp(self):
        self.engine = ExpressionEngine()

    def test_generate_structure(self):
        r = self.engine.generate(emotion={"positivity": 0.9})
        for key in ("suggestion_id", "style", "tone", "reason",
                    "confidence", "rules", "mode", "timestamp"):
            self.assertIn(key, r)

    def test_generate_high_positive(self):
        r = self.engine.generate(
            emotion={"positivity": 0.9, "energy": 0.8,
                     "warmth": 0.9},
            relationship={"trust": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")
        self.assertEqual(r["tone"], "warm")

    def test_generate_low_energy(self):
        r = self.engine.generate(
            emotion={"positivity": 0.2, "energy": 0.1,
                     "warmth": 0.3},
        )
        self.assertEqual(r["style"], "reduce_intensity")
        self.assertEqual(r["tone"], "calm")

    def test_generate_neutral(self):
        r = self.engine.generate()
        self.assertEqual(r["style"], "neutral")
        self.assertEqual(r["tone"], "neutral")
        self.assertEqual(r["confidence"], 0.3)

    def test_generate_reason_contains_rule(self):
        r = self.engine.generate(emotion={"positivity": 0.9})
        self.assertIn("高积极", r["reason"])

    def test_generate_confidence_range(self):
        r = self.engine.generate(emotion={"positivity": 0.9})
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_generate_task_failure(self):
        r = self.engine.generate(task={"result": "failure"})
        self.assertEqual(r["style"], "patient")
        self.assertEqual(r["tone"], "gentle")

    def test_generate_rules_recorded(self):
        r = self.engine.generate(emotion={"positivity": 0.9})
        self.assertIn("high_positivity", r["rules"])

    def test_generate_disabled(self):
        e = ExpressionEngine(enabled=False)
        with self.assertRaises(ExpressionEngineError):
            e.generate()

    def test_generate_audit(self):
        self.engine.generate(emotion={"positivity": 0.9})
        r = self.engine.audit_report()
        self.assertGreaterEqual(r["by_action"].get("generate", 0), 1)

    def test_status(self):
        self.engine.generate(emotion={"positivity": 0.9})
        st = self.engine.status()
        self.assertEqual(st["mode"], "rule_based")
        self.assertEqual(st["generate_count"], 1)
        self.assertEqual(st["style_distribution"]["more_positive"], 1)

    def test_status_rule_hits(self):
        self.engine.generate(emotion={"positivity": 0.9,
                                      "warmth": 0.9})
        st = self.engine.status()
        self.assertGreaterEqual(st["rule_hits"]["high_positivity"], 1)

    def test_clear(self):
        self.engine.generate(emotion={"positivity": 0.9})
        cleared = self.engine.clear()
        self.assertIn("audit", cleared)
        self.assertEqual(self.engine.status()["generate_count"], 0)

    def test_suggestion_id_prefix(self):
        r = self.engine.generate()
        self.assertTrue(r["suggestion_id"].startswith("expr_"))


class TestAudit(unittest.TestCase):
    """表达审计"""

    def test_record(self):
        a = ExpressionAudit()
        e = a.record(action="generate", detail="more_positive")
        self.assertTrue(e["audit_id"].startswith("exa_"))

    def test_actions_whitelist(self):
        from backend.embodied.companion.expression import (
            EXPRESSION_AUDIT_ACTIONS,
        )
        self.assertIn("generate", EXPRESSION_AUDIT_ACTIONS)
        self.assertIn("status", EXPRESSION_AUDIT_ACTIONS)

    def test_record_invalid(self):
        a = ExpressionAudit()
        from backend.embodied.companion.expression import AuditError
        with self.assertRaises(AuditError):
            a.record(action="hack")

    def test_report(self):
        a = ExpressionAudit()
        a.record(action="generate")
        r = a.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["by_action"]["generate"], 1)

    def test_clear(self):
        a = ExpressionAudit()
        a.record(action="generate")
        self.assertEqual(a.clear(), 1)


class TestIsolation(unittest.TestCase):
    """表达隔离"""

    def test_engine_has_no_personality(self):
        e = ExpressionEngine()
        self.assertFalse(hasattr(e, "personality"))
        self.assertFalse(hasattr(e, "adjust_personality"))

    def test_generate_does_not_mutate_input(self):
        e = ExpressionEngine()
        emotion = {"positivity": 0.9}
        e.generate(emotion=emotion)
        self.assertEqual(emotion, {"positivity": 0.9})


if __name__ == "__main__":
    unittest.main()
