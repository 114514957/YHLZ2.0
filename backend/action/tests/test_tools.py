"""
YHLZ Vision Action V1.0 - Agent 工具单元测试

覆盖:
    - request_action 工具注册 / 注销 / 元数据
    - 工具调用: 默认拒绝 / 执行成功 / 高风险待确认 / 确认后执行
"""
import json
import unittest

from backend.action.manager import ActionManager
from backend.action.permission import PermissionChecker
from backend.action.service import reset_service
from backend.action.tools import (
    ACTION_TOOL_NAMES,
    register_action_tools,
    unregister_action_tools,
)


class TestActionTools(unittest.TestCase):

    def setUp(self):
        from backend.action.executors.mock_executor import MockActionExecutor
        from backend.action.service import get_service
        reset_service()
        self.mgr = ActionManager()
        self.mgr.register_executor("test", MockActionExecutor())
        self.svc = get_service()
        self.svc.set_manager(self.mgr)
        self.svc.set_permission(PermissionChecker())
        self.n = register_action_tools(override=True)

    def tearDown(self):
        unregister_action_tools()
        reset_service()

    def _call_tool(self, params):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("request_action")
        self.assertIsNotNone(tool, "request_action 工具未注册")
        return tool.handler(params)

    # ── 注册 ──────────────────────────────────────────────────────
    def test_register_count(self):
        self.assertEqual(self.n, 1)
        from backend.agent.tool_registry import get_registry
        self.assertTrue(get_registry().has("request_action"))

    def test_tool_category(self):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("request_action")
        self.assertEqual(tool.category, "action")

    def test_tool_required_params(self):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("request_action")
        self.assertEqual(tool.parameters.required, ["action_type"])

    def test_re_register_override(self):
        n = register_action_tools(override=True)
        self.assertEqual(n, 1)

    def test_unregister(self):
        n = unregister_action_tools()
        self.assertEqual(n, 1)
        from backend.agent.tool_registry import get_registry
        self.assertFalse(get_registry().has("request_action"))

    # ── 调用 ──────────────────────────────────────────────────────
    def test_denied_by_default(self):
        out = json.loads(self._call_tool({"action_type": "check", "target": "logs"}))
        self.assertFalse(out["success"])
        self.assertEqual(out["status"], "denied")

    def test_ok(self):
        self.svc.update_permission(action_enabled=True)
        out = json.loads(self._call_tool({
            "action_type": "check", "target": "logs",
            "reason": "检查日志", "confidence": 0.8,
        }))
        self.assertTrue(out["success"])
        self.assertEqual(out["status"], "ok")
        self.assertIn("action_id", out)

    def test_awaiting_confirm_high_risk(self):
        self.svc.update_permission(action_enabled=True)
        out = json.loads(self._call_tool({
            "action_type": "execute", "target": "tmp",
            "reason": "删除临时文件", "confidence": 0.9,
        }))
        self.assertTrue(out["success"])
        self.assertEqual(out["status"], "awaiting_confirm")
        self.assertTrue(out["permission"]["require_confirm"])

    def test_confirmed_high_risk(self):
        self.svc.update_permission(action_enabled=True)
        out = json.loads(self._call_tool({
            "action_type": "execute", "target": "tmp",
            "reason": "删除临时文件", "confidence": 0.9,
            "confirmed": True,
        }))
        self.assertEqual(out["status"], "ok")

    def test_invalid_type(self):
        self.svc.update_permission(action_enabled=True)
        out = json.loads(self._call_tool({"action_type": "hack", "target": "x"}))
        self.assertFalse(out["success"])
        self.assertEqual(out["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
