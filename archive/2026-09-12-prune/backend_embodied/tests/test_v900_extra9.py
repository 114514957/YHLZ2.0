"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 9 (V9.0 Extra9)

覆盖 (生成式批量):
    - 观察类型组合矩阵
    - 服务观察矩阵
    - 记忆统计矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    ObservationLayer,
    QuestionDiscoveryEngine,
    ResearchEngine,
    ResearchMemory,
)
from backend.embodied.service import EmbodiedService


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


# ── 观察类型组合矩阵 ────────────────────────────────────────────
_TYPE_COMBOS = [
    ["user_need"],
    ["user_need", "knowledge_gap"],
    ["user_need", "long_term_goal", "unresolved"],
    ["knowledge_gap", "knowledge_gap", "knowledge_gap"],
]


class TestGeneratedTypeCombos(unittest.TestCase):
    """生成式: 类型组合"""
    pass


for _i, _types in enumerate(_TYPE_COMBOS):
    def _make(types=_types):
        def test(self):
            layer = ObservationLayer()
            for t in types:
                layer.observe(t, f"内容_{t}")
            stats = layer.stats()
            self.assertEqual(stats["observation_count"],
                             len(types))
            for t in types:
                self.assertGreaterEqual(
                    stats["by_type"].get(t, 0), 1)
        test.__name__ = f"test_typecombos_{_i}"
        test.__doc__ = f"类型组合 {_i}"
        return test
    setattr(TestGeneratedTypeCombos,
            _make().__name__, _make())


# ── 服务观察矩阵 ────────────────────────────────────────────────
class TestServiceObserve(unittest.TestCase):
    """服务观察"""

    def test_observe_all_types(self):
        svc = setup_service()
        for t in ("user_need", "knowledge_gap",
                  "long_term_goal", "unresolved"):
            obs = svc.companion_research_observe(
                t, f"内容{t}", "test",
            )
            self.assertEqual(obs["type"], t)
            self.assertEqual(obs["source"], "test")

    def test_observe_then_explore(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求A", "user",
        )
        r = svc.companion_research_explore("目标A")
        self.assertFalse(r["blocked"])
        self.assertGreaterEqual(len(r["results"]), 1)

    def test_observe_stats(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求", "user",
        )
        stats = svc.companion_research_stats()
        self.assertEqual(
            stats["observation"]["observation_count"], 1)


# ── 记忆统计矩阵 ────────────────────────────────────────────────
_MEMORY_STAT_CASES = [
    [("fact", True)],
    [("fact", True), ("evidence", True)],
    [("fact", True), ("speculation", False)],
]


class TestGeneratedMemoryStats(unittest.TestCase):
    """生成式: 记忆统计"""
    pass


for _i, _entries in enumerate(_MEMORY_STAT_CASES):
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
            self.assertEqual(
                stats["by_level"].get("fact", 0),
                sum(1 for l, _ in entries
                    if l == "fact" and
                    _ is True),
            )
        test.__name__ = f"test_memstats_{_i}"
        test.__doc__ = f"记忆统计 {_i}"
        return test
    setattr(TestGeneratedMemoryStats,
            _make().__name__, _make())


# ── 问题引擎矩阵 ────────────────────────────────────────────────
class TestQuestionEngine(unittest.TestCase):
    """问题引擎"""

    def test_discover_after_new_observe(self):
        layer = ObservationLayer()
        engine = QuestionDiscoveryEngine(layer=layer)
        self.assertEqual(engine.discover(), [])
        layer.observe("user_need", "新需求")
        questions = engine.discover()
        self.assertGreaterEqual(len(questions), 1)

    def test_importance_weighted(self):
        layer = ObservationLayer()
        layer.observe("knowledge_gap", "低")
        layer.observe("unresolved", "中")
        layer.observe("long_term_goal", "高")
        engine = QuestionDiscoveryEngine(layer=layer)
        questions = engine.discover()
        first = questions[0]
        self.assertGreaterEqual(first["importance"], 0.8)


# ── 探索矩阵 ────────────────────────────────────────────────────
class TestExploreMatrix(unittest.TestCase):
    """探索矩阵"""

    def test_explore_with_user_value(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标", "用户价值: 诚信")
        self.assertFalse(r["blocked"])

    def test_explore_without_user_value(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        self.assertFalse(r["blocked"])

    def test_explore_uses_max_loops(self):
        engine = ResearchEngine(max_loops_per_explore=2)
        for i in range(4):
            engine.observe("knowledge_gap", f"缺口{i}")
        r = engine.explore("目标")
        self.assertLessEqual(len(r["results"]), 2)


if __name__ == "__main__":
    unittest.main()
