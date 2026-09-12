"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 7 (V9.0 Extra7)

覆盖 (生成式批量 + 边界):
    - 问题发现质量矩阵
    - 记忆等级分布矩阵
    - 边界输入
"""
import unittest

from backend.embodied.companion.research_engine import (
    ObservationLayer,
    QuestionDiscoveryEngine,
    ResearchEngine,
    ResearchMemory,
)


# ── 问题发现质量矩阵 ────────────────────────────────────────────
_QUESTION_CONTENTS = [
    "如何提升伙伴体验",
    "如何优化记忆",
    "如何增强互动",
    "如何保持连续",
    "如何探索未知",
]


class TestGeneratedQuestionQuality(unittest.TestCase):
    """生成式: 问题质量"""
    pass


for _i, _content in enumerate(_QUESTION_CONTENTS):
    def _make(content=_content):
        def test(self):
            layer = ObservationLayer()
            layer.observe("user_need", content)
            engine = QuestionDiscoveryEngine(layer=layer)
            q = engine.discover()[0]
            self.assertIn(content[:8], q["question"])
            self.assertTrue(q["reason"])
            self.assertTrue(q["expected_value"])
            self.assertGreaterEqual(q["importance"], 0.0)
            self.assertLessEqual(q["importance"], 1.0)
        test.__name__ = f"test_qquality_{_i}"
        test.__doc__ = f"问题质量 {_content[:6]}"
        return test
    setattr(TestGeneratedQuestionQuality,
            _make().__name__, _make())


# ── 记忆等级分布矩阵 ────────────────────────────────────────────
_LEVEL_DIST_CASES = [
    [("fact", True)],
    [("fact", True), ("inference", True)],
    [("fact", True), ("inference", True),
     ("speculation", False)],
]


class TestGeneratedLevelDist(unittest.TestCase):
    """生成式: 等级分布"""
    pass


for _i, _entries in enumerate(_LEVEL_DIST_CASES):
    def _make(entries=_entries):
        def test(self):
            memory = ResearchMemory()
            saved = 0
            for (level, ok) in entries:
                r = memory.save(
                    "结论", "local", level=level,
                    validated=True, constitution_ok=True,
                )
                if r.get("ok", True):
                    saved += 1
            stats = memory.stats()
            self.assertEqual(stats["record_count"], saved)
            self.assertIn("by_level", stats)
        test.__name__ = f"test_leveldist_{_i}"
        test.__doc__ = f"等级分布 {_i}"
        return test
    setattr(TestGeneratedLevelDist,
            _make().__name__, _make())


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestBoundaryInputs(unittest.TestCase):
    """边界输入"""

    def test_empty_goal(self):
        engine = ResearchEngine()
        r = engine.explore("")
        self.assertFalse(r["ok"])

    def test_none_goal(self):
        engine = ResearchEngine()
        r = engine.explore(None)
        self.assertFalse(r["ok"])

    def test_whitespace_goal(self):
        engine = ResearchEngine()
        r = engine.explore("   ")
        self.assertFalse(r["ok"])

    def test_observe_none_content(self):
        engine = ResearchEngine()
        obs = engine.observe("user_need", None)
        self.assertEqual(obs["content"], "")

    def test_question_no_reason_content(self):
        layer = ObservationLayer()
        layer.observe("user_need", "")
        engine = QuestionDiscoveryEngine(layer=layer)
        self.assertEqual(engine.discover(), [])


# ── 观察-探索统计矩阵 ───────────────────────────────────────────
class TestObservationExploreStats(unittest.TestCase):
    """观察-探索统计"""

    def test_stats_after_flow(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.observe("knowledge_gap", "缺口")
        r = engine.explore("目标")
        self.assertFalse(r["blocked"])
        stats = engine.stats()
        self.assertEqual(stats["explore_count"], 1)
        self.assertEqual(
            stats["observation"]["observation_count"], 2)

    def test_question_engine_stats(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        q_stats = engine.stats()["questions"]
        self.assertGreaterEqual(q_stats["question_count"], 1)
        self.assertIn("weights", q_stats)


if __name__ == "__main__":
    unittest.main()
