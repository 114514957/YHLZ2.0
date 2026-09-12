"""
YHLZ Embodied AI V10.1 - 伙伴交互状态测试 (Partner Interaction State)

覆盖:
    - 协作目标 / 任务关系 / 交流模式
    - 会话计数
    - 交互状态 ≠ 人格 (不修改人格/身份)
    - 停用错误帧
"""
import unittest

from backend.embodied.companion.interaction.partner_state import (
    PartnerInteractionState,
    PartnerStateError,
    TASK_RELATIONS,
)


class TestPartnerState(unittest.TestCase):
    """伙伴交互状态"""

    def setUp(self):
        self.p = PartnerInteractionState()

    def test_initial(self):
        snap = self.p.snapshot()
        self.assertEqual(snap["goal"], "")
        self.assertEqual(snap["relation"], "none")
        self.assertEqual(snap["mode_name"], "casual")

    def test_set_goal(self):
        r = self.p.set_goal("共同完成项目")
        self.assertTrue(r["ok"])
        self.assertEqual(self.p.snapshot()["goal"], "共同完成项目")

    def test_set_relation(self):
        r = self.p.set_relation("collaborate")
        self.assertTrue(r["ok"])
        self.assertEqual(r["to"], "collaborate")
        self.assertEqual(
            self.p.snapshot()["relation"], "collaborate",
        )

    def test_relation_transition(self):
        self.p.set_relation("collaborate")
        r = self.p.set_relation("review")
        self.assertEqual(r["from"], "collaborate")
        self.assertEqual(r["to"], "review")

    def test_set_mode(self):
        r = self.p.set_mode("task")
        self.assertTrue(r["ok"])
        self.assertEqual(self.p.snapshot()["mode_name"], "task")

    def test_set_mode_default(self):
        r = self.p.set_mode("")
        self.assertTrue(r["ok"])
        self.assertEqual(self.p.snapshot()["mode_name"], "casual")

    def test_mark_session(self):
        r = self.p.mark_session()
        self.assertTrue(r["ok"])
        self.assertEqual(r["session_count"], 1)
        self.assertEqual(self.p.snapshot()["session_count"], 1)

    def test_mark_sessions_count(self):
        for _ in range(5):
            self.p.mark_session()
        self.assertEqual(self.p.snapshot()["session_count"], 5)

    def test_reset(self):
        self.p.set_goal("任务")
        self.p.set_relation("collaborate")
        self.p.mark_session()
        r = self.p.reset()
        self.assertTrue(r["reset"])
        snap = self.p.snapshot()
        self.assertEqual(snap["goal"], "")
        self.assertEqual(snap["relation"], "none")

    def test_relation_enum(self):
        self.assertIn("collaborate", TASK_RELATIONS)
        self.assertIn("none", TASK_RELATIONS)
        self.assertEqual(len(TASK_RELATIONS), 5)

    def test_invalid_relation(self):
        with self.assertRaises(PartnerStateError):
            self.p.set_relation("bad")

    def test_snapshot_structure(self):
        snap = self.p.snapshot()
        for key in ("goal", "relation", "mode",
                    "session_count", "last_activity"):
            self.assertIn(key, snap)


class TestPartnerSeparation(unittest.TestCase):
    """交互状态与人格分离 (核心原则)"""

    def setUp(self):
        self.p = PartnerInteractionState()

    def test_state_does_not_change_personality(self):
        # 交互状态操作不产生人格字段
        self.p.set_goal("任务")
        self.p.set_relation("collaborate")
        self.p.mark_session()
        snap = self.p.snapshot()
        self.assertNotIn("personality", snap)
        self.assertNotIn("traits", snap)
        self.assertNotIn("warmth", snap)

    def test_state_is_collaboration_not_emotion(self):
        self.p.set_mode("task")
        snap = self.p.snapshot()
        # 交互状态只描述协作, 不包含情感表演字段
        for key in ("mood", "feeling", "emotion_template"):
            self.assertNotIn(key, snap)


class TestPartnerDisabled(unittest.TestCase):
    """停用"""

    def test_disabled_set_goal(self):
        p = PartnerInteractionState(enabled=False)
        r = p.set_goal("任务")
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_disabled_snapshot_still_ok(self):
        p = PartnerInteractionState(enabled=False)
        snap = p.snapshot()
        self.assertEqual(snap["mode"], "rule_based")
        self.assertFalse(snap["enabled"])
        self.assertEqual(snap["relation"], "none")

    def test_stats(self):
        p = PartnerInteractionState()
        s = p.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertEqual(s["session_count"], 0)

    def test_stats_active(self):
        p = PartnerInteractionState()
        p.set_goal("任务")
        self.assertTrue(p.stats()["active"])

    def test_clear(self):
        p = PartnerInteractionState()
        p.mark_session()
        p.mark_session()
        self.assertEqual(p.clear(), 2)


# ── 生成式: 任务关系矩阵 ───────────────────────────────────────
_RELATION_CASES = [
    ("none", "none"),
    ("collaborate", "collaborate"),
    ("guide", "guide"),
    ("follow", "follow"),
    ("review", "review"),
]


class TestGeneratedRelations(unittest.TestCase):
    """生成式: 任务关系"""
    pass


for _i, (_name, _rel) in enumerate(_RELATION_CASES):
    def _make(name=_name, rel=_rel):
        def test_case(self):
            p = PartnerInteractionState()
            r = p.set_relation(rel)
            self.assertTrue(r["ok"])
            self.assertEqual(p.snapshot()["relation"], rel)
        test_case.__name__ = f"test_relation_{name}_{_i}"
        return test_case
    setattr(TestGeneratedRelations,
            f"test_relation_{_name}_{_i}", _make())


# ── 生成式: 会话计数矩阵 ───────────────────────────────────────
_SESSION_CASES = [
    ("one", 1, 1),
    ("three", 3, 3),
    ("ten", 10, 10),
    ("zero", 0, 0),
    ("fifty", 50, 50),
]


class TestGeneratedSessions(unittest.TestCase):
    """生成式: 会话计数"""
    pass


for _i, (_name, _n, _exp) in enumerate(_SESSION_CASES):
    def _make(name=_name, n=_n, exp=_exp):
        def test_case(self):
            p = PartnerInteractionState()
            for _ in range(n):
                p.mark_session()
            self.assertEqual(
                p.snapshot()["session_count"], exp,
            )
        test_case.__name__ = f"test_session_{name}_{_i}"
        return test_case
    setattr(TestGeneratedSessions,
            f"test_session_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
