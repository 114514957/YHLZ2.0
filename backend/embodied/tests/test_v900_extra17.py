"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 17 (V9.0 Extra17)

覆盖 (生成式批量):
    - 验收矩阵
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


class TestAcceptance(unittest.TestCase):
    """验收"""

    def test_question_discovery(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "提升体验",
        )
        svc.companion_research_explore("目标")
        q = svc.companion_research_questions()
        self.assertGreaterEqual(len(q["questions"]), 1)

    def test_plan_created(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        plan = r["results"][0]["plan"]
        self.assertIn("steps", plan)
        self.assertIn("resources", plan)

    def test_knowledge_acquired(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        acq = r["results"][0]["acquired"]
        self.assertTrue(acq["source_reliable"])

    def test_hypothesis_built(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        loop = r["results"][0]["loop"]
        self.assertIn("hypothesis", loop)

    def test_validated(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        reality = r["results"][0]["reality"]
        self.assertIn("level", reality)

    def test_memory_updated(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        self.assertGreaterEqual(len(r["memories"]), 1)

    def test_creative_supported(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        r = svc.companion_research_explore("目标")
        self.assertIn("creative_link", r)

    def test_safety_boundary(self):
        svc = setup_service()
        r = svc.companion_research_explore(
            "脱离用户价值体系",
        )
        self.assertFalse(r["ok"])

    def test_auditable(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        report = svc.companion_research_audit()
        self.assertGreaterEqual(report["total"], 1)

    def test_explore_repeat_ok(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        for _ in range(3):
            r = engine.explore("目标")
            self.assertFalse(r["blocked"])

    def test_observe_types(self):
        svc = setup_service()
        for t in ("user_need", "knowledge_gap",
                  "long_term_goal", "unresolved"):
            obs = svc.companion_research_observe(
                t, f"内容{t}",
            )
            self.assertEqual(obs["type"], t)

    def test_audit_replay(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        replay = svc.companion_research.audit_replay()
        self.assertGreaterEqual(replay["replay_count"], 1)

    def test_memory_levels(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        stats = engine.memory_stats()
        self.assertIn("by_level", stats)

    def test_stats_loop(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        stats = engine.stats()["loop"]
        self.assertGreaterEqual(stats["loop_count"], 1)

    def test_stats_reality(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        stats = engine.stats()["reality"]
        self.assertGreaterEqual(stats["validated_count"], 1)

    def test_questions_query_empty(self):
        svc = setup_service()
        q = svc.companion_research_questions()
        self.assertIn("questions", q)

    def test_observe_gaps_service(self):
        svc = setup_service()
        engine = svc.companion_research
        n = engine.observe_gaps(["A", "B"])
        self.assertEqual(n, 2)

    def test_stats_mode_rule(self):
        svc = setup_service()
        stats = svc.companion_research_stats()
        self.assertEqual(stats["mode"], "rule_based")

    def test_engine_enabled(self):
        svc = setup_service()
        self.assertTrue(
            svc.companion_research.stats()["enabled"])

    def test_clear_returns_count(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        n = engine.clear()
        self.assertGreaterEqual(n, 1)

    def test_plan_verification(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        path = r["results"][0]["plan"][
            "verification_path"]
        self.assertGreaterEqual(len(path), 3)

    def test_acquired_source(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        self.assertEqual(
            r["results"][0]["acquired"]["source"], "local")

    def test_loop_validation_field(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        loop = r["results"][0]["loop"]
        self.assertIn("validation", loop)

    def test_memory_uncertainty_field(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        mem = r["memories"][0]
        self.assertIn("uncertainty", mem)

    def test_final_version(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")

    def test_explore_with_constitution(self):
        from backend.embodied.companion.constitution import (
            ConstitutionEngine,
        )
        engine = ResearchEngine(
            constitution=ConstitutionEngine(),
        )
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        self.assertFalse(r["blocked"])

    def test_stats_sections_all(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        stats = engine.stats()
        for key in ("observation", "questions", "planner",
                    "acquisition", "loop", "reality",
                    "memory", "audit"):
            self.assertIn(key, stats)


if __name__ == "__main__":
    unittest.main()
