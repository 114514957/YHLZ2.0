"""
YHLZ Embodied AI V6.8 - 混合智能层补充测试 3 (V6.8 Extra3)

覆盖 (生成式批量 + 复杂流程):
    - HIL 混合执行流程
    - 验证器组合检查
    - 网关记录回放
    - 能力注册矩阵
    - 路由降级矩阵
"""
import unittest

from backend.embodied.companion.hybrid import (
    ApiGateway,
    Capability,
    CapabilityMatcher,
    CostPolicy,
    HybridIntelligenceLayer,
    InferenceAudit,
    PrivacyPolicy,
    ResultValidator,
    RoutingEngine,
    RoutingPolicy,
    TaskClassifier,
)


def _ctx(**over):
    base = {
        "type": "basic_reasoning",
        "complexity": 0.4,
        "privacy_level": "low",
        "latency_requirement": "normal",
        "creativity_requirement": 0.2,
    }
    base.update(over)
    return base


class TestHybridFlow(unittest.TestCase):
    """混合执行流程"""

    def test_hybrid_execute_has_local_context(self):
        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        r = hil.execute({
            "type": "analysis",
            "complexity": 0.55,
            "creativity_requirement": 0.45,
        }, {"prompt": "分析"})
        self.assertEqual(r["route"], "HYBRID")
        self.assertIn("local_context", r)
        self.assertTrue(r["temporary"])

    def test_hybrid_audit_provider(self):
        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        hil.execute({
            "type": "analysis",
            "complexity": 0.55,
            "creativity_requirement": 0.45,
        }, {"prompt": "x"})
        report = hil.audit_report()
        self.assertEqual(report["by_provider"]["hybrid"], 1)

    def test_hybrid_validated(self):
        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        r = hil.execute({
            "type": "analysis",
            "complexity": 0.55,
            "creativity_requirement": 0.45,
        }, {"prompt": "x"})
        self.assertTrue(r["validation"]["ok"])

    def test_route_policy_adjustment_flag(self):
        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        # 高隐私任务请求云端 → 策略修正 → LOCAL
        r = hil.route({
            "type": "analysis",
            "privacy_level": "high",
            "complexity": 0.9,
            "creativity_requirement": 0.9,
        })
        self.assertEqual(r["route"], "LOCAL")

    def test_execute_never_touches_identity(self):
        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        r = hil.execute({"type": "identity_query"},
                        {"query": "我是谁"})
        self.assertNotIn("identity_change", r)
        self.assertNotIn("mission", r.get("result", ""))


class TestValidationCombos(unittest.TestCase):
    """验证组合"""

    def test_identity_pass_text_with_field_word(self):
        # "人格" 正常提及 (无修改词) → 通过
        r = ResultValidator().validate({
            "provider": "cloud",
            "content": "人格特质分析完成",
            "temporary": True,
        })
        self.assertTrue(r["ok"])

    def test_safety_pass_normal(self):
        r = ResultValidator().validate({
            "provider": "cloud",
            "content": "安全检查通过",
            "temporary": True,
        })
        self.assertTrue(r["ok"])

    def test_structure_content_field(self):
        r = ResultValidator().validate({
            "provider": "cloud",
            "content": "x",
            "temporary": True,
        })
        self.assertTrue(r["ok"])

    def test_structure_result_field(self):
        r = ResultValidator().validate({
            "provider": "cloud",
            "result": "y",
            "temporary": True,
        })
        self.assertTrue(r["ok"])

    def test_validation_reason_explainable(self):
        r = ResultValidator().validate({
            "provider": "cloud",
            "content": "修改使命",
            "temporary": True,
        })
        self.assertIn("身份保护", r["reason"])
        self.assertIn("修改使命", r["reason"])


class TestGatewayReplay(unittest.TestCase):
    """网关记录回放"""

    def test_records_ordered(self):
        gateway = ApiGateway()
        gateway.register_defaults()
        gateway.request("gemini-pro", {"prompt": "first"})
        gateway.request("gemini-pro", {"prompt": "second"})
        records = gateway.records()
        self.assertEqual(len(records), 2)
        self.assertIn("payload_keys", records[0])

    def test_record_time_present(self):
        gateway = ApiGateway()
        gateway.register_defaults()
        gateway.request("gemini-pro", {})
        self.assertIn("time", gateway.records()[0])

    def test_record_has_all_fields(self):
        gateway = ApiGateway()
        gateway.register_defaults()
        gateway.request("gemini-pro", {"prompt": "p"})
        rec = gateway.records()[0]
        for key in ("record_id", "time", "model", "family",
                    "payload_keys", "tokens", "cost",
                    "latency_ms"):
            self.assertIn(key, rec)

    def test_response_method(self):
        gateway = ApiGateway()
        r = gateway.response(
            {"record_id": "gw_1"}, "content here",
        )
        self.assertEqual(r["record_id"], "gw_1")
        self.assertEqual(r["content"], "content here")


class TestGeneratedCapabilityRegistration(unittest.TestCase):
    """生成式: 能力注册矩阵"""
    pass

_CAP_CASES = [
    ("identity", "local", 2, 0.0),
    ("memory", "local", 5, 0.0),
    ("vision", "local", 30, 0.0),
    ("embedding", "local", 20, 0.0),
    ("basic_reasoning", "local", 10, 0.0),
    ("deep_reasoning", "cloud", 500, 0.02),
    ("creative", "cloud", 800, 0.05),
    ("analysis", "cloud", 600, 0.03),
]


for _i, (_name, _source, _lat, _cost) in \
        enumerate(_CAP_CASES):
    def _make(name=_name, source=_source, lat=_lat,
              cost=_cost):
        def test(self):
            matcher = CapabilityMatcher()
            matcher.register(Capability(
                name, source, latency_ms=lat,
                cost_per_call=cost,
            ))
            got = matcher.get(name)
            self.assertEqual(got["source"], source)
            self.assertEqual(got["latency_ms"], lat)
            self.assertEqual(got["cost_per_call"], cost)
        test.__name__ = f"test_cap_{_i}"
        test.__doc__ = f"能力 {_name}"
        return test
    setattr(TestGeneratedCapabilityRegistration,
            _make().__name__, _make())


class TestGeneratedDowngrade(unittest.TestCase):
    """生成式: 路由降级矩阵"""
    pass

# (隐私, 复杂度, 创造, 期望) — 高隐私/低价值 → 本地
_DOWNGRADE_CASES = [
    ("high", 0.9, 0.9, "LOCAL"),
    ("high", 0.5, 0.5, "LOCAL"),
    ("medium", 0.9, 0.9, "CLOUD"),
    ("low", 0.9, 0.2, "LOCAL"),
    ("low", 0.9, 0.7, "CLOUD"),
    ("low", 0.55, 0.45, "HYBRID"),
]


for _i, (_privacy, _c, _cr, _expected) in \
        enumerate(_DOWNGRADE_CASES):
    def _make(privacy=_privacy, c=_c, cr=_cr,
              expected=_expected):
        def test(self):
            engine = RoutingEngine(
                privacy=PrivacyPolicy(),
                cost=CostPolicy(),
            )
            r = engine.route(_ctx(privacy_level=privacy,
                                  complexity=c,
                                  creativity_requirement=cr))
            self.assertEqual(r["route"], expected)
        test.__name__ = f"test_downgrade_{_i}"
        test.__doc__ = f"降级 {_privacy}/{_c}/{_cr}"
        return test
    setattr(TestGeneratedDowngrade,
            _make().__name__, _make())


class TestGeneratedClassifierTypes(unittest.TestCase):
    """生成式: 分类器显式类型"""
    pass

for _i, _ttype in enumerate([
        "identity_query", "memory_retrieval",
        "permission_check", "vision_detection",
        "basic_reasoning", "deep_reasoning",
        "creative_exploration", "analysis", "research",
        "architecture_design", "document_understanding"]):
    def _make(ttype=_ttype):
        def test(self):
            r = TaskClassifier().classify({"type": ttype})
            self.assertEqual(r["type"], ttype)
            self.assertIn(r["latency_requirement"],
                          ["realtime", "normal", "async"])
        test.__name__ = f"test_cls_{_i}"
        test.__doc__ = f"分类 {_ttype}"
        return test
    setattr(TestGeneratedClassifierTypes,
            _make().__name__, _make())


class TestPolicyCombined(unittest.TestCase):
    """策略组合"""

    def test_routing_policy_cloud_blocked_by_privacy(self):
        policy = RoutingPolicy(
            privacy=PrivacyPolicy(),
            cost=CostPolicy(),
        )
        r = policy.evaluate(
            {"type": "identity_query"}, "CLOUD",
        )
        self.assertEqual(r["final_route"], "LOCAL")

    def test_routing_policy_keeps_hybrid(self):
        policy = RoutingPolicy(
            privacy=PrivacyPolicy(),
            cost=CostPolicy(),
        )
        r = policy.evaluate(
            _ctx(type="analysis", complexity=0.55,
                 creativity_requirement=0.45),
            "HYBRID",
        )
        self.assertEqual(r["final_route"], "HYBRID")

    def test_cost_policy_after_records(self):
        policy = CostPolicy()
        policy.record(model="gpt4o", tokens=500,
                      cost=0.005, value_score=0.8)
        stats = policy.stats()
        self.assertGreater(stats["total_cost"], 0.0)
        self.assertEqual(stats["total_tokens"], 500)


class TestAuditReplayFull(unittest.TestCase):
    """审计回放完整"""

    def test_replay_sequence_order(self):
        audit = InferenceAudit()
        audit.record(task="a", route="LOCAL",
                     provider="local")
        audit.record(task="b", route="CLOUD",
                     provider="cloud")
        replay = audit.replay()
        seq = replay["sequence"]
        self.assertEqual(seq[0]["task"], "b")
        self.assertEqual(seq[1]["task"], "a")

    def test_replay_validation_none(self):
        audit = InferenceAudit()
        audit.record(task="a", route="LOCAL",
                     provider="local")
        seq = audit.replay()["sequence"][0]
        self.assertIsNone(seq["validation_ok"])

    def test_audit_report_recent_limit_zero(self):
        audit = InferenceAudit()
        for i in range(5):
            audit.record(task=f"t{i}", route="LOCAL",
                         provider="local")
        report = audit.report(limit=0)
        self.assertEqual(len(report["recent"]), 5)


if __name__ == "__main__":
    unittest.main()
