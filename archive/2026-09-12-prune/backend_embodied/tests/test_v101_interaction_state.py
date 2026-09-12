"""
YHLZ Embodied AI V10.1 - 会话状态管理器测试 (Conversation State)

覆盖:
    - 会话生命周期 (begin/reset)
    - 任务阶段更新
    - 交流模式更新
    - 上下文裁剪 (有界保存)
    - 未完成事项 (有界)
    - 停用错误帧 / 参数校验
"""
import unittest

from backend.embodied.companion.interaction.conversation_state import (
    COMMUNICATION_MODES,
    ConversationStateError,
    ConversationStateManager,
    TASK_STAGES,
)


class TestConversationBegin(unittest.TestCase):
    """会话生命周期"""

    def setUp(self):
        self.csm = ConversationStateManager()

    def test_begin(self):
        r = self.csm.begin(goal="完成项目", mode="task")
        self.assertTrue(r["ok"])
        self.assertEqual(r["goal"], "完成项目")
        self.assertEqual(r["mode_name"], "task")
        self.assertEqual(r["stage"], "init")

    def test_begin_default_mode(self):
        r = self.csm.begin()
        self.assertTrue(r["ok"])
        self.assertEqual(r["mode_name"], "casual")

    def test_reset(self):
        self.csm.begin(goal="任务")
        self.csm.update_stage("executing")
        self.csm.add_pending("事项")
        r = self.csm.reset()
        self.assertTrue(r["reset"])
        snap = self.csm.snapshot()
        self.assertEqual(snap["goal"], "")
        self.assertEqual(snap["stage"], "init")
        self.assertEqual(snap["pending"], [])

    def test_begin_resets_state(self):
        self.csm.begin(goal="A")
        self.csm.update_stage("done")
        r = self.csm.begin(goal="B")
        self.assertEqual(r["stage"], "init")
        self.assertEqual(self.csm.snapshot()["stage"], "init")

    def test_snapshot_structure(self):
        r = self.csm.snapshot()
        for key in ("goal", "stage", "mode_name", "pending",
                    "context", "started_at", "updated_at"):
            self.assertIn(key, r)

    def test_begin_invalid_mode(self):
        with self.assertRaises(ConversationStateError):
            self.csm.begin(mode="bad_mode")

    def test_stages_enum(self):
        self.assertIn("planning", TASK_STAGES)
        self.assertIn("done", TASK_STAGES)
        self.assertEqual(len(TASK_STAGES), 7)

    def test_modes_enum(self):
        self.assertIn("casual", COMMUNICATION_MODES)
        self.assertIn("task", COMMUNICATION_MODES)


class TestConversationStage(unittest.TestCase):
    """任务阶段"""

    def setUp(self):
        self.csm = ConversationStateManager()

    def test_update_stage(self):
        self.csm.begin()
        r = self.csm.update_stage("planning")
        self.assertTrue(r["ok"])
        self.assertEqual(r["from"], "init")
        self.assertEqual(r["to"], "planning")

    def test_stage_full_cycle(self):
        self.csm.begin()
        for stage in ("understand", "planning", "executing",
                      "reviewing", "done"):
            r = self.csm.update_stage(stage)
            self.assertTrue(r["ok"])
        self.assertEqual(
            self.csm.snapshot()["stage"], "done",
        )

    def test_invalid_stage(self):
        with self.assertRaises(ConversationStateError):
            self.csm.update_stage("nope")

    def test_aborted_stage(self):
        self.csm.begin()
        self.csm.update_stage("aborted")
        self.assertEqual(
            self.csm.snapshot()["stage"], "aborted",
        )


class TestConversationContext(unittest.TestCase):
    """上下文管理"""

    def setUp(self):
        self.csm = ConversationStateManager(max_context_len=20)

    def test_set_context(self):
        r = self.csm.set_context("当前处理任务A")
        self.assertTrue(r["ok"])
        self.assertEqual(
            self.csm.snapshot()["context"], "当前处理任务A",
        )

    def test_context_clipped(self):
        r = self.csm.set_context("很长的上下文内容" * 10)
        self.assertTrue(r["clipped"])
        self.assertLessEqual(
            len(self.csm.snapshot()["context"]), 20,
        )

    def test_context_not_unlimited(self):
        self.csm.set_context("x" * 1000)
        self.assertLessEqual(
            len(self.csm.snapshot()["context"]), 20,
        )

    def test_context_short_no_clip(self):
        r = self.csm.set_context("短")
        self.assertFalse(r["clipped"])

    def test_context_empty(self):
        r = self.csm.set_context("")
        self.assertTrue(r["ok"])
        self.assertEqual(r["context_len"], 0)

    def test_context_len_report(self):
        r = self.csm.set_context("abcde")
        self.assertEqual(r["context_len"], 5)


class TestConversationPending(unittest.TestCase):
    """未完成事项"""

    def setUp(self):
        self.csm = ConversationStateManager(max_pending=3)

    def test_add_pending(self):
        r = self.csm.add_pending("确认方案")
        self.assertTrue(r["ok"])
        self.assertEqual(r["pending_count"], 1)

    def test_add_multiple(self):
        self.csm.add_pending("A")
        self.csm.add_pending("B")
        self.assertEqual(
            self.csm.snapshot()["pending"], ["A", "B"],
        )

    def test_pending_bounded(self):
        for i in range(10):
            self.csm.add_pending(f"事项{i}")
        self.assertEqual(
            len(self.csm.snapshot()["pending"]), 3,
        )

    def test_pending_keeps_latest(self):
        for i in range(5):
            self.csm.add_pending(f"事项{i}")
        self.assertEqual(
            self.csm.snapshot()["pending"],
            ["事项2", "事项3", "事项4"],
        )

    def test_resolve_pending(self):
        self.csm.add_pending("A")
        self.csm.add_pending("B")
        ok = self.csm.resolve_pending("A")
        self.assertTrue(ok)
        self.assertEqual(
            self.csm.snapshot()["pending"], ["B"],
        )

    def test_resolve_missing(self):
        ok = self.csm.resolve_pending("不存在")
        self.assertFalse(ok)

    def test_empty_pending_raises(self):
        with self.assertRaises(ConversationStateError):
            self.csm.add_pending("   ")

    def test_whitespace_pending_raises(self):
        with self.assertRaises(ConversationStateError):
            self.csm.add_pending("")


class TestConversationDisabled(unittest.TestCase):
    """停用与统计"""

    def test_disabled_begin(self):
        csm = ConversationStateManager(enabled=False)
        r = csm.begin()
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_disabled_update(self):
        csm = ConversationStateManager(enabled=False)
        r = csm.update_stage("planning")
        self.assertEqual(r["mode"], "error_frame")

    def test_disabled_context(self):
        csm = ConversationStateManager(enabled=False)
        r = csm.set_context("x")
        self.assertEqual(r["mode"], "error_frame")

    def test_stats(self):
        csm = ConversationStateManager()
        s = csm.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertEqual(s["max_context_len"], 200)

    def test_stats_active(self):
        csm = ConversationStateManager()
        csm.begin(goal="任务")
        self.assertTrue(csm.stats()["active"])

    def test_clear(self):
        csm = ConversationStateManager()
        csm.add_pending("A")
        csm.add_pending("B")
        self.assertEqual(csm.clear(), 2)
        self.assertEqual(csm.snapshot()["pending"], [])

    def test_invalid_max_context(self):
        with self.assertRaises(ConversationStateError):
            ConversationStateManager(max_context_len=0)

    def test_invalid_max_pending(self):
        with self.assertRaises(ConversationStateError):
            ConversationStateManager(max_pending=0)

    def test_enabled_flag_in_snapshot(self):
        csm = ConversationStateManager()
        self.assertTrue(csm.snapshot()["enabled"])


# ── 生成式: 阶段流转矩阵 ───────────────────────────────────────
_STAGE_CASES = [
    ("understand", "understand"),
    ("planning", "planning"),
    ("executing", "executing"),
    ("reviewing", "reviewing"),
    ("done", "done"),
    ("aborted", "aborted"),
]


class TestGeneratedStages(unittest.TestCase):
    """生成式: 阶段流转"""
    pass


for _i, (_name, _stage) in enumerate(_STAGE_CASES):
    def _make(name=_name, stage=_stage):
        def test_case(self):
            csm = ConversationStateManager()
            csm.begin()
            r = csm.update_stage(stage)
            self.assertTrue(r["ok"])
            self.assertEqual(csm.snapshot()["stage"], stage)
        test_case.__name__ = f"test_stage_{name}_{_i}"
        return test_case
    setattr(TestGeneratedStages,
            f"test_stage_{_name}_{_i}", _make())


# ── 生成式: 上下文裁剪矩阵 ─────────────────────────────────────
_CLIP_CASES = [
    ("short", "abc", 20, "abc"),
    ("exact", "a" * 20, 20, "a" * 20),
    ("long", "x" * 50, 20, None),  # 长度受裁剪
    ("empty", "", 20, ""),
    ("tiny", "你好", 3, "你好"),
]


class TestGeneratedClip(unittest.TestCase):
    """生成式: 上下文裁剪"""
    pass


for _i, (_name, _text, _max, _exp) in enumerate(_CLIP_CASES):
    def _make(name=_name, text=_text, maxl=_max, exp=_exp):
        def test_case(self):
            csm = ConversationStateManager(max_context_len=maxl)
            csm.set_context(text)
            ctx = csm.snapshot()["context"]
            if exp is not None:
                self.assertEqual(ctx, exp)
            else:
                self.assertLessEqual(len(ctx), maxl)
        test_case.__name__ = f"test_clip_{name}_{_i}"
        return test_case
    setattr(TestGeneratedClip,
            f"test_clip_{_name}_{_i}", _make())


# ── 生成式: 未完成事项矩阵 ─────────────────────────────────────
_PENDING_CASES = [
    ("one", ["A"], 10, ["A"]),
    ("two", ["A", "B"], 10, ["A", "B"]),
    ("over_cap", ["A", "B", "C", "D", "E"], 3,
     ["C", "D", "E"]),
    ("none", [], 5, []),
    ("many", [f"i{i}" for i in range(20)], 5,
     ["i15", "i16", "i17", "i18", "i19"]),
]


class TestGeneratedPending(unittest.TestCase):
    """生成式: 未完成事项"""
    pass


for _i, (_name, _items, _cap, _exp) in enumerate(_PENDING_CASES):
    def _make(name=_name, items=_items, cap=_cap, exp=_exp):
        def test_case(self):
            csm = ConversationStateManager(max_pending=cap)
            for it in items:
                csm.add_pending(it)
            self.assertEqual(csm.snapshot()["pending"], exp)
        test_case.__name__ = f"test_pending_{name}_{_i}"
        return test_case
    setattr(TestGeneratedPending,
            f"test_pending_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
