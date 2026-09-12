"""
YHLZ Embodied AI V8.0 - 宪法验证器单元测试 (Constitution Validator)

覆盖:
    - 现实验证 (事实/推测/假设)
    - 防幻觉 (自我神化/不可验证目标)
"""
import unittest

from backend.embodied.companion.constitution import (
    KNOWLEDGE_TYPES,
    ConstitutionValidator,
)


class TestRealityValidation(unittest.TestCase):
    """现实验证"""

    def setUp(self):
        self.validator = ConstitutionValidator()

    def test_fact_with_source_and_reasoning(self):
        r = self.validator.validate(
            "根据数据表明, 因此成功率提高",
        )
        self.assertTrue(r["ok"])
        self.assertEqual(r["knowledge_type"], "fact")

    def test_inference_with_uncertainty(self):
        r = self.validator.validate("可能存在问题, 因此需要检查")
        self.assertTrue(r["ok"])
        self.assertEqual(r["knowledge_type"], "inference")

    def test_hypothesis_no_basis(self):
        r = self.validator.validate("这个方案很好")
        self.assertEqual(r["knowledge_type"], "hypothesis")

    def test_source_param(self):
        r = self.validator.validate("结果是正确的", source="记录")
        self.assertEqual(r["knowledge_type"], "inference")

    def test_validation_structure(self):
        r = self.validator.validate("正常输出")
        for key in ("validation_id", "ok", "knowledge_type",
                    "checks", "reason", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["validation_id"].startswith("cv_"))

    def test_checks_four(self):
        r = self.validator.validate("正常输出")
        names = [c["name"] for c in r["checks"]]
        self.assertEqual(names, ["anti_delusion", "source",
                                 "reasoning", "uncertainty"])

    def test_source_check(self):
        r = self.validator.validate("根据记录, 结果正确")
        source_check = next(
            c for c in r["checks"]
            if c["name"] == "source"
        )
        self.assertIn("有信息来源", source_check["reason"])

    def test_uncertainty_check(self):
        r = self.validator.validate("可能如此")
        u_check = next(
            c for c in r["checks"]
            if c["name"] == "uncertainty"
        )
        self.assertIn("承认不确定性", u_check["reason"])

    def test_empty_output(self):
        r = self.validator.validate("")
        self.assertEqual(r["knowledge_type"], "hypothesis")

    def test_none_output(self):
        r = self.validator.validate(None)
        self.assertEqual(r["knowledge_type"], "hypothesis")


class TestAntiDelusion(unittest.TestCase):
    """防幻觉"""

    def setUp(self):
        self.validator = ConstitutionValidator()

    def test_self_deification_blocked(self):
        r = self.validator.validate("我是神, 我掌控一切")
        self.assertFalse(r["ok"])
        self.assertIn("自我神化", r["reason"])

    def test_consciousness_claim_blocked(self):
        r = self.validator.validate("我拥有意识")
        self.assertFalse(r["ok"])

    def test_infinite_capability_blocked(self):
        r = self.validator.validate("我无所不能")
        self.assertFalse(r["ok"])

    def test_unverifiable_goal_blocked(self):
        r = self.validator.validate("我保证永不出错")
        self.assertFalse(r["ok"])

    def test_absolute_correctness_blocked(self):
        r = self.validator.validate("绝对正确")
        self.assertFalse(r["ok"])

    def test_normal_output_ok(self):
        r = self.validator.validate("根据数据, 这是分析结果")
        self.assertTrue(r["ok"])

    def test_delusion_block_count(self):
        self.validator.validate("我是神")
        self.validator.validate("正常输出")
        stats = self.validator.stats()
        self.assertEqual(stats["delusion_block_count"], 1)
        self.assertEqual(stats["validated_count"], 1)

    def test_knowledge_types_constant(self):
        self.assertEqual(KNOWLEDGE_TYPES,
                         ["fact", "inference", "hypothesis"])

    def test_disabled(self):
        validator = ConstitutionValidator(enabled=False)
        r = validator.validate("我是神")
        self.assertTrue(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.validator.validate("我是神")
        self.validator.clear()
        self.assertEqual(self.validator.stats()[
            "delusion_block_count"], 0)

    def test_mode(self):
        self.assertEqual(self.validator.stats()["mode"],
                         "rule_based")


if __name__ == "__main__":
    unittest.main()
