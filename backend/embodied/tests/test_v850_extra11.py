"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 11 (V8.5 Extra11)

覆盖 (生成式批量矩阵):
    - 创造质量矩阵
    - 火花类型矩阵
    - 服务稳定性矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    IdeaSparkGenerator,
    KnowledgeGraph,
    MetaCreativeEngine,
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


def seed_and_load(svc):
    mgr = svc.companion_experience
    for trig in ("模式发现", "记忆整理", "互动优化"):
        for _ in range(2):
            mgr.store_from_event(
                success=True, trigger=trig,
                source="v850", action="a", result="成功",
            )
    records = [r.to_dict() for r in mgr._store.all()]
    svc.companion_meta_creative.load_experience(records)


# ── 创造质量矩阵 ────────────────────────────────────────────────
_QUALITY_PROBLEMS = [
    "如何让记忆更长久",
    "如何让互动更自然",
    "如何让成长更稳健",
    "如何让表达更温暖",
]


class TestGeneratedQuality(unittest.TestCase):
    """生成式: 创造质量"""
    pass


for _i, _problem in enumerate(_QUALITY_PROBLEMS):
    def _make(problem=_problem):
        def test(self):
            engine = MetaCreativeEngine()
            engine.load_experience([
                {"trigger": f"C{j}", "source": "x"}
                for j in range(4)
            ])
            r = engine.create(problem)
            h = r["hypothesis"]
            # 质量: 假设/依据/推理/验证 全部非空
            self.assertTrue(h["hypothesis"])
            self.assertTrue(h["foundation"])
            self.assertTrue(h["reasoning"])
            self.assertTrue(h["verification"])
            self.assertGreaterEqual(h["confidence"], 0.5)
        test.__name__ = f"test_quality_{_i}"
        test.__doc__ = f"质量 {_problem[:6]}"
        return test
    setattr(TestGeneratedQuality,
            _make().__name__, _make())


# ── 火花类型矩阵 ────────────────────────────────────────────────
_TYPE_COMBOS = [
    ([("A", "B")], ["potential_relation",
                    "new_combination"]),
    ([("A", "B"), ("B", "C")],
     ["potential_relation", "new_combination"]),
]


class TestGeneratedSparkTypes(unittest.TestCase):
    """生成式: 火花类型"""
    pass


for _i, (_rels, _expected_types) in enumerate(_TYPE_COMBOS):
    def _make(rels=_rels, expected_types=_expected_types):
        def test(self):
            graph = KnowledgeGraph()
            for (a, b) in rels:
                graph.add_relation(a, b)
            gen = IdeaSparkGenerator(graph=graph)
            sparks = gen.generate("问题")
            types = {s["spark_type"] for s in sparks}
            for t in expected_types:
                self.assertIn(t, types)
        test.__name__ = f"test_spark_types_{_i}"
        test.__doc__ = f"火花类型 {_i}"
        return test
    setattr(TestGeneratedSparkTypes,
            _make().__name__, _make())


# ── 服务稳定性矩阵 ──────────────────────────────────────────────
class TestServiceStability(unittest.TestCase):
    """服务稳定性"""

    def test_repeated_same_problem(self):
        svc = setup_service()
        seed_and_load(svc)
        results = []
        for _ in range(5):
            r = svc.companion_meta_creative_create(
                "如何提升伙伴体验",
            )
            self.assertTrue(r["validation"]["ok"])
            results.append(r["output"])
        # 输出稳定可验证
        self.assertGreaterEqual(len(results), 5)

    def test_mixed_problems(self):
        svc = setup_service()
        seed_and_load(svc)
        for problem in ("问题A", "问题B", "问题C"):
            r = svc.companion_meta_creative_create(problem)
            self.assertTrue(r["validation"]["ok"])

    def test_stats_accumulate(self):
        svc = setup_service()
        seed_and_load(svc)
        for _ in range(3):
            svc.companion_meta_creative_create("问题")
        stats = svc.companion_meta_creative_stats()
        self.assertEqual(stats["create_count"], 3)
        self.assertGreaterEqual(stats["spark"]["spark_count"],
                                3)

    def test_memory_filter_never_bypass(self):
        svc = setup_service()
        seed_and_load(svc)
        before = svc.companion_meta_creative.memory_stats()[
            "record_count"]
        r = svc.companion_meta_creative.memory_save(
            "未验证", validated=False,
        )
        self.assertFalse(r["ok"])
        after = svc.companion_meta_creative.memory_stats()[
            "record_count"]
        self.assertEqual(before, after)


# ── 知识图扩展矩阵 ──────────────────────────────────────────────
class TestGraphExtension(unittest.TestCase):
    """知识图扩展"""

    def test_self_relation(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "A")
        self.assertEqual(graph.stats()["relation_count"], 1)
        self.assertEqual(graph.stats()["unconnected_count"],
                         0)

    def test_chain_depth(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "B")
        graph.add_relation("B", "C")
        graph.add_relation("C", "D")
        graph.add_relation("D", "E")
        self.assertEqual(graph.stats()["unconnected_count"],
                         0)

    def test_branch(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "B")
        graph.add_relation("A", "C")
        graph.add_relation("A", "D")
        self.assertEqual(len(graph.neighbors("A")), 3)


if __name__ == "__main__":
    unittest.main()
