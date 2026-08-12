"""
YHLZ Embodied AI V5.1 - 伙伴协同增强集成测试 (Coordination Enhancement)

覆盖:
    - 细化默认 Agent 映射: 精确对接 Service 方法 (含参数回退)
    - Service companion_stats API + 配置驱动 (workers/topk)
    - 端到端: 打分路由 → 并发委派 → 汇总 → 统计
    - 向后兼容: V5.0 API 保持可用
    - 安全: 不写 Agent Memory / 不绕过 Permission
"""
import unittest

from backend.embodied.companion import build_default_agents
from backend.embodied.service import EmbodiedService


class TestRefinedMapping(unittest.TestCase):
    """细化默认 Agent 映射"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})
        self.reg = build_default_agents(self.svc)

    def test_perception_agent_observe(self):
        """感知 Agent → observe"""
        r = self.reg.get("perception_agent").invoke({})
        self.assertEqual(r["method"], "observe")
        self.assertIn("data", r)

    def test_reasoning_agent_context(self):
        """推理 Agent → build_environment_context"""
        r = self.reg.get("reasoning_agent").invoke({})
        self.assertEqual(r["method"], "build_environment_context")

    def test_experience_agent_policy_stats(self):
        """经验 Agent → policy_stats"""
        r = self.reg.get("experience_agent").invoke({})
        self.assertEqual(r["method"], "policy_stats")

    def test_planning_agent_overview(self):
        """规划 Agent → strategy_system_overview"""
        r = self.reg.get("planning_agent").invoke({})
        self.assertEqual(r["method"], "strategy_system_overview")

    def test_governance_agent_health(self):
        """治理 Agent → policy_health_check"""
        r = self.reg.get("governance_agent").invoke({})
        self.assertEqual(r["method"], "policy_health_check")

    def test_long_horizon_agent_with_title(self):
        """长期任务 Agent 带参数 → long_horizon_plan"""
        r = self.reg.get("long_horizon_agent").invoke({
            "title": "整理房间", "phases": ["收集", "整理"],
        })
        self.assertEqual(r["method"], "long_horizon_plan")
        data = r["data"]
        self.assertEqual(len(data["task_tree"]["milestones"]), 2)

    def test_long_horizon_agent_fallback(self):
        """长期任务 Agent 缺参数 → 回退 report"""
        r = self.reg.get("long_horizon_agent").invoke({"text": "随便"})
        self.assertEqual(r["method"], "report")
        self.assertIn("fallback_reason", r)

    def test_handler_param_whitelist(self):
        """请求参数白名单: 无关参数不传入"""
        r = self.reg.get("perception_agent").invoke({
            "environment": None, "hack": "x",
        })
        self.assertNotIn("error", r)

    def test_refined_mapping_reasoning_params(self):
        """推理 Agent 参数白名单 (include_history)"""
        r = self.reg.get("reasoning_agent").invoke({
            "include_history": False,
        })
        data = r["data"]
        self.assertNotIn("recent_changes", data)

    def test_perception_payload_keys(self):
        """感知 Agent 仅接收 environment 参数"""
        r = self.reg.get("perception_agent").invoke({
            "environment": "room",
        })
        self.assertEqual(r["method"], "observe")

    def test_handler_error_captured(self):
        """处理器异常 → 错误结果"""
        from backend.embodied.companion import SpecialistAgent
        self.reg.register_simple(
            "bad_agent", "governance",
            lambda req: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        result = self.reg.get("bad_agent").invoke({})
        self.assertIn("error", result)

    def test_reasoning_agent_without_params_ok(self):
        """推理 Agent 无参数调用成功"""
        r = self.reg.get("reasoning_agent").invoke({})
        self.assertNotIn("error", r)
        self.assertEqual(r["method"], "build_environment_context")

    def test_planning_agent_returns_matrix(self):
        """规划 Agent 数据含矩阵"""
        r = self.reg.get("planning_agent").invoke({})
        self.assertIn("matrix", r["data"])

    def test_governance_agent_returns_summary(self):
        """治理 Agent 数据含 summary"""
        r = self.reg.get("governance_agent").invoke({})
        self.assertIn("summary", r["data"])

    def test_experience_agent_returns_table(self):
        """经验 Agent 数据含 table"""
        r = self.reg.get("experience_agent").invoke({})
        self.assertIn("table", r["data"])

    def test_six_agents_descriptions(self):
        """6 Agent 描述非空"""
        agents = self.reg.snapshot()["agents"]
        self.assertTrue(all(a["description"] for a in agents))


class TestServiceV51(unittest.TestCase):
    """Service V5.1 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
            "companion_delegate_workers": 2,
            "companion_route_topk": 2,
        })

    def test_companion_stats_api(self):
        """companion_stats"""
        st = self.svc.companion_stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertIn("total_delegations", st)
        self.assertIn("top_combinations", st)
        self.assertIn("per_agent", st)

    def test_stats_after_handles(self):
        """多次处理后统计累积"""
        self.svc.companion_handle({"text": "扫描"})
        self.svc.companion_handle({"text": "扫描"})
        st = self.svc.companion_stats()
        self.assertEqual(st["total_delegations"], 2)

    def test_config_workers(self):
        """配置驱动 workers"""
        self.assertEqual(self.svc.companion._delegator._workers, 2)

    def test_config_topk(self):
        """配置驱动 top_k"""
        self.assertEqual(self.svc.companion._router._top_k, 2)

    def test_topk_limits_delegation(self):
        """Top-K=2 限制委派数"""
        r = self.svc.companion_handle(
            {"text": "扫描并整理规划治理"},
        )
        self.assertLessEqual(len(r["assigned_agents"]), 2)

    def test_parallel_flag_via_service(self):
        """经 Service 并发标记"""
        r = self.svc.companion_handle({"text": "扫描并整理"})
        self.assertTrue(r["dispatched_parallel"])

    def test_total_latency_via_service(self):
        """经 Service 耗时统计"""
        r = self.svc.companion_handle({"text": "扫描"})
        self.assertGreaterEqual(r["total_latency_ms"], 0)
        self.assertEqual(len(r["per_agent_latency_ms"]), 1)

    def test_version_5_1_0(self):
        """版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_v50_apis_still_work(self):
        """向后兼容: V5.0 API"""
        r = self.svc.companion_handle({"text": "扫描"})
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(self.svc.companion_agents()["total"], 7)
        dry = self.svc.companion_dry_run({"text": "扫描"})
        self.assertTrue(dry["dry_run"])

    def test_v47_apis_still_work(self):
        """向后兼容: V4.7 API"""
        r = self.svc.long_horizon_plan(title="t", phases=["a"])
        self.assertEqual(r["mode"], "rule_based")

    def test_no_memory_write(self):
        """伙伴请求不写 Agent Memory"""
        before = self.svc.memory.stats().get("total", 0)
        self.svc.companion_handle({"text": "扫描并整理"})
        self.svc.companion_handle({"text": "治理检查"})
        after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_audit_still_tracked(self):
        """审计仍记录 companion_handle"""
        self.svc.companion_handle({"text": "扫描"})
        log = self.svc.audit_policy_log(limit=0, action="companion_handle")
        self.assertEqual(log["total"], 1)


class TestEndToEndV51(unittest.TestCase):
    """端到端: 打分路由 → 并发 → 汇总 → 统计"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_full_coordination_flow(self):
        """完整协同流程"""
        # 1. 路由打分
        route = self.svc.companion_route(
            {"text": "扫描环境并制定长期任务"},
        )
        self.assertTrue(route["scores"])
        self.assertIn("perception", route["capabilities"])
        self.assertIn("long_horizon", route["capabilities"])

        # 2. 并发委派
        resp = self.svc.companion_handle(
            {"text": "扫描环境并制定长期任务", "title": "整理房间"},
        )
        self.assertTrue(resp["dispatched_parallel"])
        self.assertTrue(resp["aggregated"]["all_ok"])

        # 3. 统计
        st = self.svc.companion_stats()
        self.assertEqual(st["total_delegations"], 1)
        self.assertEqual(st["success_rate"], 1.0)
        self.assertEqual(st["parallel_ratio"], 1.0)

    def test_combined_intent_score_order(self):
        """组合意图得分排序 (核心词优先)"""
        # "扫描"2.0 + "环境"1.0 = 3.0 > "整理"2.0
        r = self.svc.companion_route({"text": "扫描环境并整理"})
        self.assertEqual(r["capabilities"][0], "perception")
        self.assertEqual(r["scores"][0]["score"], 3.0)

    def test_explainable_reason_full(self):
        """端到端可解释原因"""
        resp = self.svc.companion_handle({"text": "扫描并整理"})
        reason = resp["explainable_reason"]
        self.assertTrue("并行" in reason or "管道" in reason)
        self.assertIn("总耗时", reason)
        self.assertIn("ms", reason)

    def test_stats_per_agent_after_multi(self):
        """多次请求后每 Agent 统计"""
        self.svc.companion_handle({"text": "扫描"})
        self.svc.companion_handle({"text": "扫描并整理"})
        st = self.svc.companion_stats()
        self.assertIn("perception_agent", st["per_agent"])
        self.assertGreater(
            st["per_agent"]["perception_agent"]["invocations"], 0,
        )

    def test_top_combinations_after_repeats(self):
        """重复组合进入 Top 组合"""
        self.svc.companion_handle({"text": "扫描并整理"})
        self.svc.companion_handle({"text": "扫描并整理"})
        st = self.svc.companion_stats()
        top = st["top_combinations"][0]
        self.assertEqual(top["count"], 2)
        self.assertIn("perception_agent", top["agents"])

    def test_avg_latency_after_requests(self):
        """平均耗时统计"""
        self.svc.companion_handle({"text": "扫描"})
        self.svc.companion_handle({"text": "扫描"})
        st = self.svc.companion_stats()
        self.assertGreaterEqual(st["avg_latency_ms"], 0)

    def test_stats_reset_per_service(self):
        """每次 Service 独立统计"""
        svc2 = EmbodiedService()
        svc2.load_config({"embodied_enabled": True, "companion_enabled": True})
        self.assertEqual(svc2.companion_stats()["total_delegations"], 0)

    def test_route_scores_deterministic(self):
        """路由打分确定性 (两次一致)"""
        r1 = self.svc.companion_route({"text": "扫描并整理"})
        r2 = self.svc.companion_route({"text": "扫描并整理"})
        self.assertEqual(r1["scores"], r2["scores"])

    def test_route_topk_config_limits(self):
        """Top-K 配置生效"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True, "companion_enabled": True,
            "companion_route_topk": 1,
        })
        r = svc.companion_route({"text": "扫描并整理规划"})
        self.assertEqual(len(r["capabilities"]), 1)

    def test_route_all_capabilities_mappable(self):
        """全部能力域可路由"""
        cases = [
            ("观察环境", "perception"),
            ("为什么失败", "reasoning"),
            ("策略建议", "experience"),
            ("多目标规划", "planning"),
            ("长期任务进度", "long_horizon"),
            ("治理健康检查", "governance"),
        ]
        for text, expected in cases:
            r = self.svc.companion_route({"text": text})
            self.assertIn(expected, r["capabilities"], text)

    def test_weighted_composite_beats_single(self):
        """复合词得分 > 单核心词"""
        r1 = self.svc.companion_route({"text": "制定长期目标"})
        r2 = self.svc.companion_route({"text": "扫描环境"})
        lh_score = next(s["score"] for s in r1["scores"]
                        if s["capability"] == "long_horizon")
        pc_score = next(s["score"] for s in r2["scores"]
                        if s["capability"] == "perception")
        self.assertGreater(lh_score, pc_score)

    def test_stats_after_dry_run_no_effect(self):
        """预演不影响统计"""
        before = self.svc.companion_stats()["total_delegations"]
        self.svc.companion_dry_run({"text": "扫描"})
        self.svc.companion_dry_run({"text": "整理"})
        after = self.svc.companion_stats()["total_delegations"]
        self.assertEqual(after, before)

    def test_parallel_and_sequential_mix(self):
        """并行与顺序混合统计"""
        self.svc.companion_handle({"text": "扫描"})          # 顺序
        self.svc.companion_handle({"text": "扫描并整理"})    # 并行
        st = self.svc.companion_stats()
        self.assertEqual(st["total_delegations"], 2)
        self.assertGreater(st["parallel_ratio"], 0)
        self.assertLess(st["parallel_ratio"], 1.0)

    def test_stats_record_fields(self):
        """统计记录字段完整"""
        self.svc.companion_handle({"text": "扫描"})
        st = self.svc.companion_stats()
        recent = st["recent"][0]
        for key in ("timestamp", "agents", "ok_count", "total",
                    "latency_ms", "parallel"):
            self.assertIn(key, recent)


if __name__ == "__main__":
    unittest.main()
