"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 8 (V8.5 Extra8)

覆盖 (生成式批量矩阵):
    - 知识图统计矩阵
    - 火花约束矩阵
    - 服务全流程矩阵
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
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


# ── 知识图统计矩阵 ──────────────────────────────────────────────
_GRAPH_STAT_CASES = [
    (2, 0, 2),
    (3, 1, 1),
    (4, 2, 1),
    (6, 3, 2),
]


class TestGeneratedGraphStats(unittest.TestCase):
    """生成式: 图统计"""
    pass


for _i, (_nodes, _rels, _unconnected) in \
        enumerate(_GRAPH_STAT_CASES):
    def _make(nodes=_nodes, rels=_rels,
              unconnected=_unconnected):
        def test(self):
            graph = KnowledgeGraph()
            for j in range(nodes):
                graph.add_concept(f"N{j}")
            for j in range(rels):
                graph.add_relation(f"N{j}", f"N{j + 1}")
            stats = graph.stats()
            self.assertEqual(stats["node_count"], nodes)
            self.assertEqual(stats["relation_count"], rels)
            self.assertEqual(stats["unconnected_count"],
                             unconnected)
        test.__name__ = f"test_gstats_{_i}"
        test.__doc__ = f"图统计 {_nodes}/{_rels}"
        return test
    setattr(TestGeneratedGraphStats,
            _make().__name__, _make())


# ── 火花约束矩阵 ────────────────────────────────────────────────
_SPARK_CONSTRAINT_CASES = [
    ([("A", "B")], 1),
    ([("A", "B"), ("B", "C")], 2),
    ([("A", "B"), ("C", "D")], 2),
]


class TestGeneratedSparkConstraints(unittest.TestCase):
    """生成式: 火花约束"""
    pass


for _i, (_rels, _min_types) in enumerate(_SPARK_CONSTRAINT_CASES):
    def _make(rels=_rels, min_types=_min_types):
        def test(self):
            graph = KnowledgeGraph()
            for (a, b) in rels:
                graph.add_relation(a, b)
            gen = IdeaSparkGenerator(graph=graph,
                                     max_sparks=5)
            sparks = gen.generate("问题")
            self.assertLessEqual(len(sparks), 5)
            self.assertGreaterEqual(
                len({s["spark_type"] for s in sparks}),
                min_types)
        test.__name__ = f"test_spark_cons_{_i}"
        test.__doc__ = f"火花约束 {_i}"
        return test
    setattr(TestGeneratedSparkConstraints,
            _make().__name__, _make())


# ── 服务全流程矩阵 ──────────────────────────────────────────────
class TestServiceFullFlow(unittest.TestCase):
    """服务全流程"""

    def test_full_chain_service(self):
        svc = setup_service()
        seed_and_load(svc)
        r = svc.companion_meta_creative_create(
            "如何提升伙伴体验",
            human_input="要更温暖",
        )
        self.assertTrue(r["validation"]["ok"])
        self.assertIn("output", r)
        self.assertIn("boundary", r)
        self.assertIn("fusion", r)
        self.assertIn("hybrid", r)

    def test_engine_reuse_after_clear(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative_create("问题A")
        svc.companion_meta_creative.clear()
        # 清空后需重新加载
        seed_and_load(svc)
        r = svc.companion_meta_creative_create("问题B")
        self.assertTrue(r["validation"]["ok"])

    def test_constitution_engine_shared(self):
        svc = setup_service()
        self.assertIs(
            svc.companion_meta_creative._constitution,
            svc.companion_constitution_engine,
        )

    def test_stats_graph_memory(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative_create("问题")
        stats = svc.companion_meta_creative_stats()
        self.assertGreaterEqual(
            stats["graph"]["node_count"], 3)
        self.assertGreaterEqual(
            stats["memory"]["record_count"], 1)

    def test_disabled_hybrid_link(self):
        svc = setup_service(
            companion_meta_creative_hybrid_link=False,
        )
        seed_and_load(svc)
        r = svc.companion_meta_creative_create("问题")
        self.assertNotIn("hybrid", r)


# ── 引擎构造矩阵 ────────────────────────────────────────────────
class TestEngineConstruct(unittest.TestCase):
    """引擎构造"""

    def test_default_construct(self):
        engine = MetaCreativeEngine()
        self.assertTrue(engine.stats()["enabled"])

    def test_with_constitution(self):
        engine = MetaCreativeEngine(
            constitution=ConstitutionEngine(),
        )
        self.assertIsNotNone(engine._constitution)

    def test_disabled_construct(self):
        engine = MetaCreativeEngine(enabled=False)
        r = engine.create("问题")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
