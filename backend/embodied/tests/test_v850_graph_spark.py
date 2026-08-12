"""
YHLZ Embodied AI V8.5 - 知识图与思维火花单元测试 (Graph & Spark)

覆盖:
    - KnowledgeGraph: 节点/关系/未连接发现
    - IdeaSparkGenerator: 火花类型/依据
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    IdeaSparkGenerator,
    KnowledgeGraph,
)


class TestKnowledgeGraph(unittest.TestCase):
    """知识图"""

    def setUp(self):
        self.graph = KnowledgeGraph()

    def test_add_concept(self):
        node = self.graph.add_concept("模式发现", "method")
        self.assertEqual(node["concept"], "模式发现")
        self.assertEqual(node["category"], "method")
        self.assertTrue(node["node_id"].startswith("kg_"))

    def test_get_concept(self):
        self.graph.add_concept("记忆")
        got = self.graph.get("记忆")
        self.assertEqual(got["concept"], "记忆")

    def test_get_missing(self):
        self.assertIsNone(self.graph.get("不存在"))

    def test_empty_concept_error(self):
        with self.assertRaises(Exception):
            self.graph.add_concept("")

    def test_add_relation(self):
        self.graph.add_concept("A")
        self.graph.add_concept("B")
        rel = self.graph.add_relation("A", "B", "推导")
        self.assertEqual(rel["from"], "A")
        self.assertEqual(rel["to"], "B")

    def test_relation_auto_creates_concepts(self):
        self.graph.add_relation("X", "Y")
        self.assertIsNotNone(self.graph.get("X"))
        self.assertIsNotNone(self.graph.get("Y"))

    def test_relations_of(self):
        self.graph.add_relation("A", "B")
        rels = self.graph.relations_of("A")
        self.assertEqual(len(rels), 1)

    def test_unconnected(self):
        self.graph.add_concept("孤立1")
        self.graph.add_concept("孤立2")
        self.graph.add_relation("连接A", "连接B")
        lonely = self.graph.unconnected()
        names = [n["concept"] for n in lonely]
        self.assertIn("孤立1", names)
        self.assertIn("孤立2", names)
        self.assertNotIn("连接A", names)

    def test_unconnected_empty(self):
        self.graph.add_relation("A", "B")
        self.assertEqual(self.graph.unconnected(), [])

    def test_neighbors(self):
        self.graph.add_relation("A", "B")
        self.graph.add_relation("A", "C")
        nbs = self.graph.neighbors("A")
        self.assertEqual(len(nbs), 2)

    def test_load_records(self):
        n = self.graph.load_records([
            {"trigger": "模式发现", "source": "reflection",
             "confidence": 0.9},
            {"trigger": "拾取物体", "source": "experience",
             "confidence": 0.7},
            {"trigger": "", "source": "x"},
        ])
        self.assertEqual(n, 2)
        self.assertEqual(self.graph.stats()["node_count"], 2)

    def test_stats(self):
        self.graph.add_concept("A", "method")
        self.graph.add_relation("A", "B")
        stats = self.graph.stats()
        self.assertEqual(stats["node_count"], 2)
        self.assertEqual(stats["relation_count"], 1)
        self.assertIn("by_category", stats)

    def test_duplicate_concept_updates(self):
        self.graph.add_concept("A", "cat1")
        self.graph.add_concept("A", "cat2")
        self.assertEqual(self.graph.get("A")["category"],
                         "cat2")

    def test_confidence_clamp(self):
        self.graph.add_concept("A", confidence=2.0)
        self.assertEqual(self.graph.get("A")["confidence"],
                         1.0)

    def test_clear(self):
        self.graph.add_relation("A", "B")
        n = self.graph.clear()
        self.assertEqual(n, 3)
        self.assertEqual(self.graph.stats()["node_count"], 0)


class TestIdeaSparkGenerator(unittest.TestCase):
    """思维火花"""

    def setUp(self):
        self.graph = KnowledgeGraph()
        self.graph.add_relation("模式发现", "记忆整理")
        self.graph.add_relation("互动优化", "模式发现")
        self.graph.add_concept("拾取物体")
        self.graph.add_concept("孤立目标")
        self.generator = IdeaSparkGenerator(graph=self.graph)

    def test_generate_sparks(self):
        sparks = self.generator.generate("提升伙伴体验")
        self.assertGreaterEqual(len(sparks), 1)

    def test_spark_structure(self):
        sparks = self.generator.generate("问题")
        s = sparks[0]
        for key in ("spark_id", "spark_type", "idea", "basis",
                    "confidence", "related_concepts",
                    "created_at"):
            self.assertIn(key, s)
        self.assertTrue(s["spark_id"].startswith("sp_"))

    def test_unconnected_link_type(self):
        sparks = self.generator.generate("问题")
        types = [s["spark_type"] for s in sparks]
        self.assertIn("unconnected_link", types)

    def test_new_combination_type(self):
        sparks = self.generator.generate("问题")
        types = [s["spark_type"] for s in sparks]
        self.assertIn("new_combination", types)

    def test_spark_has_basis(self):
        sparks = self.generator.generate("问题")
        for s in sparks:
            self.assertTrue(s["basis"])

    def test_confidence_range(self):
        sparks = self.generator.generate("问题")
        for s in sparks:
            self.assertGreaterEqual(s["confidence"], 0.0)
            self.assertLessEqual(s["confidence"], 1.0)

    def test_no_graph_no_sparks(self):
        generator = IdeaSparkGenerator()
        self.assertEqual(generator.generate("问题"), [])

    def test_max_sparks(self):
        generator = IdeaSparkGenerator(graph=self.graph,
                                       max_sparks=2)
        sparks = generator.generate("问题")
        self.assertLessEqual(len(sparks), 2)

    def test_disabled(self):
        generator = IdeaSparkGenerator(graph=self.graph,
                                       enabled=False)
        self.assertEqual(generator.generate("问题"), [])

    def test_stats(self):
        self.generator.generate("问题")
        stats = self.generator.stats()
        self.assertGreaterEqual(stats["spark_count"], 1)
        self.assertIn("by_type", stats)

    def test_clear(self):
        self.generator.generate("问题")
        n = self.generator.clear()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(self.generator.stats()[
            "spark_count"], 0)


if __name__ == "__main__":
    unittest.main()
