"""
测试: tool_registry.py 工具注册中心 + 内置工具
覆盖: 注册/注销/列表/导出/内置工具执行
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.schemas import Tool, ToolSchema
from backend.agent.tool_registry import (
    BUILTIN_TOOLS, ToolRegistry, ToolRegistryError,
    get_registry, reset_registry,
)


class TestToolRegistry(unittest.TestCase):
    """工具注册中心"""

    def setUp(self):
        reset_registry()
        self.reg = get_registry()

    def tearDown(self):
        reset_registry()

    def test_builtin_tools_loaded(self):
        """内置工具应自动加载"""
        for name in BUILTIN_TOOLS:
            self.assertTrue(self.reg.has(name), f"缺少内置工具: {name}")

    def test_register_custom_tool(self):
        """注册自定义工具"""
        schema = ToolSchema(properties={"x": {"type": "string"}}, required=["x"])
        tool = Tool(name="my_tool", description="测试", parameters=schema, handler=lambda p: "ok")
        self.reg.register(tool)
        self.assertTrue(self.reg.has("my_tool"))

    def test_register_duplicate_raises(self):
        """重复注册应报错"""
        schema = ToolSchema()
        tool = Tool(name="get_time", description="dup", parameters=schema, handler=lambda p: "")
        with self.assertRaises(ToolRegistryError):
            self.reg.register(tool)

    def test_register_override(self):
        """override=True 可覆盖"""
        schema = ToolSchema()
        tool = Tool(name="get_time", description="override", parameters=schema, handler=lambda p: "new")
        self.reg.register(tool, override=True)
        t = self.reg.get("get_time")
        self.assertEqual(t.description, "override")

    def test_unregister(self):
        """注销工具"""
        schema = ToolSchema(properties={"x": {"type": "string"}}, required=["x"])
        tool = Tool(name="temp_tool", description="temp", parameters=schema, handler=lambda p: "")
        self.reg.register(tool)
        removed = self.reg.unregister("temp_tool")
        self.assertIsNotNone(removed)
        self.assertFalse(self.reg.has("temp_tool"))

    def test_list_names_by_category(self):
        """按分类列出工具"""
        builtin_names = self.reg.list_names("builtin")
        self.assertIn("get_time", builtin_names)
        self.assertNotIn("my_custom", builtin_names)

    def test_export_openai_tools(self):
        """导出 OpenAI tools 格式"""
        tools = self.reg.export_openai_tools()
        self.assertGreater(len(tools), 0)
        names = [t["function"]["name"] for t in tools]
        self.assertIn("get_time", names)

    def test_export_specific_tools(self):
        """导出指定工具"""
        tools = self.reg.export_openai_tools(names=["get_time"])
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["function"]["name"], "get_time")

    def test_register_function_helper(self):
        """便捷注册函数"""
        self.reg.register_function(
            name="helper",
            description="helper",
            handler=lambda p: "ok",
            parameters={"type": "object", "properties": {}, "required": []},
        )
        self.assertTrue(self.reg.has("helper"))

    def test_register_decorator_function(self):
        """注册 @plugin_entry 装饰的函数"""
        from backend.agent.plugin_sdk import plugin_entry

        @plugin_entry(id="deco_test", description="装饰器测试",
                      parameters={"type": "object", "properties": {}, "required": []})
        def my_tool(params):
            return "deco_ok"

        self.reg.register_decorator_function(my_tool)
        self.assertTrue(self.reg.has("deco_test"))


class TestBuiltinTools(unittest.TestCase):
    """内置工具执行"""

    def setUp(self):
        reset_registry()
        self.reg = get_registry()

    def tearDown(self):
        reset_registry()

    def test_get_time(self):
        import json
        tool = self.reg.get("get_time")
        result = tool.handler({})
        d = json.loads(result)
        self.assertIn("time", d)
        self.assertIn("weekday", d)

    def test_get_date(self):
        import json
        tool = self.reg.get("get_date")
        result = tool.handler({})
        d = json.loads(result)
        self.assertIn("date", d)
        self.assertIn("year", d)

    def test_calculator_basic(self):
        import json
        tool = self.reg.get("calculator")
        result = tool.handler({"expression": "1+2*3"})
        d = json.loads(result)
        self.assertEqual(d["result"], 7)

    def test_calculator_div_zero(self):
        import json
        tool = self.reg.get("calculator")
        result = tool.handler({"expression": "1/0"})
        d = json.loads(result)
        self.assertIn("error", d)

    def test_calculator_rejects_dangerous(self):
        import json
        tool = self.reg.get("calculator")
        # 拒绝函数调用
        result = tool.handler({"expression": "__import__('os').system('ls')"})
        d = json.loads(result)
        self.assertIn("error", d)

    def test_http_get_rejects_local(self):
        import json
        tool = self.reg.get("http_get")
        result = tool.handler({"url": "http://129.5.0.1/"})
        d = json.loads(result)
        self.assertIn("error", d)

    def test_http_get_rejects_no_scheme(self):
        import json
        tool = self.reg.get("http_get")
        result = tool.handler({"url": "example.com"})
        d = json.loads(result)
        self.assertIn("error", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
