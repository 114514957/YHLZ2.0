"""
YHLZ Embodied AI V10.1 - 交互协议集成测试 (Service Integration)

覆盖:
    - Service API: companion_interaction_* 全链路
    - 兼容性 (既有 API 不受影响)
"""
import unittest

from backend.embodied.service import EmbodiedService


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


class TestServiceInteraction(unittest.TestCase):
    """Service 交互协议"""

    def test_begin_session(self):
        svc = setup_service()
        r = svc.companion_interaction_begin_session(
            goal="完成项目", mode="task",
        )
        self.assertTrue(r["ok"])
        self.assertEqual(r["goal"], "完成项目")

    def test_update_stage(self):
        svc = setup_service()
        svc.companion_interaction_begin_session()
        r = svc.companion_interaction_update_stage("executing")
        self.assertTrue(r["ok"])
        self.assertEqual(r["to"], "executing")

    def test_set_context(self):
        svc = setup_service()
        r = svc.companion_interaction_set_context("请完成任务")
        self.assertTrue(r["ok"])
        snap = svc.companion_interaction_conversation_snapshot()
        self.assertEqual(snap["context"], "请完成任务")

    def test_filter_context(self):
        svc = setup_service()
        r = svc.companion_interaction_filter_context("请完成任务")
        self.assertEqual(r["topic"], "task")

    def test_pending_flow(self):
        svc = setup_service()
        svc.companion_interaction_add_pending("事项A")
        svc.companion_interaction_add_pending("事项B")
        snap = svc.companion_interaction_conversation_snapshot()
        self.assertEqual(snap["pending"], ["事项A", "事项B"])

    def test_tool_flow(self):
        svc = setup_service()
        flow = svc.companion_interaction_begin_tool_flow("查询")
        self.assertTrue(flow["ok"])
        r = svc.companion_interaction_finish_tool_flow(
            flow["flow_id"], "完成",
        )
        self.assertTrue(r["ok"])

    def test_advance_tool_flow(self):
        svc = setup_service()
        flow = svc.companion_interaction_begin_tool_flow("查询")
        r = svc.companion_interaction_advance_tool_flow(
            flow["flow_id"], "plan", "选择工具",
        )
        self.assertTrue(r["ok"])

    def test_trace_tool_flow(self):
        svc = setup_service()
        flow = svc.companion_interaction_begin_tool_flow("查询")
        trace = svc.companion_interaction_trace_tool_flow(
            flow["flow_id"],
        )
        self.assertEqual(trace["flow"]["stage"], "understand")

    def test_execute_tool_no_fn(self):
        svc = setup_service()
        flow = svc.companion_interaction_begin_tool_flow("查询")
        r = svc.companion_interaction_execute_tool(
            flow["flow_id"], "tool",
        )
        self.assertEqual(r["mode"], "error_frame")

    def test_partner_goal(self):
        svc = setup_service()
        r = svc.companion_interaction_set_partner_goal("共同完成")
        self.assertTrue(r["ok"])
        snap = svc.companion_interaction_partner_snapshot()
        self.assertEqual(snap["goal"], "共同完成")

    def test_mark_latency(self):
        svc = setup_service()
        r = svc.companion_interaction_mark_latency("response", 200)
        self.assertTrue(r["ok"])
        report = svc.companion_interaction_latency_report()
        self.assertGreaterEqual(
            report["stages"]["response"]["count"], 1,
        )

    def test_audit_api(self):
        svc = setup_service()
        svc.companion_interaction_begin_session(goal="任务")
        svc.companion_interaction_mark_latency("tts", 10)
        r = svc.companion_interaction_audit()
        self.assertGreaterEqual(r["stats"]["total"], 2)

    def test_stats_api(self):
        svc = setup_service()
        r = svc.companion_interaction_stats()
        self.assertEqual(r["mode"], "rule_based")
        for key in ("conversation", "tool_flow", "latency"):
            self.assertIn(key, r)

    def test_latency_report_api(self):
        svc = setup_service()
        r = svc.companion_interaction_latency_report()
        self.assertIn("stages", r)

    def test_conversation_snapshot_api(self):
        svc = setup_service()
        r = svc.companion_interaction_conversation_snapshot()
        self.assertEqual(r["stage"], "init")

    def test_partner_snapshot_api(self):
        svc = setup_service()
        r = svc.companion_interaction_partner_snapshot()
        self.assertEqual(r["relation"], "none")

    def test_full_scenario(self):
        svc = setup_service()
        # 完整协作场景
        svc.companion_interaction_begin_session(
            goal="完成部署", mode="task",
        )
        svc.companion_interaction_update_stage("planning")
        svc.companion_interaction_set_context("部署生产环境")
        svc.companion_interaction_add_pending("确认版本")
        flow = svc.companion_interaction_begin_tool_flow("检查状态")
        svc.companion_interaction_finish_tool_flow(
            flow["flow_id"], "状态正常",
        )
        svc.companion_interaction_set_partner_goal("协同完成")
        snap = svc.companion_interaction_conversation_snapshot()
        self.assertEqual(snap["stage"], "planning")
        self.assertEqual(snap["pending"], ["确认版本"])
        partner = svc.companion_interaction_partner_snapshot()
        self.assertEqual(partner["goal"], "协同完成")


class TestCompatibility(unittest.TestCase):
    """兼容性"""

    def test_health_ok(self):
        svc = setup_service()
        r = svc.companion_health()
        self.assertEqual(r["mode"], "rule_based")

    def test_meta_cognition_ok(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_monitor("任务")
        self.assertIn("monitor_id", r)

    def test_memory_stabilize_ok(self):
        svc = setup_service()
        r = svc.companion_memory_stabilize()
        self.assertEqual(r["mode"], "rule_based")

    def test_experience_stats_ok(self):
        svc = setup_service()
        r = svc.companion_experience_stats()
        self.assertIn("mode", r)

    def test_status_version(self):
        svc = setup_service()
        r = svc.companion_status()
        self.assertEqual(r["version"], "9.5.0")

    def test_personality_ok(self):
        svc = setup_service()
        r = svc.companion_personality()
        self.assertIn("base", r)

    def test_growth_stats_ok(self):
        svc = setup_service()
        r = svc.companion_growth_stats()
        self.assertIn("mode", r)

    def test_research_stats_ok(self):
        svc = setup_service()
        r = svc.companion_research_stats()
        self.assertIn("mode", r)

    def test_creative_stats_ok(self):
        svc = setup_service()
        r = svc.companion_meta_creative_stats()
        self.assertIn("mode", r)


if __name__ == "__main__":
    unittest.main()
