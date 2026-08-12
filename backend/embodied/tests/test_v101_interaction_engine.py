"""
YHLZ Embodied AI V10.1 - 交互协议审计与引擎门面测试
(Interaction Audit & Protocol Engine)

覆盖:
    - 审计 (记录/查询/回放/统计/落盘)
    - 协议引擎门面 (会话/上下文/工具流/伙伴/延迟 聚合)
    - 停用错误帧
"""
import json
import os
import tempfile
import unittest

from backend.embodied.companion.interaction import (
    INTERACTION_ACTIONS,
    InteractionAudit,
    InteractionAuditError,
    InteractionProtocol,
)


class TestAudit(unittest.TestCase):
    """交互审计"""

    def test_record_basic(self):
        a = InteractionAudit()
        entry = a.record("state_change", "s1", "开始", {"ok": True})
        self.assertEqual(entry["action"], "state_change")
        self.assertEqual(entry["ref_id"], "s1")
        self.assertIn("audit_id", entry)
        self.assertIn("timestamp", entry)

    def test_invalid_action(self):
        a = InteractionAudit()
        with self.assertRaises(InteractionAuditError):
            a.record("bad")

    def test_query_by_action(self):
        a = InteractionAudit()
        a.record("tool_call", "f1")
        a.record("state_change", "s1")
        hits = a.query(action="tool_call")
        self.assertEqual(len(hits), 1)

    def test_query_limit(self):
        a = InteractionAudit()
        for i in range(10):
            a.record("tool_call", f"f{i}")
        self.assertEqual(len(a.query(limit=3)), 3)

    def test_replay_newest_first(self):
        a = InteractionAudit()
        a.record("tool_call", "f1")
        a.record("state_change", "s1")
        replay = a.replay()
        self.assertEqual(replay[0]["action"], "state_change")

    def test_stats(self):
        a = InteractionAudit()
        a.record("tool_call", "f1")
        a.record("tool_call", "f2")
        a.record("state_change", "s1")
        s = a.stats()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_action"]["tool_call"], 2)

    def test_max_records(self):
        a = InteractionAudit(max_records=3)
        for i in range(10):
            a.record("tool_call", f"f{i}")
        self.assertEqual(a.stats()["total"], 3)

    def test_clear(self):
        a = InteractionAudit()
        a.record("tool_call", "f1")
        self.assertEqual(a.clear(), 1)

    def test_save_to_file(self):
        a = InteractionAudit()
        a.record("state_change", "s1", "测试", {"ok": True})
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ia.jsonl")
            n = a.save_to_file(path)
            self.assertEqual(n, 1)
            with open(path, "r", encoding="utf-8") as f:
                data = json.loads(f.readline())
            self.assertEqual(data["action"], "state_change")

    def test_actions_list(self):
        self.assertIn("tool_call", INTERACTION_ACTIONS)
        self.assertIn("latency", INTERACTION_ACTIONS)
        self.assertEqual(len(INTERACTION_ACTIONS), 5)

    def test_invalid_max(self):
        with self.assertRaises(InteractionAuditError):
            InteractionAudit(max_records=0)


class TestProtocolEngine(unittest.TestCase):
    """协议引擎门面"""

    def setUp(self):
        self.p = InteractionProtocol(enabled=True)

    def test_begin_session(self):
        r = self.p.begin_session(goal="任务", mode="task")
        self.assertTrue(r["ok"])
        self.assertEqual(r["goal"], "任务")

    def test_update_stage(self):
        self.p.begin_session()
        r = self.p.update_stage("planning")
        self.assertTrue(r["ok"])
        self.assertEqual(r["to"], "planning")

    def test_set_context(self):
        r = self.p.set_context("请完成任务")
        self.assertTrue(r["ok"])
        self.assertEqual(self.p.conversation_snapshot()["context"],
                         "请完成任务")

    def test_filter_context(self):
        r = self.p.filter_context("请完成任务")
        self.assertEqual(r["topic"], "task")

    def test_pending_flow(self):
        self.p.add_pending("事项A")
        self.p.add_pending("事项B")
        self.p.resolve_pending("事项A")
        snap = self.p.conversation_snapshot()
        self.assertEqual(snap["pending"], ["事项B"])

    def test_tool_flow_end_to_end(self):
        flow = self.p.begin_tool_flow("查询")
        r = self.p.execute_tool(flow["flow_id"], "get",
                                lambda: {"x": 1})
        self.assertTrue(r["ok"])
        self.p.finish_tool_flow(flow["flow_id"], "完成")
        trace = self.p.trace_tool_flow(flow["flow_id"])
        self.assertEqual(trace["flow"]["tool"], "get")
        self.assertEqual(trace["flow"]["stage"], "response")

    def test_execute_tool_no_fn(self):
        flow = self.p.begin_tool_flow("t")
        r = self.p.execute_tool(flow["flow_id"], "tool", None, {})
        self.assertEqual(r["mode"], "error_frame")

    def test_tool_flow_records_latency(self):
        flow = self.p.begin_tool_flow("t")
        self.p.execute_tool(flow["flow_id"], "tool", lambda: 1)
        report = self.p.latency_report()
        self.assertGreaterEqual(
            report["stages"]["tool"]["count"], 1,
        )

    def test_partner_goal(self):
        r = self.p.set_partner_goal("共同完成")
        self.assertTrue(r["ok"])
        self.assertEqual(self.p.partner_snapshot()["goal"], "共同完成")

    def test_partner_relation(self):
        self.p.set_partner_relation("collaborate")
        self.assertEqual(
            self.p.partner_snapshot()["relation"], "collaborate",
        )

    def test_mark_partner_session(self):
        self.p.mark_partner_session()
        self.assertEqual(self.p.partner_snapshot()["session_count"], 1)

    def test_mark_latency(self):
        r = self.p.mark_latency("response", 200.5)
        self.assertTrue(r["ok"])
        report = self.p.latency_report()
        self.assertEqual(
            report["stages"]["response"]["avg_ms"], 200.5,
        )

    def test_audit_report(self):
        self.p.begin_session(goal="任务")
        self.p.begin_tool_flow("查询")
        report = self.p.audit_report()
        self.assertGreaterEqual(report["stats"]["total"], 2)

    def test_stats_structure(self):
        s = self.p.stats()
        for key in ("conversation", "context_filter", "tool_flow",
                    "partner", "latency", "audit"):
            self.assertIn(key, s)

    def test_clear(self):
        self.p.begin_session(goal="任务")
        self.p.begin_tool_flow("查询")
        self.p.clear()
        self.assertEqual(self.p.audit_report()["stats"]["total"], 0)


class TestProtocolDisabled(unittest.TestCase):
    """停用"""

    def test_disabled_begin(self):
        p = InteractionProtocol(enabled=False)
        r = p.begin_session()
        self.assertEqual(r["mode"], "error_frame")

    def test_disabled_filter(self):
        p = InteractionProtocol(enabled=False)
        r = p.filter_context("内容")
        self.assertEqual(r["mode"], "error_frame")

    def test_disabled_stats_ok(self):
        p = InteractionProtocol(enabled=False)
        s = p.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertFalse(s["enabled"])

    def test_disabled_latency(self):
        p = InteractionProtocol(enabled=False)
        r = p.mark_latency("tts", 1.0)
        self.assertEqual(r["mode"], "error_frame")


class TestProtocolConfig(unittest.TestCase):
    """配置驱动"""

    def test_config_context_len(self):
        p = InteractionProtocol(config={
            "companion_interaction_max_context_len": 10,
        })
        p.set_context("很长的上下文内容很长的上下文内容")
        self.assertLessEqual(
            len(p.conversation_snapshot()["context"]), 10,
        )

    def test_config_max_flows(self):
        p = InteractionProtocol(config={
            "companion_interaction_max_flows": 3,
        })
        for i in range(8):
            p.begin_tool_flow(f"t{i}")
        self.assertEqual(p.stats()["tool_flow"]["total_flows"], 3)

    def test_config_audit_max(self):
        p = InteractionProtocol(config={
            "companion_interaction_audit_max": 2,
        })
        for i in range(5):
            p.mark_latency("tts", 1.0)
        self.assertEqual(p.audit_report()["stats"]["total"], 2)


# ── 生成式: 审计动作矩阵 ───────────────────────────────────────
_AUDIT_ACTIONS = [
    ("state_change", "s1"),
    ("context_update", "s1"),
    ("tool_call", "f1"),
    ("partner_state", "partner"),
    ("latency", "tts"),
]


class TestGeneratedAuditActions(unittest.TestCase):
    """生成式: 审计动作"""
    pass


for _i, (_action, _ref) in enumerate(_AUDIT_ACTIONS):
    def _make(action=_action, ref=_ref):
        def test_case(self):
            a = InteractionAudit()
            entry = a.record(action, ref)
            self.assertEqual(entry["action"], action)
            self.assertEqual(entry["ref_id"], ref)
        test_case.__name__ = f"test_audit_action_{action}_{_i}"
        return test_case
    setattr(TestGeneratedAuditActions,
            f"test_audit_action_{_action}_{_i}", _make())


# ── 生成式: 引擎操作矩阵 ───────────────────────────────────────
_PROTO_OPS = [
    ("begin_session", True),
    ("update_stage", True),
    ("set_context", True),
    ("add_pending", True),
    ("begin_tool_flow", True),
    ("set_partner_goal", True),
    ("mark_partner_session", True),
    ("mark_latency", True),
]


class TestGeneratedProtoOps(unittest.TestCase):
    """生成式: 引擎操作"""
    pass


for _i, (_op, _exp) in enumerate(_PROTO_OPS):
    def _make(op=_op, exp=_exp):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            if op == "update_stage":
                p.begin_session()
                r = p.update_stage("planning")
            elif op == "set_context":
                r = p.set_context("内容")
            elif op == "add_pending":
                r = p.add_pending("事项")
            elif op == "begin_tool_flow":
                r = p.begin_tool_flow("意图")
            elif op == "set_partner_goal":
                r = p.set_partner_goal("目标")
            elif op == "mark_partner_session":
                r = p.mark_partner_session()
            elif op == "mark_latency":
                r = p.mark_latency("tts", 1.0)
            else:
                r = p.begin_session()
            self.assertEqual(r.get("ok"), exp)
        test_case.__name__ = f"test_op_{op}_{_i}"
        return test_case
    setattr(TestGeneratedProtoOps,
            f"test_op_{_op}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
