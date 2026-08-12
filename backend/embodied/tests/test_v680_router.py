"""
YHLZ Embodied AI V6.8 - 混合智能层路由单元测试 (Hybrid Router)

覆盖:
    - TaskClassifier: 类型判定/特征规范化/非法输入
    - CapabilityMatcher: 注册/匹配/缺失
    - RoutingEngine: LOCAL/CLOUD/HYBRID 路由规则
"""
import unittest

from backend.embodied.companion.hybrid import (
    Capability,
    CapabilityMatcher,
    CostPolicy,
    PrivacyPolicy,
    RoutingEngine,
    TaskClassifier,
)
from backend.embodied.companion.hybrid.router.task_classifier import (
    LATENCY_LEVELS,
    PRIVACY_LEVELS,
    TASK_PROFILES,
    TASK_TYPES,
    ClassifierError,
)
from backend.embodied.companion.hybrid.router.capability_matcher import (
    CAPABILITY_SOURCES,
    TASK_CAPABILITIES,
    MatcherError,
)


class TestTaskClassifier(unittest.TestCase):
    """任务分类器"""

    def setUp(self):
        self.classifier = TaskClassifier()

    def test_explicit_type(self):
        r = self.classifier.classify({"type": "identity_query"})
        self.assertEqual(r["type"], "identity_query")

    def test_keyword_inference(self):
        r = self.classifier.classify({"text": "我是谁"})
        self.assertEqual(r["type"], "identity_query")

    def test_keyword_vision(self):
        r = self.classifier.classify({"text": "用摄像头识别"})
        self.assertEqual(r["type"], "vision_detection")

    def test_keyword_creative(self):
        r = self.classifier.classify({"text": "给个创意方案"})
        self.assertEqual(r["type"], "creative_exploration")

    def test_keyword_default(self):
        r = self.classifier.classify({"text": "随便聊聊"})
        self.assertEqual(r["type"], "basic_reasoning")

    def test_none_input(self):
        r = self.classifier.classify(None)
        self.assertEqual(r["type"], "basic_reasoning")
        self.assertEqual(r["complexity"], 0.4)

    def test_empty_input(self):
        r = self.classifier.classify({})
        self.assertEqual(r["mode"], "rule_based")

    def test_invalid_type(self):
        with self.assertRaises(ClassifierError):
            self.classifier.classify({"type": "bogus"})

    def test_identity_profile(self):
        r = self.classifier.classify({"type": "identity_query"})
        self.assertEqual(r["privacy_level"], "high")
        self.assertEqual(r["latency_requirement"], "realtime")

    def test_complexity_clamp_high(self):
        r = self.classifier.classify(
            {"type": "basic_reasoning", "complexity": 5.0},
        )
        self.assertEqual(r["complexity"], 1.0)

    def test_complexity_clamp_low(self):
        r = self.classifier.classify(
            {"type": "basic_reasoning", "complexity": -1},
        )
        self.assertEqual(r["complexity"], 0.0)

    def test_complexity_invalid_type(self):
        r = self.classifier.classify(
            {"type": "basic_reasoning", "complexity": "high"},
        )
        self.assertEqual(r["complexity"], 0.4)

    def test_privacy_override(self):
        r = self.classifier.classify(
            {"type": "analysis", "privacy_level": "high"},
        )
        self.assertEqual(r["privacy_level"], "high")

    def test_privacy_invalid_fallback(self):
        r = self.classifier.classify(
            {"type": "analysis", "privacy_level": "x"},
        )
        self.assertEqual(r["privacy_level"], "medium")

    def test_creativity_override(self):
        r = self.classifier.classify(
            {"type": "creative_exploration",
             "creativity_requirement": 0.5},
        )
        self.assertEqual(r["creativity_requirement"], 0.5)

    def test_all_task_types_valid(self):
        for ttype in TASK_TYPES:
            r = self.classifier.classify({"type": ttype})
            self.assertEqual(r["type"], ttype)

    def test_profiles_complete(self):
        for ttype in TASK_TYPES:
            self.assertIn(ttype, TASK_PROFILES)

    def test_stats_count(self):
        self.classifier.classify({"type": "analysis"})
        self.classifier.classify({"type": "analysis"})
        stats = self.classifier.stats()
        self.assertEqual(stats["classified_count"], 2)
        self.assertEqual(stats["type_distribution"][
            "analysis"], 2)

    def test_stats_types(self):
        self.assertEqual(self.classifier.stats()["task_types"],
                         TASK_TYPES)

    def test_constants(self):
        self.assertIn("high", PRIVACY_LEVELS)
        self.assertIn("realtime", LATENCY_LEVELS)

    def test_clear(self):
        self.classifier.classify({"type": "analysis"})
        self.classifier.clear()
        self.assertEqual(self.classifier.stats()[
            "classified_count"], 0)


class TestCapabilityMatcher(unittest.TestCase):
    """能力匹配器"""

    def setUp(self):
        self.matcher = CapabilityMatcher()

    def test_register_and_get(self):
        cap = Capability("identity", "local")
        self.matcher.register(cap)
        got = self.matcher.get("identity")
        self.assertEqual(got["name"], "identity")
        self.assertEqual(got["source"], "local")

    def test_register_defaults(self):
        n = self.matcher.register_defaults()
        self.assertEqual(n, 8)

    def test_default_capability_sources(self):
        self.matcher.register_defaults()
        all_caps = self.matcher.list_all()
        self.assertEqual(len(all_caps["local"]), 5)
        self.assertEqual(len(all_caps["cloud"]), 3)

    def test_match_identity(self):
        self.matcher.register_defaults()
        r = self.matcher.match("identity_query")
        names = [c["name"] for c in r["matched"]]
        self.assertIn("identity", names)
        self.assertNotEqual(r["missing"], ["identity"])

    def test_match_cloud_capability(self):
        self.matcher.register_defaults()
        r = self.matcher.match("architecture_design")
        names = [c["name"] for c in r["matched"]]
        self.assertIn("deep_reasoning", names)
        self.assertEqual(len(r["cloud"]), 2)

    def test_match_missing(self):
        self.matcher.register_defaults()
        r = self.matcher.match("bogus_type")
        self.assertEqual(r["missing"], [])

    def test_match_local_only(self):
        self.matcher.register_defaults()
        r = self.matcher.match("vision_detection")
        self.assertEqual(len(r["local"]), 1)
        self.assertEqual(r["cloud"], [])

    def test_unregister(self):
        cap = Capability("memory", "local")
        self.matcher.register(cap)
        self.assertTrue(self.matcher.unregister("memory"))
        self.assertIsNone(self.matcher.get("memory"))

    def test_duplicate_register_overwrites(self):
        self.matcher.register(Capability("memory", "local",
                                         latency_ms=5))
        self.matcher.register(Capability("memory", "local",
                                         latency_ms=99))
        got = self.matcher.get("memory")
        self.assertEqual(got["latency_ms"], 99)

    def test_invalid_source(self):
        with self.assertRaises(MatcherError):
            Capability("x", "remote")

    def test_empty_name(self):
        with self.assertRaises(MatcherError):
            Capability("", "local")

    def test_task_capabilities_map(self):
        self.assertIn("identity_query", TASK_CAPABILITIES)
        self.assertIn("creative_exploration",
                      TASK_CAPABILITIES)

    def test_sources_constant(self):
        self.assertEqual(CAPABILITY_SOURCES, ["local", "cloud"])

    def test_clear(self):
        self.matcher.register_defaults()
        n = self.matcher.clear()
        self.assertEqual(n, 8)
        self.assertEqual(self.matcher.stats()[
            "capability_count"], 0)

    def test_stats(self):
        self.matcher.register_defaults()
        self.matcher.match("identity_query")
        self.assertEqual(self.matcher.stats()["match_count"], 1)


class TestRoutingEngine(unittest.TestCase):
    """路由引擎"""

    def setUp(self):
        self.matcher = CapabilityMatcher()
        self.matcher.register_defaults()
        self.privacy = PrivacyPolicy()
        self.cost = CostPolicy()
        self.engine = RoutingEngine(
            privacy=self.privacy,
            cost=self.cost,
            matcher=self.matcher,
        )

    def ctx(self, **over):
        base = {
            "type": "basic_reasoning",
            "complexity": 0.4,
            "privacy_level": "low",
            "latency_requirement": "normal",
            "creativity_requirement": 0.2,
        }
        base.update(over)
        return base

    def test_identity_route_local(self):
        r = self.engine.route(self.ctx(type="identity_query"))
        self.assertEqual(r["route"], "LOCAL")

    def test_permission_route_local(self):
        r = self.engine.route(self.ctx(type="permission_check"))
        self.assertEqual(r["route"], "LOCAL")

    def test_memory_route_local(self):
        r = self.engine.route(self.ctx(type="memory_retrieval"))
        self.assertEqual(r["route"], "LOCAL")

    def test_high_privacy_route_local(self):
        r = self.engine.route(self.ctx(privacy_level="high"))
        self.assertEqual(r["route"], "LOCAL")

    def test_realtime_route_local(self):
        r = self.engine.route(self.ctx(
            latency_requirement="realtime",
            complexity=0.8,
        ))
        self.assertEqual(r["route"], "LOCAL")

    def test_high_complexity_route_cloud(self):
        r = self.engine.route(self.ctx(
            type="architecture_design",
            complexity=0.9,
            creativity_requirement=0.7,
        ))
        self.assertEqual(r["route"], "CLOUD")

    def test_high_creativity_route_cloud(self):
        r = self.engine.route(self.ctx(
            type="creative_exploration",
            complexity=0.6,
            creativity_requirement=0.9,
        ))
        self.assertEqual(r["route"], "CLOUD")

    def test_hybrid_route(self):
        r = self.engine.route(self.ctx(
            complexity=0.55,
            creativity_requirement=0.45,
        ))
        self.assertEqual(r["route"], "HYBRID")

    def test_low_complexity_route_local(self):
        r = self.engine.route(self.ctx(
            complexity=0.3, creativity_requirement=0.1,
        ))
        self.assertEqual(r["route"], "LOCAL")

    def test_route_structure(self):
        r = self.engine.route(self.ctx())
        for key in ("route_id", "route", "reason",
                    "confidence", "checks", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["route_id"].startswith("rt_"))

    def test_confidence_range(self):
        for route in ("LOCAL", "CLOUD", "HYBRID"):
            r = self.engine.route(self.ctx(
                type="creative_exploration",
                complexity=0.9, creativity_requirement=0.9,
            ))
            self.assertGreaterEqual(r["confidence"], 0.0)
            self.assertLessEqual(r["confidence"], 1.0)

    def test_reason_explainable(self):
        r = self.engine.route(self.ctx(type="identity_query"))
        self.assertGreater(len(r["reason"]), 5)

    def test_checks_present(self):
        r = self.engine.route(self.ctx())
        self.assertIsInstance(r["checks"], list)

    def test_disabled_engine(self):
        engine = RoutingEngine(enabled=False)
        r = engine.route(self.ctx())
        self.assertEqual(r["route"], "LOCAL")
        self.assertIn("停用", r["reason"])

    def test_none_context(self):
        r = self.engine.route(None)
        self.assertEqual(r["route"], "LOCAL")

    def test_stats_distribution(self):
        self.engine.route(self.ctx(type="identity_query"))
        self.engine.route(self.ctx(type="architecture_design",
                                   complexity=0.9,
                                   creativity_requirement=0.7))
        stats = self.engine.stats()
        self.assertEqual(stats["distribution"]["LOCAL"], 1)
        self.assertEqual(stats["distribution"]["CLOUD"], 1)

    def test_stats_targets(self):
        self.assertEqual(self.engine.stats()["targets"],
                         ["LOCAL", "CLOUD", "HYBRID"])

    def test_clear(self):
        self.engine.route(self.ctx())
        n = self.engine.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.engine.stats()["route_count"], 0)

    def test_cost_policy_blocks_cloud(self):
        cost = CostPolicy(low_value_threshold=0.95)
        engine = RoutingEngine(
            privacy=PrivacyPolicy(),
            cost=cost,
            matcher=self.matcher,
        )
        r = engine.route(self.ctx(
            type="creative_exploration",
            complexity=0.6,
            creativity_requirement=0.9,
        ))
        # 云端被成本策略拦截 → 降级本地
        self.assertEqual(r["route"], "LOCAL")
        self.assertIn("成本", r["reason"])


class TestRoutingEdge(unittest.TestCase):
    """路由边界"""

    def setUp(self):
        self.matcher = CapabilityMatcher()
        self.matcher.register_defaults()
        self.engine = RoutingEngine(matcher=self.matcher)

    def test_cloud_missing_capability_downgrade(self):
        matcher = CapabilityMatcher()  # 无默认能力
        engine = RoutingEngine(matcher=matcher)
        r = engine.route({
            "type": "architecture_design",
            "complexity": 0.9,
            "creativity_requirement": 0.8,
            "privacy_level": "low",
            "latency_requirement": "async",
        })
        self.assertEqual(r["route"], "LOCAL")
        self.assertIn("降级", r["reason"])

    def test_complexity_boundary_cloud(self):
        r = self.engine.route({
            "type": "deep_reasoning",
            "complexity": 0.75,
            "creativity_requirement": 0.2,
            "privacy_level": "low",
            "latency_requirement": "async",
        })
        self.assertEqual(r["route"], "CLOUD")

    def test_complexity_below_boundary(self):
        r = self.engine.route({
            "type": "deep_reasoning",
            "complexity": 0.7,
            "creativity_requirement": 0.2,
            "privacy_level": "low",
            "latency_requirement": "async",
        })
        self.assertEqual(r["route"], "LOCAL")


if __name__ == "__main__":
    unittest.main()
