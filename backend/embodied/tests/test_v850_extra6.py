"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 6 (V8.5 Extra6)

覆盖 (生成式批量矩阵):
    - 假设-验证联合矩阵
    - 协同-记忆矩阵
    - 服务联动矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    ConceptFusion,
    CreativeValidation,
    HypothesisEngine,
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


# ── 假设-验证联合矩阵 ───────────────────────────────────────────
_FUSION_INPUTS = [
    ("经验", "创造", "merge"),
    ("模式", "记忆", "transfer"),
    ("互动", "价值", "analogy"),
    ("连续", "成长", "extension"),
    ("感知", "理解", "merge"),
]


class TestGeneratedHypothesisValidation(unittest.TestCase):
    """生成式: 假设-验证"""
    pass


for _i, (_a, _b, _logic) in enumerate(_FUSION_INPUTS):
    def _make(a=_a, b=_b, logic=_logic):
        def test(self):
            fusion = ConceptFusion().fuse(a, b, "情境", logic)
            h = HypothesisEngine().build(None, fusion)
            v = CreativeValidation().validate(h)
            self.assertTrue(v["ok"])
            self.assertEqual(v["knowledge_type"],
                             "inference")
            self.assertTrue(h["falsifiable"])
        test.__name__ = f"test_hv_{_i}"
        test.__doc__ = f"假设验证 {_a}+{_b}"
        return test
    setattr(TestGeneratedHypothesisValidation,
            _make().__name__, _make())


# ── 协同-记忆矩阵 ───────────────────────────────────────────────
class TestCollabMemory(unittest.TestCase):
    """协同与记忆"""

    def test_collab_after_creates(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative_create("问题")
        r = svc.companion_meta_creative.collaborate(
            "人类方向", "AI分析", "目标",
        )
        self.assertIn("combined", r)
        self.assertEqual(r["goal"], "目标")

    def test_memory_and_collab_stats(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative_create("问题A")
        svc.companion_meta_creative.collaborate("a", "b")
        stats = svc.companion_meta_creative.stats()
        self.assertGreaterEqual(stats["create_count"], 1)
        self.assertGreaterEqual(
            stats["collaborative"]["collab_count"], 1)


# ── 服务联动矩阵 ────────────────────────────────────────────────
class TestServiceLinkage(unittest.TestCase):
    """服务联动"""

    def test_create_after_many_experiences(self):
        svc = setup_service()
        seed_and_load(svc)
        r = svc.companion_meta_creative_create(
            "如何提升伙伴体验",
        )
        self.assertTrue(r["validation"]["ok"])

    def test_sparks_without_create(self):
        svc = setup_service()
        seed_and_load(svc)
        r = svc.companion_meta_creative_sparks("问题")
        self.assertGreaterEqual(r["spark_count"], 1)

    def test_hypothesis_without_create(self):
        svc = setup_service()
        seed_and_load(svc)
        r = svc.companion_meta_creative_hypothesis("问题")
        self.assertTrue(r["validation"]["ok"])

    def test_stats_after_mixed(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative_create("问题A")
        svc.companion_meta_creative_sparks("问题B")
        svc.companion_meta_creative_hypothesis("问题C")
        stats = svc.companion_meta_creative_stats()
        self.assertEqual(stats["create_count"], 1)
        self.assertGreaterEqual(stats["spark"]["spark_count"],
                                1)


# ── 图边界矩阵 ──────────────────────────────────────────────────
class TestGeneratedGraphBoundary(unittest.TestCase):
    """生成式: 图边界"""

    def test_large_graph(self):
        graph = KnowledgeGraph()
        for i in range(50):
            graph.add_concept(f"概念{i}")
        stats = graph.stats()
        self.assertEqual(stats["node_count"], 50)

    def test_many_relations(self):
        graph = KnowledgeGraph()
        for i in range(20):
            graph.add_relation(f"A{i}", f"B{i}")
        self.assertEqual(graph.stats()["relation_count"], 20)

    def test_cycle_relations(self):
        graph = KnowledgeGraph()
        graph.add_relation("A", "B")
        graph.add_relation("B", "C")
        graph.add_relation("C", "A")
        self.assertEqual(graph.stats()["node_count"], 3)
        self.assertEqual(graph.stats()["unconnected_count"],
                         0)


if __name__ == "__main__":
    unittest.main()
