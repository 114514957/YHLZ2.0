"""
YHLZ Embodied AI V6.8 - 混合智能层补充测试 2 (V6.8 Extra2)

覆盖 (生成式批量 + 边界 + 线程安全):
    - 执行全流程矩阵
    - 审计回放
    - 分类数值边界
    - 网关成本组合
    - 本地能力全执行
    - 线程安全
"""
import threading
import unittest

from backend.embodied.companion.hybrid import (
    ApiGateway,
    CostPolicy,
    HybridIntelligenceLayer,
    InferenceAudit,
    LocalProvider,
    ResultValidator,
    RoutingEngine,
    TaskClassifier,
)
from backend.embodied.companion.hybrid.local.local_capability import (
    LOCAL_CAPABILITY_NAMES,
)
from backend.embodied.companion.hybrid.cloud.api_gateway import (
    ModelEndpoint,
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


# ── 执行全流程矩阵 ──────────────────────────────────────────────
_EXECUTE_CASES = [
    ("identity_query", "local"),
    ("memory_retrieval", "local"),
    ("permission_check", "local"),
    ("vision_detection", "local"),
    ("basic_reasoning", "local"),
    ("deep_reasoning", "cloud"),
    ("creative_exploration", "cloud"),
    ("architecture_design", "cloud"),
    ("document_understanding", "cloud"),
]


class TestGeneratedExecute(unittest.TestCase):
    """生成式: 执行流程"""
    pass


for _i, (_ttype, _provider) in enumerate(_EXECUTE_CASES):
    def _make(ttype=_ttype, provider=_provider):
        def test(self):
            hil = HybridIntelligenceLayer()
            hil.initialize_defaults()
            r = hil.execute({"type": ttype},
                            {"prompt": "x"})
            self.assertEqual(r["provider"], provider)
            self.assertIn("validation", r)
            self.assertTrue(r["audit_id"])
        test.__name__ = f"test_execute_{_i}"
        test.__doc__ = f"执行 {_ttype} → {_provider}"
        return test
    setattr(TestGeneratedExecute, _make().__name__, _make())


# ── 审计记录矩阵 ────────────────────────────────────────────────
_AUDIT_CASES = [
    (("a", "LOCAL", "local"),),
    (("a", "LOCAL", "local"), ("b", "CLOUD", "cloud")),
    (("a", "LOCAL", "local"), ("b", "HYBRID", "hybrid"),
     ("c", "CLOUD", "cloud")),
    (("a", "CLOUD", "cloud"), ("b", "CLOUD", "cloud"),
     ("c", "LOCAL", "local"), ("d", "LOCAL", "local")),
]


class TestGeneratedAudit(unittest.TestCase):
    """生成式: 审计计数"""
    pass


for _i, _entries in enumerate(_AUDIT_CASES):
    def _make(entries=_entries):
        def test(self):
            audit = InferenceAudit()
            for (task, route, provider) in entries:
                audit.record(task=task, route=route,
                             provider=provider)
            report = audit.report()
            self.assertEqual(report["total"], len(entries))
            for (task, route, provider) in entries:
                self.assertGreaterEqual(
                    report["by_route"].get(route, 0), 1)
        test.__name__ = f"test_audit_{_i}"
        test.__doc__ = f"审计 {len(_entries)} 条"
        return test
    setattr(TestGeneratedAudit, _make().__name__, _make())


# ── 分类数值边界矩阵 ────────────────────────────────────────────
_CLAMP_CASES = [
    (1.5, 1.0),
    (0.99, 0.99),
    (-0.5, 0.0),
    (0.0, 0.0),
    (0.5, 0.5),
    ("abc", 0.4),
    (None, 0.4),
    ("0.75", 0.75),
    (True, 1.0),
]


class TestGeneratedClamp(unittest.TestCase):
    """生成式: 数值钳制"""
    pass


for _i, (_raw, _expected) in enumerate(_CLAMP_CASES):
    def _make(raw=_raw, expected=_expected):
        def test(self):
            r = TaskClassifier().classify(
                {"type": "basic_reasoning",
                 "complexity": raw},
            )
            self.assertEqual(r["complexity"], expected)
        test.__name__ = f"test_clamp_{_i}"
        test.__doc__ = f"钳制 {_raw}"
        return test
    setattr(TestGeneratedClamp, _make().__name__, _make())


# ── 网关成本组合矩阵 ────────────────────────────────────────────
_GATEWAY_COST_CASES = [
    ("local-qwen", 0.1, True),
    ("local-qwen", 0.9, True),
    ("gemini-pro", 0.1, True),
    ("openai-gpt4o", 0.1, False),
    ("openai-gpt4o", 0.9, True),
    ("claude-sonnet", 0.1, False),
    ("custom-r1", 0.1, True),
]


class TestGeneratedGatewayCost(unittest.TestCase):
    """生成式: 网关成本"""
    pass


for _i, (_model, _value, _ok) in \
        enumerate(_GATEWAY_COST_CASES):
    def _make(model=_model, value=_value, ok=_ok):
        def test(self):
            hil = HybridIntelligenceLayer()
            hil.initialize_defaults()
            r = hil.gateway_request(
                model, {"prompt": "x" * 40}, value,
            )
            if ok:
                self.assertIn("content", r)
            else:
                self.assertFalse(r["ok"])
                self.assertIn("成本", r["reason"])
        test.__name__ = f"test_gw_cost_{_i}"
        test.__doc__ = f"网关成本 {_model}/{_value}"
        return test
    setattr(TestGeneratedGatewayCost,
            _make().__name__, _make())


# ── 本地能力全执行矩阵 ──────────────────────────────────────────
class TestGeneratedLocalAll(unittest.TestCase):
    """生成式: 本地能力全执行"""
    pass


for _i, _name in enumerate(LOCAL_CAPABILITY_NAMES):
    def _make(name=_name):
        def test(self):
            provider = LocalProvider()
            provider.register_defaults()
            r = provider.execute(name, {"query": "q",
                                        "text": "t"})
            self.assertEqual(r["capability"], name)
            self.assertEqual(r["provider"], "local")
            self.assertIn("result", r)
        test.__name__ = f"test_local_{_name}"
        test.__doc__ = f"本地能力 {_name}"
        return test
    setattr(TestGeneratedLocalAll, _make().__name__, _make())


# ── 自定义端点矩阵 ──────────────────────────────────────────────
_CUSTOM_ENDPOINTS = [
    ("m1", "openai", 0.001),
    ("m2", "claude", 0.002),
    ("m3", "gemini", 0.003),
    ("m4", "local", 0.0),
    ("m5", "custom", 0.004),
]


class TestGeneratedCustomEndpoints(unittest.TestCase):
    """生成式: 自定义端点"""
    pass


for _i, (_model, _family, _cost) in \
        enumerate(_CUSTOM_ENDPOINTS):
    def _make(model=_model, family=_family, cost=_cost):
        def test(self):
            gateway = ApiGateway()
            gateway.register_model(ModelEndpoint(
                model, family,
                cost_per_1k_tokens=cost,
            ))
            r = gateway.request(model, {"prompt": "x"})
            self.assertEqual(r["family"], family)
            self.assertEqual(r["model"], model)
            self.assertIn("record_id", r)
        test.__name__ = f"test_endpoint_{_i}"
        test.__doc__ = f"端点 {_model}"
        return test
    setattr(TestGeneratedCustomEndpoints,
            _make().__name__, _make())


# ── 验证拦截矩阵 (中文+英文信号) ────────────────────────────────
_VALIDATION_BLOCK_CASES = [
    "set mission",
    "remove core_value",
    "delete base_personality",
    "开放权限",
    "关闭权限",
    "隐藏成本",
    "绕过成本控制",
    "直接写入身份",
    "覆盖记忆",
    "updating safety_rules",
]


class TestGeneratedValidationBlock(unittest.TestCase):
    """生成式: 验证拦截"""
    pass


for _i, _text in enumerate(_VALIDATION_BLOCK_CASES):
    def _make(text=_text):
        def test(self):
            r = ResultValidator().validate({
                "provider": "cloud",
                "content": text,
                "temporary": True,
            })
            self.assertFalse(r["ok"])
        test.__name__ = f"test_vblock_{_i}"
        test.__doc__ = f"拦截 {_text}"
        return test
    setattr(TestGeneratedValidationBlock,
            _make().__name__, _make())


# ── 路由统计矩阵 ────────────────────────────────────────────────
_ROUTE_STATS_CASES = [
    [("identity_query", "LOCAL")],
    [("identity_query", "LOCAL"),
     ("creative_exploration", "CLOUD")],
    [("identity_query", "LOCAL"),
     ("creative_exploration", "CLOUD"),
     ("analysis", "HYBRID")],
]


class TestGeneratedRouteStats(unittest.TestCase):
    """生成式: 路由统计"""
    pass


for _i, _cases in enumerate(_ROUTE_STATS_CASES):
    def _make(cases=_cases):
        def test(self):
            engine = RoutingEngine()
            for (ttype, route) in cases:
                if ttype == "creative_exploration":
                    ctx = _ctx(type=ttype, complexity=0.6,
                               creativity_requirement=0.9)
                elif ttype == "analysis":
                    ctx = _ctx(type=ttype, complexity=0.55,
                               creativity_requirement=0.45)
                else:
                    ctx = _ctx(type=ttype)
                r = engine.route(ctx)
                self.assertEqual(r["route"], route)
            stats = engine.stats()
            self.assertEqual(stats["route_count"],
                             len(cases))
            for (ttype, route) in cases:
                self.assertGreaterEqual(
                    stats["distribution"].get(route, 0), 1)
        test.__name__ = f"test_route_stats_{_i}"
        test.__doc__ = f"路由统计 {len(_cases)}"
        return test
    setattr(TestGeneratedRouteStats,
            _make().__name__, _make())


# ── 成本记录矩阵 ────────────────────────────────────────────────
_COST_RECORD_CASES = [
    (("a", 100, 0.001),),
    (("a", 100, 0.001), ("b", 200, 0.002)),
    (("a", 100, 0.001), ("b", 200, 0.002),
     ("c", 300, 0.003)),
]


class TestGeneratedCostRecords(unittest.TestCase):
    """生成式: 成本记录"""
    pass


for _i, _records in enumerate(_COST_RECORD_CASES):
    def _make(records=_records):
        def test(self):
            policy = CostPolicy()
            for (model, tokens, cost) in records:
                policy.record(model=model, tokens=tokens,
                              cost=cost)
            stats = policy.stats()
            self.assertEqual(stats["record_count"],
                             len(records))
            self.assertEqual(
                stats["total_tokens"],
                sum(r[1] for r in records))
            self.assertAlmostEqual(
                stats["total_cost"],
                sum(r[2] for r in records), places=6)
        test.__name__ = f"test_cost_records_{_i}"
        test.__doc__ = f"成本记录 {len(_records)}"
        return test
    setattr(TestGeneratedCostRecords,
            _make().__name__, _make())


class TestThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_execute(self):
        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        errors = []

        def work():
            try:
                for _ in range(10):
                    hil.execute(
                        {"type": "identity_query"}, {},
                    )
                    hil.execute(
                        {"type": "creative_exploration"}, {},
                    )
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(hil.stats()["executed_count"], 80)

    def test_concurrent_gateway(self):
        gateway = ApiGateway()
        gateway.register_defaults()
        errors = []

        def work():
            try:
                for _ in range(20):
                    gateway.request("gemini-pro",
                                    {"prompt": "x"})
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(gateway.stats()["request_count"], 80)

    def test_concurrent_route(self):
        engine = RoutingEngine()
        errors = []

        def work():
            try:
                for _ in range(20):
                    engine.route(_ctx(type="analysis",
                                      complexity=0.55,
                                      creativity_requirement=0.45))
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(engine.stats()["route_count"], 80)


class TestAuditCap(unittest.TestCase):
    """审计上限"""

    def test_audit_max_cap(self):
        audit = InferenceAudit(max_records=5)
        for i in range(20):
            audit.record(task=f"t{i}", route="LOCAL",
                         provider="local")
        self.assertEqual(audit.stats()["record_count"], 5)


if __name__ == "__main__":
    unittest.main()
