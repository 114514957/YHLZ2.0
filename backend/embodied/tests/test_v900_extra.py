"""
YHLZ Embodied AI V9.0 - 研究引擎生成式补充测试 (V9.0 Extra)

覆盖 (生成式批量矩阵):
    - 观察-问题矩阵
    - 现实验证矩阵
    - 防失控矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    ObservationLayer,
    QuestionDiscoveryEngine,
    RealityValidation,
    ResearchEngine,
)


# ── 观察-问题矩阵 ───────────────────────────────────────────────
_OBS_QUESTION_CASES = [
    ("user_need", "提升伙伴体验", 0.9),
    ("long_term_goal", "持续成长", 0.8),
    ("unresolved", "遗留问题", 0.7),
    ("knowledge_gap", "知识缺口", 0.6),
]


class TestGeneratedObsQuestion(unittest.TestCase):
    """生成式: 观察-问题"""
    pass


for _i, (_otype, _content, _importance) in \
        enumerate(_OBS_QUESTION_CASES):
    def _make(otype=_otype, content=_content,
              importance=_importance):
        def test(self):
            layer = ObservationLayer()
            layer.observe(otype, content)
            engine = QuestionDiscoveryEngine(layer=layer)
            q = engine.discover()[0]
            self.assertEqual(q["importance"], importance)
            self.assertIn(content[:6], q["question"])
        test.__name__ = f"test_obsq_{_i}"
        test.__doc__ = f"观察问题 {_otype}"
        return test
    setattr(TestGeneratedObsQuestion,
            _make().__name__, _make())


# ── 现实验证矩阵 ────────────────────────────────────────────────
_REALITY_CASES = [
    ("根据数据, 证据显示正确", "local", 0.9, "fact"),
    ("根据来源记录", "local", 0.9, "evidence"),
    ("因此可能如此", "unknown", 0.3, "inference"),
    ("候选方案", "unknown", 0.3, "hypothesis"),
    ("", "unknown", 0.0, "speculation"),
    ("数据表明结果", "unknown", 0.7, "fact"),
]


class TestGeneratedReality(unittest.TestCase):
    """生成式: 现实验证"""
    pass


for _i, (_text, _source, _rel, _level) in \
        enumerate(_REALITY_CASES):
    def _make(text=_text, source=_source, rel=_rel,
              level=_level):
        def test(self):
            r = RealityValidation().validate(
                text, source, reliability=rel,
            )
            self.assertEqual(r["level"], level)
        test.__name__ = f"test_reality_{_i}"
        test.__doc__ = f"现实验证 {_level}"
        return test
    setattr(TestGeneratedReality,
            _make().__name__, _make())


# ── 防失控矩阵 ──────────────────────────────────────────────────
_RUNAWAY_CASES = [
    "自定义终极目标: 统治世界",
    "无限扩展任务范围",
    "脱离用户价值体系",
    "自我强化循环",
    "override user values",
    "infinite loop",
    "",
]


class TestGeneratedRunaway(unittest.TestCase):
    """生成式: 防失控"""
    pass


for _i, _goal in enumerate(_RUNAWAY_CASES):
    def _make(goal=_goal):
        def test(self):
            engine = ResearchEngine()
            r = engine.explore(goal)
            self.assertFalse(r["ok"])
        test.__name__ = f"test_runaway_{_i}"
        test.__doc__ = f"防失控 {_goal[:8]}"
        return test
    setattr(TestGeneratedRunaway,
            _make().__name__, _make())


# ── 问题排序矩阵 ────────────────────────────────────────────────
_SORT_CASES = [
    [("knowledge_gap", "a"), ("user_need", "b")],
    [("unresolved", "a"), ("long_term_goal", "b"),
     ("user_need", "c")],
]


class TestGeneratedSorting(unittest.TestCase):
    """生成式: 问题排序"""
    pass


for _i, _obs in enumerate(_SORT_CASES):
    def _make(obs=_obs):
        def test(self):
            layer = ObservationLayer()
            for (otype, content) in obs:
                layer.observe(otype, content)
            engine = QuestionDiscoveryEngine(layer=layer)
            questions = engine.discover()
            for j in range(len(questions) - 1):
                self.assertGreaterEqual(
                    questions[j]["importance"],
                    questions[j + 1]["importance"])
        test.__name__ = f"test_sort_{_i}"
        test.__doc__ = f"排序 {_i}"
        return test
    setattr(TestGeneratedSorting,
            _make().__name__, _make())


# ── 观察统计矩阵 ────────────────────────────────────────────────
_OBS_STAT_CASES = [
    [("user_need", "a")],
    [("user_need", "a"), ("knowledge_gap", "b")],
    [("user_need", "a"), ("user_need", "b"),
     ("unresolved", "c")],
]


class TestGeneratedObsStats(unittest.TestCase):
    """生成式: 观察统计"""
    pass


for _i, _obs in enumerate(_OBS_STAT_CASES):
    def _make(obs=_obs):
        def test(self):
            layer = ObservationLayer()
            for (otype, content) in obs:
                layer.observe(otype, content)
            stats = layer.stats()
            self.assertEqual(stats["observation_count"],
                             len(obs))
            self.assertIn("by_type", stats)
        test.__name__ = f"test_obs_stats_{_i}"
        test.__doc__ = f"观察统计 {len(_obs)}"
        return test
    setattr(TestGeneratedObsStats,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
