"""
YHLZ Embodied AI V6.8 - 混合智能层策略单元测试 (Policies)

覆盖:
    - PrivacyPolicy: 隐私等级/云端禁止
    - CostPolicy: 成本评估/记录/优化
    - RoutingPolicy: 综合约束
"""
import unittest

from backend.embodied.companion.hybrid import (
    CostPolicy,
    PrivacyPolicy,
    RoutingPolicy,
)
from backend.embodied.companion.hybrid.policy.cost_policy import (
    COST_TIERS,
    CostError,
)
from backend.embodied.companion.hybrid.policy.privacy_policy import (
    IDENTITY_TASK_TYPES,
    PRIVACY_CLOUD_ALLOWED,
    PRIVACY_LEVELS,
)


class TestPrivacyPolicy(unittest.TestCase):
    """隐私策略"""

    def setUp(self):
        self.policy = PrivacyPolicy()

    def test_high_privacy_blocks_cloud(self):
        r = self.policy.evaluate({"privacy_level": "high"})
        self.assertFalse(r["cloud_allowed"])

    def test_medium_allows_cloud(self):
        r = self.policy.evaluate({"privacy_level": "medium"})
        self.assertTrue(r["cloud_allowed"])

    def test_low_allows_cloud(self):
        r = self.policy.evaluate({"privacy_level": "low"})
        self.assertTrue(r["cloud_allowed"])

    def test_identity_task_forced_high(self):
        for ttype in IDENTITY_TASK_TYPES:
            r = self.policy.evaluate({"type": ttype,
                                      "privacy_level": "low"})
            self.assertFalse(r["cloud_allowed"])
            self.assertEqual(r["privacy_level"], "high")

    def test_identity_reason(self):
        r = self.policy.evaluate({"type": "identity_query"})
        self.assertIn("强制本地", r["reason"])

    def test_invalid_level_fallback_medium(self):
        r = self.policy.evaluate({"privacy_level": "bogus"})
        self.assertEqual(r["privacy_level"], "medium")

    def test_none_input(self):
        r = self.policy.evaluate(None)
        self.assertEqual(r["privacy_level"], "medium")

    def test_confidence(self):
        r = self.policy.evaluate({"privacy_level": "high"})
        self.assertGreaterEqual(r["confidence"], 0.9)

    def test_mode(self):
        self.assertEqual(self.policy.evaluate({})["mode"],
                         "rule_based")

    def test_cloud_allowed_map(self):
        self.assertFalse(PRIVACY_CLOUD_ALLOWED["high"])
        self.assertTrue(PRIVACY_CLOUD_ALLOWED["medium"])
        self.assertTrue(PRIVACY_CLOUD_ALLOWED["low"])

    def test_levels(self):
        self.assertEqual(PRIVACY_LEVELS,
                         ["high", "medium", "low"])

    def test_block_count(self):
        self.policy.evaluate({"privacy_level": "high"})
        self.policy.evaluate({"privacy_level": "low"})
        stats = self.policy.stats()
        self.assertEqual(stats["evaluate_count"], 2)
        self.assertEqual(stats["cloud_block_count"], 1)

    def test_disabled(self):
        policy = PrivacyPolicy(enabled=False)
        r = policy.evaluate({"privacy_level": "high"})
        self.assertTrue(r["cloud_allowed"])
        self.assertIn("停用", r["reason"])


class TestCostPolicy(unittest.TestCase):
    """成本策略"""

    def setUp(self):
        self.policy = CostPolicy()

    def test_low_value_high_cost_blocked(self):
        r = self.policy.evaluate(
            value_score=0.1, model="openai-gpt4o",
        )
        self.assertFalse(r["allowed"])
        self.assertIn("高成本", r["reason"])

    def test_high_value_high_cost_allowed(self):
        r = self.policy.evaluate(
            value_score=0.9, model="openai-gpt4o",
        )
        self.assertTrue(r["allowed"])

    def test_low_value_free_model_allowed(self):
        r = self.policy.evaluate(
            value_score=0.1, model="local-qwen",
        )
        self.assertTrue(r["allowed"])

    def test_explicit_cost_override(self):
        r = self.policy.evaluate(
            value_score=0.1, model="x",
            cost_per_1k_tokens=0.001,
        )
        self.assertTrue(r["allowed"])

    def test_tier_free(self):
        self.assertEqual(
            self.policy._tier_of(0.0), "free")

    def test_tier_low(self):
        self.assertEqual(
            self.policy._tier_of(0.001), "low")

    def test_tier_medium(self):
        self.assertEqual(
            self.policy._tier_of(0.005), "medium")

    def test_tier_high(self):
        self.assertEqual(
            self.policy._tier_of(0.03), "high")

    def test_model_cost_mapping(self):
        self.assertEqual(
            self.policy._model_cost("local-qwen"), 0.0)
        self.assertGreater(
            self.policy._model_cost("openai-gpt4o"), 0.0)
        self.assertGreater(
            self.policy._model_cost("deep_reasoning"), 0.0)

    def test_record(self):
        entry = self.policy.record(
            model="gpt4o", tokens=100, cost=0.001,
            value_score=0.8,
        )
        self.assertEqual(entry["model"], "gpt4o")
        self.assertEqual(entry["tokens"], 100)

    def test_record_totals(self):
        self.policy.record(model="a", tokens=100, cost=0.01)
        self.policy.record(model="b", tokens=200, cost=0.02)
        stats = self.policy.stats()
        self.assertEqual(stats["total_tokens"], 300)
        self.assertAlmostEqual(stats["total_cost"], 0.03,
                               places=6)

    def test_block_count(self):
        self.policy.evaluate(value_score=0.1,
                             model="openai-gpt4o")
        self.policy.evaluate(value_score=0.9,
                             model="openai-gpt4o")
        self.assertEqual(self.policy.stats()["block_count"], 1)

    def test_optimization_empty(self):
        opt = self.policy.optimization()
        self.assertEqual(opt["top_cost_models"], [])

    def test_optimization_top_model(self):
        self.policy.record(model="gpt4o", tokens=1000,
                           cost=1.0)
        self.policy.record(model="local", tokens=1000,
                           cost=0.0)
        opt = self.policy.optimization()
        self.assertEqual(opt["top_cost_models"][0]["model"],
                         "gpt4o")
        self.assertIn("suggestion",
                      opt["top_cost_models"][0])

    def test_thresholds_in_stats(self):
        stats = self.policy.stats()
        self.assertEqual(stats["thresholds"][
            "high_cost_threshold"], 0.01)
        self.assertEqual(stats["thresholds"][
            "low_value_threshold"], 0.3)

    def test_disabled(self):
        policy = CostPolicy(enabled=False)
        r = policy.evaluate(value_score=0.0,
                            model="openai-gpt4o")
        self.assertTrue(r["allowed"])
        self.assertIn("停用", r["reason"])

    def test_invalid_high_threshold(self):
        with self.assertRaises(CostError):
            CostPolicy(high_cost_threshold=0)

    def test_clear(self):
        self.policy.record(model="a", tokens=10, cost=0.1)
        n = self.policy.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.policy.stats()["total_cost"], 0.0)

    def test_value_clamped(self):
        r = self.policy.evaluate(value_score=5.0,
                                 model="openai-gpt4o")
        self.assertTrue(r["allowed"])

    def test_tiers_constant(self):
        self.assertIn("free", COST_TIERS)
        self.assertIn("high", COST_TIERS)


class TestRoutingPolicy(unittest.TestCase):
    """路由策略"""

    def setUp(self):
        self.policy = RoutingPolicy(
            privacy=PrivacyPolicy(),
            cost=CostPolicy(),
        )

    def test_local_stays_local(self):
        r = self.policy.evaluate(
            {"type": "basic_reasoning"}, "LOCAL",
        )
        self.assertEqual(r["final_route"], "LOCAL")
        self.assertTrue(r["allowed"])

    def test_high_privacy_downgrades_cloud(self):
        r = self.policy.evaluate(
            {"type": "basic_reasoning",
             "privacy_level": "high"}, "CLOUD",
        )
        self.assertEqual(r["final_route"], "LOCAL")
        self.assertIn("隐私", r["reasons"][0])

    def test_cost_downgrades_cloud(self):
        policy = RoutingPolicy(
            privacy=PrivacyPolicy(),
            cost=CostPolicy(low_value_threshold=0.95),
        )
        r = policy.evaluate(
            {"type": "creative_exploration",
             "creativity_requirement": 0.1}, "CLOUD",
        )
        self.assertEqual(r["final_route"], "LOCAL")

    def test_realtime_hybrid(self):
        r = self.policy.evaluate(
            {"type": "deep_reasoning",
             "latency_requirement": "realtime",
             "creativity_requirement": 0.9}, "CLOUD",
        )
        self.assertEqual(r["final_route"], "HYBRID")

    def test_cloud_stays_cloud(self):
        r = self.policy.evaluate(
            {"type": "architecture_design",
             "latency_requirement": "async",
             "creativity_requirement": 0.9}, "CLOUD",
        )
        self.assertEqual(r["final_route"], "CLOUD")

    def test_none_context(self):
        r = self.policy.evaluate(None, "LOCAL")
        self.assertEqual(r["final_route"], "LOCAL")

    def test_mode(self):
        self.assertEqual(self.policy.evaluate({}, "LOCAL")[
            "mode"], "rule_based")

    def test_stats(self):
        self.policy.evaluate({}, "LOCAL")
        self.assertEqual(self.policy.stats()[
            "evaluate_count"], 1)

    def test_disabled(self):
        policy = RoutingPolicy(enabled=False)
        r = policy.evaluate({}, "CLOUD")
        self.assertEqual(r["final_route"], "CLOUD")
        self.assertTrue(r["allowed"])


if __name__ == "__main__":
    unittest.main()
