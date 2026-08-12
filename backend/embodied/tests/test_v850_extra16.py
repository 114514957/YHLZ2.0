"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 16 (V8.5 Extra16)

覆盖 (生成式批量):
    - 最终验收矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    CreativeMemory,
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


class TestFinalAcceptance(unittest.TestCase):
    """最终验收"""

    def test_memory_statuses_all(self):
        memory = CreativeMemory()
        for status in ("success", "failure", "incomplete",
                       "falsified"):
            memory.save(f"内容_{status}", status=status,
                        validated=True)
        stats = memory.stats()
        self.assertEqual(stats["record_count"], 4)
        self.assertEqual(len(stats["by_status"]), 4)

    def test_validation_complete(self):
        r = CreativeValidation().validate({
            "hypothesis": "h",
            "foundation": "f",
            "reasoning": "r",
            "verification": "v",
        })
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["checks"]), 4)

    def test_service_create_ok(self):
        svc = setup_service()
        mgr = svc.companion_experience
        for trig in ("模式发现", "记忆整理"):
            for _ in range(2):
                mgr.store_from_event(
                    success=True, trigger=trig,
                    source="v850", action="a",
                    result="成功",
                )
        records = [r.to_dict() for r in mgr._store.all()]
        svc.companion_meta_creative.load_experience(records)
        r = svc.companion_meta_creative_create("问题")
        self.assertTrue(r["validation"]["ok"])

    def test_engine_metrics(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        engine.create("问题")
        stats = engine.stats()
        self.assertIn("create_count", stats)
        self.assertIn("blocked_count", stats)
        self.assertIn("graph", stats)
        self.assertIn("memory", stats)

    def test_clear_resets_all(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        engine.create("问题")
        engine.collaborate("a", "b")
        n = engine.clear()
        self.assertGreater(n, 0)
        stats = engine.stats()
        self.assertEqual(stats["create_count"], 0)
        self.assertEqual(stats["graph"]["node_count"], 0)

    def test_collab_role_division(self):
        engine = MetaCreativeEngine()
        r = engine.collaborate("人类", "AI")
        roles = r["role_division"]
        self.assertIn("跳跃式创造", roles["human"])
        self.assertIn("可行性分析", roles["ai"])

    def test_memory_filter_consistency(self):
        memory = CreativeMemory()
        r1 = memory.save("x", validated=True)
        r2 = memory.save("y", validated=False)
        self.assertTrue(r1.get("ok", True))
        self.assertFalse(r2["ok"])
        self.assertEqual(memory.stats()["record_count"], 1)


if __name__ == "__main__":
    unittest.main()
