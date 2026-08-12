"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 15 (V9.0 Extra15)

覆盖 (生成式批量):
    - 最终矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    ResearchEngine,
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


class TestFinalMatrix(unittest.TestCase):
    """最终矩阵"""

    def test_research_observe_api(self):
        svc = setup_service()
        obs = svc.companion_research_observe(
            "user_need", "需求", "user",
        )
        self.assertEqual(obs["type"], "user_need")
        self.assertEqual(obs["source"], "user")

    def test_research_explore_api(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        r = svc.companion_research_explore("目标")
        self.assertIn("results", r)

    def test_research_questions_api(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        q = svc.companion_research_questions()
        self.assertIn("questions", q)

    def test_research_audit_api(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        r = svc.companion_research_audit()
        self.assertIn("total", r)

    def test_research_stats_api(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        stats = svc.companion_research_stats()
        self.assertIn("explore_count", stats)

    def test_engine_observe_gaps(self):
        engine = ResearchEngine()
        n = engine.observe_gaps(["A", "B", "C"])
        self.assertEqual(n, 3)

    def test_engine_stats_mode(self):
        engine = ResearchEngine()
        self.assertEqual(engine.stats()["mode"],
                         "rule_based")

    def test_engine_enabled_flag(self):
        engine = ResearchEngine()
        self.assertTrue(engine.stats()["enabled"])
        engine2 = ResearchEngine(enabled=False)
        self.assertFalse(engine2.stats()["enabled"])

    def test_engine_clear(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        n = engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(engine.stats()[
            "explore_count"], 0)

    def test_version_final(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")


if __name__ == "__main__":
    unittest.main()
