"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 13 (V8.5 Extra13)

覆盖 (生成式批量矩阵):
    - 假设质量矩阵
    - 服务矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    ConceptFusion,
    CreativeValidation,
    HypothesisEngine,
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
    for trig in ("模式发现", "记忆整理"):
        for _ in range(2):
            mgr.store_from_event(
                success=True, trigger=trig,
                source="v850", action="a", result="成功",
            )
    records = [r.to_dict() for r in mgr._store.all()]
    svc.companion_meta_creative.load_experience(records)


# ── 假设质量矩阵 ────────────────────────────────────────────────
_FUSION_QUALITY_CASES = [
    ("模式", "记忆"),
    ("经验", "创造"),
    ("互动", "价值"),
    ("感知", "理解"),
    ("连续", "成长"),
    ("情绪", "表达"),
]


class TestGeneratedHypothesisQuality(unittest.TestCase):
    """生成式: 假设质量"""
    pass


for _i, (_a, _b) in enumerate(_FUSION_QUALITY_CASES):
    def _make(a=_a, b=_b):
        def test(self):
            fusion = ConceptFusion().fuse(a, b, "情境")
            h = HypothesisEngine().build(None, fusion)
            # 五字段质量
            self.assertTrue(h["hypothesis"])
            self.assertTrue(h["foundation"])
            self.assertTrue(h["reasoning"])
            self.assertGreaterEqual(h["confidence"], 0.5)
            self.assertTrue(h["verification"])
            self.assertTrue(h["falsifiable"])
            # 验证通过
            v = CreativeValidation().validate(h)
            self.assertTrue(v["ok"])
        test.__name__ = f"test_hquality_{_i}"
        test.__doc__ = f"假设质量 {_a}+{_b}"
        return test
    setattr(TestGeneratedHypothesisQuality,
            _make().__name__, _make())


# ── 服务矩阵 ────────────────────────────────────────────────────
class TestServiceFinal(unittest.TestCase):
    """服务最终"""

    def test_full_flow_with_human(self):
        svc = setup_service()
        seed_and_load(svc)
        r = svc.companion_meta_creative_create(
            "如何提升伙伴体验",
            human_input="希望更自然温暖",
        )
        self.assertTrue(r["validation"]["ok"])
        self.assertIn("hybrid", r)

    def test_create_stats_and_memory(self):
        svc = setup_service()
        seed_and_load(svc)
        r = svc.companion_meta_creative_create("问题A")
        r2 = svc.companion_meta_creative_create("问题B")
        stats = svc.companion_meta_creative.stats()
        self.assertEqual(stats["create_count"], 2)
        self.assertTrue(r["output"])
        self.assertTrue(r2["output"])

    def test_stats_sections(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative_create("问题")
        stats = svc.companion_meta_creative.stats()
        self.assertEqual(stats["mode"], "rule_based")
        self.assertTrue(stats["enabled"])
        self.assertIn("blocked_count", stats)

    def test_disabled_sparks(self):
        svc = setup_service(
            companion_meta_creative_enabled=False,
        )
        seed_and_load(svc)
        r = svc.companion_meta_creative_create("问题")
        self.assertFalse(r["ok"])


# ── 引擎矩阵 ────────────────────────────────────────────────────
class TestEngineFinal(unittest.TestCase):
    """引擎最终"""

    def test_create_repeat_stable(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(6)
        ])
        for _ in range(3):
            r = engine.create("如何优化")
            self.assertTrue(r["validation"]["ok"])

    def test_memory_after_create(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        engine.create("问题")
        stats = engine.memory_stats()
        self.assertGreaterEqual(stats["record_count"], 1)

    def test_graph_after_load(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        self.assertEqual(
            engine.stats()["graph"]["node_count"], 4)


if __name__ == "__main__":
    unittest.main()
