"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 5 (V8.5 Extra5)

覆盖 (生成式批量矩阵):
    - 概念-关系-火花联动矩阵
    - 验证检查矩阵
    - 服务端到端矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    CreativeValidation,
    IdeaSparkGenerator,
    KnowledgeGraph,
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


def seed_and_load(svc, triggers=("模式发现", "记忆整理",
                                 "互动优化")):
    mgr = svc.companion_experience
    for trig in triggers:
        for _ in range(2):
            mgr.store_from_event(
                success=True, trigger=trig,
                source="v850", action="a", result="成功",
            )
    records = [r.to_dict() for r in mgr._store.all()]
    svc.companion_meta_creative.load_experience(records)


# ── 概念-关系-火花联动矩阵 ──────────────────────────────────────
_GRAPH_SPARK_CASES = [
    (["A", "B"], [], "unconnected_link"),
    (["A", "B", "C"], [("A", "B")], "potential_relation"),
    (["A", "B"], [("A", "B")], "potential_relation"),
]


class TestGeneratedGraphSpark(unittest.TestCase):
    """生成式: 图-火花联动"""
    pass


for _i, (_concepts, _rels, _expect_type) in \
        enumerate(_GRAPH_SPARK_CASES):
    def _make(concepts=_concepts, rels=_rels,
              expect_type=_expect_type):
        def test(self):
            graph = KnowledgeGraph()
            for c in concepts:
                graph.add_concept(c)
            for (a, b) in rels:
                graph.add_relation(a, b)
            gen = IdeaSparkGenerator(graph=graph)
            sparks = gen.generate("问题")
            types = [s["spark_type"] for s in sparks]
            self.assertIn(expect_type, types)
        test.__name__ = f"test_gspark_{_i}"
        test.__doc__ = f"图火花 {_i}"
        return test
    setattr(TestGeneratedGraphSpark,
            _make().__name__, _make())


# ── 验证检查矩阵 ────────────────────────────────────────────────
_CHECK_NAMES = ["foundation", "reasoning", "logic_jump",
                "verifiable"]


class TestGeneratedChecks(unittest.TestCase):
    """生成式: 验证检查"""
    pass


for _i, _name in enumerate(_CHECK_NAMES):
    def _make(name=_name):
        def test(self):
            good = {
                "foundation": "有依据",
                "reasoning": "有推理",
                "verification": "有验证",
            }
            r = CreativeValidation().validate(
                dict(good, hypothesis="x"),
            )
            self.assertTrue(r["ok"])
            check = next(c for c in r["checks"]
                         if c["name"] == name)
            self.assertTrue(check["passed"])
        test.__name__ = f"test_check_{_i}"
        test.__doc__ = f"检查 {_name}"
        return test
    setattr(TestGeneratedChecks,
            _make().__name__, _make())


# ── 服务端到端矩阵 ──────────────────────────────────────────────
_SERVICE_PROBLEMS = [
    "如何提升伙伴体验",
    "如何优化记忆管理",
    "如何增强互动温度",
]


class TestGeneratedServiceProblems(unittest.TestCase):
    """生成式: 服务问题"""
    pass


for _i, _problem in enumerate(_SERVICE_PROBLEMS):
    def _make(problem=_problem):
        def test(self):
            svc = setup_service()
            seed_and_load(svc)
            r = svc.companion_meta_creative_create(problem)
            self.assertTrue(r["validation"]["ok"])
            self.assertTrue(r["output"])
            self.assertIn("hybrid", r)
        test.__name__ = f"test_svc_prob_{_i}"
        test.__doc__ = f"服务问题 {_problem[:6]}"
        return test
    setattr(TestGeneratedServiceProblems,
            _make().__name__, _make())


# ── 服务记忆矩阵 ────────────────────────────────────────────────
class TestServiceMemory(unittest.TestCase):
    """服务记忆"""

    def test_memory_after_creates(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative_create("问题A")
        svc.companion_meta_creative_create("问题B")
        stats = svc.companion_meta_creative.memory_stats()
        self.assertGreaterEqual(
            stats["by_status"].get("incomplete", 0), 2)

    def test_memory_filter_service(self):
        svc = setup_service()
        r = svc.companion_meta_creative.memory_save(
            "未验证方案", validated=False,
        )
        self.assertFalse(r["ok"])

    def test_memory_all_statuses(self):
        svc = setup_service()
        for status in ("success", "failure", "incomplete",
                       "falsified"):
            svc.companion_meta_creative.memory_save(
                f"内容_{status}", status=status,
                validated=True,
            )
        stats = svc.companion_meta_creative.memory_stats()
        self.assertEqual(stats["record_count"], 4)
        self.assertEqual(len(stats["by_status"]), 4)


# ── 组合边界矩阵 ────────────────────────────────────────────────
class TestGeneratedCombos(unittest.TestCase):
    """生成式: 组合边界"""

    def test_relation_chain(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "B")
        graph.add_relation("B", "C")
        graph.add_relation("C", "D")
        self.assertEqual(graph.stats()["relation_count"], 3)
        self.assertEqual(graph.stats()["node_count"], 4)
        self.assertEqual(graph.stats()["unconnected_count"],
                         0)

    def test_unconnected_after_partial(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "B")
        graph.add_concept("孤岛")
        self.assertEqual(graph.stats()["unconnected_count"],
                         1)

    def test_spark_confidence_stable(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "B")
        graph.add_concept("孤岛1")
        graph.add_concept("孤岛2")
        gen = IdeaSparkGenerator(graph=graph)
        sparks = gen.generate("问题")
        for s in sparks:
            self.assertGreaterEqual(s["confidence"], 0.3)
            self.assertLessEqual(s["confidence"], 0.7)


if __name__ == "__main__":
    unittest.main()
