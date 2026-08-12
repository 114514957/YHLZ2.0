"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 9 (V8.5 Extra9)

覆盖 (生成式批量矩阵):
    - 创造-验证-记忆闭环矩阵
    - 服务配置矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
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


# ── 创造-验证-记忆闭环矩阵 ──────────────────────────────────────
_CLOSED_LOOP_CASES = [
    "如何提升效率",
    "如何优化记忆",
    "如何增强互动",
    "如何探索未知",
    "如何创造价值",
    "如何保持连续",
]


class TestGeneratedClosedLoop(unittest.TestCase):
    """生成式: 闭环"""
    pass


for _i, _problem in enumerate(_CLOSED_LOOP_CASES):
    def _make(problem=_problem):
        def test(self):
            engine = MetaCreativeEngine()
            engine.load_experience([
                {"trigger": f"C{j}", "source": "x"}
                for j in range(4)
            ])
            r = engine.create(problem)
            # 验证通过 → 记忆保存
            self.assertTrue(r["validation"]["ok"])
            memory = engine.memory_stats()
            self.assertGreaterEqual(
                memory["record_count"], 1)
            # 假设可证伪
            self.assertTrue(r["hypothesis"]["falsifiable"])
            # 知识类型明确
            self.assertIn(
                r["validation"]["knowledge_type"],
                ["fact", "inference", "hypothesis",
                 "unknown"])
        test.__name__ = f"test_loop_{_i}"
        test.__doc__ = f"闭环 {_problem[:6]}"
        return test
    setattr(TestGeneratedClosedLoop,
            _make().__name__, _make())


# ── 服务配置矩阵 ────────────────────────────────────────────────
class TestServiceConfig(unittest.TestCase):
    """服务配置"""

    def test_max_sparks_config(self):
        svc = setup_service(
            companion_meta_creative_max_sparks=3,
        )
        seed_and_load(svc)
        r = svc.companion_meta_creative_create("问题")
        self.assertLessEqual(len(r["sparks"]), 3)

    def test_enabled_default(self):
        svc = setup_service()
        engine = svc.companion_meta_creative
        self.assertTrue(engine.stats()["enabled"])

    def test_disabled_returns_error(self):
        svc = setup_service(
            companion_meta_creative_enabled=False,
        )
        r = svc.companion_meta_creative_create("问题")
        self.assertFalse(r["ok"])

    def test_stats_shape(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative_create("问题")
        stats = svc.companion_meta_creative_stats()
        for key in ("graph", "spark", "fusion", "boundary",
                    "hypothesis", "validation", "memory",
                    "collaborative"):
            self.assertIn(key, stats)


# ── 知识图质量矩阵 ──────────────────────────────────────────────
class TestGraphQuality(unittest.TestCase):
    """知识图质量"""

    def test_confidence_loaded(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": "A", "confidence": 0.95},
        ])
        node = engine._graph.get("A")
        self.assertEqual(node["confidence"], 0.95)

    def test_source_loaded(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": "A", "source": "reflection"},
        ])
        node = engine._graph.get("A")
        self.assertEqual(node["source"], "reflection")

    def test_category_by_source(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": "A", "source": "x"},
        ])
        node = engine._graph.get("A")
        self.assertEqual(node["category"], "experience")


if __name__ == "__main__":
    unittest.main()
