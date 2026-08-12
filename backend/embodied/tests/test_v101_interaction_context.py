"""
YHLZ Embodied AI V10.1 - 上下文筛选器测试 (Context Filter)

覆盖:
    - 主题检测
    - 实体提取
    - 目标提取
    - 约束提取
    - 摘要裁剪 (筛选 ≠ 长期记忆)
    - 停用错误帧
"""
import unittest

from backend.embodied.companion.interaction.context_filter import (
    ContextFilterError,
    InteractionContextFilter,
)


class TestContextFilterBasic(unittest.TestCase):
    """上下文筛选"""

    def setUp(self):
        self.f = InteractionContextFilter()

    def test_filter_basic(self):
        r = self.f.filter("请完成任务")
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["source_len"], 5)

    def test_topic_task(self):
        r = self.f.filter("请完成任务并处理问题")
        self.assertEqual(r["topic"], "task")

    def test_topic_plan(self):
        r = self.f.filter("需要制定一个方案")
        self.assertEqual(r["topic"], "plan")

    def test_topic_chat(self):
        r = self.f.filter("我们来聊聊最近的事")
        self.assertEqual(r["topic"], "chat")

    def test_topic_problem(self):
        r = self.f.filter("系统报错了")
        self.assertEqual(r["topic"], "problem")

    def test_topic_memory(self):
        r = self.f.filter("你还记得上次的事吗")
        self.assertEqual(r["topic"], "memory")

    def test_topic_general(self):
        r = self.f.filter("今天天气不错")
        self.assertEqual(r["topic"], "general")

    def test_entities_extracted(self):
        r = self.f.filter("请查看「项目文档」中的内容")
        self.assertIn("项目文档", r["entities"])

    def test_goal_extracted(self):
        r = self.f.filter("请完成部署任务")
        self.assertIn("完成", r["goal"])

    def test_constraints_extracted(self):
        r = self.f.filter("禁止删除数据，必须保留备份")
        self.assertGreaterEqual(len(r["constraints"]), 2)

    def test_reason_explainable(self):
        r = self.f.filter("请完成任务")
        self.assertIn("不等同长期记忆", r["reason"])

    def test_summary_field(self):
        r = self.f.filter("内容")
        self.assertEqual(r["summary"], "内容")

    def test_extra_passthrough(self):
        r = self.f.filter("内容", extra={"source": "user"})
        self.assertEqual(r["extra"]["source"], "user")

    def test_empty_text(self):
        r = self.f.filter("")
        self.assertEqual(r["source_len"], 0)
        self.assertEqual(r["topic"], "general")


class TestContextFilterClip(unittest.TestCase):
    """摘要裁剪"""

    def setUp(self):
        self.f = InteractionContextFilter(max_len=10)

    def test_clipped(self):
        r = self.f.filter("很长的上下文内容很长的上下文内容" * 3)
        self.assertTrue(r["clipped"])
        self.assertLessEqual(len(r["summary"]), 10)

    def test_not_clipped(self):
        r = self.f.filter("短内容")
        self.assertFalse(r["clipped"])

    def test_exact_len(self):
        r = self.f.filter("a" * 10)
        self.assertFalse(r["clipped"])
        self.assertEqual(len(r["summary"]), 10)


class TestContextFilterDisabled(unittest.TestCase):
    """停用与统计"""

    def test_disabled(self):
        f = InteractionContextFilter(enabled=False)
        r = f.filter("内容")
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_stats(self):
        f = InteractionContextFilter()
        s = f.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertEqual(s["filter_count"], 0)

    def test_stats_after_filter(self):
        f = InteractionContextFilter()
        f.filter("内容")
        self.assertEqual(f.stats()["filter_count"], 1)

    def test_clear(self):
        f = InteractionContextFilter()
        f.filter("a")
        f.filter("b")
        self.assertEqual(f.clear(), 2)

    def test_invalid_max_len(self):
        with self.assertRaises(ContextFilterError):
            InteractionContextFilter(max_len=0)


# ── 生成式: 主题检测矩阵 ───────────────────────────────────────
_TOPIC_CASES = [
    ("task_zh", "完成任务", "task"),
    ("task_en", "please handle the task", "task"),
    ("plan_zh", "制定计划", "plan"),
    ("plan_en", "make a plan", "plan"),
    ("chat_zh", "聊聊天吧", "chat"),
    ("chat_en", "let's chat", "chat"),
    ("problem_zh", "出现了故障", "problem"),
    ("problem_en", "there is a bug", "problem"),
    ("memory_zh", "你还记得吗", "memory"),
    ("general", "今天天气", "general"),
]


class TestGeneratedTopics(unittest.TestCase):
    """生成式: 主题矩阵"""
    pass


for _i, (_name, _text, _exp) in enumerate(_TOPIC_CASES):
    def _make(name=_name, text=_text, exp=_exp):
        def test_case(self):
            f = InteractionContextFilter()
            r = f.filter(text)
            self.assertEqual(r["topic"], exp)
        test_case.__name__ = f"test_topic_{name}_{_i}"
        return test_case
    setattr(TestGeneratedTopics,
            f"test_topic_{_name}_{_i}", _make())


# ── 生成式: 裁剪矩阵 ───────────────────────────────────────────
_CLIP2_CASES = [
    ("short", "abc", 100, False),
    ("long", "x" * 500, 100, True),
    ("empty", "", 100, False),
    ("boundary", "y" * 100, 100, False),
    ("over_boundary", "z" * 101, 100, True),
]


class TestGeneratedClip2(unittest.TestCase):
    """生成式: 裁剪矩阵"""
    pass


for _i, (_name, _text, _max, _exp) in enumerate(_CLIP2_CASES):
    def _make(name=_name, text=_text, maxl=_max, exp=_exp):
        def test_case(self):
            f = InteractionContextFilter(max_len=maxl)
            r = f.filter(text)
            self.assertEqual(r["clipped"], exp)
        test_case.__name__ = f"test_clip2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedClip2,
            f"test_clip2_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
