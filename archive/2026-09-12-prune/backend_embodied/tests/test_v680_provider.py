"""
YHLZ Embodied AI V6.8 - 混合智能层提供器单元测试 (Providers)

覆盖:
    - LocalProvider: 本地能力执行/错误帧
    - ApiGateway: 模型注册/调用记录/成本
    - CloudProvider: 云端执行/临时标记
"""
import unittest

from backend.embodied.companion.hybrid import (
    ApiGateway,
    CloudProvider,
    LocalProvider,
    ModelEndpoint,
)
from backend.embodied.companion.hybrid.cloud.api_gateway import (
    MODEL_FAMILIES,
    GatewayError,
)
from backend.embodied.companion.hybrid.local.local_capability import (
    LOCAL_CAPABILITY_NAMES,
    LocalCapability,
    LocalCapabilityError,
)


class TestLocalProvider(unittest.TestCase):
    """本地智能提供器"""

    def setUp(self):
        self.provider = LocalProvider()
        self.provider.register_defaults()

    def test_register_defaults(self):
        caps = self.provider.capabilities()
        self.assertEqual(caps["total"], 5)

    def test_execute_identity(self):
        r = self.provider.execute("identity",
                                  {"query": "我是谁"})
        self.assertEqual(r["provider"], "local")
        self.assertEqual(r["capability"], "identity")
        self.assertIn("result", r)

    def test_execute_memory(self):
        r = self.provider.execute("memory",
                                  {"query": "昨天的事"})
        self.assertEqual(r["capability"], "memory")
        self.assertIn("本地记忆检索", r["result"])

    def test_execute_vision(self):
        r = self.provider.execute("vision", {})
        self.assertIn("视觉检测", r["result"])

    def test_execute_embedding(self):
        r = self.provider.execute("embedding",
                                  {"text": "你好"})
        self.assertEqual(r["dimension"], 128)

    def test_execute_basic(self):
        r = self.provider.execute("basic_reasoning",
                                  {"query": "判断"})
        self.assertIn("基础推理", r["result"])

    def test_execute_all_defaults(self):
        for name in LOCAL_CAPABILITY_NAMES:
            r = self.provider.execute(name, {})
            self.assertEqual(r["capability"], name)
            self.assertIn("result", r)

    def test_unknown_capability_error_frame(self):
        r = self.provider.execute("bogus", {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["mode"], "error_frame")

    def test_disabled_provider(self):
        provider = LocalProvider(enabled=False)
        r = provider.execute("identity", {})
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_custom_handler(self):
        def handler(req):
            return {"mode": "rule_based", "result": "custom"}

        provider = LocalProvider()
        provider.register_defaults()
        from backend.embodied.companion.hybrid import (
            LocalCapability,
        )
        provider._registry.register(LocalCapability(
            name="identity", handler=handler,
        ))
        r = provider.execute("identity", {})
        self.assertEqual(r["result"], "custom")

    def test_capability_available(self):
        self.assertTrue(self.provider.has_capability("identity"))
        self.assertFalse(self.provider.has_capability("bogus"))

    def test_latency_recorded(self):
        r = self.provider.execute("identity", {})
        self.assertIn("latency_ms", r)

    def test_execute_count(self):
        self.provider.execute("identity", {})
        self.provider.execute("memory", {})
        self.assertEqual(self.provider.stats()[
            "execute_count"], 2)

    def test_stats_structure(self):
        stats = self.provider.stats()
        self.assertEqual(stats["provider"], "local")
        self.assertIn("capability_count", stats)

    def test_clear(self):
        self.provider.execute("identity", {})
        n = self.provider.clear()
        self.assertGreater(n, 0)
        self.assertEqual(self.provider.stats()[
            "execute_count"], 0)

    def test_unregistered_raises_via_error_frame(self):
        provider = LocalProvider()
        r = provider.execute("identity", {})
        self.assertFalse(r["ok"])


class TestApiGateway(unittest.TestCase):
    """API 网关"""

    def setUp(self):
        self.gateway = ApiGateway()
        self.gateway.register_defaults()

    def test_register_defaults(self):
        models = self.gateway.models()
        self.assertEqual(models["total"], 5)

    def test_request_mock_response(self):
        r = self.gateway.request("openai-gpt4o",
                                 {"prompt": "hello"})
        self.assertEqual(r["mode"], "mock")
        self.assertIn("content", r)

    def test_request_unknown_model(self):
        r = self.gateway.request("bogus-model", {})
        self.assertFalse(r["ok"])
        self.assertIn("未注册", r["reason"])

    def test_request_records(self):
        self.gateway.request("openai-gpt4o",
                             {"prompt": "x" * 40})
        records = self.gateway.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["model"], "openai-gpt4o")

    def test_record_id_in_response(self):
        r = self.gateway.request("gemini-pro", {})
        self.assertTrue(r["record_id"].startswith("gw_"))

    def test_cost_calculated(self):
        r = self.gateway.request("openai-gpt4o",
                                 {"prompt": "x" * 400})
        self.assertGreaterEqual(r["cost"], 0.0)

    def test_usage_tokens(self):
        r = self.gateway.request("openai-gpt4o",
                                 {"prompt": "x" * 100})
        self.assertGreater(r["usage"]["total_tokens"], 0)

    def test_custom_endpoint_handler(self):
        def handler(payload):
            return {
                "mode": "real",
                "content": "custom response",
                "usage": {"total_tokens": 10},
            }

        self.gateway.register_model(ModelEndpoint(
            "custom-model", "custom", handler=handler,
        ))
        r = self.gateway.request("custom-model", {})
        self.assertEqual(r["content"], "custom response")

    def test_register_overwrite(self):
        self.gateway.register_model(ModelEndpoint(
            "openai-gpt4o", "openai",
            cost_per_1k_tokens=0.99,
        ))
        models = self.gateway.models()
        m = next(x for x in models["models"]
                 if x["model"] == "openai-gpt4o")
        self.assertEqual(m["cost_per_1k_tokens"], 0.99)

    def test_unregister_model(self):
        self.gateway.register_model(ModelEndpoint("temp-m"))
        self.assertTrue(self.gateway.unregister_model("temp-m"))
        r = self.gateway.request("temp-m", {})
        self.assertFalse(r["ok"])

    def test_invalid_family(self):
        with self.assertRaises(GatewayError):
            ModelEndpoint("x", "bogus")

    def test_families_constant(self):
        self.assertEqual(MODEL_FAMILIES,
                         ["openai", "claude", "gemini",
                          "local", "custom"])

    def test_disabled_gateway(self):
        gateway = ApiGateway(enabled=False)
        r = gateway.request("openai-gpt4o", {})
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_stats_totals(self):
        self.gateway.request("openai-gpt4o", {"prompt": "x"})
        self.gateway.request("claude-sonnet", {"prompt": "y"})
        stats = self.gateway.stats()
        self.assertEqual(stats["request_count"], 2)
        self.assertEqual(stats["record_count"], 2)
        self.assertGreaterEqual(stats["total_tokens"], 0)

    def test_records_replayable(self):
        self.gateway.request("gemini-pro",
                             {"prompt": "question"})
        records = self.gateway.records()
        self.assertIn("time", records[0])
        self.assertIn("family", records[0])
        self.assertIn("tokens", records[0])

    def test_clear(self):
        self.gateway.request("gemini-pro", {})
        n = self.gateway.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.gateway.stats()[
            "request_count"], 0)


class TestCloudProvider(unittest.TestCase):
    """云端智能提供器"""

    def setUp(self):
        self.gateway = ApiGateway()
        self.gateway.register_defaults()
        self.provider = CloudProvider(gateway=self.gateway)

    def test_execute_deep_reasoning(self):
        r = self.provider.execute("deep_reasoning",
                                  {"prompt": "推理"})
        self.assertEqual(r["provider"], "cloud")
        self.assertEqual(r["capability"], "deep_reasoning")

    def test_execute_creative(self):
        r = self.provider.execute("creative",
                                  {"prompt": "创意"})
        self.assertEqual(r["capability"], "creative")

    def test_execute_analysis(self):
        r = self.provider.execute("analysis",
                                  {"prompt": "分析"})
        self.assertEqual(r["capability"], "analysis")

    def test_unknown_capability(self):
        r = self.provider.execute("bogus", {})
        self.assertFalse(r["ok"])
        self.assertIn("未知", r["reason"])

    def test_temporary_marked(self):
        r = self.provider.execute("deep_reasoning", {})
        self.assertTrue(r["temporary"])

    def test_records_gateway_calls(self):
        self.provider.execute("deep_reasoning", {})
        records = self.provider.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["model"], "custom-r1")

    def test_disabled_provider(self):
        provider = CloudProvider(enabled=False)
        r = provider.execute("deep_reasoning", {})
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_capability_distribution(self):
        self.provider.execute("deep_reasoning", {})
        self.provider.execute("deep_reasoning", {})
        self.provider.execute("creative", {})
        stats = self.provider.stats()
        self.assertEqual(stats["capability_distribution"][
            "deep_reasoning"], 2)
        self.assertEqual(stats["capability_distribution"][
            "creative"], 1)

    def test_stats_gateway(self):
        stats = self.provider.stats()
        self.assertIn("gateway", stats)

    def test_clear(self):
        self.provider.execute("deep_reasoning", {})
        n = self.provider.clear()
        self.assertGreater(n, 0)
        self.assertEqual(self.provider.stats()[
            "execute_count"], 0)


if __name__ == "__main__":
    unittest.main()
