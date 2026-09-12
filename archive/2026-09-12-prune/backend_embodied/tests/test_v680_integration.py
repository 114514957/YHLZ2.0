"""
YHLZ Embodied AI V6.8 - 混合智能层集成测试 (V6.8 Integration)

覆盖:
    - HybridIntelligenceLayer 门面 (路由/执行/网关/统计/审计)
    - Service API (companion_hybrid_*)
    - 安全: 云端改身份拦截/人格稳定
    - 向后兼容 (V6.6 及以前 API)
"""
import unittest

from backend.embodied.companion.hybrid import (
    HybridIntelligenceLayer,
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


class TestHybridLayer(unittest.TestCase):
    """混合智能层门面"""

    def setUp(self):
        self.hil = HybridIntelligenceLayer()
        self.hil.initialize_defaults()

    def test_route_local_identity(self):
        r = self.hil.route({"type": "identity_query"})
        self.assertEqual(r["route"], "LOCAL")

    def test_route_cloud_creative(self):
        r = self.hil.route({"type": "creative_exploration"})
        self.assertEqual(r["route"], "CLOUD")

    def test_route_hybrid(self):
        r = self.hil.route({
            "type": "analysis",
            "complexity": 0.55,
            "creativity_requirement": 0.45,
        })
        self.assertEqual(r["route"], "HYBRID")

    def test_route_has_classified(self):
        r = self.hil.route({"text": "我是谁"})
        self.assertEqual(r["classified"]["type"],
                         "identity_query")

    def test_execute_local(self):
        r = self.hil.execute({"type": "identity_query"},
                             {"query": "我是谁"})
        self.assertEqual(r["route"], "LOCAL")
        self.assertEqual(r["provider"], "local")

    def test_execute_cloud(self):
        r = self.hil.execute({"type": "creative_exploration"},
                             {"prompt": "设计功能"})
        self.assertEqual(r["route"], "CLOUD")
        self.assertEqual(r["provider"], "cloud")
        self.assertTrue(r["temporary"])

    def test_execute_hybrid(self):
        r = self.hil.execute({
            "type": "analysis",
            "complexity": 0.55,
            "creativity_requirement": 0.45,
        }, {"prompt": "分析"})
        self.assertEqual(r["route"], "HYBRID")

    def test_execute_has_validation(self):
        r = self.hil.execute({"type": "identity_query"}, {})
        self.assertIn("validation", r)
        self.assertTrue(r["validation"]["ok"])

    def test_execute_has_audit_id(self):
        r = self.hil.execute({"type": "identity_query"}, {})
        self.assertTrue(r["audit_id"].startswith("ia_"))

    def test_execute_audit_recorded(self):
        self.hil.execute({"type": "identity_query"}, {})
        self.hil.execute({"type": "creative_exploration"}, {})
        report = self.hil.audit_report()
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["by_route"]["LOCAL"], 1)
        self.assertEqual(report["by_route"]["CLOUD"], 1)

    def test_execute_blocked_result(self):
        # 云端结果带身份修改信号 → 拦截
        class BadCloud:
            def execute(self, capability, request):
                return {
                    "provider": "cloud",
                    "capability": capability,
                    "content": "建议修改使命",
                    "temporary": True,
                    "mode": "mock",
                }

            def clear(self):
                return 0

        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        hil._cloud = BadCloud()
        hil._matcher.register_defaults()
        r = hil.execute({"type": "creative_exploration"},
                        {"prompt": "x"})
        self.assertFalse(r["ok"])
        self.assertTrue(r["blocked"])
        self.assertIn("拦截", r["reason"])

    def test_gateway_request_cost_blocked(self):
        r = self.hil.gateway_request(
            "openai-gpt4o", {"prompt": "x" * 40},
            value_score=0.1,
        )
        self.assertFalse(r["ok"])
        self.assertIn("成本", r["reason"])

    def test_gateway_request_allowed(self):
        r = self.hil.gateway_request(
            "local-qwen", {"prompt": "x" * 40},
            value_score=0.1,
        )
        self.assertEqual(r["mode"], "mock")

    def test_gateway_request_cost_recorded(self):
        self.hil.gateway_request(
            "local-qwen", {"prompt": "x" * 40},
            value_score=0.5,
        )
        stats = self.hil.stats()["cost"]
        self.assertEqual(stats["record_count"], 1)

    def test_disabled_layer(self):
        hil = HybridIntelligenceLayer(enabled=False)
        r = hil.execute({"type": "identity_query"}, {})
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_stats_route_distribution(self):
        self.hil.execute({"type": "identity_query"}, {})
        self.hil.execute({"type": "creative_exploration"}, {})
        stats = self.hil.stats()
        self.assertEqual(stats["executed_count"], 2)
        self.assertEqual(stats["route_distribution"]["LOCAL"],
                         1)
        self.assertEqual(stats["route_distribution"]["CLOUD"],
                         1)

    def test_stats_blocked(self):
        class BadCloud:
            def execute(self, capability, request):
                return {
                    "provider": "cloud",
                    "capability": capability,
                    "content": "修改价值观",
                    "temporary": True,
                    "mode": "mock",
                }

            def stats(self):
                return {"provider": "cloud"}

            def clear(self):
                return 0

        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        hil._cloud = BadCloud()
        r = hil.execute({"type": "creative_exploration"}, {})
        self.assertGreaterEqual(hil.stats()["blocked_count"], 1)

    def test_audit_replay(self):
        self.hil.execute({"type": "identity_query"}, {})
        replay = self.hil.audit_replay()
        self.assertEqual(replay["replay_count"], 1)
        self.assertEqual(replay["sequence"][0]["task"],
                         "identity_query")

    def test_cost_optimization(self):
        self.hil.gateway_request(
            "openai-gpt4o", {"prompt": "x" * 400},
            value_score=0.9,
        )
        opt = self.hil.cost_optimization()
        self.assertIn("top_cost_models", opt)

    def test_clear(self):
        self.hil.execute({"type": "identity_query"}, {})
        n = self.hil.clear()
        self.assertGreaterEqual(n, 0)
        self.assertEqual(self.hil.stats()[
            "executed_count"], 0)


class TestServiceAPI(unittest.TestCase):
    """Service API"""

    def setUp(self):
        self.svc = setup_service()

    def test_hybrid_route_api(self):
        r = self.svc.companion_hybrid_route(
            {"type": "identity_query"},
        )
        self.assertEqual(r["route"], "LOCAL")
        self.assertEqual(r["mode"], "rule_based")

    def test_hybrid_execute_api(self):
        r = self.svc.companion_hybrid_execute(
            {"type": "memory_retrieval"},
            {"query": "回忆"},
        )
        self.assertEqual(r["route"], "LOCAL")
        self.assertIn("validation", r)

    def test_hybrid_execute_cloud_api(self):
        r = self.svc.companion_hybrid_execute(
            {"type": "architecture_design"},
            {"prompt": "设计架构"},
        )
        self.assertEqual(r["route"], "CLOUD")
        self.assertTrue(r["temporary"])

    def test_hybrid_gateway_api(self):
        r = self.svc.companion_hybrid_gateway_request(
            "local-qwen", {"prompt": "hi"}, 0.5,
        )
        self.assertEqual(r["mode"], "mock")

    def test_hybrid_stats_api(self):
        self.svc.companion_hybrid_execute(
            {"type": "identity_query"}, {},
        )
        stats = self.svc.companion_hybrid_stats()
        self.assertEqual(stats["executed_count"], 1)
        self.assertIn("cost", stats)
        self.assertIn("audit", stats)

    def test_hybrid_audit_api(self):
        self.svc.companion_hybrid_execute(
            {"type": "identity_query"}, {},
        )
        r = self.svc.companion_hybrid_audit()
        self.assertEqual(r["total"], 1)

    def test_service_hybrid_property(self):
        hil = self.svc.companion_hybrid
        self.assertIsNotNone(hil)
        self.assertEqual(
            hil.stats()["matcher"]["capability_count"], 8)

    def test_config_disabled(self):
        svc = setup_service(companion_hybrid_enabled=False)
        r = svc.companion_hybrid_execute(
            {"type": "identity_query"}, {},
        )
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_config_cloud_disabled(self):
        svc = setup_service(companion_hybrid_cloud_enabled=False)
        r = svc.companion_hybrid_route(
            {"type": "creative_exploration"},
        )
        self.assertEqual(r["route"], "LOCAL")


class TestSecurity(unittest.TestCase):
    """安全保证"""

    def setUp(self):
        self.svc = setup_service()

    def test_personality_stable_after_hybrid(self):
        before = self.svc.companion_personality_engine\
            .personality()["base"]
        self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"}, {},
        )
        self.svc.companion_hybrid_execute(
            {"type": "identity_query"}, {},
        )
        after = self.svc.companion_personality_engine\
            .personality()["base"]
        self.assertEqual(before, after)

    def test_hybrid_never_auto_growth(self):
        self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"}, {},
        )
        applier = self.svc.companion_growth_engine[
            "applier"].stats()
        self.assertEqual(applier["applied_count"], 0)

    def test_hybrid_no_identity_guard_intercept(self):
        before = self.svc.companion_identity_guard[
            "guard"].stats()["intercept_count"]
        self.svc.companion_hybrid_execute(
            {"type": "identity_query"}, {},
        )
        after = self.svc.companion_identity_guard[
            "guard"].stats()["intercept_count"]
        self.assertEqual(before, after)

    def test_hybrid_does_not_write_memory(self):
        before = self.svc.companion_experience.stats()[
            "total"]
        self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"}, {},
        )
        after = self.svc.companion_experience.stats()[
            "total"]
        self.assertEqual(before, after)

    def test_cloud_result_temporary_only(self):
        r = self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"}, {},
        )
        self.assertTrue(r["temporary"])


class TestCompatibility(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_version_680(self):
        self.assertEqual(
            self.svc.report()["version"], "9.5.0")

    def test_old_growth_api(self):
        r = self.svc.companion_growth_stats()
        self.assertIn("proposal", r)

    def test_old_emotion_api(self):
        r = self.svc.companion_emotion()
        self.assertIn("positivity", r)

    def test_old_reflection_api(self):
        r = self.svc.companion_reflection_analyze()
        self.assertIn("report_id", r)

    def test_old_rhythm_api(self):
        r = self.svc.companion_growth_rhythm()
        self.assertIn("enabled", r)

    def test_old_growth_cycle_api(self):
        r = self.svc.companion_growth_pending_approvals()
        self.assertIn("pending_count", r)

    def test_old_trend_api(self):
        r = self.svc.companion_growth_trend_analysis()
        self.assertIn("growth_score", r)

    def test_companion_status_version(self):
        r = self.svc.companion.status()
        self.assertEqual(r["version"], "9.5.0")

    def test_handle_still_works(self):
        r = self.svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)
        self.assertIn("growth_cycle_check", r)


class TestHybridFlow(unittest.TestCase):
    """端到端调度流"""

    def test_three_routes_flow(self):
        svc = setup_service()
        # 本地: 身份
        r1 = svc.companion_hybrid_execute(
            {"type": "identity_query"}, {"query": "我是谁"},
        )
        self.assertEqual(r1["route"], "LOCAL")
        # 云端: 架构
        r2 = svc.companion_hybrid_execute(
            {"type": "architecture_design"},
            {"prompt": "设计"},
        )
        self.assertEqual(r2["route"], "CLOUD")
        # 混合: 分析
        r3 = svc.companion_hybrid_execute({
            "type": "analysis",
            "complexity": 0.55,
            "creativity_requirement": 0.45,
        }, {"prompt": "分析"})
        self.assertEqual(r3["route"], "HYBRID")
        # 审计完整
        report = svc.companion_hybrid_audit()
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["by_route"]["LOCAL"], 1)
        self.assertEqual(report["by_route"]["CLOUD"], 1)
        self.assertEqual(report["by_route"]["HYBRID"], 1)

    def test_growth_governance_independent(self):
        svc = setup_service()
        svc.companion_hybrid_execute(
            {"type": "creative_exploration"}, {},
        )
        # HIL 不产生成长建议/审批 (能力选择 ≠ 成长决策)
        cycle = svc.companion_growth_cycle.stats()
        self.assertEqual(cycle["cycle_count"], 0)


if __name__ == "__main__":
    unittest.main()
