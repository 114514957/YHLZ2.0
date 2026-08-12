"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 15 (V8.5 Extra15)

覆盖 (生成式批量):
    - 创造基础矩阵
    - 知识图关系矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    ConceptFusion,
    KnowledgeGraph,
    MetaCreativeEngine,
)


# ── 创造基础矩阵 ────────────────────────────────────────────────
_BASIS_CASES = [
    ("A", "B"),
    ("模式", "记忆"),
    ("经验", "创造"),
    ("互动", "价值"),
]


class TestGeneratedBasis(unittest.TestCase):
    """生成式: 创造基础"""
    pass


for _i, (_a, _b) in enumerate(_BASIS_CASES):
    def _make(a=_a, b=_b):
        def test(self):
            fusion = ConceptFusion().fuse(a, b)
            self.assertIn("derivation", fusion)
            self.assertTrue(fusion["derivation"])
        test.__name__ = f"test_basis_{_i}"
        test.__doc__ = f"基础 {_a}+{_b}"
        return test
    setattr(TestGeneratedBasis,
            _make().__name__, _make())


# ── 知识图关系矩阵 ──────────────────────────────────────────────
_REL_VARIANTS = [
    ("A", "B", "推导"),
    ("A", "C", "包含"),
    ("B", "C", "相关"),
    ("C", "D", "冲突"),
]


class TestGeneratedRelVariants(unittest.TestCase):
    """生成式: 关系变体"""
    pass


for _i, (_a, _b, _rel) in enumerate(_REL_VARIANTS):
    def _make(a=_a, b=_b, rel=_rel):
        def test(self):
            graph = KnowledgeGraph()
            graph.add_relation(a, b, rel)
            rels = graph.relations_of(a)
            self.assertEqual(rels[0]["relation"], rel)
            self.assertIsNotNone(graph.get(b))
        test.__name__ = f"test_relvar_{_i}"
        test.__doc__ = f"关系变体 {_rel}"
        return test
    setattr(TestGeneratedRelVariants,
            _make().__name__, _make())


# ── 引擎矩阵 ────────────────────────────────────────────────────
class TestEngineBasic(unittest.TestCase):
    """引擎基础"""

    def test_load_and_create(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": "概念A", "source": "x"},
            {"trigger": "概念B", "source": "x"},
        ])
        r = engine.create("问题")
        self.assertTrue(r["validation"]["ok"])

    def test_stats_after_operations(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        engine.create("问题A")
        engine.create("问题B")
        stats = engine.stats()
        self.assertEqual(stats["create_count"], 2)
        self.assertEqual(stats["mode"], "rule_based")


if __name__ == "__main__":
    unittest.main()
