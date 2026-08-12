"""
YHLZ Embodied AI V10.1 - 交互协议生成式测试 3 (V10.1 Interaction Extra3)

覆盖 (生成式):
    - 会话状态机完整矩阵
    - 伙伴状态矩阵
    - 协议统计字段矩阵
"""
import unittest

from backend.embodied.companion.interaction import InteractionProtocol
from backend.embodied.companion.interaction.conversation_state import (
    ConversationStateManager,
    TASK_STAGES,
)
from backend.embodied.companion.interaction.partner_state import (
    PartnerInteractionState,
    TASK_RELATIONS,
)


# ── 生成式: 会话状态机完整流转矩阵 ─────────────────────────────
_STATE_MACHINE = [
    # (名称, 阶段序列, 期望最终阶段)
    ("init_to_done", ["understand", "planning", "executing",
                      "reviewing", "done"], "done"),
    ("abort_anytime", ["understand", "aborted"], "aborted"),
    ("planning_only", ["planning"], "planning"),
    ("executing_abort", ["executing", "aborted"], "aborted"),
    ("review_done", ["reviewing", "done"], "done"),
    ("understand_plan", ["understand", "planning"], "planning"),
]


class TestGeneratedStateMachine(unittest.TestCase):
    """生成式: 状态机流转"""
    pass


for _i, (_name, _seq, _exp) in enumerate(_STATE_MACHINE):
    def _make(name=_name, seq=_seq, exp=_exp):
        def test_case(self):
            csm = ConversationStateManager()
            csm.begin()
            for s in seq:
                csm.update_stage(s)
            self.assertEqual(csm.snapshot()["stage"], exp)
        test_case.__name__ = f"test_sm_{name}_{_i}"
        return test_case
    setattr(TestGeneratedStateMachine,
            f"test_sm_{_name}_{_i}", _make())


# ── 生成式: 全部任务阶段可达性矩阵 ─────────────────────────────
_STAGE_ALL = [
    ("s_init", "init"),
    ("s_understand", "understand"),
    ("s_planning", "planning"),
    ("s_executing", "executing"),
    ("s_reviewing", "reviewing"),
    ("s_done", "done"),
    ("s_aborted", "aborted"),
]


class TestGeneratedStageAll(unittest.TestCase):
    """生成式: 全部阶段可达"""
    pass


for _i, (_name, _stage) in enumerate(_STAGE_ALL):
    def _make(name=_name, stage=_stage):
        def test_case(self):
            csm = ConversationStateManager()
            csm.begin()
            r = csm.update_stage(stage)
            self.assertTrue(r["ok"])
            self.assertEqual(csm.snapshot()["stage"], stage)
        test_case.__name__ = f"test_stage_all_{name}_{_i}"
        return test_case
    setattr(TestGeneratedStageAll,
            f"test_stage_all_{_name}_{_i}", _make())


# ── 生成式: 伙伴状态矩阵 ───────────────────────────────────────
_PARTNER_MATRIX = [
    # (名称, 目标, 关系, 会话数, 期望快照)
    ("full_collab", "项目", "collaborate", 3, "collaborate"),
    ("no_goal", "", "none", 0, "none"),
    ("guide_mode", "辅导", "guide", 1, "guide"),
    ("follow_mode", "跟随", "follow", 2, "follow"),
    ("review_mode", "复盘", "review", 5, "review"),
]


class TestGeneratedPartnerMatrix(unittest.TestCase):
    """生成式: 伙伴状态"""
    pass


for _i, (_name, _goal, _rel, _sessions, _exp) in \
        enumerate(_PARTNER_MATRIX):
    def _make(name=_name, goal=_goal, rel=_rel, sessions=_sessions,
              exp=_exp):
        def test_case(self):
            p = PartnerInteractionState()
            p.set_goal(goal)
            p.set_relation(rel)
            for _ in range(sessions):
                p.mark_session()
            snap = p.snapshot()
            self.assertEqual(snap["relation"], exp)
            self.assertEqual(snap["session_count"], sessions)
        test_case.__name__ = f"test_pm_{name}_{_i}"
        return test_case
    setattr(TestGeneratedPartnerMatrix,
            f"test_pm_{_name}_{_i}", _make())


# ── 生成式: 协议统计字段矩阵 ───────────────────────────────────
_STATS_FIELDS = [
    # (名称, 操作, 期望非零字段)
    ("session_op", "session", "conversation"),
    ("tool_op", "tool", "tool_flow"),
    ("latency_op", "latency", "latency"),
    ("partner_op", "partner", "partner"),
    ("audit_op", "audit", "audit"),
]


class TestGeneratedStatsFields(unittest.TestCase):
    """生成式: 统计字段"""
    pass


for _i, (_name, _op, _field) in enumerate(_STATS_FIELDS):
    def _make(name=_name, op=_op, field=_field):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            if op == "session":
                p.begin_session(goal="任务")
            elif op == "tool":
                flow = p.begin_tool_flow("t")
                p.finish_tool_flow(flow["flow_id"], "r")
            elif op == "latency":
                p.mark_latency("tts", 1.0)
            elif op == "partner":
                p.set_partner_goal("目标")
            elif op == "audit":
                p.begin_session()
            s = p.stats()
            self.assertIn(field, s)
            self.assertEqual(s["mode"], "rule_based")
        test_case.__name__ = f"test_sf_{name}_{_i}"
        return test_case
    setattr(TestGeneratedStatsFields,
            f"test_sf_{_name}_{_i}", _make())


# ── 生成式: 协议审计追踪矩阵 ───────────────────────────────────
_TRACE_CASES = [
    # (名称, 会话+工具+伙伴+延迟, 期望审计分类存在)
    ("all_actions", "all", {"state_change", "tool_call",
                            "partner_state", "latency"}),
    ("session_tool", "st", {"state_change", "tool_call"}),
    ("partner_latency", "pl", {"partner_state", "latency"}),
    ("session_only", "s", {"state_change"}),
]


class TestGeneratedTrace(unittest.TestCase):
    """生成式: 审计分类"""
    pass


for _i, (_name, _op, _expected) in enumerate(_TRACE_CASES):
    def _make(name=_name, op=_op, expected=_expected):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            if op in ("all", "st", "s"):
                p.begin_session(goal="任务")
            if op in ("all", "st"):
                flow = p.begin_tool_flow("t")
                p.finish_tool_flow(flow["flow_id"], "r")
            if op in ("all", "pl"):
                p.set_partner_goal("目标")
                p.mark_latency("tts", 1.0)
            elif op == "pl":
                p.set_partner_goal("目标")
                p.mark_latency("tts", 1.0)
            report = p.audit_report()
            by = report["stats"]["by_action"]
            for action in expected:
                self.assertGreaterEqual(by.get(action, 0), 1)
        test_case.__name__ = f"test_trace_{name}_{_i}"
        return test_case
    setattr(TestGeneratedTrace,
            f"test_trace_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
