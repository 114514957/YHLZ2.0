"""
YHLZ Embodied AI V5.0 - 专业 Agent 注册中心单元测试 (Specialist Registry)

覆盖 (specialist.py):
    - SpecialistAgent: 构造校验 / invoke / 调用计数 / 错误捕获 / to_dict
    - SpecialistRegistry: 注册 / 快捷注册 / 注销 / 清空 / 查询 /
      按能力域查询 / 启用停用 / 快照
    - 能力域白名单校验
    - 异常隔离: Agent 处理器抛异常 → 错误结果 (不中断)
"""
import unittest

from backend.embodied.companion import (
    SPECIALIST_CAPABILITIES,
    SpecialistAgent,
    SpecialistError,
    SpecialistRegistry,
)


def ok_handler(request):
    return {"echo": request.get("text", "")}


def boom_handler(request):
    raise RuntimeError("boom")


class TestSpecialistAgent(unittest.TestCase):
    """专业 Agent 模型"""

    def test_create_valid(self):
        """合法创建"""
        a = SpecialistAgent("test_agent", "perception", ok_handler)
        self.assertEqual(a.name, "test_agent")
        self.assertEqual(a.capability, "perception")
        self.assertTrue(a.enabled)
        self.assertEqual(a.invocations, 0)

    def test_invalid_capability_raises(self):
        """非法能力域 → SpecialistError"""
        with self.assertRaises(SpecialistError):
            SpecialistAgent("a", "hacker", ok_handler)

    def test_none_handler_raises(self):
        """处理器不可调用 → SpecialistError"""
        with self.assertRaises(SpecialistError):
            SpecialistAgent("a", "perception", None)

    def test_invoke_success(self):
        """invoke 成功 + 计数"""
        a = SpecialistAgent("a", "perception", ok_handler)
        r = a.invoke({"text": "hi"})
        self.assertEqual(r["echo"], "hi")
        self.assertEqual(a.invocations, 1)

    def test_invoke_error_captured(self):
        """invoke 异常 → 错误结果 + 计数"""
        a = SpecialistAgent("a", "perception", boom_handler)
        r = a.invoke({})
        self.assertIn("error", r)
        self.assertIn("boom", r["error"])
        self.assertEqual(a.invocations, 1)
        self.assertEqual(a.last_error, "boom")

    def test_to_dict(self):
        """to_dict 字段完整"""
        a = SpecialistAgent("a", "perception", ok_handler, "感知")
        d = a.to_dict()
        for key in ("name", "capability", "description", "enabled",
                    "invocations", "last_error", "created_at"):
            self.assertIn(key, d)
        self.assertEqual(d["description"], "感知")

    def test_capabilities_whitelist(self):
        """能力域白名单 = 7 个 (V5.3 含执行)"""
        self.assertEqual(set(SPECIALIST_CAPABILITIES), {
            "perception", "reasoning", "experience",
            "planning", "long_horizon", "governance", "execution",
        })


class TestSpecialistRegistry(unittest.TestCase):
    """注册中心"""

    def setUp(self):
        self.registry = SpecialistRegistry()

    def _register_three(self):
        self.registry.register_simple("p1", "perception", ok_handler)
        self.registry.register_simple("r1", "reasoning", ok_handler)
        self.registry.register_simple("p2", "perception", ok_handler)

    def test_register(self):
        """注册"""
        a = SpecialistAgent("x", "perception", ok_handler)
        self.registry.register(a)
        self.assertEqual(self.registry.count(), 1)
        self.assertIs(self.registry.get("x"), a)

    def test_register_simple(self):
        """快捷注册"""
        self.registry.register_simple("x", "perception", ok_handler, "描述")
        a = self.registry.get("x")
        self.assertEqual(a.capability, "perception")
        self.assertEqual(a.description, "描述")

    def test_register_override(self):
        """同名称覆盖"""
        self.registry.register_simple("x", "perception", ok_handler)
        self.registry.register_simple("x", "reasoning", ok_handler)
        self.assertEqual(self.registry.count(), 1)
        self.assertEqual(self.registry.get("x").capability, "reasoning")

    def test_unregister(self):
        """注销"""
        self.registry.register_simple("x", "perception", ok_handler)
        self.assertTrue(self.registry.unregister("x"))
        self.assertFalse(self.registry.unregister("x"))
        self.assertEqual(self.registry.count(), 0)

    def test_clear(self):
        """清空"""
        self._register_three()
        self.assertEqual(self.registry.clear(), 3)
        self.assertEqual(self.registry.count(), 0)

    def test_get_missing(self):
        """不存在的 Agent → None"""
        self.assertIsNone(self.registry.get("nope"))

    def test_all(self):
        """全部 Agent"""
        self._register_three()
        self.assertEqual(len(self.registry.all()), 3)

    def test_enabled_agents(self):
        """已启用 Agent"""
        self._register_three()
        self.registry.set_enabled("p2", False)
        enabled = self.registry.enabled_agents()
        self.assertEqual(len(enabled), 2)
        self.assertNotIn("p2", [a.name for a in enabled])

    def test_by_capability(self):
        """按能力域查询"""
        self._register_three()
        ps = self.registry.by_capability("perception")
        self.assertEqual(len(ps), 2)
        rs = self.registry.by_capability("reasoning")
        self.assertEqual(len(rs), 1)

    def test_by_capability_excludes_disabled(self):
        """按能力域查询排除停用"""
        self._register_three()
        self.registry.set_enabled("p2", False)
        ps = self.registry.by_capability("perception")
        self.assertEqual(len(ps), 1)

    def test_set_enabled(self):
        """启用/停用"""
        self.registry.register_simple("x", "perception", ok_handler)
        a = self.registry.set_enabled("x", False)
        self.assertFalse(a.enabled)
        self.assertIsNone(self.registry.set_enabled("nope", True))

    def test_snapshot(self):
        """快照结构"""
        self._register_three()
        snap = self.registry.snapshot()
        self.assertEqual(snap["mode"], "rule_based")
        self.assertEqual(snap["total"], 3)
        self.assertEqual(len(snap["agents"]), 3)


if __name__ == "__main__":
    unittest.main()
