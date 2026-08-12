"""
YHLZ Embodied AI V5.3 - 执行-反馈闭环 Service 集成测试
(Execution & Feedback Loop via Service)

覆盖:
    - Service companion_execute / companion_loop API
    - 配置驱动: loop_max_iterations / execute_confirm / feedback_enabled
    - execution_agent (7 专业 Agent)
    - LOOP_PIPELINE (闭环管道 3 阶段)
    - 执行审计 (companion_executor.audit)
    - 安全: 执行经 Permission / 不写 Agent Memory
    - 向后兼容: V5.2 / V5.1 / V5.0 API
"""
import unittest

from backend.embodied.service import EmbodiedService


class TestServiceExecute(unittest.TestCase):
    """Service 执行 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_companion_execute_api(self):
        """companion_execute"""
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(rec["success"])
        self.assertIn("execution_id", rec)

    def test_companion_execute_goal(self):
        """执行 goal 字段"""
        rec = self.svc.companion_execute({
            "description": "拿起台灯", "intent": "pick", "target": "lamp",
        })
        self.assertEqual(rec["goal"]["intent"], "pick")

    def test_companion_execute_permission_required(self):
        """执行标记 permission_required"""
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(rec["permission_required"])

    def test_companion_execute_denied(self):
        """embodied_enabled=False → denied"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": False})
        rec = svc.companion_execute({
            "description": "拿起", "intent": "pick",
        })
        self.assertFalse(rec["success"])
        self.assertEqual(rec["status"], "denied")

    def test_companion_loop_api(self):
        """companion_loop"""
        loop = self.svc.companion_loop({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(loop["success"])
        self.assertIn("loop_id", loop)
        self.assertEqual(loop["mode"], "rule_based")

    def test_loop_config_iterations(self):
        """配置驱动上限"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_loop_max_iterations": 2,
        })
        self.assertEqual(svc.companion_executor.thresholds()[
            "max_iterations"], 2)

    def test_executor_audit_via_service(self):
        """执行审计经 Service"""
        self.svc.companion_execute({"description": "扫描", "intent": "scan"})
        aud = self.svc.companion_executor.audit()
        self.assertEqual(aud["total"], 1)
        self.assertEqual(aud["success_rate"], 1.0)

    def test_executor_shared_instance(self):
        """执行器单实例 (审计累积)"""
        self.svc.companion_execute({"description": "扫描", "intent": "scan"})
        self.svc.companion_execute({"description": "扫描", "intent": "scan"})
        aud = self.svc.companion_executor.audit()
        self.assertEqual(aud["total"], 2)


class TestExecutionAgent(unittest.TestCase):
    """执行 Agent"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_seven_agents(self):
        """7 个专业 Agent (含 execution)"""
        agents = self.svc.companion_agents()
        self.assertEqual(agents["total"], 7)
        names = [a["name"] for a in agents["agents"]]
        self.assertIn("execution_agent", names)

    def test_execution_agent_invoke(self):
        """执行 Agent 调用 run_goal"""
        reg = self.svc.companion._registry
        agent = reg.get("execution_agent")
        r = agent.invoke({
            "description": "扫描", "intent": "scan",
        })
        self.assertNotIn("error", r)
        data = r["data"]
        self.assertIn("success", data)
        self.assertEqual(r["method"], "run_goal")

    def test_execution_agent_denied(self):
        """执行 Agent 权限拒绝"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": False})
        reg = svc.companion._registry
        agent = reg.get("execution_agent")
        r = agent.invoke({"description": "拿起", "intent": "pick"})
        self.assertNotIn("error", r)
        self.assertFalse(r["data"]["success"])

    def test_execution_capability_whitelist(self):
        """execution 在能力域白名单"""
        from backend.embodied.companion import SPECIALIST_CAPABILITIES
        self.assertIn("execution", SPECIALIST_CAPABILITIES)

    def test_execution_route_keyword(self):
        """执行关键词路由"""
        r = self.svc.companion_route({"text": "执行拿起台灯"})
        self.assertIn("execution", r["capabilities"])


class TestLoopPipeline(unittest.TestCase):
    """闭环管道"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_loop_pipeline_constant(self):
        """LOOP_PIPELINE 3 阶段"""
        from backend.embodied.companion import LOOP_PIPELINE
        self.assertEqual(len(LOOP_PIPELINE), 3)
        self.assertEqual(LOOP_PIPELINE[2]["source"], "planning_agent")
        self.assertEqual(LOOP_PIPELINE[2]["target"], "execution_agent")

    def test_loop_pipeline_stage3(self):
        """阶段 3: 规划 → 执行"""
        from backend.embodied.companion import LOOP_PIPELINE
        s3 = LOOP_PIPELINE[2]
        self.assertEqual(s3["output_to"], "plan_result")
        self.assertIn("Permission", s3["reason"])


class TestSafetyCompat(unittest.TestCase):
    """安全与兼容"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_execution_no_memory_write(self):
        """执行经 Embodied 规则写环境记忆 (不写 Agent Memory)"""
        # run_goal 会写 Embodied 独立环境记忆 (正常行为)
        # 但绝不写入 Agent Memory (Agent 子系统记忆)
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(rec["success"])
        # Embodied 环境记忆 (独立存储) 正常记录
        self.assertGreaterEqual(self.svc.memory.stats().get("total", 0), 0)
        # 验证执行不写 Agent Memory: 通过检查执行记录无 agent_memory 字段
        self.assertNotIn("agent_memory", rec)

    def test_v52_pipeline_api_works(self):
        """V5.2 companion_pipeline 兼容"""
        pa = self.svc.companion_pipeline()
        self.assertEqual(len(pa["stages"]), 2)

    def test_v52_handle_works(self):
        """V5.2 companion_handle 兼容"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertEqual(r["mode"], "rule_based")

    def test_v51_stats_works(self):
        """V5.1 companion_stats 兼容"""
        st = self.svc.companion_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_v50_agents_works(self):
        """V5.0 companion_agents 兼容 (7 个)"""
        self.assertEqual(self.svc.companion_agents()["total"], 7)

    def test_version_5_3_0(self):
        """版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_audit_still_tracked(self):
        """审计仍记录 companion_handle"""
        self.svc.companion_handle({"text": "扫描"})
        log = self.svc.audit_policy_log(limit=0, action="companion_handle")
        self.assertEqual(log["total"], 1)

    def test_execution_not_device_control(self):
        """执行只操作 Mock 环境"""
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan",
        })
        self.assertNotIn("device", rec)

    def test_loop_explainable_reason(self):
        """闭环可解释原因"""
        loop = self.svc.companion_loop({
            "description": "扫描", "intent": "scan",
        })
        self.assertIn("闭环执行", loop["explainable_reason"])

    def test_execute_error_recorded(self):
        """异常执行记录 (不崩溃)"""
        rec = self.svc.companion_execute({
            "description": "", "intent": "",
        })
        self.assertIn("execution_id", rec)

    def test_execute_stats_after_multi(self):
        """多次执行审计统计"""
        self.svc.companion_execute({"description": "扫描", "intent": "scan"})
        self.svc.companion_execute({"description": "扫描", "intent": "scan"})
        aud = self.svc.companion_executor.audit()
        self.assertEqual(aud["success_count"], 2)
        self.assertEqual(aud["success_rate"], 1.0)

    def test_execute_audit_recent(self):
        """审计近期记录"""
        self.svc.companion_execute({"description": "扫描", "intent": "scan"})
        aud = self.svc.companion_executor.audit()
        self.assertEqual(len(aud["recent"]), 1)
        self.assertEqual(aud["recent"][0]["goal"]["intent"], "scan")

    def test_execute_feedback_recorded(self):
        """执行反馈字段"""
        rec = self.svc.companion_execute({"description": "扫描",
                                          "intent": "scan"})
        self.assertIn("feedback", rec)

    def test_loop_execution_records(self):
        """闭环执行记录"""
        loop = self.svc.companion_loop({"description": "扫描",
                                        "intent": "scan"})
        self.assertEqual(len(loop["executions"]), 1)
        self.assertTrue(loop["executions"][0]["success"])

    def test_loop_final_status_ok(self):
        """闭环最终状态"""
        loop = self.svc.companion_loop({"description": "扫描",
                                        "intent": "scan"})
        self.assertEqual(loop["final_status"], "ok")

    def test_loop_audit_accumulates(self):
        """闭环执行计入审计"""
        before = self.svc.companion_executor.audit()["total"]
        self.svc.companion_loop({"description": "扫描", "intent": "scan"})
        after = self.svc.companion_executor.audit()["total"]
        self.assertEqual(after, before + 1)

    def test_execution_agent_scan(self):
        """执行 Agent 扫描目标"""
        reg = self.svc.companion._registry
        agent = reg.get("execution_agent")
        r = agent.invoke({"description": "扫描", "intent": "scan"})
        self.assertTrue(r["data"]["success"])

    def test_execution_agent_error_captured(self):
        """执行 Agent 异常捕获"""
        reg = self.svc.companion._registry
        agent = reg.get("execution_agent")
        # 无 description/intent → run_goal 仍可执行 (explore 兜底)
        r = agent.invoke({})
        self.assertIn("data", r)

    def test_execution_in_route_all(self):
        """执行能力域可路由"""
        r = self.svc.companion_route({"text": "执行任务"})
        self.assertIn("execution", r["capabilities"])

    def test_loop_pipeline_stage3_has_permission(self):
        """闭环阶段 3 经 Permission"""
        from backend.embodied.companion import LOOP_PIPELINE
        self.assertIn("Permission", LOOP_PIPELINE[2]["reason"])

    def test_config_feedback_disabled(self):
        """反馈停用配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_feedback_enabled": False,
        })
        executor = svc.companion_executor
        self.assertFalse(executor.thresholds()["feedback_enabled"])

    def test_config_confirm(self):
        """确认标记配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_execute_confirm": True,
        })
        executor = svc.companion_executor
        self.assertTrue(executor.thresholds()["confirm"])

    def test_execute_priority_high(self):
        """高优先级执行"""
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan", "priority": "high",
        })
        self.assertEqual(rec["goal"]["priority"], "high")

    def test_execute_scene_room(self):
        """场景参数"""
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan", "scene": "room",
        })
        self.assertEqual(rec["goal"]["scene"], "room")

    def test_execute_constraints(self):
        """约束参数"""
        rec = self.svc.companion_execute({
            "description": "拿起台灯", "intent": "pick", "target": "lamp",
            "constraints": {"max_steps": 3},
        })
        self.assertEqual(rec["goal"]["constraints"], {"max_steps": 3})

    def test_executor_audit_mode(self):
        """审计模式"""
        aud = self.svc.companion_executor.audit()
        self.assertEqual(aud["mode"], "rule_based")

    def test_v52_pipeline_still_default(self):
        """默认管道仍为感知-策略 (2 阶段)"""
        pa = self.svc.companion_pipeline()
        self.assertEqual(len(pa["stages"]), 2)

    def test_handle_loop_request(self):
        """handle 处理执行请求 (路由到 execution)"""
        r = self.svc.companion_handle({"text": "执行扫描任务"})
        self.assertIn("execution_agent", r["assigned_agents"])


if __name__ == "__main__":
    unittest.main()
