"""
YHLZ Vision Memory V1.0 - Agent 工具单元测试

覆盖:
    - search_visual_memory 工具注册 / 注销
    - 工具调用: 检索 / 无结果 / 权限拒绝 / 参数校验
"""
import json
import unittest

from backend.vision.memory.manager import MemoryManager
from backend.vision.memory.permission import PermissionChecker
from backend.vision.memory.schema import VisualMemoryRecord
from backend.vision.memory.service import MemoryService, reset_service
from backend.vision.memory.stores.memory_store import InMemoryMemoryStore
from backend.vision.memory.tools import (
    VISION_MEMORY_TOOL_NAMES,
    register_vision_memory_tools,
    unregister_vision_memory_tools,
)


class TestVisionMemoryTools(unittest.TestCase):

    def setUp(self):
        # 工具 handler 调用全局单例 get_service(), 因此注入测试依赖到单例
        from backend.vision.memory.service import get_service, reset_service
        reset_service()
        self.store = InMemoryMemoryStore()
        self.mgr = MemoryManager()
        self.mgr.register_store("test", self.store)
        self.svc = get_service()
        self.svc.set_manager(self.mgr)
        self.svc.set_permission(PermissionChecker())
        self.n = register_vision_memory_tools(override=True)

    def tearDown(self):
        unregister_vision_memory_tools()
        reset_service()

    def _call_tool(self, params):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("search_visual_memory")
        self.assertIsNotNone(tool, "search_visual_memory 工具未注册")
        return tool.handler(params)

    def _enable_and_seed(self):
        self.svc.update_permission(vision_memory_enabled=True)
        rec = VisualMemoryRecord.create(
            description="桌面上有代码编辑器",
            scene_type="desktop",
            tags=["代码"],
        )
        self.svc.save(rec)

    # ── 注册 ──────────────────────────────────────────────────────
    def test_register_count(self):
        self.assertEqual(self.n, 1)
        from backend.agent.tool_registry import get_registry
        self.assertTrue(get_registry().has("search_visual_memory"))

    def test_tool_category(self):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("search_visual_memory")
        self.assertEqual(tool.category, "vision")

    def test_tool_required_params(self):
        from backend.agent.tool_registry import get_registry
        tool = get_registry().get("search_visual_memory")
        self.assertEqual(tool.parameters.required, [])

    def test_re_register_override(self):
        n = register_vision_memory_tools(override=True)
        self.assertEqual(n, 1)

    def test_unregister(self):
        n = unregister_vision_memory_tools()
        self.assertEqual(n, 1)
        from backend.agent.tool_registry import get_registry
        self.assertFalse(get_registry().has("search_visual_memory"))

    # ── 调用 ──────────────────────────────────────────────────────
    def test_search_found(self):
        self._enable_and_seed()
        out = json.loads(self._call_tool({"keyword": "代码"}))
        self.assertTrue(out["success"])
        self.assertEqual(out["count"], 1)
        self.assertIn("代码编辑器", out["records"][0]["description"])

    def test_search_all(self):
        self._enable_and_seed()
        out = json.loads(self._call_tool({}))
        self.assertTrue(out["success"])
        self.assertEqual(out["count"], 1)

    def test_search_no_match(self):
        self._enable_and_seed()
        out = json.loads(self._call_tool({"keyword": "不存在的关键词"}))
        self.assertTrue(out["success"])
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["records"], [])

    def test_search_denied(self):
        out = json.loads(self._call_tool({"keyword": "代码"}))
        self.assertFalse(out["success"])
        self.assertEqual(out["status"], "denied")

    def test_search_limit(self):
        self.svc.update_permission(vision_memory_enabled=True)
        for i in range(10):
            self.svc.save(VisualMemoryRecord.create(description=f"记录{i}"))
        out = json.loads(self._call_tool({"limit": 3}))
        self.assertEqual(out["count"], 3)

    def test_search_invalid_limit(self):
        self._enable_and_seed()
        out = json.loads(self._call_tool({"limit": -5}))
        self.assertTrue(out["success"])
        self.assertEqual(out["count"], 1)

    def test_search_filter_tag(self):
        self.svc.update_permission(vision_memory_enabled=True)
        self.svc.save(VisualMemoryRecord.create(description="工作内容", tags=["工作"]))
        self.svc.save(VisualMemoryRecord.create(description="娱乐内容", tags=["娱乐"]))
        out = json.loads(self._call_tool({"tag": "工作"}))
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["records"][0]["description"], "工作内容")


if __name__ == "__main__":
    unittest.main()
