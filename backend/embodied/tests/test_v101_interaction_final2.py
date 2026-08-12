"""
YHLZ Embodied AI V10.1 - 交互协议最终验收 (V10.1 Interaction Final2)

覆盖:
    - 全能力验收矩阵
    - 热机原则验证 (不污染记忆/不改身份/不绕过宪法)
"""
import unittest

from backend.embodied.companion.interaction import InteractionProtocol
from backend.embodied.service import EmbodiedService


class TestFinal2Protocol(unittest.TestCase):
    """最终验收"""

    def test_four_retained_modules(self):
        """保留模块: 会话状态/上下文筛选/工具流/伙伴状态"""
        p = InteractionProtocol(enabled=True)
        p.begin_session(goal="目标", mode="task")
        p.update_stage("planning")
        ctx = p.filter_context("请完成任务")
        p.set_context(ctx["summary"])
        flow = p.begin_tool_flow("查询")
        p.finish_tool_flow(flow["flow_id"], "完成")
        p.set_partner_goal("协作")
        p.set_partner_relation("collaborate")
        # 四模块全部可用
        snap = p.conversation_snapshot()
        self.assertEqual(snap["stage"], "planning")
        self.assertEqual(snap["goal"], "目标")
        partner = p.partner_snapshot()
        self.assertEqual(partner["relation"], "collaborate")
        trace = p.trace_tool_flow(flow["flow_id"])
        self.assertEqual(trace["flow"]["stage"], "response")
        self.assertEqual(p.audit_report()["stats"]["total"] >= 6,
                         True)

    def test_no_memory_pollution(self):
        """不污染 Memory Layer: 协议无记忆写入字段"""
        p = InteractionProtocol(enabled=True)
        p.begin_session(goal="任务")
        snap = p.conversation_snapshot()
        for key in ("memory_id", "experience_id",
                    "stored_to_memory"):
            self.assertNotIn(key, snap)

    def test_no_identity_change(self):
        """不修改 Identity Layer: 无身份字段"""
        p = InteractionProtocol(enabled=True)
        p.set_partner_goal("协作")
        p.begin_session(goal="任务")
        snap = p.partner_snapshot()
        conv = p.conversation_snapshot()
        for s in (snap, conv):
            for key in ("identity", "base_personality",
                        "mission", "core_value"):
                self.assertNotIn(key, s)

    def test_constitution_untouched(self):
        """不绕过 Constitution: 协议无治理字段"""
        p = InteractionProtocol(enabled=True)
        p.begin_session(goal="任务")
        s = p.stats()
        for key in ("constitution", "governance",
                    "principles"):
            self.assertNotIn(key, s)

    def test_context_filtered_not_memory(self):
        """上下文必须筛选: 摘要 ≠ 原始"""
        p = InteractionProtocol(enabled=True)
        r = p.filter_context("x" * 500)
        self.assertTrue(r["clipped"])
        self.assertLess(len(r["summary"]), len("x" * 500))

    def test_session_bounded(self):
        """会话有界: 不无限保存"""
        p = InteractionProtocol(enabled=True)
        p.begin_session(goal="任务")
        for i in range(30):
            p.add_pending(f"事项{i}")
        snap = p.conversation_snapshot()
        self.assertLessEqual(len(snap["pending"]), 20)

    def test_context_bounded(self):
        """上下文裁剪保护"""
        p = InteractionProtocol(enabled=True)
        p.set_context("长内容" * 100)
        snap = p.conversation_snapshot()
        self.assertLessEqual(snap["context_len"], 200)

    def test_protocol_audit_traceable(self):
        """审计可追踪"""
        p = InteractionProtocol(enabled=True)
        p.begin_session(goal="任务")
        p.begin_tool_flow("查询")
        replay = p.audit_report(limit=10)["recent"]
        self.assertGreaterEqual(len(replay), 2)
        for entry in replay:
            self.assertIn("audit_id", entry)
            self.assertIn("timestamp", entry)
            self.assertIn("action", entry)

    def test_protocol_partner_session_counting(self):
        """伙伴会话计数"""
        p = InteractionProtocol(enabled=True)
        for _ in range(3):
            p.mark_partner_session()
        self.assertEqual(
            p.partner_snapshot()["session_count"], 3,
        )


class TestFinal2Service(unittest.TestCase):
    """Service 验收"""

    def _svc(self):
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })
        return svc

    def test_service_all_apis(self):
        svc = self._svc()
        r = svc.companion_interaction_begin_session(
            goal="部署", mode="task",
        )
        self.assertTrue(r["ok"])
        svc.companion_interaction_update_stage("executing")
        svc.companion_interaction_add_pending("确认")
        flow = svc.companion_interaction_begin_tool_flow("检查")
        svc.companion_interaction_advance_tool_flow(
            flow["flow_id"], "plan",
        )
        svc.companion_interaction_finish_tool_flow(
            flow["flow_id"], "正常",
        )
        trace = svc.companion_interaction_trace_tool_flow(
            flow["flow_id"],
        )
        self.assertEqual(trace["flow"]["stage"], "response")
        svc.companion_interaction_set_partner_goal("协同")
        svc.companion_interaction_mark_latency("response", 100)
        report = svc.companion_interaction_latency_report()
        self.assertGreaterEqual(
            report["stages"]["response"]["count"], 1,
        )
        audit = svc.companion_interaction_audit()
        self.assertGreaterEqual(audit["stats"]["total"], 5)

    def test_service_compat_unchanged(self):
        svc = self._svc()
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
        self.assertEqual(
            svc.companion_meta_cognition_stats()["mode"],
            "rule_based",
        )


if __name__ == "__main__":
    unittest.main()
