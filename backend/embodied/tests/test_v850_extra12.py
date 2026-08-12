"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 12 (V8.5 Extra12)

覆盖 (生成式批量矩阵):
    - 验证多样性矩阵
    - 创造边界矩阵
    - 服务容错矩阵
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.companion.creative_intelligence import (
    CreativeValidation,
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


# ── 验证多样性矩阵 ──────────────────────────────────────────────
_VALIDATION_VARIANTS = [
    ("根据观察, 因此可能有效", "inference"),
    ("来源显示结果", "inference"),
    ("可能存在问题", "inference"),
    ("没有依据", "inference"),
    ("推测方向", "inference"),
]


class TestGeneratedValidationVariants(unittest.TestCase):
    """生成式: 验证多样性"""
    pass


for _i, (_text, _ktype) in enumerate(_VALIDATION_VARIANTS):
    def _make(text=_text, ktype=_ktype):
        def test(self):
            h = {
                "hypothesis": "假设",
                "foundation": text,
                "reasoning": "有推理",
                "verification": "有验证",
            }
            r = CreativeValidation().validate(h)
            self.assertEqual(r["knowledge_type"], ktype)
        test.__name__ = f"test_vvariants_{_i}"
        test.__doc__ = f"验证多样性 {_text[:6]}"
        return test
    setattr(TestGeneratedValidationVariants,
            _make().__name__, _make())


# ── 创造边界矩阵 ────────────────────────────────────────────────
class TestCreativeBoundary(unittest.TestCase):
    """创造边界"""

    def test_single_concept_error(self):
        engine = MetaCreativeEngine(
            constitution=ConstitutionEngine(),
        )
        engine.load_experience([
            {"trigger": "唯一", "source": "x"},
        ])
        r = engine.create("问题")
        self.assertFalse(r["ok"])

    def test_two_concepts_ok(self):
        engine = MetaCreativeEngine(
            constitution=ConstitutionEngine(),
        )
        engine.load_experience([
            {"trigger": "概念A", "source": "x"},
            {"trigger": "概念B", "source": "x"},
        ])
        r = engine.create("问题")
        self.assertTrue(r["validation"]["ok"])

    def test_three_concepts_more_sparks(self):
        engine = MetaCreativeEngine(
            constitution=ConstitutionEngine(),
        )
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(3)
        ])
        r = engine.create("问题")
        self.assertGreaterEqual(len(r["sparks"]), 1)


# ── 服务容错矩阵 ────────────────────────────────────────────────
class TestServiceTolerance(unittest.TestCase):
    """服务容错"""

    def test_no_load_create_error_frame(self):
        svc = setup_service()
        r = svc.companion_meta_creative_create("问题")
        self.assertFalse(r["ok"])
        self.assertIn("无基础", r["reason"])

    def test_no_load_sparks_empty(self):
        svc = setup_service()
        r = svc.companion_meta_creative_sparks("问题")
        self.assertEqual(r["spark_count"], 0)

    def test_no_load_hypothesis_error(self):
        svc = setup_service()
        r = svc.companion_meta_creative_hypothesis("问题")
        self.assertFalse(r["ok"])

    def test_stats_empty_engine(self):
        svc = setup_service()
        stats = svc.companion_meta_creative_stats()
        self.assertEqual(stats["create_count"], 0)
        self.assertEqual(stats["graph"]["node_count"], 0)

    def test_reload_after_clear(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative.create("问题")
        svc.companion_meta_creative.clear()
        seed_and_load(svc)
        r = svc.companion_meta_creative.create("问题")
        self.assertTrue(r["validation"]["ok"])


# ── 配置矩阵 ────────────────────────────────────────────────────
class TestConfigMatrix(unittest.TestCase):
    """配置矩阵"""

    def test_memory_max_config(self):
        svc = setup_service(
            companion_meta_creative_memory_max=5,
        )
        memory = svc.companion_meta_creative._memory
        self.assertEqual(memory._max_records, 5)

    def test_max_sparks_config_bound(self):
        svc = setup_service(
            companion_meta_creative_max_sparks=2,
        )
        seed_and_load(svc)
        r = svc.companion_meta_creative_create("问题")
        self.assertLessEqual(len(r["sparks"]), 2)

    def test_constitution_link_config(self):
        svc = setup_service(
            companion_meta_creative_constitution_link=False,
        )
        self.assertIsNone(
            svc.companion_meta_creative._constitution)


if __name__ == "__main__":
    unittest.main()
