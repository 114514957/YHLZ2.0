"""
YHLZ Embodied AI V8.5 - 概念重组与边界检测单元测试 (Fusion & Boundary)

覆盖:
    - ConceptFusion: 重组/来源/推导
    - ThoughtBoundaryDetector: 已知/未知边界/探索方向
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    ConceptFusion,
    KnowledgeGraph,
    ThoughtBoundaryDetector,
)
from backend.embodied.companion.creative_intelligence.concept_fusion import (
    FUSION_LOGIC_TYPES,
    FusionError,
)


class TestConceptFusion(unittest.TestCase):
    """概念重组"""

    def setUp(self):
        self.fusion = ConceptFusion()

    def test_fuse_merge(self):
        r = self.fusion.fuse("A", "B", "新情境", "merge")
        self.assertEqual(r["fusion_logic"], "merge")
        self.assertIn("融合", r["new_concept"])
        self.assertTrue(r["fusion_id"].startswith("cf_"))

    def test_fuse_analogy(self):
        r = self.fusion.fuse("A", "B", "", "analogy")
        self.assertIn("类比", r["new_concept"])

    def test_fuse_transfer(self):
        r = self.fusion.fuse("A", "B", "", "transfer")
        self.assertIn("迁移", r["new_concept"])

    def test_fuse_extension(self):
        r = self.fusion.fuse("A", "B", "", "extension")
        self.assertIn("延伸", r["new_concept"])

    def test_result_structure(self):
        r = self.fusion.fuse("A", "B", "ctx", "merge")
        for key in ("fusion_id", "new_concept",
                    "fusion_logic", "derivation", "sources",
                    "new_context", "mode"):
            self.assertIn(key, r)

    def test_sources_recorded(self):
        r = self.fusion.fuse("A", "B", "", "merge")
        self.assertEqual(len(r["sources"]), 2)
        self.assertEqual(r["sources"][0]["concept"], "A")

    def test_derivation_explainable(self):
        r = self.fusion.fuse("模式发现", "记忆整理", "",
                             "transfer")
        self.assertIn("迁移", r["derivation"])

    def test_empty_concept_error(self):
        with self.assertRaises(FusionError):
            self.fusion.fuse("", "B")

    def test_invalid_logic(self):
        with self.assertRaises(FusionError):
            self.fusion.fuse("A", "B", "", "bogus")

    def test_logic_types_constant(self):
        self.assertEqual(FUSION_LOGIC_TYPES,
                         ["analogy", "merge", "transfer",
                          "extension"])

    def test_stats(self):
        self.fusion.fuse("A", "B", "", "merge")
        self.fusion.fuse("C", "D", "", "analogy")
        stats = self.fusion.stats()
        self.assertEqual(stats["fusion_count"], 2)
        self.assertEqual(stats["by_logic"]["merge"], 1)

    def test_history(self):
        self.fusion.fuse("A", "B", "", "merge")
        h = self.fusion.history()
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["new_context"], "")

    def test_disabled(self):
        fusion = ConceptFusion(enabled=False)
        r = fusion.fuse("A", "B")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.fusion.fuse("A", "B")
        n = self.fusion.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.fusion.stats()[
            "fusion_count"], 0)


class TestThoughtBoundaryDetector(unittest.TestCase):
    """思维断口"""

    def setUp(self):
        self.graph = KnowledgeGraph()
        self.graph.add_relation("模式发现", "记忆整理")
        self.graph.add_concept("孤立概念")
        self.detector = ThoughtBoundaryDetector(graph=self.graph)

    def test_detect_structure(self):
        r = self.detector.detect("如何优化")
        for key in ("boundary_id", "known_area",
                    "unknown_boundary",
                    "exploration_direction", "confidence",
                    "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["boundary_id"].startswith("bd_"))

    def test_known_area_from_problem(self):
        r = self.detector.detect("模式发现如何提升")
        self.assertIn("模式发现", r["known_area"])

    def test_unknown_boundary(self):
        r = self.detector.detect("问题")
        self.assertGreaterEqual(len(r["unknown_boundary"]),
                                1)

    def test_exploration_directions(self):
        r = self.detector.detect("问题")
        self.assertGreaterEqual(
            len(r["exploration_direction"]), 1)

    def test_known_concepts_param(self):
        r = self.detector.detect(
            "问题", known_concepts=["概念X"],
        )
        self.assertIn("概念X", r["known_area"])

    def test_confidence_range(self):
        r = self.detector.detect("问题")
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_reason_explainable(self):
        r = self.detector.detect("问题")
        self.assertIn("已知", r["reason"])

    def test_disabled(self):
        detector = ThoughtBoundaryDetector(enabled=False)
        r = detector.detect("问题")
        self.assertEqual(r["exploration_direction"], [])
        self.assertIn("停用", r["reason"])

    def test_no_graph(self):
        detector = ThoughtBoundaryDetector()
        r = detector.detect("问题", known_concepts=["A"])
        self.assertIn("A", r["known_area"])

    def test_stats(self):
        self.detector.detect("问题")
        self.assertEqual(self.detector.stats()[
            "detect_count"], 1)

    def test_clear(self):
        self.detector.detect("问题")
        self.detector.clear()
        self.assertEqual(self.detector.stats()[
            "detect_count"], 0)


if __name__ == "__main__":
    unittest.main()
