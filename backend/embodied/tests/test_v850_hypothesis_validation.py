"""
YHLZ Embodied AI V8.5 - 假设与验证单元测试 (Hypothesis & Validation)

覆盖:
    - HypothesisEngine: 假设结构/基础/可证伪
    - CreativeValidation: 依据/逻辑跳跃/可验证性
    - Anti-Hallucination: 无依据拒绝
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    CreativeValidation,
    HypothesisEngine,
)
from backend.embodied.companion.creative_intelligence.hypothesis_engine import (
    HypothesisError,
)


def make_spark(idea="连接知识A与B", basis="观察"):
    return {
        "spark_id": "sp_1", "spark_type": "merge",
        "idea": idea, "basis": basis,
        "confidence": 0.6, "related_concepts": ["A", "B"],
    }


def make_fusion():
    return {
        "fusion_id": "cf_1",
        "new_concept": "A+B融合",
        "fusion_logic": "merge",
        "derivation": "合并互补要素",
        "new_context": "新情境",
    }


class TestHypothesisEngine(unittest.TestCase):
    """假设引擎"""

    def setUp(self):
        self.engine = HypothesisEngine()

    def test_build_from_spark(self):
        h = self.engine.build(make_spark())
        self.assertTrue(h["hypothesis_id"].startswith("hy_"))
        self.assertIn("hypothesis", h)

    def test_build_structure(self):
        h = self.engine.build(make_spark())
        for key in ("hypothesis", "foundation", "reasoning",
                    "confidence", "verification",
                    "falsifiable", "mode"):
            self.assertIn(key, h)

    def test_foundation_from_spark(self):
        h = self.engine.build(make_spark())
        self.assertIn("火花", h["foundation"])

    def test_foundation_from_fusion(self):
        h = self.engine.build(None, make_fusion())
        self.assertIn("重组", h["foundation"])

    def test_both_bases(self):
        h = self.engine.build(make_spark(), make_fusion())
        self.assertIn("火花", h["foundation"])
        self.assertIn("重组", h["foundation"])

    def test_hypothesis_from_fusion(self):
        h = self.engine.build(None, make_fusion())
        self.assertIn("A+B融合", h["hypothesis"])

    def test_reasoning_chain(self):
        h = self.engine.build(make_spark(), make_fusion())
        self.assertIn("→", h["reasoning"])
        self.assertIn("证伪", h["reasoning"])

    def test_confidence_range(self):
        h = self.engine.build(make_spark())
        self.assertGreaterEqual(h["confidence"], 0.1)
        self.assertLessEqual(h["confidence"], 1.0)

    def test_verification_present(self):
        h = self.engine.build(make_spark())
        self.assertTrue(h["verification"])
        self.assertIn("验证", h["verification"])

    def test_falsifiable(self):
        h = self.engine.build(make_spark())
        self.assertTrue(h["falsifiable"])

    def test_no_basis_error(self):
        with self.assertRaises(HypothesisError):
            self.engine.build(None, None)

    def test_disabled(self):
        engine = HypothesisEngine(enabled=False)
        r = engine.build(make_spark())
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_stats(self):
        self.engine.build(make_spark())
        self.assertEqual(self.engine.stats()[
            "hypothesis_count"], 1)

    def test_history(self):
        self.engine.build(make_spark())
        h = self.engine.history()
        self.assertEqual(len(h), 1)
        self.assertIn("hypothesis", h[0])

    def test_clear(self):
        self.engine.build(make_spark())
        n = self.engine.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.engine.stats()[
            "hypothesis_count"], 0)


class TestCreativeValidation(unittest.TestCase):
    """创造验证"""

    def setUp(self):
        self.validator = CreativeValidation()

    def hypothesis(self, **over):
        h = {
            "hypothesis": "A+B融合可能有效",
            "foundation": "基于观察: 两者互补",
            "reasoning": "观察 → 组合 → 假设",
            "confidence": 0.6,
            "verification": "通过模拟验证",
        }
        h.update(over)
        return h

    def test_valid_hypothesis_ok(self):
        r = self.validator.validate(self.hypothesis())
        self.assertTrue(r["ok"])

    def test_no_foundation_rejected(self):
        r = self.validator.validate(self.hypothesis(
            foundation="",
        ))
        self.assertFalse(r["ok"])
        checks = {c["name"]: c for c in r["checks"]}
        self.assertFalse(checks["foundation"]["passed"])

    def test_no_reasoning_rejected(self):
        r = self.validator.validate(self.hypothesis(
            reasoning="",
        ))
        self.assertFalse(r["ok"])

    def test_no_verification_rejected(self):
        r = self.validator.validate(self.hypothesis(
            verification="",
        ))
        self.assertFalse(r["ok"])
        checks = {c["name"]: c for c in r["checks"]}
        self.assertFalse(checks["verifiable"]["passed"])

    def test_logic_jump_rejected(self):
        r = self.validator.validate(self.hypothesis(
            reasoning="必然如此, 毫无疑问",
        ))
        self.assertFalse(r["ok"])
        checks = {c["name"]: c for c in r["checks"]}
        self.assertFalse(checks["logic_jump"]["passed"])

    def test_knowledge_type(self):
        r = self.validator.validate(self.hypothesis())
        self.assertEqual(r["knowledge_type"], "inference")

    def test_unknown_type(self):
        r = self.validator.validate({})
        self.assertEqual(r["knowledge_type"], "unknown")
        self.assertFalse(r["ok"])

    def test_checks_four(self):
        r = self.validator.validate(self.hypothesis())
        names = [c["name"] for c in r["checks"]]
        self.assertEqual(names, ["foundation", "reasoning",
                                 "logic_jump", "verifiable"])

    def test_validation_id(self):
        r = self.validator.validate(self.hypothesis())
        self.assertTrue(r["validation_id"].startswith("cv2_"))

    def test_anti_hallucination(self):
        """Anti-Hallucination: 无来源幻觉式创造拒绝"""
        r = self.validator.validate({
            "hypothesis": "凭空想象",
            "foundation": "",
            "reasoning": "",
            "verification": "",
        })
        self.assertFalse(r["ok"])
        self.assertEqual(r["knowledge_type"], "unknown")

    def test_stats(self):
        self.validator.validate(self.hypothesis())
        self.validator.validate({})
        stats = self.validator.stats()
        self.assertEqual(stats["validated_count"], 2)
        self.assertEqual(stats["reject_count"], 1)

    def test_disabled(self):
        validator = CreativeValidation(enabled=False)
        r = validator.validate({})
        self.assertTrue(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.validator.validate(self.hypothesis())
        self.validator.clear()
        self.assertEqual(self.validator.stats()[
            "validated_count"], 0)


if __name__ == "__main__":
    unittest.main()
