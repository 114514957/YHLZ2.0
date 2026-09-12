"""
YHLZ Embodied AI V8.5 - 元创造力引擎生成式补充测试 (V8.5 Extra)

覆盖 (生成式批量矩阵):
    - 知识图操作矩阵
    - 火花生成矩阵
    - 组合逻辑矩阵
    - 假设结构矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    ConceptFusion,
    CreativeValidation,
    HypothesisEngine,
    IdeaSparkGenerator,
    KnowledgeGraph,
)


# ── 知识图操作矩阵 ──────────────────────────────────────────────
_GRAPH_CASES = [
    ("概念1", "method"),
    ("概念2", "experience"),
    ("概念3", "memory"),
    ("概念4", "general"),
    ("概念5", "creative"),
]


class TestGeneratedGraphOps(unittest.TestCase):
    """生成式: 知识图操作"""
    pass


for _i, (_concept, _category) in enumerate(_GRAPH_CASES):
    def _make(concept=_concept, category=_category):
        def test(self):
            graph = KnowledgeGraph()
            graph.add_concept(concept, category)
            got = graph.get(concept)
            self.assertEqual(got["category"], category)
            self.assertEqual(got["source"], "memory")
        test.__name__ = f"test_graph_{_i}"
        test.__doc__ = f"知识图 {_concept}"
        return test
    setattr(TestGeneratedGraphOps,
            _make().__name__, _make())


# ── 关系矩阵 ────────────────────────────────────────────────────
_RELATION_CASES = [
    ("A", "B", "推导"),
    ("C", "D", "包含"),
    ("E", "F", "相关"),
    ("G", "H", "冲突"),
]


class TestGeneratedRelations(unittest.TestCase):
    """生成式: 关系"""
    pass


for _i, (_a, _b, _rel) in enumerate(_RELATION_CASES):
    def _make(a=_a, b=_b, rel=_rel):
        def test(self):
            graph = KnowledgeGraph()
            r = graph.add_relation(a, b, rel)
            self.assertEqual(r["relation"], rel)
            self.assertEqual(len(graph.relations_of(a)), 1)
        test.__name__ = f"test_rel_{_i}"
        test.__doc__ = f"关系 {_a}-{_b}"
        return test
    setattr(TestGeneratedRelations,
            _make().__name__, _make())


# ── 火花问题矩阵 ────────────────────────────────────────────────
_PROBLEM_CASES = [
    "如何提升效率",
    "如何增强记忆",
    "如何优化互动",
    "如何创造价值",
    "如何保持连续",
]


class TestGeneratedProblems(unittest.TestCase):
    """生成式: 火花问题"""
    pass


for _i, _problem in enumerate(_PROBLEM_CASES):
    def _make(problem=_problem):
        def test(self):
            graph = KnowledgeGraph()
            graph.add_relation("效率", "记忆")
            graph.add_relation("互动", "价值")
            graph.add_concept("连续")
            gen = IdeaSparkGenerator(graph=graph)
            sparks = gen.generate(problem)
            self.assertGreaterEqual(len(sparks), 1)
            for s in sparks:
                self.assertTrue(s["basis"])
        test.__name__ = f"test_problem_{_i}"
        test.__doc__ = f"问题 {_problem}"
        return test
    setattr(TestGeneratedProblems,
            _make().__name__, _make())


# ── 组合逻辑矩阵 ────────────────────────────────────────────────
_FUSION_COMBOS = [
    ("A", "B", "merge"),
    ("A", "B", "analogy"),
    ("A", "B", "transfer"),
    ("A", "B", "extension"),
    ("模式", "记忆", "merge"),
    ("经验", "创造", "transfer"),
]


class TestGeneratedFusionCombos(unittest.TestCase):
    """生成式: 组合逻辑"""
    pass


for _i, (_a, _b, _logic) in enumerate(_FUSION_COMBOS):
    def _make(a=_a, b=_b, logic=_logic):
        def test(self):
            r = ConceptFusion().fuse(a, b, "情境", logic)
            self.assertEqual(r["fusion_logic"], logic)
            self.assertIn("derivation", r)
            self.assertIn("sources", r)
        test.__name__ = f"test_fusion_{_i}"
        test.__doc__ = f"组合 {_a}+{_b}/{_logic}"
        return test
    setattr(TestGeneratedFusionCombos,
            _make().__name__, _make())


# ── 假设结构矩阵 ────────────────────────────────────────────────
_SPARK_VARIANTS = [
    "连接知识",
    "探索关系",
    "组合概念",
    "迁移方法",
]


class TestGeneratedHypothesis(unittest.TestCase):
    """生成式: 假设结构"""
    pass


for _i, _idea in enumerate(_SPARK_VARIANTS):
    def _make(idea=_idea):
        def test(self):
            h = HypothesisEngine().build({
                "spark_id": "sp_x", "spark_type": "merge",
                "idea": idea, "basis": "观察依据",
                "confidence": 0.6,
                "related_concepts": ["X", "Y"],
            })
            for key in ("hypothesis", "foundation",
                        "reasoning", "confidence",
                        "verification", "falsifiable"):
                self.assertIn(key, h)
            self.assertTrue(h["foundation"])
            self.assertTrue(h["verification"])
        test.__name__ = f"test_hyp_{_i}"
        test.__doc__ = f"假设 {_idea}"
        return test
    setattr(TestGeneratedHypothesis,
            _make().__name__, _make())


# ── 验证矩阵 ────────────────────────────────────────────────────
_VALIDATION_CASES = [
    ({"foundation": "有", "reasoning": "有",
      "verification": "有"}, True),
    ({"foundation": "", "reasoning": "有",
      "verification": "有"}, False),
    ({"foundation": "有", "reasoning": "",
      "verification": "有"}, False),
    ({"foundation": "有", "reasoning": "有",
      "verification": ""}, False),
    ({}, False),
    ({"foundation": "有", "reasoning": "必然如此",
      "verification": "有"}, False),
]


class TestGeneratedValidation(unittest.TestCase):
    """生成式: 验证矩阵"""
    pass


for _i, (_h, _ok) in enumerate(_VALIDATION_CASES):
    def _make(h=_h, ok=_ok):
        def test(self):
            r = CreativeValidation().validate(dict(h))
            self.assertEqual(r["ok"], ok)
        test.__name__ = f"test_valid_{_i}"
        test.__doc__ = f"验证 {_i}"
        return test
    setattr(TestGeneratedValidation,
            _make().__name__, _make())


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestGeneratedEdge(unittest.TestCase):
    """生成式: 边界"""
    pass


for _i, _concept in enumerate(["", "a", "b", "c", "d"]):
    def _make(concept=_concept):
        def test(self):
            graph = KnowledgeGraph()
            if concept:
                graph.add_concept(concept)
                self.assertIsNotNone(graph.get(concept))
            else:
                with self.assertRaises(Exception):
                    graph.add_concept("")
        test.__name__ = f"test_edge_{_i}"
        test.__doc__ = f"边界 {_i}"
        return test
    setattr(TestGeneratedEdge,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
