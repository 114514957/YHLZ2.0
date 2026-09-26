"""
测试: plugin_sdk.py 插件开发 SDK
覆盖: NekoPluginBase / neko_plugin / plugin_entry / Ok / Err / ToolRegistry.load_plugin
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.plugin_sdk import (
    Err, NekoPluginBase, Ok, neko_plugin, plugin_entry,
)
from backend.agent.schemas import Tool, ToolSchema
from backend.agent.tool_registry import ToolRegistry, get_registry, reset_registry


class TestResultTypes(unittest.TestCase):
    """Ok / Err Result 类型"""

    def test_ok_is_ok(self):
        r = Ok(42)
        self.assertTrue(r.is_ok)
        self.assertFalse(r.is_err)
        self.assertEqual(r.unwrap(), 42)

    def test_err_is_err(self):
        r = Err("出错了")
        self.assertTrue(r.is_err)
        self.assertFalse(r.is_ok)
        with self.assertRaises(RuntimeError):
            r.unwrap()


class TestNekoPluginBase(unittest.TestCase):
    """NekoPluginBase 插件基类"""

    def test_load_unload_lifecycle(self):
        """load / unload 生命周期"""
        class MyPlugin(NekoPluginBase):
            name = "my_plugin"
            version = "1.0.0"
            description = "测试插件"

            def __init__(self):
                super().__init__()
                self.loaded_flag = False

            def on_load(self):
                self.loaded_flag = True

            def on_unload(self):
                self.loaded_flag = False

            def get_tools(self):
                return [Tool(
                    name="my_tool",
                    description="测试工具",
                    parameters=ToolSchema(),
                    handler=lambda params: "ok",
                )]

        p = MyPlugin()
        self.assertFalse(p._loaded)
        ok = p.load()
        self.assertTrue(ok)
        self.assertTrue(p._loaded)
        self.assertTrue(p.loaded_flag)
        self.assertEqual(len(p._tools), 1)

        p.unload()
        self.assertFalse(p._loaded)
        self.assertFalse(p.loaded_flag)

    def test_load_failure(self):
        """加载失败 (get_tools 抛异常)"""
        class BadPlugin(NekoPluginBase):
            name = "bad"
            def get_tools(self):
                raise RuntimeError("boom")

        p = BadPlugin()
        ok = p.load()
        self.assertFalse(ok)
        self.assertFalse(p._loaded)

    def test_get_tools_not_implemented(self):
        """基类 get_tools 默认抛 NotImplementedError"""
        p = NekoPluginBase()
        with self.assertRaises(NotImplementedError):
            p.get_tools()


class TestNekoPluginDecorator(unittest.TestCase):
    """neko_plugin 类装饰器"""

    def test_decorator_marks_plugin(self):
        @neko_plugin
        class WeatherPlugin(NekoPluginBase):
            name = "weather"

            def get_tools(self):
                return []

        p = WeatherPlugin()
        self.assertTrue(getattr(p, "_is_neko_plugin", False))


class TestPluginEntryDecorator(unittest.TestCase):
    """plugin_entry 函数装饰器"""

    def test_plugin_entry_attaches_meta(self):
        @plugin_entry(
            id="echo",
            description="回显工具",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            category="plugin",
        )
        def echo(params):
            return params.get("text", "")

        # 被装饰函数应仍可调用
        self.assertEqual(echo({"text": "hi"}), "hi")
        # 应携带 _tool_meta
        meta = getattr(echo, "_tool_meta", None)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["name"], "echo")
        self.assertEqual(meta["description"], "回显工具")
        self.assertEqual(meta["category"], "plugin")


class TestToolRegistryLoadPlugin(unittest.TestCase):
    """ToolRegistry.load_plugin 集成"""

    def setUp(self):
        reset_registry()
        self.reg = get_registry()

    def tearDown(self):
        reset_registry()

    def test_load_plugin_registers_tools(self):
        """加载插件后, 工具应注册到 registry"""
        class CalcPlugin(NekoPluginBase):
            name = "calc_plugin"
            version = "1.0.0"

            def get_tools(self):
                return [Tool(
                    name="double",
                    description="翻倍",
                    parameters=ToolSchema(
                        properties={"x": {"type": "number"}},
                        required=["x"],
                    ),
                    handler=lambda params: {"result": params["x"] * 2},
                    category="plugin",
                )]

        p = CalcPlugin()
        ok = self.reg.load_plugin(p)
        self.assertTrue(ok)
        # 工具应可查询
        t = self.reg.get("double")
        self.assertIsNotNone(t)
        self.assertEqual(t.category, "plugin")
        # 应出现在 plugin 类别列表
        names = self.reg.list_names("plugin")
        self.assertIn("double", names)

    def test_load_plugin_idempotent(self):
        """重复加载同一插件不会重复注册"""
        class SinglePlugin(NekoPluginBase):
            name = "single"
            def get_tools(self):
                return [Tool(name="only", description="唯一", parameters=ToolSchema(), handler=lambda p: "ok", category="plugin")]

        p = SinglePlugin()
        self.assertTrue(self.reg.load_plugin(p))
        # 第二次加载 (已 loaded)
        ok = self.reg.load_plugin(p)
        self.assertTrue(ok)
        # 仍然只有一个 only
        self.assertEqual(len(self.reg.list_names("plugin")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
