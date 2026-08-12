"""
YHLZ Embodied AI V10.1 - 交互协议生成式测试 1 (V10.1 Interaction Extra)

覆盖 (生成式):
    - 会话状态矩阵
    - 伙伴关系矩阵
    - 上下文筛选矩阵
"""
import unittest

from backend.embodied.companion.interaction import InteractionProtocol
from backend.embodied.companion.interaction.context_filter import (
    InteractionContextFilter,
)
from backend.embodied.companion.interaction.conversation_state import (
    ConversationStateManager,
)
from backend.embodied.companion.interaction.partner_state import (
    PartnerInteractionState,
)


# ── 生成式: 会话-伙伴联动矩阵 ──────────────────────────────────
_COLLAB_CASES = [
    # (名称, 目标, 模式, 阶段, 关系, 期望 ok)
    ("task_full", "项目", "task", "executing", "collaborate", True),
    ("casual", "闲聊", "casual", "init", "none", True),
    ("guide", "辅导", "task", "planning", "guide", True),
    ("follow", "跟随", "casual", "understand", "follow", True),
    ("review", "复盘", "review", "reviewing", "review", True),
]


class TestGeneratedCollaboration(unittest.TestCase):
    """生成式: 会话-伙伴联动"""
    pass


for _i, (_name, _goal, _mode, _stage, _rel, _exp) in \
        enumerate(_COLLAB_CASES):
    def _make(name=_name, goal=_goal, mode=_mode, stage=_stage,
              rel=_rel, exp=_exp):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            r1 = p.begin_session(goal=goal, mode=mode)
            r2 = p.update_stage(stage)
            r3 = p.set_partner_relation(rel)
            r4 = p.set_partner_goal(goal)
            self.assertTrue(r1["ok"])
            self.assertTrue(r2["ok"])
            self.assertTrue(r3["ok"])
            self.assertTrue(r4["ok"])
            self.assertEqual(p.conversation_snapshot()["stage"],
                             stage)
            self.assertEqual(p.partner_snapshot()["relation"], rel)
        test_case.__name__ = f"test_collab_{name}_{_i}"
        return test_case
    setattr(TestGeneratedCollaboration,
            f"test_collab_{_name}_{_i}", _make())


# ── 生成式: 伙伴关系完整矩阵 ───────────────────────────────────
_REL2_CASES = [
    ("none", "none"),
    ("collaborate", "collaborate"),
    ("guide", "guide"),
    ("follow", "follow"),
    ("review", "review"),
]


class TestGeneratedRelations2(unittest.TestCase):
    """生成式: 伙伴关系完整"""
    pass


for _i, (_name, _rel) in enumerate(_REL2_CASES):
    def _make(name=_name, rel=_rel):
        def test_case(self):
            p = PartnerInteractionState()
            r = p.set_relation(rel)
            self.assertTrue(r["ok"])
            self.assertEqual(r["to"], rel)
        test_case.__name__ = f"test_rel2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedRelations2,
            f"test_rel2_{_name}_{_i}", _make())


# ── 生成式: 会话上下文筛选矩阵 ─────────────────────────────────
_CTX_CASES = [
    # (名称, 文本, 期望主题)
    ("task_ctx", "请完成部署任务", "task"),
    ("plan_ctx", "帮我规划一下方案", "plan"),
    ("chat_ctx", "随便聊聊", "chat"),
    ("problem_ctx", "这边报错了", "problem"),
    ("memory_ctx", "你还记得吗", "memory"),
    ("general_ctx", "今天天气不错", "general"),
    ("mixed_ctx", "完成任务并规划方案", "task"),
]


class TestGeneratedContext(unittest.TestCase):
    """生成式: 上下文主题"""
    pass


for _i, (_name, _text, _exp) in enumerate(_CTX_CASES):
    def _make(name=_name, text=_text, exp=_exp):
        def test_case(self):
            f = InteractionContextFilter()
            r = f.filter(text)
            self.assertEqual(r["topic"], exp)
        test_case.__name__ = f"test_ctx_{name}_{_i}"
        return test_case
    setattr(TestGeneratedContext,
            f"test_ctx_{_name}_{_i}", _make())


# ── 生成式: 会话快照一致性矩阵 ─────────────────────────────────
_SNAP_CASES = [
    # (名称, 操作序列, 期望阶段)
    ("no_op", [], "init"),
    ("stage_only", [("stage", "planning")], "planning"),
    ("stage_twice", [("stage", "understand"), ("stage", "done")],
     "done"),
    ("stage_abort", [("stage", "executing"), ("stage", "aborted")],
     "aborted"),
    ("context_only", [("ctx", "内容")], "init"),
]


class TestGeneratedSnapshot(unittest.TestCase):
    """生成式: 快照一致性"""
    pass


for _i, (_name, _ops, _exp) in enumerate(_SNAP_CASES):
    def _make(name=_name, ops=_ops, exp=_exp):
        def test_case(self):
            csm = ConversationStateManager()
            csm.begin()
            for op, arg in ops:
                if op == "stage":
                    csm.update_stage(arg)
                elif op == "ctx":
                    csm.set_context(arg)
            self.assertEqual(csm.snapshot()["stage"], exp)
        test_case.__name__ = f"test_snap_{name}_{_i}"
        return test_case
    setattr(TestGeneratedSnapshot,
            f"test_snap_{_name}_{_i}", _make())


# ── 生成式: 协议引擎全流程稳定性矩阵 ───────────────────────────
_PROTO_STABLE = [
    # (名称, 目标, 模式)
    ("stable_a", "任务A", "task"),
    ("stable_b", "聊天", "casual"),
    ("stable_c", "规划B", "planning"),
]


class TestGeneratedProtoStable(unittest.TestCase):
    """生成式: 协议稳定性"""
    pass


for _i, (_name, _goal, _mode) in enumerate(_PROTO_STABLE):
    def _make(name=_name, goal=_goal, mode=_mode):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            r = p.begin_session(goal=goal, mode=mode)
            self.assertTrue(r["ok"])
            self.assertEqual(
                p.conversation_snapshot()["goal"], goal,
            )
        test_case.__name__ = f"test_stable_{name}_{_i}"
        return test_case
    setattr(TestGeneratedProtoStable,
            f"test_stable_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
