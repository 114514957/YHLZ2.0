"""
YHLZ Embodied AI V9.0 - 研究计划与知识获取单元测试 (Planner & Acquisition)

覆盖:
    - ResearchPlanner: 问题拆解/资源/验证路径/成本
    - KnowledgeAcquisition: 来源记录/可靠度
"""
import unittest

from backend.embodied.companion.research_engine import (
    KnowledgeAcquisition,
    ResearchPlanner,
)
from backend.embodied.companion.research_engine.knowledge_acquisition import (
    SOURCE_RELIABILITY,
    SOURCE_TYPES,
    AcquisitionError,
)
from backend.embodied.companion.research_engine.research_planner import (
    COST_LEVELS,
    RESOURCE_TYPES,
)


class TestResearchPlanner(unittest.TestCase):
    """研究计划器"""

    def setUp(self):
        self.planner = ResearchPlanner()

    def test_plan_structure(self):
        plan = self.planner.plan("如何提升体验", 0.7)
        for key in ("plan_id", "question", "steps",
                    "resources", "verification_path",
                    "estimated_cost", "mode"):
            self.assertIn(key, plan)
        self.assertTrue(plan["plan_id"].startswith("rp_"))

    def test_plan_steps(self):
        plan = self.planner.plan("问题", 0.5)
        self.assertGreaterEqual(len(plan["steps"]), 3)
        self.assertEqual(plan["steps"][0]["step"], 1)

    def test_steps_have_method(self):
        plan = self.planner.plan("问题", 0.5)
        methods = {s["method"] for s in plan["steps"]}
        self.assertIn("hypothesis_loop", methods)
        self.assertIn("validation", methods)

    def test_resources_high_importance(self):
        plan = self.planner.plan("问题", 0.9)
        self.assertIn("cloud", plan["resources"])
        self.assertIn("tool", plan["resources"])

    def test_resources_low_importance(self):
        plan = self.planner.plan("问题", 0.3)
        self.assertNotIn("cloud", plan["resources"])

    def test_verification_path(self):
        plan = self.planner.plan("问题", 0.5)
        self.assertGreaterEqual(len(
            plan["verification_path"]), 3)

    def test_cost_high(self):
        plan = self.planner.plan("问题", 0.9)
        self.assertEqual(plan["estimated_cost"], "high")

    def test_cost_low(self):
        plan = self.planner.plan("问题", 0.3)
        self.assertEqual(plan["estimated_cost"], "low")

    def test_cost_levels_constant(self):
        self.assertEqual(COST_LEVELS, ["low", "medium",
                                       "high"])

    def test_resource_types_constant(self):
        self.assertEqual(RESOURCE_TYPES,
                         ["local", "user_authorized",
                          "cloud", "tool"])

    def test_stats(self):
        self.planner.plan("问题", 0.5)
        self.assertEqual(self.planner.stats()["plan_count"], 1)

    def test_disabled(self):
        planner = ResearchPlanner(enabled=False)
        r = planner.plan("问题")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.planner.plan("问题")
        n = self.planner.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.planner.stats()[
            "plan_count"], 0)


class TestKnowledgeAcquisition(unittest.TestCase):
    """知识获取"""

    def setUp(self):
        self.acq = KnowledgeAcquisition()

    def test_acquire_structure(self):
        r = self.acq.acquire("问题", "local")
        for key in ("result_id", "query", "content",
                    "source", "source_reliable",
                    "reliability", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["result_id"].startswith("ka_"))

    def test_local_reliable(self):
        r = self.acq.acquire("问题", "local")
        self.assertTrue(r["source_reliable"])

    def test_unknown_source_unreliable(self):
        r = self.acq.acquire("问题", "unknown")
        self.assertFalse(r["source_reliable"])
        self.assertEqual(r["reliability"], 0.0)

    def test_cloud_medium(self):
        r = self.acq.acquire("问题", "cloud")
        self.assertTrue(r["source_reliable"])
        self.assertEqual(r["reliability"], 0.7)

    def test_invalid_source_fallback(self):
        r = self.acq.acquire("问题", "bogus")
        self.assertEqual(r["source"], "unknown")
        self.assertFalse(r["source_reliable"])

    def test_provider_injection(self):
        def provider(query):
            return f"provider结果: {query}"

        acq = KnowledgeAcquisition(providers={
            "local": provider,
        })
        r = acq.acquire("测试", "local")
        self.assertIn("provider结果", r["content"])

    def test_provider_failure_fallback(self):
        def provider(query):
            raise RuntimeError("boom")

        acq = KnowledgeAcquisition(providers={
            "local": provider,
        })
        r = acq.acquire("测试", "local")
        self.assertIn("获取失败", r["content"])

    def test_source_types_constant(self):
        self.assertEqual(SOURCE_TYPES,
                         ["local", "user_authorized", "cloud",
                          "tool", "unknown"])

    def test_reliability_map(self):
        self.assertEqual(SOURCE_RELIABILITY["local"], 0.9)
        self.assertEqual(SOURCE_RELIABILITY["unknown"], 0.0)

    def test_records(self):
        self.acq.acquire("a", "local")
        self.acq.acquire("b", "cloud")
        records = self.acq.records()
        self.assertEqual(len(records), 2)

    def test_stats_by_source(self):
        self.acq.acquire("a", "local")
        self.acq.acquire("b", "local")
        self.acq.acquire("c", "unknown")
        stats = self.acq.stats()
        self.assertEqual(stats["by_source"]["local"], 2)
        self.assertEqual(stats["unreliable_count"], 1)

    def test_disabled(self):
        acq = KnowledgeAcquisition(enabled=False)
        r = acq.acquire("问题")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.acq.acquire("a")
        n = self.acq.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.acq.stats()["record_count"], 0)


if __name__ == "__main__":
    unittest.main()
