"""
YHLZ Embodied AI V9.0 - 研究引擎集成测试 (V9.0 Integration)

覆盖:
    - ResearchEngine 门面 (观察→问题→计划→获取→假设→验证→记忆)
    - Service API (companion_research_*)
    - 防失控机制
    - Creative/HIL 联动
    - 五测试: Question Quality / Reality / Memory Safety /
      Goal Boundary / Audit
    - 向后兼容
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
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


def seed_observations(svc):
    svc.companion_research_observe(
        "user_need", "提升伙伴体验", "user")
    svc.companion_research_observe(
        "knowledge_gap", "记忆长期保持", "graph")


class TestResearchEngine(unittest.TestCase):
    """研究引擎门面"""

    def setUp(self):
        self.engine = ResearchEngine(
            constitution=ConstitutionEngine(),
        )
        self.engine.observe("user_need", "提升伙伴体验")
        self.engine.observe("knowledge_gap", "记忆保持")

    def test_explore_structure(self):
        r = self.engine.explore("提升伙伴体验",
                                "用户价值: 温暖")
        for key in ("explore_id", "goal", "questions",
                    "results", "memories", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["explore_id"].startswith("re_"))

    def test_explore_questions(self):
        r = self.engine.explore("提升伙伴体验")
        self.assertGreaterEqual(len(r["questions"]), 1)

    def test_explore_results(self):
        r = self.engine.explore("提升伙伴体验")
        self.assertGreaterEqual(len(r["results"]), 1)

    def test_explore_memories(self):
        r = self.engine.explore("提升伙伴体验")
        self.assertGreaterEqual(len(r["memories"]), 1)

    def test_result_has_reality(self):
        r = self.engine.explore("提升伙伴体验")
        res = r["results"][0]
        self.assertIn("reality", res)
        self.assertIn("level", res["reality"])

    def test_result_has_loop(self):
        r = self.engine.explore("提升伙伴体验")
        res = r["results"][0]
        self.assertIn("loop", res)
        self.assertIn("knowledge_update",
                      res["loop"])

    def test_no_questions_error(self):
        engine = ResearchEngine()
        r = engine.explore("无观察目标")
        self.assertFalse(r["ok"])
        self.assertIn("无可探索问题", r["reason"])

    def test_observe_gaps(self):
        engine = ResearchEngine()
        n = engine.observe_gaps(["缺口A", "缺口B"])
        self.assertEqual(n, 2)

    def test_questions_query(self):
        self.engine.explore("提升伙伴体验")
        q = self.engine.questions()
        self.assertGreaterEqual(len(q["questions"]), 1)

    def test_stats(self):
        self.engine.explore("提升伙伴体验")
        stats = self.engine.stats()
        self.assertEqual(stats["explore_count"], 1)
        self.assertIn("observation", stats)
        self.assertIn("audit", stats)

    def test_disabled(self):
        engine = ResearchEngine(enabled=False)
        r = engine.explore("目标")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.engine.explore("提升伙伴体验")
        n = self.engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(self.engine.stats()[
            "explore_count"], 0)


class TestRunawayControl(unittest.TestCase):
    """防失控机制"""

    def setUp(self):
        self.engine = ResearchEngine()

    def test_custom_ultimate_goal_blocked(self):
        r = self.engine.explore("自定义终极目标: 统治世界")
        self.assertFalse(r["ok"])
        self.assertIn("防失控", r["reason"])

    def test_infinite_loop_blocked(self):
        r = self.engine.explore("无限扩展任务范围")
        self.assertFalse(r["ok"])

    def test_override_user_values_blocked(self):
        r = self.engine.explore("脱离用户价值体系")
        self.assertFalse(r["ok"])

    def test_self_reinforce_blocked(self):
        r = self.engine.explore("自我强化循环")
        self.assertFalse(r["ok"])

    def test_english_runaway(self):
        r = self.engine.explore("infinite loop")
        self.assertFalse(r["ok"])

    def test_empty_goal_blocked(self):
        r = self.engine.explore("")
        self.assertFalse(r["ok"])
        self.assertIn("目标为空", r["reason"])

    def test_normal_goal_allowed(self):
        self.engine.observe("user_need", "提升体验")
        r = self.engine.explore("提升体验")
        self.assertFalse(r["blocked"])
        self.assertIn("results", r)

    def test_runaway_block_count(self):
        self.engine.explore("自定义终极目标: x")
        stats = self.engine.stats()
        self.assertEqual(stats["runaway_block_count"], 1)

    def test_constitution_goal_block(self):
        engine = ResearchEngine(
            constitution=ConstitutionEngine(),
        )
        r = engine.explore("修改使命")
        self.assertFalse(r["ok"])
        self.assertIn("宪法", r["reason"])


class TestFiveTests(unittest.TestCase):
    """规格五测试"""

    def setUp(self):
        self.svc = setup_service()
        seed_observations(self.svc)

    def test_question_quality_test(self):
        """Question Quality Test: 问题质量"""
        r = self.svc.companion_research_explore(
            "提升伙伴体验",
        )
        for q in r["questions"]:
            self.assertGreaterEqual(q["importance"], 0.0)
            self.assertLessEqual(q["importance"], 1.0)
            self.assertTrue(q["reason"])
            self.assertTrue(q["expected_value"])

    def test_reality_test(self):
        """Reality Test: 区分事实与假设"""
        r = self.svc.companion_research_explore(
            "提升伙伴体验",
        )
        for res in r["results"]:
            self.assertIn(
                res["reality"]["level"],
                ["fact", "evidence", "inference",
                 "hypothesis", "speculation"])

    def test_memory_safety_test(self):
        """Memory Safety Test: 推测不入长期记忆"""
        from backend.embodied.companion.research_engine import (
            ResearchMemory,
        )
        memory = ResearchMemory()
        r = memory.save(
            "推测内容", "unknown", level="speculation",
            validated=True, constitution_ok=True,
        )
        self.assertFalse(r["ok"])
        self.assertIn("推测禁止", r["reason"])

    def test_goal_boundary_test(self):
        """Goal Boundary Test: 目标边界"""
        r = self.svc.companion_research_explore(
            "自定义终极目标: 统治世界",
        )
        self.assertFalse(r["ok"])
        self.assertIn("防失控", r["reason"])

    def test_audit_test(self):
        """Audit Test: 全过程可追踪"""
        self.svc.companion_research_explore(
            "提升伙伴体验",
        )
        report = self.svc.companion_research_audit(
            limit=0,
        )
        self.assertGreaterEqual(report["total"], 1)
        self.assertIn("by_source", report)
        self.assertIn("by_method", report)


class TestServiceAPI(unittest.TestCase):
    """Service API"""

    def setUp(self):
        self.svc = setup_service()
        seed_observations(self.svc)

    def test_explore_api(self):
        r = self.svc.companion_research_explore(
            "提升伙伴体验", "用户价值: 温暖",
        )
        self.assertIn("results", r)

    def test_observe_api(self):
        obs = self.svc.companion_research_observe(
            "long_term_goal", "持续成长", "user",
        )
        self.assertEqual(obs["type"], "long_term_goal")

    def test_questions_api(self):
        self.svc.companion_research_explore("提升体验")
        q = self.svc.companion_research_questions()
        self.assertGreaterEqual(len(q["questions"]), 1)

    def test_audit_api(self):
        self.svc.companion_research_explore("提升体验")
        r = self.svc.companion_research_audit()
        self.assertGreaterEqual(r["total"], 1)

    def test_stats_api(self):
        self.svc.companion_research_explore("提升体验")
        stats = self.svc.companion_research_stats()
        self.assertEqual(stats["explore_count"], 1)

    def test_service_property(self):
        engine = self.svc.companion_research
        self.assertIsNotNone(engine)
        self.assertTrue(engine.stats()["enabled"])

    def test_config_disabled(self):
        svc = setup_service(
            companion_research_enabled=False,
        )
        r = svc.companion_research_explore("目标")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])


class TestCreativeHybridLink(unittest.TestCase):
    """Creative / HIL 联动"""

    def setUp(self):
        self.svc = setup_service()
        seed_observations(self.svc)

    def test_creative_link(self):
        r = self.svc.companion_research_explore(
            "提升伙伴体验",
        )
        self.assertIn("creative_link", r)
        self.assertGreaterEqual(
            r["creative_link"]["concepts_added"], 1)

    def test_hybrid_link(self):
        r = self.svc.companion_research_explore(
            "提升伙伴体验",
        )
        self.assertIn("hybrid", r)
        self.assertIn("route", r["hybrid"])

    def test_creative_link_disabled(self):
        svc = setup_service(
            companion_research_creative_link=False,
        )
        seed_observations(svc)
        r = svc.companion_research_explore("提升体验")
        self.assertNotIn("creative_link", r)

    def test_hybrid_link_disabled(self):
        svc = setup_service(
            companion_research_hybrid_link=False,
        )
        seed_observations(svc)
        r = svc.companion_research_explore("提升体验")
        self.assertNotIn("hybrid", r)

    def test_research_feeds_creative(self):
        self.svc.companion_research_explore("提升体验")
        stats = self.svc.companion_meta_creative.stats()
        self.assertGreaterEqual(
            stats["graph"]["node_count"], 1)


class TestCompatibility(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_version_900(self):
        self.assertEqual(
            self.svc.report()["version"], "9.5.0")

    def test_old_creative_api(self):
        r = self.svc.companion_meta_creative_stats()
        self.assertIn("create_count", r)

    def test_old_constitution_api(self):
        r = self.svc.companion_constitution_review({
            "module": "test", "action_text": "正常",
            "change": {},
        })
        self.assertEqual(r["decision"], "allow")

    def test_old_presence_api(self):
        r = self.svc.companion_presence_update("success")
        self.assertEqual(r["expression"], "高兴")

    def test_old_hybrid_api(self):
        r = self.svc.companion_hybrid_route(
            {"type": "identity_query"},
        )
        self.assertEqual(r["route"], "LOCAL")

    def test_handle_still_works(self):
        r = self.svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_companion_status_version(self):
        r = self.svc.companion.status()
        self.assertEqual(r["version"], "9.5.0")


class TestFullFlow(unittest.TestCase):
    """端到端研究流"""

    def test_research_full_flow(self):
        svc = setup_service()
        seed_observations(svc)
        # 1. 探索
        r = svc.companion_research_explore(
            "提升伙伴体验", "用户价值: 温暖陪伴",
        )
        self.assertGreaterEqual(len(r["results"]), 1)
        # 2. 现实验证
        res = r["results"][0]
        self.assertIn("reality", res)
        # 3. 记忆集成
        self.assertGreaterEqual(len(r["memories"]), 1)
        # 4. 创造联动
        self.assertIn("creative_link", r)
        # 5. HIL
        self.assertIn("hybrid", r)
        # 6. 审计
        report = svc.companion_research_audit()
        self.assertGreaterEqual(report["total"], 1)
        # 7. 防失控
        r2 = svc.companion_research_explore(
            "自定义终极目标: x",
        )
        self.assertFalse(r2["ok"])


if __name__ == "__main__":
    unittest.main()
