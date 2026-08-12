"""
YHLZ Vision Action V1.0 - 权限单元测试

覆盖:
    - 默认拒绝 (action_enabled=False)
    - load / update / reset
    - 风险评估: 低 / 中 / 高风险关键词
    - 高风险需确认 (require_confirm)
    - ActionPermission 序列化
"""
import unittest

from backend.action.permission import (
    ActionPermission,
    ActionPermissionConfig,
    PermissionChecker,
)
from backend.action.schema import ActionRequest


class TestActionPermission(unittest.TestCase):

    def test_default_denied(self):
        perm = ActionPermissionConfig()
        self.assertFalse(perm.action_enabled)
        self.assertTrue(perm.require_confirm_high_risk)

    def test_to_dict_from_dict(self):
        cfg = ActionPermissionConfig(action_enabled=True, require_confirm_high_risk=False)
        d = cfg.to_dict()
        self.assertTrue(d["action_enabled"])
        cfg2 = ActionPermissionConfig.from_dict(d)
        self.assertTrue(cfg2.action_enabled)
        self.assertFalse(cfg2.require_confirm_high_risk)

    def test_action_permission_to_dict(self):
        p = ActionPermission(allowed=True, require_confirm=True, risk_level="high", reason="x")
        d = p.to_dict()
        self.assertTrue(d["allowed"])
        self.assertTrue(d["require_confirm"])
        self.assertEqual(d["risk_level"], "high")


class TestPermissionChecker(unittest.TestCase):

    def setUp(self):
        self.checker = PermissionChecker()

    def test_check_enabled_default_denied(self):
        allowed, reason = self.checker.check_enabled()
        self.assertFalse(allowed)
        self.assertIn("action_enabled", reason)

    def test_check_enabled_after_load(self):
        self.checker.load(action_enabled=True)
        allowed, _ = self.checker.check_enabled()
        self.assertTrue(allowed)

    def test_load_from_config(self):
        self.checker.load_from_config(ActionPermissionConfig(action_enabled=True))
        allowed, _ = self.checker.check_enabled()
        self.assertTrue(allowed)

    def test_update(self):
        self.checker.update(action_enabled=True)
        self.assertTrue(self.checker.config.action_enabled)
        self.checker.update(require_confirm_high_risk=False)
        self.assertFalse(self.checker.config.require_confirm_high_risk)

    def test_reset(self):
        self.checker.load(action_enabled=True)
        self.checker.reset()
        allowed, _ = self.checker.check_enabled()
        self.assertFalse(allowed)

    # ── 风险评估 ──────────────────────────────────────────────────
    def test_risk_low(self):
        req = ActionRequest.create(action_type="check", target="logs", reason="查看日志")
        self.assertEqual(PermissionChecker.risk_of(req), "low")

    def test_risk_medium_keyword(self):
        req = ActionRequest.create(action_type="check", target="config", reason="查看配置")
        self.assertEqual(PermissionChecker.risk_of(req), "medium")

    def test_risk_high_keyword(self):
        req = ActionRequest.create(action_type="execute", target="delete tmp", reason="清理")
        self.assertEqual(PermissionChecker.risk_of(req), "high")

    def test_risk_high_chinese(self):
        req = ActionRequest.create(action_type="execute", target="", reason="删除文件")
        self.assertEqual(PermissionChecker.risk_of(req), "high")

    def test_risk_declared_high_wins(self):
        req = ActionRequest.create(action_type="check", target="logs", risk_level="high")
        self.assertEqual(PermissionChecker.risk_of(req), "high")

    def test_risk_declared_high_over_medium_text(self):
        req = ActionRequest.create(action_type="check", target="config", risk_level="high")
        self.assertEqual(PermissionChecker.risk_of(req), "high")

    def test_risk_parameters_considered(self):
        req = ActionRequest.create(
            action_type="execute", target="file",
            parameters={"op": "format"}, reason="")
        self.assertEqual(PermissionChecker.risk_of(req), "high")

    # ── 权限判定 ──────────────────────────────────────────────────
    def test_evaluate_denied_when_disabled(self):
        req = ActionRequest.create(action_type="check", target="logs")
        perm = self.checker.evaluate(req)
        self.assertFalse(perm.allowed)
        self.assertIn("总开关", perm.reason)

    def test_evaluate_low_allowed(self):
        self.checker.load(action_enabled=True)
        req = ActionRequest.create(action_type="check", target="logs")
        perm = self.checker.evaluate(req)
        self.assertTrue(perm.allowed)
        self.assertFalse(perm.require_confirm)
        self.assertEqual(perm.risk_level, "low")

    def test_evaluate_high_requires_confirm(self):
        self.checker.load(action_enabled=True)
        req = ActionRequest.create(action_type="execute", target="", reason="删除文件")
        perm = self.checker.evaluate(req)
        self.assertTrue(perm.allowed)
        self.assertTrue(perm.require_confirm)
        self.assertEqual(perm.risk_level, "high")

    def test_evaluate_high_no_confirm_configured(self):
        self.checker.load(action_enabled=True, require_confirm_high_risk=False)
        req = ActionRequest.create(action_type="execute", target="", reason="删除文件")
        perm = self.checker.evaluate(req)
        self.assertTrue(perm.allowed)
        self.assertFalse(perm.require_confirm)

    def test_to_dict(self):
        self.checker.load(action_enabled=True)
        d = self.checker.to_dict()
        self.assertTrue(d["action_enabled"])


if __name__ == "__main__":
    unittest.main()
