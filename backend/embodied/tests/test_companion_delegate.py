"""
YHLZ Embodied AI V5.0 - 任务委派与结果汇总单元测试 (Task Delegation)

覆盖 (delegate.py):
    - CompanionResponse 结构: request_id / intent / assigned_agents /
      results / aggregated / explainable_reason / mode
    - 委派: 路由 → 专业 Agent 顺序执行
    - 汇总: total / ok_count / fail_count / all_ok / payloads
    - 异常隔离: 单个 Agent 失败 → 标记 error, 不中断整体
    - 未注册 Agent / 停用 Agent 处理
    - 参数校验: 非法路由器
"""
import unittest

from backend.embodied.companion import (
    DelegateError,
    CompanionRouter,
    SpecialistRegistry,
    TaskDelegator,
)


def ok_handler(request):
    return {"echo": request.get("text", "")}


def boom_handler(request):
    raise RuntimeError("boom")


def make_setup(agents=None, with_boom=False):
    reg = SpecialistRegistry()
    if with_boom:
        reg.register_simple("perception_agent", "perception", boom_handler)
        reg.register_simple("experience_agent", "experience", ok_handler)
    else:
        for name, cap in (agents or [
            ("perception_agent", "perception"),
            ("experience_agent", "experience"),
        ]):
            reg.register_simple(name, cap, ok_handler)
    router = CompanionRouter(reg)
    delegator = TaskDelegator(router)
    return reg, router, delegator


class TestDelegate(unittest.TestCase):
    """委派流程"""

    def setUp(self):
        self.reg, self.router, self.delegator = make_setup()

    def test_delegate_structure(self):
        """CompanionResponse 结构完整"""
        r = self.delegator.delegate({"text": "扫描环境"})
        for key in ("request_id", "intent", "assigned_agents",
                    "results", "aggregated", "explainable_reason", "mode"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")
        self.assertTrue(r["request_id"].startswith("req_"))

    def test_delegate_assigns_agents(self):
        """扫描 → perception_agent"""
        r = self.delegator.delegate({"text": "扫描"})
        self.assertIn("perception_agent", r["assigned_agents"])
        self.assertEqual(len(r["results"]), 1)

    def test_delegate_results_ok(self):
        """成功结果标记 ok"""
        r = self.delegator.delegate({"text": "扫描"})
        result = r["results"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["agent"], "perception_agent")
        self.assertIn("echo", result["result"])

    def test_aggregated_counts(self):
        """汇总计数"""
        r = self.delegator.delegate({"text": "扫描"})
        agg = r["aggregated"]
        self.assertEqual(agg["total"], 1)
        self.assertEqual(agg["ok_count"], 1)
        self.assertEqual(agg["fail_count"], 0)
        self.assertTrue(agg["all_ok"])

    def test_aggregated_multi_agents(self):
        """多 Agent 委派 (fallback: perception + experience)"""
        r = self.delegator.delegate({"text": "zzz"})
        agg = r["aggregated"]
        self.assertEqual(agg["total"], 2)
        self.assertEqual(agg["ok_count"], 2)

    def test_reason_explainable(self):
        """委派原因可解释"""
        r = self.delegator.delegate({"text": "扫描"})
        self.assertIn("委派顺序", r["explainable_reason"])
        self.assertIn("perception_agent", r["explainable_reason"])

    def test_payloads_aggregated(self):
        """payloads 汇总各 Agent 结果"""
        r = self.delegator.delegate({"text": "zzz"})
        payloads = r["aggregated"]["payloads"]
        self.assertEqual(len(payloads), 2)
        self.assertTrue(all("result" in p for p in payloads))


class TestDelegateErrors(unittest.TestCase):
    """委派异常处理"""

    def test_single_agent_failure_isolated(self):
        """单 Agent 失败 → 不中断整体"""
        _, _, delegator = make_setup(with_boom=True)
        r = delegator.delegate({"text": "扫描"})
        self.assertEqual(len(r["results"]), 1)
        result = r["results"][0]
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])
        agg = r["aggregated"]
        self.assertEqual(agg["ok_count"], 0)
        self.assertEqual(agg["fail_count"], 1)
        self.assertFalse(agg["all_ok"])

    def test_partial_failure(self):
        """部分失败: 成功+失败混合"""
        _, _, delegator = make_setup(with_boom=True)
        r = delegator.delegate({"text": "zzz"})  # fallback: perception(boom) + experience(ok)
        agg = r["aggregated"]
        self.assertEqual(agg["ok_count"], 1)
        self.assertEqual(agg["fail_count"], 1)
        self.assertFalse(agg["all_ok"])

    def test_unregistered_agent(self):
        """未注册能力域 Agent → 只委派已注册的"""
        reg = SpecialistRegistry()
        reg.register_simple("experience_agent", "experience", ok_handler)
        router = CompanionRouter(reg)
        delegator = TaskDelegator(router)
        # fallback: perception + experience, 只有 experience 注册
        r = delegator.delegate({"text": "zzz"})
        self.assertEqual(len(r["results"]), 1)
        self.assertEqual(r["results"][0]["agent"], "experience_agent")
        self.assertTrue(r["results"][0]["ok"])

    def test_disabled_agent(self):
        """全部停用 → 占位错误标记"""
        reg = SpecialistRegistry()
        reg.register_simple("perception_agent", "perception", ok_handler)
        reg.set_enabled("perception_agent", False)
        router = CompanionRouter(reg)
        delegator = TaskDelegator(router)
        r = delegator.delegate({"text": "扫描"})
        self.assertEqual(len(r["results"]), 1)
        self.assertFalse(r["results"][0]["ok"])
        self.assertIn("Agent", r["results"][0]["error"])

    def test_invalid_router_raises(self):
        """非法路由器 → DelegateError"""
        with self.assertRaises(DelegateError):
            TaskDelegator(None)

    def test_thresholds(self):
        """阈值暴露"""
        _, _, delegator = make_setup()
        th = delegator.thresholds()
        self.assertIn("timeout", th)
        self.assertEqual(th["rule_version"], "v1")


if __name__ == "__main__":
    unittest.main()
