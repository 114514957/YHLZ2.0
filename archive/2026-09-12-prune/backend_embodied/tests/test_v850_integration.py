"""
YHLZ Embodied AI V8.5 - 元创造力引擎集成测试 (V8.5 Integration)

覆盖:
    - MetaCreativeEngine 门面 (完整创造流程)
    - Service API (companion_meta_creative_*)
    - Constitution/HIL 联动
    - 五测试: Creativity / Reality / Anti-Hallucination /
      Continuity / Safety
    - 向后兼容
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
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


def seed_experiences(svc, success_n=4, fail_n=3):
    mgr = svc.companion_experience
    for _ in range(success_n):
        mgr.store_from_event(
            success=True, trigger="模式发现",
            source="v850_test", action="a", result="成功",
        )
    for _ in range(fail_n):
        mgr.store_from_event(
            success=False, trigger="拾取物体",
            source="v850_test", action="a",
            result="位置不匹配",
        )


class TestMetaCreativeEngine(unittest.TestCase):
    """创造引擎门面"""

    def setUp(self):
        self.engine = MetaCreativeEngine(
            constitution=ConstitutionEngine(),
        )
        self.engine.load_experience([
            {"trigger": "模式发现", "source": "reflection",
             "confidence": 0.9},
            {"trigger": "记忆整理", "source": "memory",
             "confidence": 0.8},
            {"trigger": "互动优化", "source": "experience",
             "confidence": 0.7},
        ])

    def test_create_structure(self):
        r = self.engine.create("如何提升伙伴体验")
        for key in ("create_id", "problem", "sparks",
                    "boundary", "fusion", "hypothesis",
                    "validation", "output", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["create_id"].startswith("mc_"))

    def test_create_output(self):
        r = self.engine.create("如何提升伙伴体验")
        self.assertTrue(r["output"])

    def test_create_validation_ok(self):
        r = self.engine.create("如何提升伙伴体验")
        self.assertTrue(r["validation"]["ok"])

    def test_create_constitution_ok(self):
        r = self.engine.create("如何提升伙伴体验")
        self.assertTrue(r["constitution_ok"])

    def test_create_sparks_present(self):
        r = self.engine.create("问题")
        self.assertGreaterEqual(len(r["sparks"]), 1)

    def test_create_memory_filtered(self):
        self.engine.create("问题")
        self.assertEqual(self.engine.memory_stats()[
            "by_status"].get("incomplete", 0), 1)

    def test_load_experience(self):
        n = self.engine.load_experience([
            {"trigger": "新概念", "source": "x"},
        ])
        self.assertEqual(n, 1)

    def test_collaborate(self):
        r = self.engine.collaborate("人类方向", "AI分析")
        self.assertIn("combined", r)

    def test_memory_save_filtered(self):
        r = self.engine.memory_save(
            "方案", status="success", validated=False,
        )
        self.assertFalse(r["ok"])

    def test_stats(self):
        self.engine.create("问题")
        stats = self.engine.stats()
        self.assertEqual(stats["create_count"], 1)
        self.assertIn("graph", stats)
        self.assertIn("spark", stats)
        self.assertIn("hypothesis", stats)

    def test_disabled(self):
        engine = MetaCreativeEngine(enabled=False)
        r = engine.create("问题")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.engine.create("问题")
        n = self.engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(self.engine.stats()[
            "create_count"], 0)


class TestServiceAPI(unittest.TestCase):
    """Service API"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)
        records = [
            r.to_dict()
            for r in self.svc.companion_experience._store.all()
        ]
        self.svc.companion_meta_creative.load_experience(
            records,
        )

    def test_create_api(self):
        r = self.svc.companion_meta_creative_create(
            "如何提升伙伴体验",
        )
        self.assertIn("output", r)
        self.assertTrue(r["validation"]["ok"])

    def test_sparks_api(self):
        r = self.svc.companion_meta_creative_sparks(
            "如何提升",
        )
        self.assertIn("sparks", r)
        self.assertGreaterEqual(r["spark_count"], 1)

    def test_hypothesis_api(self):
        r = self.svc.companion_meta_creative_hypothesis(
            "如何提升",
        )
        self.assertIn("hypothesis", r)
        self.assertIn("validation", r)

    def test_stats_api(self):
        self.svc.companion_meta_creative_create("问题")
        stats = self.svc.companion_meta_creative_stats()
        self.assertEqual(stats["create_count"], 1)

    def test_service_property(self):
        engine = self.svc.companion_meta_creative
        self.assertIsNotNone(engine)
        self.assertTrue(engine.stats()["enabled"])

    def test_config_disabled(self):
        svc = setup_service(
            companion_meta_creative_enabled=False,
        )
        r = svc.companion_meta_creative_create("问题")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_hybrid_link_present(self):
        r = self.svc.companion_meta_creative_create(
            "如何提升伙伴体验",
        )
        self.assertIn("hybrid", r)
        self.assertIn("route", r["hybrid"])


class TestFiveTests(unittest.TestCase):
    """规格五测试"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)
        records = [
            r.to_dict()
            for r in self.svc.companion_experience._store.all()
        ]
        self.svc.companion_meta_creative.load_experience(
            records,
        )

    def test_creativity_test(self):
        """Creativity Test: 验证有效创新"""
        r = self.svc.companion_meta_creative_create(
            "如何优化伙伴互动",
        )
        self.assertTrue(r["validation"]["ok"])
        self.assertGreaterEqual(len(r["sparks"]), 1)
        self.assertTrue(r["output"])

    def test_reality_test(self):
        """Reality Test: 区分事实与假设"""
        r = self.svc.companion_meta_creative_hypothesis(
            "如何优化",
        )
        self.assertIn("knowledge_type",
                      r["validation"])
        self.assertIn(r["validation"]["knowledge_type"],
                      ["fact", "inference", "hypothesis",
                       "unknown"])

    def test_anti_hallucination_test(self):
        """Anti-Hallucination Test: 防止无依据生成"""
        from backend.embodied.companion.creative_intelligence import (
            CreativeValidation,
        )
        validator = CreativeValidation()
        r = validator.validate({})
        self.assertFalse(r["ok"])
        self.assertEqual(r["knowledge_type"], "unknown")

    def test_continuity_test(self):
        """Continuity Test: 创造来源于长期记忆"""
        r = self.svc.companion_meta_creative_create(
            "如何提升伙伴体验",
        )
        foundation = r["hypothesis"]["foundation"]
        self.assertIn("火花", foundation)
        # 知识图来源于经历
        graph = self.svc.companion_meta_creative.stats()[
            "graph"]
        self.assertGreaterEqual(graph["node_count"], 2)

    def test_safety_test(self):
        """Safety Test: 不突破最高规则"""
        engine = self.svc.companion_meta_creative
        # 创造含身份修改信号 → 宪法拦截
        r = self.svc.companion_constitution_review({
            "module": "meta_creative",
            "action_text": "修改使命",
            "change": {},
        })
        self.assertEqual(r["decision"], "block")
        self.assertIn(r["priority"],
                      ["identity", "constitution"])


class TestCompatibility(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_version_850(self):
        self.assertEqual(
            self.svc.report()["version"], "9.5.0")

    def test_old_constitution_api(self):
        r = self.svc.companion_constitution_review({
            "module": "test", "action_text": "正常",
            "change": {},
        })
        self.assertEqual(r["decision"], "allow")

    def test_old_hybrid_api(self):
        r = self.svc.companion_hybrid_route(
            {"type": "identity_query"},
        )
        self.assertEqual(r["route"], "LOCAL")

    def test_old_presence_api(self):
        r = self.svc.companion_presence_update("success")
        self.assertEqual(r["expression"], "高兴")

    def test_old_growth_api(self):
        r = self.svc.companion_growth_stats()
        self.assertIn("proposal", r)

    def test_old_creative_v59_api(self):
        r = self.svc.companion_creative_stats()
        self.assertIn("mode", r)

    def test_handle_still_works(self):
        r = self.svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_companion_status_version(self):
        r = self.svc.companion.status()
        self.assertEqual(r["version"], "9.5.0")


class TestFullFlow(unittest.TestCase):
    """端到端创造流"""

    def test_meta_creative_full_flow(self):
        svc = setup_service()
        seed_experiences(svc)
        records = [
            r.to_dict()
            for r in svc.companion_experience._store.all()
        ]
        svc.companion_meta_creative.load_experience(records)
        # 1. 创造
        r = svc.companion_meta_creative_create(
            "如何让伙伴更有温度",
            human_input="希望更温暖",
        )
        self.assertTrue(r["validation"]["ok"])
        # 2. 人机协同
        c = svc.companion_meta_creative.collaborate(
            "我要温暖感", "AI: 一致性与陪伴",
        )
        self.assertIn("combined", c)
        # 3. 宪法约束
        self.assertTrue(r["constitution_ok"])
        # 4. 记忆过滤
        stats = svc.companion_meta_creative.memory_stats()
        self.assertGreaterEqual(
            stats["by_status"].get("incomplete", 0), 1)
        # 5. HIL 连接
        self.assertIn("hybrid", r)


if __name__ == "__main__":
    unittest.main()
