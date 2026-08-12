"""
YHLZ Embodied AI V4.0 - 权限系统单元测试

覆盖:
    - 默认关闭 (embodied_enabled=False 全部拒绝)
    - 风险等级评估 (低 / 中 / 高 / 声明高)
    - 高风险确认机制
    - 配置加载 / 更新 / 重置
"""
import unittest

from backend.embodied.permission import (
    HIGH_RISK_KEYWORDS,
    MEDIUM_RISK_KEYWORDS,
    EmbodiedPermissionConfig,
    PermissionChecker,
)
from backend.embodied.schema import EmbodiedAction


class TestDefaultDeny(unittest.TestCase):

    def setUp(self):
        self.checker = PermissionChecker()

    def test_default_disabled(self):
        """安全默认: 具身总开关默认关闭"""
        self.assertFalse(self.checker.config.embodied_enabled)

    def test_evaluate_denied_when_disabled(self):
        a = EmbodiedAction.create(action_type="scan")
        perm = self.checker.evaluate(a)
        self.assertFalse(perm.allowed)
        self.assertIn("embodied_enabled=False", perm.reason)

    def test_config_defaults(self):
        cfg = EmbodiedPermissionConfig()
        self.assertFalse(cfg.embodied_enabled)
        self.assertTrue(cfg.require_confirm_high_risk)

    def test_config_from_dict_defaults(self):
        cfg = EmbodiedPermissionConfig.from_dict({})
        self.assertFalse(cfg.embodied_enabled)
        self.assertTrue(cfg.require_confirm_high_risk)


class TestRiskEvaluation(unittest.TestCase):

    def setUp(self):
        self.checker = PermissionChecker()
        self.checker.load(embodied_enabled=True)

    def test_low_risk_scan(self):
        a = EmbodiedAction.create(action_type="scan", intent="扫描环境")
        perm = self.checker.evaluate(a)
        self.assertTrue(perm.allowed)
        self.assertEqual(perm.risk_level, "low")
        self.assertFalse(perm.require_confirm)

    def test_medium_risk_move(self):
        a = EmbodiedAction.create(action_type="move", intent="移动到门口", parameters={"dx": 1, "dy": 0})
        perm = self.checker.evaluate(a)
        self.assertEqual(perm.risk_level, "medium")

    def test_high_risk_keyword(self):
        a = EmbodiedAction.create(action_type="custom", intent="重置整个环境")
        perm = self.checker.evaluate(a)
        self.assertEqual(perm.risk_level, "high")

    def test_high_risk_target(self):
        a = EmbodiedAction.create(action_type="custom", target="delete")
        perm = self.checker.evaluate(a)
        self.assertEqual(perm.risk_level, "high")

    def test_declared_high_is_high(self):
        a = EmbodiedAction.create(action_type="scan", risk_level="high")
        perm = self.checker.evaluate(a)
        self.assertEqual(perm.risk_level, "high")

    def test_high_risk_requires_confirm(self):
        a = EmbodiedAction.create(action_type="custom", intent="shutdown")
        perm = self.checker.evaluate(a)
        self.assertTrue(perm.require_confirm)

    def test_no_confirm_when_configured(self):
        self.checker.load(embodied_enabled=True, require_confirm_high_risk=False)
        a = EmbodiedAction.create(action_type="custom", intent="shutdown")
        perm = self.checker.evaluate(a)
        self.assertFalse(perm.require_confirm)
        self.assertTrue(perm.allowed)

    def test_risk_of_parameters(self):
        a = EmbodiedAction.create(action_type="custom", parameters={"op": "format"})
        self.assertEqual(self.checker.risk_of(a), "high")

    def test_risk_of_parameters_unserializable(self):
        a = EmbodiedAction.create(action_type="scan", parameters={"bad": object()})
        self.assertEqual(self.checker.risk_of(a), "low")


class TestPermissionConfigOps(unittest.TestCase):

    def setUp(self):
        self.checker = PermissionChecker()

    def test_load_kwargs(self):
        self.checker.load(embodied_enabled=True, require_confirm_high_risk=False)
        self.assertTrue(self.checker.config.embodied_enabled)
        self.assertFalse(self.checker.config.require_confirm_high_risk)

    def test_load_from_config(self):
        cfg = EmbodiedPermissionConfig(embodied_enabled=True)
        self.checker.load_from_config(cfg)
        self.assertTrue(self.checker.config.embodied_enabled)

    def test_update_field(self):
        self.checker.load(embodied_enabled=False)
        self.checker.update(embodied_enabled=True)
        self.assertTrue(self.checker.config.embodied_enabled)

    def test_update_none_ignored(self):
        self.checker.update(embodied_enabled=None)
        self.assertFalse(self.checker.config.embodied_enabled)

    def test_update_unknown_ignored(self):
        self.checker.update(nonexistent_field=123)
        self.assertFalse(hasattr(self.checker.config, "nonexistent_field"))

    def test_reset_to_default(self):
        self.checker.load(embodied_enabled=True)
        self.checker.reset()
        self.assertFalse(self.checker.config.embodied_enabled)

    def test_to_dict(self):
        self.checker.load(embodied_enabled=True)
        d = self.checker.to_dict()
        self.assertTrue(d["embodied_enabled"])
        self.assertIn("require_confirm_high_risk", d)

    def test_check_enabled(self):
        ok, reason = self.checker.check_enabled()
        self.assertFalse(ok)
        self.checker.load(embodied_enabled=True)
        ok, _ = self.checker.check_enabled()
        self.assertTrue(ok)

    def test_permission_to_dict(self):
        from backend.embodied.permission import EmbodiedPermission
        p = EmbodiedPermission(allowed=True, require_confirm=True, risk_level="high", reason="r")
        d = p.to_dict()
        self.assertTrue(d["allowed"])
        self.assertEqual(d["risk_level"], "high")


class TestKeywordTables(unittest.TestCase):

    def test_keywords_non_empty(self):
        self.assertTrue(HIGH_RISK_KEYWORDS)
        self.assertTrue(MEDIUM_RISK_KEYWORDS)

    def test_no_overlap(self):
        """高风险与中风险关键词互不重叠 (评估顺序确定)"""
        self.assertEqual(set(HIGH_RISK_KEYWORDS) & set(MEDIUM_RISK_KEYWORDS), set())


if __name__ == "__main__":
    unittest.main()
