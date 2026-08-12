"""
集成测试: tools.py - Agent 视觉理解工具注册与调用
覆盖: 工具注册 / 参数定义 / 调用返回 JSON / 权限拒绝 / 注销
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.schema import SceneType
from backend.vision.understanding.service import reset_service
from backend.vision.understanding.tools import (
    UNDERSTANDING_TOOL_NAMES,
    register_understanding_tools,
    unregister_understanding_tools,
)


class TestUnderstandingToolsRegistration(unittest.TestCase):

    def setUp(self):
        reset_service()
        self.n = register_understanding_tools(override=True)

    def tearDown(self):
        unregister_understanding_tools()
        reset_service()

    def test_register_two_tools(self):
        self.assertEqual(self.n, 2)
        self.assertEqual(len(UNDERSTANDING_TOOL_NAMES), 2)

    def test_register_idempotent(self):
        n2 = register_understanding_tools(override=True)
        self.assertEqual(n2, 2)

    def test_tool_category_is_vision(self):
        from backend.agent.tool_registry import get_registry
        reg = get_registry()
        for name in UNDERSTANDING_TOOL_NAMES:
            tool = reg.get(name)
            self.assertIsNotNone(tool)
            self.assertEqual(tool.category, "vision")

    def test_tool_exported_to_openai_format(self):
        from backend.agent.tool_registry import get_registry
        reg = get_registry()
        tools = reg.export_openai_tools()
        names = {t["function"]["name"] for t in tools}
        self.assertIn("describe_scene", names)
        self.assertIn("answer_visual", names)

    def test_describe_scene_parameters(self):
        from backend.agent.tool_registry import get_registry
        reg = get_registry()
        tool = reg.get("describe_scene")
        props = tool.parameters.properties
        self.assertIn("region", props)
        self.assertIn("language", props)

    def test_answer_visual_parameters(self):
        from backend.agent.tool_registry import get_registry
        reg = get_registry()
        tool = reg.get("answer_visual")
        props = tool.parameters.properties
        self.assertIn("question", props)
        self.assertIn("question", tool.parameters.required)

    def test_unregister_vision_tools(self):
        from backend.agent.tool_registry import get_registry
        reg = get_registry()
        n = unregister_understanding_tools()
        self.assertEqual(n, 2)
        for name in UNDERSTANDING_TOOL_NAMES:
            self.assertIsNone(reg.get(name))


class TestUnderstandingToolsHandlerWithMock(unittest.TestCase):

    def setUp(self):
        reset_service()
        register_understanding_tools(override=True)
        # 注入 Mock UnderstandingService: 注入 Mock VisionService
        from backend.vision.understanding.service import get_service
        svc = get_service()
        svc.load_config({"understanding_enabled": True})

        image = np.zeros((100, 200, 3), dtype=np.uint8)
        mock_vision = MagicMock()
        frame = MagicMock()
        frame.image = image
        cap_result = MagicMock()
        cap_result.is_ok = True
        cap_result.frame = frame
        mock_vision.capture.return_value = cap_result

        from backend.vision.service import VisionService
        svc._vision_service = MagicMock(spec=VisionService)
        svc._vision_service.capture.return_value = cap_result

    def tearDown(self):
        unregister_understanding_tools()
        reset_service()

    def _call_handler(self, name, params):
        from backend.agent.tool_registry import get_registry
        reg = get_registry()
        tool = reg.get(name)
        return tool.handler(params)

    def test_describe_scene_with_mock(self):
        out = self._call_handler("describe_scene", {})
        data = json.loads(out)
        self.assertTrue(data["success"])
        self.assertEqual(data["scene_type"], SceneType.DESKTOP.value)
        self.assertGreater(len(data["description"]), 0)

    def test_answer_visual_with_mock(self):
        out = self._call_handler("answer_visual", {"question": "屏幕上有几个窗口?"})
        data = json.loads(out)
        self.assertTrue(data["success"])
        self.assertGreater(len(data["answer"]), 0)

    def test_answer_visual_missing_question(self):
        out = self._call_handler("answer_visual", {})
        data = json.loads(out)
        self.assertFalse(data["success"])
        self.assertIn("question", data["error"])

    def test_handler_returns_json_string(self):
        """handler 返回 JSON 字符串 (失败也返回 JSON, 不抛异常)"""
        out = self._call_handler("describe_scene", {})
        data = json.loads(out)
        self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main()
