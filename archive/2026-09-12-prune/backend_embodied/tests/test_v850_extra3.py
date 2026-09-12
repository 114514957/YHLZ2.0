"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 3 (V8.5 Extra3)

覆盖 (生成式批量矩阵):
    - 知识图规模矩阵
    - 火花多样性矩阵
    - 验证边界矩阵
    - 服务级创造矩阵
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.companion.creative_intelligence import (
    ConceptFusion,
    CreativeValidation,
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
    for _ in range(3):
        mgr.store_from_event(
            success=True, trigger="模式发现",
            source="v850", action="a", result="成功",
        )
    for _ in range(2):
        mgr.store_from_event(
            success=False, trigger="拾取物体",
            source="v850", action="a", result="失败",
        )
    records = [
        r.to_dict()
        for r in mgr._store.all()
    ]
    svc.companion_meta_creative.load_experience(records)


# ── 知识图规模矩阵 ──────────────────────────────────────────────
_SCALE_CASES = [1, 3, 5, 8, 12]


class TestGeneratedGraphScale(unittest.TestCase):
    """生成式: 知识图规模"""
    pass


for _i, _n in enumerate(_SCALE_CASES):
    def _make(n=_n):
        def test(self):
            graph = KnowledgeGraph()
            for j in range(n):
                graph.add_concept(f"概念{j}")
            stats = graph.stats()
            self.assertEqual(stats["node_count"], n)
            self.assertEqual(stats["unconnected_count"], n)
        test.__name__ = f"test_scale_{_i}"
        test.__doc__ = f"规模 {_n}"
        return test
    setattr(TestGeneratedGraphScale,
            _make().__name__, _make())


# ── 火花多样性矩阵 ──────────────────────────────────────────────
_DIVERSITY_CASES = [
    (["A", "B"], ["C", "D"]),
    (["A", "B", "C"], ["D", "E"]),
    (["A", "B", "C", "D"], ["E", "F"]),
]


class TestGeneratedSparkDiversity(unittest.TestCase):
    """生成式: 火花多样性"""
    pass


for _i, (_connected, _lonely) in enumerate(_DIVERSITY_CASES):
    def _make(connected=_connected, lonely=_lonely):
        def test(self):
            graph = KnowledgeGraph()
            for a, b in zip(connected[:-1], connected[1:]):
                graph.add_relation(a, b)
            for c in lonely:
                graph.add_concept(c)
            gen = IdeaSparkGenerator(graph=graph)
            sparks = gen.generate("问题")
            types = {s["spark_type"] for s in sparks}
            self.assertIn("unconnected_link", types)
            self.assertIn("new_combination", types)
        test.__name__ = f"test_diversity_{_i}"
        test.__doc__ = f"多样性 {_i}"
        return test
    setattr(TestGeneratedSparkDiversity,
            _make().__name__, _make())


# ── 验证边界矩阵 ────────────────────────────────────────────────
_VALIDATION_EDGE_CASES = [
    ({"foundation": "有"}, False),
    ({"foundation": "有", "reasoning": "有"}, False),
    ({"foundation": "有", "reasoning": "有",
      "verification": "有"}, True),
    ({"foundation": "有", "reasoning": "有",
      "verification": "有",
      "hypothesis": "毫无疑问有效"}, False),
]


class TestGeneratedValidationEdge(unittest.TestCase):
    """生成式: 验证边界"""
    pass


for _i, (_h, _ok) in enumerate(_VALIDATION_EDGE_CASES):
    def _make(h=_h, ok=_ok):
        def test(self):
            r = CreativeValidation().validate(dict(h))
            self.assertEqual(r["ok"], ok)
        test.__name__ = f"test_vedge_{_i}"
        test.__doc__ = f"验证边界 {_i}"
        return test
    setattr(TestGeneratedValidationEdge,
            _make().__name__, _make())


# ── 组合推理矩阵 ────────────────────────────────────────────────
_FUSION_REASON_CASES = [
    ("经验", "创造", "transfer"),
    ("模式", "记忆", "merge"),
    ("互动", "价值", "analogy"),
    ("连续", "成长", "extension"),
]


class TestGeneratedFusionReason(unittest.TestCase):
    """生成式: 组合推理"""
    pass


for _i, (_a, _b, _logic) in enumerate(_FUSION_REASON_CASES):
    def _make(a=_a, b=_b, logic=_logic):
        def test(self):
            r = ConceptFusion().fuse(a, b, "情境", logic)
            self.assertIn("derivation", r)
            self.assertTrue(r["derivation"])
            self.assertEqual(r["sources"][0]["concept"], a)
            self.assertEqual(r["sources"][1]["concept"], b)
        test.__name__ = f"test_freason_{_i}"
        test.__doc__ = f"推理 {_a}+{_b}"
        return test
    setattr(TestGeneratedFusionReason,
            _make().__name__, _make())


# ── 服务级创造矩阵 ──────────────────────────────────────────────
class TestServiceCreate(unittest.TestCase):
    """服务级创造"""

    def setUp(self):
        self.svc = setup_service()
        seed_and_load(self.svc)

    def test_service_create_ok(self):
        r = self.svc.companion_meta_creative_create(
            "如何提升伙伴体验",
        )
        self.assertTrue(r["validation"]["ok"])
        self.assertTrue(r["output"])

    def test_service_sparks_ok(self):
        r = self.svc.companion_meta_creative_sparks(
            "如何提升",
        )
        self.assertGreaterEqual(r["spark_count"], 1)

    def test_service_hypothesis_ok(self):
        r = self.svc.companion_meta_creative_hypothesis(
            "如何提升",
        )
        self.assertIn("hypothesis", r)
        self.assertTrue(r["validation"]["ok"])

    def test_service_stats_after_creates(self):
        self.svc.companion_meta_creative_create("问题A")
        self.svc.companion_meta_creative_create("问题B")
        stats = self.svc.companion_meta_creative_stats()
        self.assertEqual(stats["create_count"], 2)

    def test_service_hybrid_route_note(self):
        r = self.svc.companion_meta_creative_create(
            "如何提升伙伴体验",
        )
        self.assertIn("hybrid", r)
        self.assertIn("route", r["hybrid"])

    def test_service_collaborate(self):
        r = self.svc.companion_meta_creative.collaborate(
            "人类方向", "AI分析",
        )
        self.assertIn("combined", r)


# ── 宪法联动矩阵 ────────────────────────────────────────────────
class TestConstitutionLink(unittest.TestCase):
    """宪法联动"""

    def test_engine_with_constitution(self):
        engine = MetaCreativeEngine(
            constitution=ConstitutionEngine(),
        )
        engine.load_experience([
            {"trigger": "模式发现", "source": "x"},
            {"trigger": "记忆整理", "source": "x"},
        ])
        r = engine.create("如何优化")
        self.assertIn("constitution_ok", r)

    def test_engine_without_constitution(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": "模式发现", "source": "x"},
            {"trigger": "记忆整理", "source": "x"},
        ])
        r = engine.create("如何优化")
        self.assertTrue(r["constitution_ok"])

    def test_link_disabled_config(self):
        svc = setup_service(
            companion_meta_creative_constitution_link=False,
        )
        seed_and_load(svc)
        r = svc.companion_meta_creative_create("问题")
        self.assertTrue(r["constitution_ok"])


if __name__ == "__main__":
    unittest.main()
