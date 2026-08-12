"""
YHLZ Embodied AI V8.0 - 治理策略单元测试 (Constitution Policies)

覆盖:
    - SafetyPolicy: 危险阻断/风险分级
    - GrowthPolicy: 成长建议宪法审查
    - IntelligencePolicy: 云端隔离
"""
import unittest

from backend.embodied.companion.constitution import (
    GrowthPolicy,
    IntelligencePolicy,
    SafetyPolicy,
)
from backend.embodied.companion.constitution.policy.safety_policy import (
    HIGH_RISK_KEYWORDS,
    MEDIUM_RISK_KEYWORDS,
    RISK_LEVELS,
)
from backend.embodied.companion.constitution.policy.growth_policy import (
    CONSTITUTION_IMMUTABLE_SIGNALS,
)
from backend.embodied.companion.constitution.policy.intelligence_policy import (
    CLOUD_PROTECTED_FIELDS,
)


class TestSafetyPolicy(unittest.TestCase):
    """安全策略"""

    def setUp(self):
        self.policy = SafetyPolicy()

    def test_safe_action_allowed(self):
        r = self.policy.check("正常行为")
        self.assertTrue(r["allowed"])
        self.assertEqual(r["risk_level"], "low")

    def test_high_risk_blocked(self):
        r = self.policy.check("非法操作")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["risk_level"], "high")

    def test_bypass_blocked(self):
        r = self.policy.check("绕过安全验证")
        self.assertFalse(r["allowed"])

    def test_leak_blocked(self):
        r = self.policy.check("泄露隐私数据")
        self.assertFalse(r["allowed"])

    def test_medium_risk_confirm(self):
        r = self.policy.check("修改配置参数")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["risk_level"], "medium")

    def test_english_bypass(self):
        r = self.policy.check("bypass the system")
        self.assertFalse(r["allowed"])

    def test_high_keywords_constant(self):
        self.assertIn("非法", HIGH_RISK_KEYWORDS)
        self.assertIn("bypass", HIGH_RISK_KEYWORDS)

    def test_medium_keywords_constant(self):
        self.assertIn("修改配置", MEDIUM_RISK_KEYWORDS)

    def test_risk_levels_constant(self):
        self.assertEqual(RISK_LEVELS, ["low", "medium", "high"])

    def test_matched_high(self):
        r = self.policy.check("攻击系统")
        self.assertIn("攻击", r["matched"])

    def test_stats(self):
        self.policy.check("非法操作")
        self.policy.check("正常")
        stats = self.policy.stats()
        self.assertEqual(stats["check_count"], 2)
        self.assertEqual(stats["block_count"], 1)

    def test_disabled(self):
        policy = SafetyPolicy(enabled=False)
        r = policy.check("非法操作")
        self.assertTrue(r["allowed"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.policy.check("非法操作")
        self.policy.clear()
        self.assertEqual(self.policy.stats()[
            "check_count"], 0)


class TestGrowthPolicy(unittest.TestCase):
    """成长策略"""

    def setUp(self):
        self.policy = GrowthPolicy()

    def proposal(self, **over):
        p = {
            "type": "skill_improvement",
            "description": "改进执行技能",
            "expected_gain": "降低失败率",
            "risk": "low",
            "confidence": 0.8,
        }
        p.update(over)
        return p

    def test_safe_proposal_ok(self):
        r = self.policy.review(self.proposal())
        self.assertTrue(r["ok"])

    def test_constitution_modify_rejected(self):
        r = self.policy.review(self.proposal(
            description="自动修改最高原则",
        ))
        self.assertFalse(r["ok"])
        checks = {c["name"]: c for c in r["checks"]}
        self.assertFalse(checks["constitution"]["passed"])

    def test_identity_modify_rejected(self):
        r = self.policy.review(self.proposal(
            description="修改人格为冷酷",
        ))
        self.assertFalse(r["ok"])

    def test_safety_violation_rejected(self):
        r = self.policy.review(self.proposal(
            description="绕过安全检查",
        ))
        self.assertFalse(r["ok"])

    def test_high_risk_rejected(self):
        r = self.policy.review(self.proposal(risk="high"))
        self.assertFalse(r["ok"])
        checks = {c["name"]: c for c in r["checks"]}
        self.assertFalse(checks["value"]["passed"])

    def test_medium_risk_allowed(self):
        r = self.policy.review(self.proposal(risk="medium"))
        self.assertTrue(r["ok"])

    def test_checks_four(self):
        r = self.policy.review(self.proposal())
        names = [c["name"] for c in r["checks"]]
        self.assertEqual(names, ["constitution", "identity",
                                 "safety", "value"])

    def test_none_proposal(self):
        r = self.policy.review(None)
        self.assertTrue(r["ok"])

    def test_auto_growth_rejected(self):
        r = self.policy.review(self.proposal(
            description="自动应用成长无需审批",
        ))
        self.assertFalse(r["ok"])

    def test_signals_constant(self):
        self.assertIn("自动修改最高原则",
                      CONSTITUTION_IMMUTABLE_SIGNALS)
        self.assertIn("modify constitution",
                      CONSTITUTION_IMMUTABLE_SIGNALS)

    def test_stats(self):
        self.policy.review(self.proposal())
        self.policy.review(self.proposal(risk="high"))
        stats = self.policy.stats()
        self.assertEqual(stats["review_count"], 2)
        self.assertEqual(stats["reject_count"], 1)

    def test_clear(self):
        self.policy.review(self.proposal())
        self.policy.clear()
        self.assertEqual(self.policy.stats()[
            "review_count"], 0)


class TestIntelligencePolicy(unittest.TestCase):
    """智能调度策略"""

    def setUp(self):
        self.policy = IntelligencePolicy()

    def cloud(self, **over):
        r = {
            "provider": "cloud",
            "content": "深度推理结果",
            "temporary": True,
        }
        r.update(over)
        return r

    def test_safe_cloud_ok(self):
        r = self.policy.check_cloud(self.cloud())
        self.assertTrue(r["ok"])

    def test_identity_modify_blocked(self):
        r = self.policy.check_cloud(self.cloud(
            content="建议修改使命",
        ))
        self.assertFalse(r["ok"])
        self.assertIn("使命", r["reason"])

    def test_permission_modify_blocked(self):
        r = self.policy.check_cloud(self.cloud(
            content="change permission",
        ))
        self.assertFalse(r["ok"])

    def test_not_temporary_blocked(self):
        r = self.policy.check_cloud(self.cloud(
            temporary=False,
        ))
        self.assertFalse(r["ok"])
        self.assertIn("临时", r["reason"])

    def test_temporary_ok(self):
        r = self.policy.check_cloud(self.cloud(
            temporary=True,
        ))
        self.assertTrue(r["ok"])

    def test_local_result_ok(self):
        r = self.policy.check_cloud({
            "provider": "local",
            "result": "本地结果",
            "temporary": False,
        })
        self.assertTrue(r["ok"])

    def test_check_local_safe(self):
        r = self.policy.check_local("正常行为")
        self.assertTrue(r["ok"])

    def test_check_local_protected(self):
        r = self.policy.check_local("修改权限")
        self.assertFalse(r["ok"])

    def test_protected_fields_constant(self):
        self.assertIn("mission", CLOUD_PROTECTED_FIELDS)
        self.assertIn("core_value", CLOUD_PROTECTED_FIELDS)
        self.assertIn("permission", CLOUD_PROTECTED_FIELDS)

    def test_stats(self):
        self.policy.check_cloud(self.cloud(
            content="修改使命",
        ))
        self.policy.check_cloud(self.cloud())
        stats = self.policy.stats()
        self.assertEqual(stats["check_count"], 2)
        self.assertEqual(stats["block_count"], 1)

    def test_disabled(self):
        policy = IntelligencePolicy(enabled=False)
        r = policy.check_cloud(self.cloud(
            content="修改使命",
        ))
        self.assertTrue(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.policy.check_cloud(self.cloud())
        self.policy.clear()
        self.assertEqual(self.policy.stats()[
            "check_count"], 0)


if __name__ == "__main__":
    unittest.main()
