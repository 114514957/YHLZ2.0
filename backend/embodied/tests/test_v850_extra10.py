"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 10 (V8.5 Extra10)

覆盖 (生成式批量矩阵):
    - 火花-边界联动矩阵
    - 服务创造矩阵
    - 容错矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    CreativeValidation,
    IdeaSparkGenerator,
    KnowledgeGraph,
    MetaCreativeEngine,
    ThoughtBoundaryDetector,
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
    for trig in ("模式发现", "记忆整理"):
        for _ in range(2):
            mgr.store_from_event(
                success=True, trigger=trig,
                source="v850", action="a", result="成功",
            )
    records = [r.to_dict() for r in mgr._store.all()]
    svc.companion_meta_creative.load_experience(records)


# ── 火花-边界联动矩阵 ───────────────────────────────────────────
_SPARK_BOUNDARY_CASES = [
    (["A", "B"], []),
    (["A", "B", "C"], [("A", "B")]),
    (["A", "B", "C", "D"], [("A", "B"), ("C", "D")]),
]


class TestGeneratedSparkBoundary(unittest.TestCase):
    """生成式: 火花-边界"""
    pass


for _i, (_concepts, _rels) in enumerate(_SPARK_BOUNDARY_CASES):
    def _make(concepts=_concepts, rels=_rels):
        def test(self):
            graph = KnowledgeGraph()
            for c in concepts:
                graph.add_concept(c)
            for (a, b) in rels:
                graph.add_relation(a, b)
            gen = IdeaSparkGenerator(graph=graph)
            boundary = ThoughtBoundaryDetector(graph=graph)
            sparks = gen.generate("问题")
            b = boundary.detect("问题")
            self.assertGreaterEqual(len(sparks), 1)
            self.assertGreaterEqual(
                len(b["exploration_direction"]), 1)
        test.__name__ = f"test_sb_{_i}"
        test.__doc__ = f"火花边界 {_i}"
        return test
    setattr(TestGeneratedSparkBoundary,
            _make().__name__, _make())


# ── 服务创造矩阵 ────────────────────────────────────────────────
_SERVICE_CREATE_CASES = [
    ("如何提升伙伴体验", {}),
    ("如何优化记忆管理", {"human_input": "要直观"}),
    ("如何增强互动温度", {"context": {"goal": "温暖"}}),
]


class TestGeneratedServiceCreate2(unittest.TestCase):
    """生成式: 服务创造"""
    pass


for _i, (_problem, _extra) in enumerate(_SERVICE_CREATE_CASES):
    def _make(problem=_problem, extra=_extra):
        def test(self):
            svc = setup_service()
            seed_and_load(svc)
            r = svc.companion_meta_creative_create(
                problem, **extra,
            )
            self.assertTrue(r["validation"]["ok"])
            self.assertTrue(r["output"])
        test.__name__ = f"test_svc_create2_{_i}"
        test.__doc__ = f"服务创造 {_problem[:6]}"
        return test
    setattr(TestGeneratedServiceCreate2,
            _make().__name__, _make())


# ── 容错矩阵 ────────────────────────────────────────────────────
class TestTolerance(unittest.TestCase):
    """容错"""

    def test_validation_none_input(self):
        r = CreativeValidation().validate(None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["knowledge_type"], "unknown")

    def test_validation_partial(self):
        r = CreativeValidation().validate({
            "foundation": "只有依据",
        })
        self.assertFalse(r["ok"])

    def test_engine_empty_problem(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        r = engine.create("")
        self.assertTrue(r["validation"]["ok"])

    def test_engine_after_clear_graceful(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        engine.clear()
        r = engine.create("问题")
        self.assertFalse(r["ok"])

    def test_service_sparks_no_load(self):
        svc = setup_service()
        r = svc.companion_meta_creative_sparks("问题")
        self.assertEqual(r["spark_count"], 0)

    def test_service_hypothesis_no_load(self):
        svc = setup_service()
        r = svc.companion_meta_creative_hypothesis("问题")
        self.assertFalse(r["ok"])


# ── 知识图质量矩阵 ──────────────────────────────────────────────
class TestGraphExtra(unittest.TestCase):
    """知识图扩展"""

    def test_relation_evidence(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "B", evidence="观察记录")
        rels = graph.relations_of("A")
        self.assertEqual(rels[0]["evidence"], "观察记录")

    def test_relation_count_in_stats(self):
        graph = KnowledgeGraph()
        for i in range(5):
            graph.add_relation(f"A{i}", f"B{i}")
        self.assertEqual(graph.stats()["relation_count"], 5)

    def test_neighbors_dedup(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "B")
        graph.add_relation("A", "B")
        self.assertEqual(len(graph.neighbors("A")), 2)


if __name__ == "__main__":
    unittest.main()
