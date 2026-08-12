"""
YHLZ Embodied AI V5.0 - 主伙伴 Agent 与 Service 集成测试
(Main Companion Agent + Service API)

覆盖 (main_agent.py + service.py V5.0 API):
    - MainCompanionAgent: handle / route / agents / dry_run / status
    - 统一人格: personality = 铁哥们 (专业 Agent 无独立人格)
    - 参数校验: 空请求 / 停用主 Agent
    - Service API: companion_handle / companion_agents / companion_route /
      companion_dry_run / companion_status
    - 默认专业 Agent (6 能力域对接 Service)
    - 审计: companion_handle 入审计
    - 安全: 不写 Agent Memory / 不绕过 Permission
    - 向后兼容: V4.7 API 保持可用
    - 端到端: 多 Agent 协同 (P1)
"""
import unittest

from backend.embodied.companion import (
    MainAgentError,
    MainCompanionAgent,
    CompanionRouter,
    SpecialistRegistry,
    TaskDelegator,
    build_default_agents,
)
from backend.embodied.service import EmbodiedService
from backend.embodied.strategy.audit import AUDIT_ACTIONS


def ok_handler(request):
    return {"ok": True}


def make_agent(enabled=True):
    reg = SpecialistRegistry()
    reg.register_simple("perception_agent", "perception", ok_handler)
    reg.register_simple("reasoning_agent", "reasoning", ok_handler)
    router = CompanionRouter(reg)
    delegator = TaskDelegator(router)
    return MainCompanionAgent(
        registry=reg, router=router, delegator=delegator,
        personality="铁哥们", enabled=enabled,
    )


class TestMainAgent(unittest.TestCase):
    """主伙伴 Agent"""

    def setUp(self):
        self.agent = make_agent()

    def test_handle(self):
        """主入口处理"""
        r = self.agent.handle({"text": "扫描"})
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("request_id", r)

    def test_handle_empty_raises(self):
        """空请求 → MainAgentError"""
        with self.assertRaises(MainAgentError):
            self.agent.handle({})
        with self.assertRaises(MainAgentError):
            self.agent.handle(None)

    def test_handle_disabled_raises(self):
        """停用主 Agent → MainAgentError"""
        agent = make_agent(enabled=False)
        with self.assertRaises(MainAgentError):
            agent.handle({"text": "扫描"})

    def test_route(self):
        """路由分析"""
        r = self.agent.route({"text": "扫描"})
        self.assertIn("perception_agent", r["assigned_agents"])

    def test_agents_snapshot(self):
        """Agent 清单"""
        r = self.agent.agents()
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["mode"], "rule_based")

    def test_dry_run(self):
        """预演 (不调用专业 Agent)"""
        r = self.agent.dry_run({"text": "扫描"})
        self.assertTrue(r["dry_run"])
        self.assertTrue(r["protection_checks"]["passed"])
        self.assertIn("route", r)
        self.assertIn("would_delegate", r)

    def test_dry_run_protection_checks(self):
        """保护规则: 5 项"""
        r = self.agent.dry_run({"text": "扫描"})
        names = {c["name"] for c in r["protection_checks"]["checks"]}
        self.assertEqual(names, {
            "no_execution", "no_memory_write", "permission_layer_untouched",
            "rule_based_only", "single_consciousness",
        })

    def test_status(self):
        """状态: 人格 / 版本 / 计数"""
        st = self.agent.status()
        self.assertEqual(st["version"], "9.5.0")
        self.assertEqual(st["personality"], "铁哥们")
        self.assertEqual(st["mode"], "rule_based")
        self.assertTrue(st["enabled"])

    def test_handle_count(self):
        """处理计数"""
        self.agent.handle({"text": "扫描"})
        self.agent.handle({"text": "扫描"})
        self.assertEqual(self.agent.status()["handled_count"], 2)

    def test_set_enabled(self):
        """启用/停用控制"""
        self.agent.set_enabled(False)
        with self.assertRaises(MainAgentError):
            self.agent.handle({"text": "扫描"})
        self.agent.set_enabled(True)
        self.agent.handle({"text": "扫描"})

    def test_personality_property(self):
        """人格属性"""
        self.assertEqual(self.agent.personality, "铁哥们")


class TestBuildDefaultAgents(unittest.TestCase):
    """默认专业 Agent (对接 Service)"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_six_capabilities(self):
        """7 个能力域 Agent (V5.3 含执行)"""
        reg = build_default_agents(self.svc)
        self.assertEqual(reg.count(), 7)
        caps = {a.capability for a in reg.all()}
        self.assertEqual(caps, {
            "perception", "reasoning", "experience", "planning",
            "long_horizon", "governance", "execution",
        })

    def test_agent_invocation(self):
        """专业 Agent 调用 Service 能力"""
        reg = build_default_agents(self.svc)
        perception = reg.get("perception_agent")
        r = perception.invoke({})
        self.assertNotIn("error", r)
        self.assertIn("data", r)

    def test_reasoning_agent(self):
        """推理 Agent 返回上下文"""
        reg = build_default_agents(self.svc)
        reasoning = reg.get("reasoning_agent")
        r = reasoning.invoke({})
        self.assertNotIn("error", r)
        data = r.get("data", {})
        self.assertIn("current_state", data)

    def test_governance_agent(self):
        """治理 Agent 返回健康检查"""
        reg = build_default_agents(self.svc)
        gov = reg.get("governance_agent")
        r = gov.invoke({})
        self.assertNotIn("error", r)
        self.assertIn("health_score", r["data"])


class TestServiceCompanion(unittest.TestCase):
    """Service V5.0 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_companion_handle_api(self):
        """companion_handle"""
        r = self.svc.companion_handle({"text": "扫描环境"})
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("assigned_agents", r)

    def test_companion_handle_empty_raises(self):
        """空请求 → EmbodiedServiceError"""
        from backend.embodied.service import EmbodiedServiceError
        with self.assertRaises(EmbodiedServiceError):
            self.svc.companion_handle({})

    def test_companion_agents_api(self):
        """companion_agents"""
        r = self.svc.companion_agents()
        self.assertEqual(r["total"], 7)
        self.assertEqual(r["mode"], "rule_based")

    def test_companion_route_api(self):
        """companion_route"""
        r = self.svc.companion_route({"text": "帮我整理房间"})
        self.assertIn("long_horizon", r["capabilities"])
        self.assertFalse(r["fallback"])

    def test_companion_dry_run_api(self):
        """companion_dry_run"""
        r = self.svc.companion_dry_run({"text": "扫描"})
        self.assertTrue(r["dry_run"])
        self.assertTrue(r["protection_checks"]["passed"])

    def test_companion_status_api(self):
        """companion_status"""
        st = self.svc.companion_status()
        self.assertEqual(st["personality"], "铁哥们")
        self.assertEqual(st["version"], "9.5.0")

    def test_handle_full_flow_perception(self):
        """感知请求 → perception_agent 调用 Service"""
        r = self.svc.companion_handle({"text": "扫描环境"})
        result = r["results"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["agent"], "perception_agent")

    def test_handle_full_flow_governance(self):
        """治理请求 → governance_agent"""
        r = self.svc.companion_handle({"text": "策略治理健康检查"})
        self.assertIn("governance_agent", r["assigned_agents"])

    def test_audit_companion_handle(self):
        """审计记录 companion_handle"""
        self.svc.companion_handle({"text": "扫描"})
        log = self.svc.audit_policy_log(limit=0, action="companion_handle")
        self.assertEqual(log["total"], 1)
        self.assertIn("伙伴请求", log["recent"][0]["reason"])

    def test_audit_action_whitelist(self):
        """companion_handle 在白名单"""
        self.assertIn("companion_handle", AUDIT_ACTIONS)

    def test_audit_export_includes_companion(self):
        """审计导出含 companion_handle"""
        self.svc.companion_handle({"text": "扫描"})
        exp = self.svc.audit_system_export()
        actions = {e["action"] for e in exp["audit"]["entries"]}
        self.assertIn("companion_handle", actions)

    def test_no_memory_write(self):
        """伙伴请求不写 Agent Memory"""
        before = self.svc.memory.stats().get("total", 0)
        self.svc.companion_handle({"text": "扫描"})
        self.svc.companion_handle({"text": "整理房间"})
        self.svc.companion_dry_run({"text": "扫描"})
        after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_version_5_0_0(self):
        """Service 版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_v47_apis_still_work(self):
        """向后兼容: V4.7 API 保持可用"""
        r = self.svc.long_horizon_plan(title="整理", phases=["收集"])
        self.assertEqual(r["mode"], "rule_based")
        gid = r["goal"]["goal_id"]
        self.assertEqual(self.svc.long_horizon_progress(gid)["total"], 1)

    def test_config_driven_rule_version(self):
        """配置驱动: 路由规则版本"""
        svc = EmbodiedService()
        svc.load_config({
            "companion_route_rule_version": "v2",
            "companion_enabled": True,
        })
        r = svc.companion_route({"text": "扫描"})
        self.assertEqual(r["rule_version"], "v2")

    def test_config_driven_enabled(self):
        """companion_enabled 默认 False"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        self.assertFalse(svc.companion_status()["enabled"])


class TestEndToEndCompanion(unittest.TestCase):
    """端到端: 多 Agent 协同 (P1)"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_multi_agent_coordination(self):
        """多能力域请求 → 多 Agent 协同 → 汇总"""
        r = self.svc.companion_handle(
            {"text": "扫描环境后检查策略健康"},
        )
        self.assertGreaterEqual(len(r["assigned_agents"]), 2)
        self.assertTrue(r["aggregated"]["all_ok"])
        self.assertEqual(r["aggregated"]["ok_count"],
                         r["aggregated"]["total"])

    def test_fallback_flow(self):
        """无法识别意图 → 回退默认委派"""
        r = self.svc.companion_handle({"text": "随便说点什么"})
        self.assertTrue(
            self.svc.companion_route({"text": "随便说点什么"})["fallback"],
        )
        self.assertEqual(len(r["assigned_agents"]), 2)

    def test_explainable_response(self):
        """完整响应可解释"""
        r = self.svc.companion_handle({"text": "扫描"})
        self.assertIn("委派顺序", r["explainable_reason"])
        self.assertIn("perception_agent", r["explainable_reason"])

    def test_aggregated_payloads(self):
        """汇总 payloads 包含各 Agent 结果"""
        r = self.svc.companion_handle({"text": "扫描"})
        payloads = r["aggregated"]["payloads"]
        self.assertEqual(len(payloads), 1)
        self.assertIn("result", payloads[0])

    def test_request_id_unique(self):
        """请求 ID 唯一"""
        r1 = self.svc.companion_handle({"text": "扫描"})
        r2 = self.svc.companion_handle({"text": "扫描"})
        self.assertNotEqual(r1["request_id"], r2["request_id"])

    def test_long_term_task_coordination(self):
        """长期任务协同: 整理房间 → long_horizon_agent"""
        r = self.svc.companion_handle({"text": "帮我整理房间"})
        self.assertIn("long_horizon_agent", r["assigned_agents"])
        self.assertTrue(r["aggregated"]["all_ok"])

    def test_reasoning_coordination(self):
        """推理协同: 为什么失败 → reasoning_agent"""
        r = self.svc.companion_handle({"text": "为什么失败了"})
        self.assertIn("reasoning_agent", r["assigned_agents"])

    def test_planning_coordination(self):
        """规划协同: 做个多目标规划 → planning_agent"""
        r = self.svc.companion_handle({"text": "做个多目标规划"})
        self.assertIn("planning_agent", r["assigned_agents"])

    def test_experience_coordination(self):
        """经验协同: 有什么策略建议 → experience_agent"""
        r = self.svc.companion_handle({"text": "有什么策略建议"})
        self.assertIn("experience_agent", r["assigned_agents"])

    def test_combined_intent(self):
        """组合意图: 扫描+整理 → 多 Agent"""
        r = self.svc.companion_handle({"text": "扫描环境再整理房间"})
        caps = set(self.svc.companion_route(
            {"text": "扫描环境再整理房间"},
        )["capabilities"])
        self.assertTrue({"perception", "long_horizon"} <= caps)
        self.assertGreaterEqual(len(r["assigned_agents"]), 2)

    def test_reasoning_agent_invocation_success(self):
        """推理 Agent 实际调用 Service 成功"""
        reg = self.svc.companion._registry
        agent = reg.get("reasoning_agent")
        result = agent.invoke({})
        self.assertTrue("error" not in result)
        data = result.get("data", {})
        self.assertIn("current_state", data)

    def test_experience_agent_invocation(self):
        """经验 Agent 实际调用 policy_stats"""
        reg = self.svc.companion._registry
        agent = reg.get("experience_agent")
        result = agent.invoke({})
        self.assertTrue("error" not in result)
        data = result.get("data", {})
        self.assertIn("table", data)

    def test_planning_agent_invocation(self):
        """规划 Agent 实际调用 overview"""
        reg = self.svc.companion._registry
        agent = reg.get("planning_agent")
        result = agent.invoke({})
        self.assertTrue("error" not in result)
        data = result.get("data", {})
        self.assertIn("matrix", data)

    def test_long_horizon_agent_invocation(self):
        """长期任务 Agent 实际调用 report"""
        reg = self.svc.companion._registry
        agent = reg.get("long_horizon_agent")
        result = agent.invoke({})
        self.assertTrue("error" not in result)
        data = result.get("data", {})
        self.assertIn("version", data)

    def test_governance_agent_invocation_full(self):
        """治理 Agent 完整数据 (health_score + summary)"""
        reg = self.svc.companion._registry
        agent = reg.get("governance_agent")
        result = agent.invoke({})
        self.assertTrue("error" not in result)
        data = result.get("data", {})
        self.assertIn("summary", data)
        self.assertIn("mode", data)

    def test_dry_run_no_side_effect(self):
        """预演不产生副作用 (不改变 Agent 调用计数)"""
        reg = self.svc.companion._registry
        before = sum(a.invocations for a in reg.all())
        self.svc.companion_dry_run({"text": "扫描"})
        self.svc.companion_dry_run({"text": "整理房间"})
        after = sum(a.invocations for a in reg.all())
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
