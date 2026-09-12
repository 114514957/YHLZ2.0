"""
YHLZ Personality Engine V3.4 - Agent 工具单元测试

覆盖:
    - get_personality_style 工具注册 / 注销 / 元数据
    - 工具调用: 风格生成 / 上下文 / 权限拒绝 / 异常
"""
import json
import unittest

from backend.personality.manager import PersonalityManager
from backend.personality.permission import PermissionChecker
from backend.personality.service import reset_service
from backend.personality.stores.memory_store import InMemoryPersonalityStore
from backend.personality.tools import (
    PERSONALITY_TOOL_NAMES,
    register_personality_tools,
    unregister_personality_tools,
)


class TestPersonalityTools(unittest.TestCase):

    def setUp(self):
        from backend.personality.service import get_service
        reset_service()
        self.store = InMemoryPersonalityStore()
        self.mgr = PersonalityManager()
        self.mgr.register_store("test", self.store)
        self.svc = get_service()
        self.svc.set_manager(self.mgr)
        self.svc.set_permission(PermissionChecker())
        self.n = register_personality_tools(override=True)

    def tearDown(self):
        unregister_personality_tools()
        reset_service()

    def _call_tool(self, params):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("get_personality_style")
        self.assertIsNotNone(tool, "get_personality_style 工具未注册")
        return tool.handler(params)

    # ── 注册 ──────────────────────────────────────────────────────
    def test_register_count(self):
        self.assertEqual(self.n, 1)
        from backend.agent.tool_registry import get_registry
        self.assertTrue(get_registry().has("get_personality_style"))

    def test_tool_category(self):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("get_personality_style")
        self.assertEqual(tool.category, "personality")

    def test_tool_required_params(self):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("get_personality_style")
        self.assertEqual(tool.parameters.required, [])

    def test_re_register_override(self):
        n = register_personality_tools(override=True)
        self.assertEqual(n, 1)

    def test_unregister(self):
        n = unregister_personality_tools()
        self.assertEqual(n, 1)
        from backend.agent.tool_registry import get_registry
        self.assertFalse(get_registry().has("get_personality_style"))

    # ── 调用 ──────────────────────────────────────────────────────
    def test_style_denied_by_default(self):
        out = json.loads(self._call_tool({}))
        self.assertFalse(out["success"])
        self.assertEqual(out["status"], "denied")

    def test_style_ok(self):
        self.svc.update_permission(personality_enabled=True)
        self.svc.load_default()
        out = json.loads(self._call_tool({}))
        self.assertTrue(out["success"])
        self.assertIn("你是 YHLZ 默认人格", out["style"])
        self.assertEqual(out["profile_name"], "YHLZ 默认人格")

    def test_style_custom_profile(self):
        self.svc.update_permission(personality_enabled=True)
        from backend.personality.schema import PersonalityProfile
        self.svc.save(PersonalityProfile.create(name="严谨人格", active=True))
        out = json.loads(self._call_tool({}))
        self.assertTrue(out["success"])
        self.assertIn("严谨人格", out["style"])

    def test_context_ok(self):
        self.svc.update_permission(personality_enabled=True)
        self.svc.load_default()
        out = json.loads(self._call_tool({"include_context": True}))
        self.assertTrue(out["success"])
        self.assertIn("人格档案", out["context"])

    def test_context_denied(self):
        out = json.loads(self._call_tool({"include_context": True}))
        self.assertFalse(out["success"])
        self.assertEqual(out["status"], "denied")

    def test_style_no_profile(self):
        self.svc.update_permission(personality_enabled=True)
        out = json.loads(self._call_tool({}))
        # 无活跃档案时 load_default 会自动创建
        self.assertTrue(out["success"])


if __name__ == "__main__":
    unittest.main()
