"""
YHLZ Embodied AI V10.1 - 交互协议最终验收测试 (V10.1 Interaction Final)

覆盖:
    - 全链路端到端场景
    - DEMO 交互协议流程验证
    - 审计可追踪性
    - 边界矩阵
"""
import unittest

from backend.embodied.companion.interaction import InteractionProtocol
from backend.embodied.service import EmbodiedService


class TestFinalScenario(unittest.TestCase):
    """端到端场景: 协作任务"""

    def test_long_collaboration_flow(self):
        p = InteractionProtocol(enabled=True)
        # 会话开始
        p.begin_session(goal="完成季度报告", mode="task")
        # 理解阶段
        p.update_stage("understand")
        # 筛选上下文
        ctx = p.filter_context("请完成季度报告并提交审核")
        self.assertEqual(ctx["topic"], "task")
        p.set_context(ctx["summary"])
        # 规划
        p.update_stage("planning")
        p.add_pending("收集数据")
        p.add_pending("撰写报告")
        # 执行
        p.update_stage("executing")
        flow = p.begin_tool_flow("查询数据")
        p.execute_tool(flow["flow_id"], "query_data",
                       lambda: {"rows": 100})
        p.finish_tool_flow(flow["flow_id"], "已查询 100 行")
        # 复盘
        p.update_stage("reviewing")
        p.resolve_pending("收集数据")
        p.update_stage("done")
        # 验证
        snap = p.conversation_snapshot()
        self.assertEqual(snap["stage"], "done")
        self.assertEqual(snap["pending"], ["撰写报告"])
        trace = p.trace_tool_flow(flow["flow_id"])
        self.assertEqual(trace["flow"]["tool"], "query_data")
        self.assertGreaterEqual(
            p.audit_report()["stats"]["total"], 8,
        )

    def test_interaction_state_separate_from_personality(self):
        p = InteractionProtocol(enabled=True)
        p.set_partner_goal("协作")
        p.set_partner_relation("collaborate")
        snap = p.partner_snapshot()
        # 交互状态不含人格字段
        self.assertNotIn("warmth", snap)
        self.assertNotIn("traits", snap)
        self.assertNotIn("personality", snap)

    def test_context_not_long_term_memory(self):
        p = InteractionProtocol(enabled=True)
        r = p.filter_context("请完成任务并处理问题")
        # 上下文筛选结果不含记忆写入字段
        self.assertNotIn("memory_id", r)
        self.assertNotIn("stored", r)
        self.assertIn("summary", r)


class TestFinalService(unittest.TestCase):
    """Service 端到端"""

    def _svc(self):
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })
        return svc

    def test_service_full_flow(self):
        svc = self._svc()
        svc.companion_interaction_begin_session(
            goal="部署", mode="task",
        )
        svc.companion_interaction_update_stage("executing")
        svc.companion_interaction_set_context("部署生产")
        svc.companion_interaction_add_pending("确认")
        flow = svc.companion_interaction_begin_tool_flow("检查")
        svc.companion_interaction_finish_tool_flow(
            flow["flow_id"], "正常",
        )
        svc.companion_interaction_set_partner_goal("协同")
        svc.companion_interaction_mark_latency("response", 150)
        stats = svc.companion_interaction_stats()
        self.assertEqual(stats["mode"], "rule_based")
        audit = svc.companion_interaction_audit()
        self.assertGreaterEqual(audit["stats"]["total"], 6)

    def test_service_compat_all(self):
        svc = self._svc()
        # 既有 API 不受影响
        self.assertEqual(
            svc.companion_status()["version"], "9.5.0",
        )
        self.assertEqual(
            svc.companion_health()["mode"], "rule_based",
        )
        self.assertEqual(
            svc.companion_memory_stabilize()["mode"],
            "rule_based",
        )


# ── 生成式: 最终矩阵 ───────────────────────────────────────────
_FINAL_CASES = [
    # (名称, 目标, 模式, 期望 stage)
    ("task_mode", "任务", "task", "init"),
    ("plan_mode", "规划", "planning", "init"),
    ("review_mode", "复盘", "review", "init"),
    ("casual_mode", "闲聊", "casual", "init"),
]


class TestGeneratedFinal(unittest.TestCase):
    """生成式: 模式矩阵"""
    pass


for _i, (_name, _goal, _mode, _exp) in enumerate(_FINAL_CASES):
    def _make(name=_name, goal=_goal, mode=_mode, exp=_exp):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            r = p.begin_session(goal=goal, mode=mode)
            self.assertTrue(r["ok"])
            self.assertEqual(
                p.conversation_snapshot()["stage"], exp,
            )
            self.assertEqual(r["mode_name"], mode)
        test_case.__name__ = f"test_final_{name}_{_i}"
        return test_case
    setattr(TestGeneratedFinal,
            f"test_final_{_name}_{_i}", _make())


# ── 生成式: 工具流程边界矩阵 ───────────────────────────────────
_FLOW_BOUNDARY = [
    ("begin_only", 1),
    ("begin_finish", 2),
    ("begin_advance_finish", 3),
    ("begin_execute_finish", 4),
    ("begin_execute_reflect_finish", 5),
]


class TestGeneratedFlowBoundary(unittest.TestCase):
    """生成式: 流程边界"""
    pass


for _i, (_name, _steps) in enumerate(_FLOW_BOUNDARY):
    def _make(name=_name, steps=_steps):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            flow = p.begin_tool_flow("t")
            steps_remaining = steps - 1
            if steps_remaining >= 1:
                p.advance_tool_flow(flow["flow_id"], "plan")
                steps_remaining -= 1
            if steps_remaining >= 1:
                p.execute_tool(flow["flow_id"], "tool",
                               lambda: 1)
                steps_remaining -= 1
            if steps_remaining >= 1:
                p.advance_tool_flow(flow["flow_id"], "reflect")
                steps_remaining -= 1
            p.finish_tool_flow(flow["flow_id"], "done")
            trace = p.trace_tool_flow(flow["flow_id"])
            self.assertEqual(trace["flow"]["stage"], "response")
        test_case.__name__ = f"test_flow_boundary_{name}_{_i}"
        return test_case
    setattr(TestGeneratedFlowBoundary,
            f"test_flow_boundary_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
