"""
单元测试: tools.py - Agent 工具注册
覆盖: register_vision_tools / unregister_vision_tools / 工具参数 schema / handler 调用 (Mock)
注意: 不真实截屏 (依赖 PerceptionService Mock)
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.agent.tool_registry import get_registry, reset_registry
from backend.vision.perception.tools import (
    VISION_TOOL_NAMES,
    register_vision_tools,
    unregister_vision_tools,
)


class TestVisionToolsRegistration(unittest.TestCase):

    def setUp(self):
        reset_registry()

    def tearDown(self):
        reset_registry()

    def test_register_vision_tools(self):
        n = register_vision_tools()
        self.assertEqual(n, 2)
        reg = get_registry()
        for name in VISION_TOOL_NAMES:
            self.assertTrue(reg.has(name))

    def test_register_idempotent(self):
        """重复注册 (override=True) 不报错"""
        register_vision_tools()
        register_vision_tools()
        reg = get_registry()
        self.assertEqual(len([t for t in reg.list_tools() if t.category == "vision"]), 2)

    def test_unregister_vision_tools(self):
        register_vision_tools()
        n = unregister_vision_tools()
        self.assertEqual(n, 2)
        reg = get_registry()
        for name in VISION_TOOL_NAMES:
            self.assertFalse(reg.has(name))

    def test_tool_category_is_vision(self):
        register_vision_tools()
        reg = get_registry()
        tool = reg.get("read_screen_text")
        self.assertEqual(tool.category, "vision")
        tool2 = reg.get("detect_objects")
        self.assertEqual(tool2.category, "vision")

    def test_tool_exported_to_openai_format(self):
        register_vision_tools()
        reg = get_registry()
        tools = reg.export_openai_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("read_screen_text", names)
        self.assertIn("detect_objects", names)

    def test_read_screen_text_parameters(self):
        register_vision_tools()
        reg = get_registry()
        tool = reg.get("read_screen_text")
        self.assertEqual(tool.name, "read_screen_text")
        self.assertIn("language", tool.parameters.properties)
        self.assertIn("region", tool.parameters.properties)
        # 无必填参数
        self.assertEqual(tool.parameters.required, [])

    def test_detect_objects_parameters(self):
        register_vision_tools()
        reg = get_registry()
        tool = reg.get("detect_objects")
        self.assertEqual(tool.name, "detect_objects")
        self.assertIn("min_confidence", tool.parameters.properties)
        self.assertIn("max_objects", tool.parameters.properties)
        self.assertIn("region", tool.parameters.properties)

    def test_handler_returns_json_string(self):
        """handler 应返回 JSON 字符串 (失败也返回 JSON, 不抛)"""
        register_vision_tools()
        reg = get_registry()
        tool = reg.get("read_screen_text")
        # 未初始化 PerceptionService, 应返回失败 JSON (不抛异常)
        result = tool.handler({})
        self.assertIsInstance(result, str)
        data = json.loads(result)
        self.assertIn("success", data)


class TestVisionToolsHandlerWithMock(unittest.TestCase):
    """使用 Mock PerceptionService 验证 handler 行为"""

    def setUp(self):
        reset_registry()
        # 重置 PerceptionService 单例
        from backend.vision.perception.service import reset_service
        reset_service()

    def tearDown(self):
        reset_registry()
        from backend.vision.perception.service import reset_service
        reset_service()

    def test_read_screen_text_without_permission(self):
        """权限关闭时, handler 返回失败 JSON"""
        register_vision_tools()
        reg = get_registry()
        tool = reg.get("read_screen_text")
        result = tool.handler({})
        data = json.loads(result)
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    def test_read_screen_text_with_mock_image(self):
        """配置 Mock + 开启权限后, 但未注入 VisionService → 仍失败"""
        from backend.vision.perception.service import get_service
        svc = get_service()
        svc.load_config({
            "perception_enabled": True,
            "ocr_enabled": True,
        })
        register_vision_tools()
        reg = get_registry()
        tool = reg.get("read_screen_text")
        result = tool.handler({})
        data = json.loads(result)
        # 未注入 VisionService, 应失败
        self.assertFalse(data["success"])


if __name__ == "__main__":
    unittest.main()
