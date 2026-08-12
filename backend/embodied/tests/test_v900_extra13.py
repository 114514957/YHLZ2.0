"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 13 (V9.0 Extra13)

覆盖 (生成式批量):
    - 最终验收矩阵
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


class TestFinalAcceptance(unittest.TestCase):
    """最终验收"""

    def test_research_full_flow(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "提升伙伴体验", "user",
        )
        r = svc.companion_research_explore(
            "提升伙伴体验", "用户价值: 温暖",
        )
        self.assertFalse(r["blocked"])
        self.assertGreaterEqual(len(r["results"]), 1)
        self.assertGreaterEqual(len(r["memories"]), 1)
        self.assertIn("creative_link", r)
        self.assertIn("hybrid", r)

    def test_goal_boundary(self):
        svc = setup_service()
        r = svc.companion_research_explore(
            "无限扩展任务范围",
        )
        self.assertFalse(r["ok"])
        self.assertIn("防失控", r["reason"])

    def test_memory_safety(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        stats = svc.companion_research.memory_stats()
        self.assertGreaterEqual(stats["record_count"], 1)

    def test_audit_traceable(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        replay = svc.companion_research.audit_replay()
        self.assertGreaterEqual(replay["replay_count"], 1)

    def test_question_quality(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "提升伙伴体验",
        )
        svc.companion_research_explore("目标")
        q = svc.companion_research_questions()
        for question in q["questions"]:
            self.assertGreaterEqual(
                question["importance"], 0.0)
            self.assertLessEqual(question["importance"],
                                 1.0)

    def test_reality_levels(self):
        from backend.embodied.companion.research_engine import (
            RealityValidation,
        )
        validator = RealityValidation()
        r = validator.validate("推测", "unknown")
        self.assertEqual(r["level"], "inference")

    def test_version(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")


if __name__ == "__main__":
    unittest.main()
