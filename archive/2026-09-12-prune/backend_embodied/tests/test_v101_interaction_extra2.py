"""
YHLZ Embodied AI V10.1 - 交互协议生成式测试 2 (V10.1 Interaction Extra2)

覆盖 (生成式):
    - 工具流程完整矩阵
    - 延迟报告矩阵
    - 审计统计矩阵
"""
import unittest

from backend.embodied.companion.interaction import InteractionProtocol
from backend.embodied.companion.interaction.interaction_audit import (
    InteractionAudit,
)
from backend.embodied.companion.interaction.latency_tracker import (
    InteractionLatencyTracker,
)
from backend.embodied.companion.interaction.tool_flow import (
    ToolFlowRecorder,
)


# ── 生成式: 工具流程完整生命周期矩阵 ───────────────────────────
_TOOL_LIFE = [
    # (名称, 阶段序列 (除 understand/response), 期望最终阶段)
    ("direct_finish", [], "response"),
    ("plan_then_finish", ["plan"], "response"),
    ("full_chain", ["plan", "tool", "result", "reflect"],
     "response"),
    ("tool_only", ["tool"], "response"),
    ("reflect_only", ["reflect"], "response"),
]


class TestGeneratedToolLife(unittest.TestCase):
    """生成式: 工具生命周期"""
    pass


for _i, (_name, _stages, _exp) in enumerate(_TOOL_LIFE):
    def _make(name=_name, stages=_stages, exp=_exp):
        def test_case(self):
            tfr = ToolFlowRecorder()
            flow = tfr.begin("意图")
            for s in stages:
                tfr.advance(flow["flow_id"], s, s)
            tfr.finish(flow["flow_id"], "响应")
            trace = tfr.trace(flow["flow_id"])
            self.assertEqual(trace["flow"]["stage"], exp)
        test_case.__name__ = f"test_tool_life_{name}_{_i}"
        return test_case
    setattr(TestGeneratedToolLife,
            f"test_tool_life_{_name}_{_i}", _make())


# ── 生成式: 工具执行成功/失败矩阵 ──────────────────────────────
_TOOL_RES = [
    # (名称, 回调, 期望 ok)
    ("ok_int", lambda: 1, True),
    ("ok_str", lambda: "a", True),
    ("ok_dict", lambda: {"k": "v"}, True),
    ("ok_list", lambda: [1, 2], True),
    ("fail_type", lambda: int("x"), False),
    ("fail_div", lambda: 1 / 0, False),
    ("fail_key", lambda: {}["nope"], False),
]


class TestGeneratedToolRes(unittest.TestCase):
    """生成式: 工具执行结果"""
    pass


for _i, (_name, _fn, _exp) in enumerate(_TOOL_RES):
    def _make(name=_name, fn=_fn, exp=_exp):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            flow = p.begin_tool_flow("t")
            r = p.execute_tool(flow["flow_id"], "tool", fn, {})
            self.assertEqual(r["ok"], exp)
        test_case.__name__ = f"test_tool_res_{name}_{_i}"
        return test_case
    setattr(TestGeneratedToolRes,
            f"test_tool_res_{_name}_{_i}", _make())


# ── 生成式: 延迟多阶段矩阵 ─────────────────────────────────────
_LAT_MULTI = [
    # (名称, 阶段-延迟对, 期望样本总数)
    ("one_stage", [("tts", 10.0)], 1),
    ("two_stages", [("tts", 10.0), ("play", 5.0)], 2),
    ("repeat_stage", [("tts", 1.0), ("tts", 2.0)], 2),
    ("all_stages", [("user_input", 1.0), ("understand", 2.0),
                    ("context", 3.0), ("tool", 4.0),
                    ("response", 5.0), ("tts", 6.0),
                    ("play", 7.0)], 7),
    ("many_marks", [("response", float(i)) for i in range(20)],
     20),
]


class TestGeneratedLatMulti(unittest.TestCase):
    """生成式: 延迟多阶段"""
    pass


for _i, (_name, _marks, _exp) in enumerate(_LAT_MULTI):
    def _make(name=_name, marks=_marks, exp=_exp):
        def test_case(self):
            t = InteractionLatencyTracker()
            for stage, ms in marks:
                t.mark(stage, ms)
            r = t.report()
            self.assertEqual(r["total_samples"], exp)
        test_case.__name__ = f"test_lat_multi_{name}_{_i}"
        return test_case
    setattr(TestGeneratedLatMulti,
            f"test_lat_multi_{_name}_{_i}", _make())


# ── 生成式: 审计混合动作矩阵 ───────────────────────────────────
_AUDIT_MIX = [
    # (名称, 动作序列, 期望 total, 期望 tool_call 数)
    ("one", ["tool_call"], 1, 1),
    ("mixed", ["tool_call", "state_change", "latency"], 3, 1),
    ("many_tools", ["tool_call", "tool_call", "tool_call"], 3, 3),
    ("no_tools", ["state_change", "context_update"], 2, 0),
    ("all_types", ["state_change", "context_update", "tool_call",
                   "partner_state", "latency"], 5, 1),
]


class TestGeneratedAuditMix(unittest.TestCase):
    """生成式: 审计混合动作"""
    pass


for _i, (_name, _actions, _exp_total, _exp_tool) in \
        enumerate(_AUDIT_MIX):
    def _make(name=_name, actions=_actions, et=_exp_total,
              etool=_exp_tool):
        def test_case(self):
            a = InteractionAudit()
            for act in actions:
                a.record(act, "ref")
            s = a.stats()
            self.assertEqual(s["total"], et)
            self.assertEqual(
                s["by_action"].get("tool_call", 0), etool,
            )
        test_case.__name__ = f"test_audit_mix_{name}_{_i}"
        return test_case
    setattr(TestGeneratedAuditMix,
            f"test_audit_mix_{_name}_{_i}", _make())


# ── 生成式: 协议引擎组合操作矩阵 ───────────────────────────────
_COMBO_OPS = [
    # (名称, 操作数, 期望审计增长)
    ("sessions", "session", 1),
    ("stages", "stage", 2),
    ("tools", "tool", 2),
    ("partners", "partner", 1),
    ("latencies", "latency", 1),
    ("mixed_ops", "mix", 5),
]


class TestGeneratedCombo(unittest.TestCase):
    """生成式: 组合操作"""
    pass


for _i, (_name, _op, _exp_growth) in enumerate(_COMBO_OPS):
    def _make(name=_name, op=_op, exp=_exp_growth):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            before = p.audit_report()["stats"]["total"]
            if op == "session":
                p.begin_session(goal="任务")
            elif op == "stage":
                p.begin_session()
                p.update_stage("planning")
            elif op == "tool":
                flow = p.begin_tool_flow("t")
                p.finish_tool_flow(flow["flow_id"], "r")
            elif op == "partner":
                p.set_partner_goal("目标")
            elif op == "latency":
                p.mark_latency("tts", 1.0)
            elif op == "mix":
                p.begin_session(goal="任务")
                p.set_context("内容")
                flow = p.begin_tool_flow("t")
                p.finish_tool_flow(flow["flow_id"], "r")
                p.mark_latency("tts", 1.0)
            after = p.audit_report()["stats"]["total"]
            self.assertEqual(after - before, exp)
        test_case.__name__ = f"test_combo_{name}_{_i}"
        return test_case
    setattr(TestGeneratedCombo,
            f"test_combo_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
