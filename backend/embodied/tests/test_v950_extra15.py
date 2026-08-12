"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 15 (V9.5 Extra15)

覆盖 (生成式批量):
    - 最终矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    MetaCognitionEngine,
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


class TestFinalMatrix2(unittest.TestCase):
    """最终矩阵"""

    def test_service_property(self):
        svc = setup_service()
        engine = svc.companion_meta_cognition
        self.assertIsNotNone(engine)
        self.assertTrue(engine.stats()["enabled"])

    def test_constitution_shared(self):
        svc = setup_service()
        self.assertIs(
            svc.companion_meta_cognition._constitution,
            svc.companion_constitution_engine,
        )

    def test_old_api_compat(self):
        svc = setup_service()
        r = svc.companion_research_stats()
        self.assertIn("explore_count", r)
        r = svc.companion_meta_creative_stats()
        self.assertIn("create_count", r)
        r = svc.companion_constitution_review({
            "module": "m", "action_text": "正常",
            "change": {},
        })
        self.assertEqual(r["decision"], "allow")
        r = svc.companion_presence_interpreter("success")
        self.assertEqual(r["expression"], "高兴")

    def test_handle_ok(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_version(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")

    def test_engine_stats_mode(self):
        engine = MetaCognitionEngine()
        self.assertEqual(engine.stats()["mode"],
                         "rule_based")

    def test_engine_enabled_flag(self):
        self.assertTrue(
            MetaCognitionEngine().stats()["enabled"])
        self.assertFalse(
            MetaCognitionEngine(enabled=False).stats()[
                "enabled"])

    def test_engine_clear(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        n = engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(engine.stats()[
            "operation_count"], 0)

    def test_repeat_monitor(self):
        engine = MetaCognitionEngine()
        for _ in range(3):
            r = engine.monitor("任务")
            self.assertIn("monitor_id", r)
        self.assertEqual(engine.stats()[
            "operation_count"], 3)


if __name__ == "__main__":
    unittest.main()
