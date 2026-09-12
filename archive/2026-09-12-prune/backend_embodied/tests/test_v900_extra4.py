"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 4 (V9.0 Extra4)

覆盖 (生成式批量 + 边界):
    - 探索结果质量矩阵
    - 知识等级矩阵
    - 边界输入
"""
import unittest

from backend.embodied.companion.research_engine import (
    RealityValidation,
    ResearchEngine,
    ResearchMemory,
)


def make_engine():
    engine = ResearchEngine()
    engine.observe("user_need", "提升伙伴体验")
    engine.observe("knowledge_gap", "记忆保持")
    return engine


# ── 探索结果质量矩阵 ────────────────────────────────────────────
_QUALITY_GOALS = [
    "提升伙伴体验",
    "优化记忆管理",
    "增强互动温度",
    "探索未知方向",
]


class TestGeneratedResultQuality(unittest.TestCase):
    """生成式: 结果质量"""
    pass


for _i, _goal in enumerate(_QUALITY_GOALS):
    def _make(goal=_goal):
        def test(self):
            engine = make_engine()
            r = engine.explore(goal)
            for res in r["results"]:
                # 计划完整
                self.assertIn("plan", res)
                self.assertGreaterEqual(
                    len(res["plan"]["steps"]), 3)
                # 获取有来源
                self.assertIn("source",
                              res["acquired"])
                self.assertTrue(
                    res["acquired"]["source_reliable"])
                # 现实验证有等级
                self.assertIn("level",
                              res["reality"])
                # 循环完整
                self.assertIn("knowledge_update",
                              res["loop"])
        test.__name__ = f"test_quality_{_i}"
        test.__doc__ = f"结果质量 {_goal[:6]}"
        return test
    setattr(TestGeneratedResultQuality,
            _make().__name__, _make())


# ── 知识等级矩阵 ────────────────────────────────────────────────
_LEVEL_CASES = [
    ("本地知识摘要", "local", "evidence"),
    ("云端分析结果", "cloud", "hypothesis"),
    ("因此推断", "unknown", "inference"),
    ("候选假设", "unknown", "hypothesis"),
]


class TestGeneratedLevels(unittest.TestCase):
    """生成式: 知识等级"""
    pass


for _i, (_text, _source, _level) in enumerate(_LEVEL_CASES):
    def _make(text=_text, source=_source, level=_level):
        def test(self):
            r = RealityValidation().validate(text, source)
            self.assertEqual(r["level"], level)
        test.__name__ = f"test_level_{_i}"
        test.__doc__ = f"等级 {_level}"
        return test
    setattr(TestGeneratedLevels,
            _make().__name__, _make())


# ── 记忆等级矩阵 ────────────────────────────────────────────────
_MEMORY_LEVEL_CASES = [
    ("fact", True),
    ("evidence", True),
    ("inference", True),
    ("hypothesis", True),
    ("speculation", False),
]


class TestGeneratedMemoryLevels(unittest.TestCase):
    """生成式: 记忆等级"""
    pass


for _i, (_level, _ok) in enumerate(_MEMORY_LEVEL_CASES):
    def _make(level=_level, ok=_ok):
        def test(self):
            memory = ResearchMemory()
            r = memory.save(
                "结论", "local", level=level,
                validated=True, constitution_ok=True,
            )
            self.assertEqual(r.get("ok", True), ok)
        test.__name__ = f"test_memlevel_{_i}"
        test.__doc__ = f"记忆等级 {_level}"
        return test
    setattr(TestGeneratedMemoryLevels,
            _make().__name__, _make())


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestGeneratedBoundary(unittest.TestCase):
    """生成式: 边界"""

    def test_empty_observe_content(self):
        engine = ResearchEngine()
        obs = engine.observe("user_need", "")
        self.assertEqual(obs["content"], "")

    def test_no_observation_explore(self):
        engine = ResearchEngine()
        r = engine.explore("目标")
        self.assertFalse(r["ok"])
        self.assertIn("无可探索问题", r["reason"])

    def test_single_observation(self):
        engine = ResearchEngine()
        engine.observe("user_need", "单一需求")
        r = engine.explore("目标")
        self.assertFalse(r["blocked"])
        self.assertGreaterEqual(len(r["results"]), 1)

    def test_many_observations(self):
        engine = ResearchEngine()
        for i in range(10):
            engine.observe("knowledge_gap", f"缺口{i}")
        r = engine.explore("目标")
        self.assertLessEqual(len(r["results"]), 3)

    def test_clear_resets(self):
        engine = make_engine()
        engine.explore("提升体验")
        n = engine.clear()
        self.assertGreater(n, 0)
        stats = engine.stats()
        self.assertEqual(stats["explore_count"], 0)
        self.assertEqual(
            stats["observation"]["observation_count"], 0)


# ── 观察-探索闭环矩阵 ───────────────────────────────────────────
class TestGeneratedObsExploreLoop(unittest.TestCase):
    """生成式: 观察-探索闭环"""

    def test_observe_then_explore(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求A")
        engine.observe("long_term_goal", "目标B")
        r = engine.explore("目标B")
        self.assertFalse(r["blocked"])
        questions = [q["question"] for q in r["questions"]]
        matched = [
            q for q in questions if "需求A" in q
        ]
        self.assertGreaterEqual(len(matched), 1)

    def test_explore_repeat(self):
        engine = make_engine()
        r1 = engine.explore("提升体验")
        r2 = engine.explore("提升体验")
        self.assertGreaterEqual(len(r1["results"]), 1)
        self.assertGreaterEqual(len(r2["results"]), 1)


if __name__ == "__main__":
    unittest.main()
