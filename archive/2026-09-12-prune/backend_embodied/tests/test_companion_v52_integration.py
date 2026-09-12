"""
YHLZ Embodied AI V5.2 - 感知-战略集成 Service 测试
(Perception & Strategy Integration via Service)

覆盖:
    - Service companion_pipeline API
    - 配置驱动: pipeline_enabled / pipeline_strict
    - 感知-策略闭环端到端 (扫描 → 策略 → 规划)
    - CompanionResponse 含 pipeline / pipeline_stages
    - 向后兼容: V5.1 API / V4.7 API
    - 安全: 不写 Agent Memory / 不绕过 Permission
"""
import unittest

from backend.embodied.service import EmbodiedService


class TestServicePipeline(unittest.TestCase):
    """Service V5.2 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_companion_pipeline_api(self):
        """companion_pipeline 分析"""
        pa = self.svc.companion_pipeline()
        self.assertTrue(pa["enabled"])
        self.assertFalse(pa["strict"])
        self.assertEqual(len(pa["stages"]), 2)
        self.assertIn("execution_order", pa)

    def test_pipeline_execution_order_api(self):
        """执行顺序 = 感知 → 经验 → 规划"""
        pa = self.svc.companion_pipeline()
        self.assertEqual(pa["execution_order"],
                         ["perception_agent", "experience_agent",
                          "planning_agent"])

    def test_pipeline_stages_fields(self):
        """阶段字段完整"""
        pa = self.svc.companion_pipeline()
        for s in pa["stages"]:
            for key in ("stage", "source", "target", "input_from",
                        "output_to", "reason"):
                self.assertIn(key, s)

    def test_config_pipeline_disabled(self):
        """pipeline_enabled=False → 停用"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True, "companion_enabled": True,
            "companion_pipeline_enabled": False,
        })
        pa = svc.companion_pipeline()
        self.assertFalse(pa["enabled"])

    def test_config_pipeline_strict(self):
        """pipeline_strict=True → 严格模式"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True, "companion_enabled": True,
            "companion_pipeline_strict": True,
        })
        pa = svc.companion_pipeline()
        self.assertTrue(pa["strict"])

    def test_handle_includes_pipeline(self):
        """响应含管道明细"""
        r = self.svc.companion_handle({"text": "扫描并规划"})
        self.assertIn("pipeline", r)
        self.assertIsNotNone(r["pipeline"])
        self.assertEqual(len(r["pipeline_stages"]), 2)

    def test_version_5_2_0(self):
        """版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")


class TestPerceptionStrategyLoop(unittest.TestCase):
    """感知-策略闭环端到端"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_full_loop(self):
        """扫描环境并规划 → 管道闭环"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        self.assertEqual(r["pipeline"]["enabled"], True)
        result_agents = [x["agent"] for x in r["results"]]
        self.assertEqual(result_agents,
                         ["perception_agent", "experience_agent",
                          "planning_agent"])

    def test_loop_all_success(self):
        """闭环全链路成功"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        self.assertTrue(r["aggregated"]["all_ok"])

    def test_loop_reason_pipeline_stages(self):
        """原因含管道阶段"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        self.assertIn("[管道]", r["explainable_reason"])
        self.assertIn("阶段1", r["explainable_reason"])
        self.assertIn("阶段2", r["explainable_reason"])

    def test_perception_result_payload(self):
        """感知 Agent 输出实际环境状态"""
        r = self.svc.companion_handle({"text": "扫描环境"})
        perception = next(x for x in r["results"]
                          if x["agent"] == "perception_agent")
        self.assertTrue(perception["ok"])
        self.assertIn("data", perception["result"])

    def test_experience_pipeline_input(self):
        """经验 Agent 收到管道 env_state (宽松: 或标记忽略)"""
        r = self.svc.companion_handle({"text": "扫描环境并查看策略"})
        exp = next(x for x in r["results"]
                   if x["agent"] == "experience_agent")
        self.assertTrue(exp["ok"])

    def test_planning_receives_strategy(self):
        """规划 Agent 收到管道策略建议"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        plan = next(x for x in r["results"]
                    if x["agent"] == "planning_agent")
        self.assertTrue(plan["ok"])

    def test_governance_not_in_pipeline(self):
        """治理请求不走管道 (常规委派)"""
        r = self.svc.companion_handle({"text": "治理健康检查"})
        self.assertIsNone(r["pipeline"])
        self.assertEqual(r["pipeline_stages"], [])

    def test_stats_tracked(self):
        """管道委派计入协同统计"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        st = self.svc.companion_stats()
        self.assertGreaterEqual(st["total_delegations"], 1)

    def test_stats_parallel_ratio_pipeline(self):
        """管道委派 parallel 标记 (多 Agent)"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        st = self.svc.companion_stats()
        self.assertGreaterEqual(st["total_agents_invoked"], 3)


class TestCompatAndSafety(unittest.TestCase):
    """兼容与安全"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_v51_stats_api_works(self):
        """V5.1 companion_stats 兼容"""
        self.svc.companion_handle({"text": "扫描"})
        st = self.svc.companion_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_v51_route_api_works(self):
        """V5.1 companion_route 兼容"""
        r = self.svc.companion_route({"text": "扫描"})
        self.assertIn("scores", r)

    def test_v51_dry_run_works(self):
        """V5.1 companion_dry_run 兼容"""
        r = self.svc.companion_dry_run({"text": "扫描"})
        self.assertTrue(r["dry_run"])

    def test_v50_agents_api_works(self):
        """V5.0 companion_agents 兼容"""
        self.assertEqual(self.svc.companion_agents()["total"], 7)

    def test_v47_long_horizon_works(self):
        """V4.7 long_horizon 兼容"""
        r = self.svc.long_horizon_plan(title="t", phases=["a"])
        self.assertEqual(r["mode"], "rule_based")

    def test_no_memory_write(self):
        """管道不写 Agent Memory"""
        before = self.svc.memory.stats().get("total", 0)
        self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        self.svc.companion_handle({"text": "治理健康检查"})
        after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_pipeline_no_device_control(self):
        """管道只传数据不控制设备"""
        # 管道输出只有 pipeline 明细, 无执行动作
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        self.assertNotIn("executed_actions", r)
        self.assertNotIn("device", r)

    def test_pipeline_audit_still_tracked(self):
        """审计仍记录 companion_handle"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议制定规划"})
        log = self.svc.audit_policy_log(limit=0, action="companion_handle")
        self.assertEqual(log["total"], 1)

    def test_pipeline_stats_latency(self):
        """管道耗时统计"""
        r = self.svc.companion_handle({"text": "扫描环境并制定规划"})
        self.assertGreaterEqual(r["total_latency_ms"], 0)
        self.assertEqual(len(r["per_agent_latency_ms"]),
                         len(r["assigned_agents"]))

    def test_pipeline_response_request_id(self):
        """响应含 request_id"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertTrue(r["request_id"].startswith("req_"))

    def test_pipeline_mode_rule_based(self):
        """模式 rule_based"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertEqual(r["mode"], "rule_based")

    def test_pipeline_stages_in_response(self):
        """响应含 pipeline_stages"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertEqual(len(r["pipeline_stages"]), 2)

    def test_pipeline_reason_line(self):
        """原因含管道行"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("[管道]", r["explainable_reason"])

    def test_perception_invocation_count(self):
        """感知 Agent 被调用"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        agents = self.svc.companion_agents()
        perception = next(a for a in agents["agents"]
                          if a["name"] == "perception_agent")
        self.assertGreater(perception["invocations"], 0)

    def test_pipeline_stats_integrated(self):
        """管道统计计入协同统计"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        st = self.svc.companion_stats()
        self.assertEqual(st["total_delegations"], 1)

    def test_strict_config_in_analysis(self):
        """严格模式在分析中反映"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True, "companion_enabled": True,
            "companion_pipeline_strict": True,
        })
        self.assertTrue(svc.companion_pipeline()["strict"])

    def test_pipeline_disabled_no_stages(self):
        """管道停用 → 无阶段"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True, "companion_enabled": True,
            "companion_pipeline_enabled": False,
        })
        r = svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertEqual(r["pipeline_stages"], [])
        self.assertIsNone(r["pipeline"])

    def test_pipeline_analysis_rule_based(self):
        """管道分析 mode"""
        pa = self.svc.companion_pipeline()
        self.assertIn("reason", pa)

    def test_pipeline_stages_order_consistent(self):
        """阶段顺序一致"""
        pa = self.svc.companion_pipeline()
        self.assertEqual([s["stage"] for s in pa["stages"]], [1, 2])

    def test_perception_to_experience_stage(self):
        """阶段 1 数据流正确"""
        pa = self.svc.companion_pipeline()
        s1 = pa["stages"][0]
        self.assertEqual(s1["source"], "perception_agent")
        self.assertEqual(s1["target"], "experience_agent")

    def test_experience_to_planning_stage(self):
        """阶段 2 数据流正确"""
        pa = self.svc.companion_pipeline()
        s2 = pa["stages"][1]
        self.assertEqual(s2["source"], "experience_agent")
        self.assertEqual(s2["target"], "planning_agent")

    def test_handle_pipeline_mode_parallel(self):
        """管道请求 dispatched_parallel (多 Agent)"""
        r = self.svc.companion_handle(
            {"text": "扫描环境查看策略建议制定规划"},
        )
        self.assertTrue(r["dispatched_parallel"])

    def test_handle_experience_payload(self):
        """经验 Agent 输出统计"""
        r = self.svc.companion_handle(
            {"text": "扫描环境查看策略建议制定规划"},
        )
        exp = next(x for x in r["results"]
                   if x["agent"] == "experience_agent")
        self.assertTrue(exp["ok"])
        self.assertIn("data", exp["result"])

    def test_handle_planning_payload(self):
        """规划 Agent 输出总览"""
        r = self.svc.companion_handle(
            {"text": "扫描环境查看策略建议制定规划"},
        )
        plan = next(x for x in r["results"]
                    if x["agent"] == "planning_agent")
        self.assertTrue(plan["ok"])
        self.assertIn("data", plan["result"])

    def test_pipeline_strict_response_ok(self):
        """严格模式正常请求成功"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True, "companion_enabled": True,
            "companion_pipeline_strict": True,
        })
        r = svc.companion_handle(
            {"text": "扫描环境查看策略建议制定规划"},
        )
        self.assertTrue(r["aggregated"]["all_ok"])

    def test_single_agent_pipeline_off(self):
        """单 Agent 请求 (无管道)"""
        r = self.svc.companion_handle({"text": "治理健康检查"})
        self.assertIsNone(r["pipeline"])

    def test_pipeline_request_id_unique(self):
        """管道请求 ID 唯一"""
        r1 = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        r2 = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertNotEqual(r1["request_id"], r2["request_id"])


if __name__ == "__main__":
    unittest.main()
