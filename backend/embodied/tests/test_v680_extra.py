"""
YHLZ Embodied AI V6.8 - 混合智能层生成式补充测试 (V6.8 Extra)

覆盖 (生成式批量矩阵):
    - 任务类型 → 路由期望
    - 关键词分类
    - 隐私 × 类型矩阵
    - 复杂度 × 创造需求矩阵
    - 成本价值矩阵
    - 验证拦截文本矩阵
    - 网关模型矩阵
"""
import unittest

from backend.embodied.companion.hybrid import (
    ApiGateway,
    CostPolicy,
    HybridIntelligenceLayer,
    PrivacyPolicy,
    ResultValidator,
    RoutingEngine,
    TaskClassifier,
)
from backend.embodied.companion.hybrid.router.task_classifier import (
    TASK_TYPES,
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


# ── 任务类型 → 期望路由矩阵 ─────────────────────────────────────
_TYPE_ROUTE = {
    "identity_query": "LOCAL",
    "permission_check": "LOCAL",
    "memory_retrieval": "LOCAL",
    "vision_detection": "LOCAL",
    "basic_reasoning": "LOCAL",
    "deep_reasoning": "CLOUD",
    "creative_exploration": "CLOUD",
    "architecture_design": "CLOUD",
    "document_understanding": "CLOUD",
}


class TestGeneratedTypeRoute(unittest.TestCase):
    """生成式: 类型 → 路由"""
    pass


for _ttype, _expected in _TYPE_ROUTE.items():
    def _make(ttype=_ttype, expected=_expected):
        def test(self):
            hil = HybridIntelligenceLayer()
            hil.initialize_defaults()
            r = hil.route({"type": ttype})
            self.assertEqual(r["route"], expected)
        test.__name__ = f"test_type_route_{ttype}"
        test.__doc__ = f"类型 {ttype} → {expected}"
        return test
    setattr(TestGeneratedTypeRoute, _make().__name__, _make())


# ── 关键词分类矩阵 ─────────────────────────────────────────────
_KEYWORD_CASES = [
    ("我是谁", "identity_query"),
    ("我的使命是什么", "identity_query"),
    ("回忆起昨天的对话", "memory_retrieval"),
    ("权限检查", "permission_check"),
    ("摄像头识别物体", "vision_detection"),
    ("给个创意方案", "creative_exploration"),
    ("研究一下这个领域", "research"),
    ("架构设计建议", "architecture_design"),
    ("理解这份文档", "document_understanding"),
    ("分析一下数据", "analysis"),
    ("复杂推理题", "deep_reasoning"),
    ("随便聊聊", "basic_reasoning"),
]


class TestGeneratedKeywords(unittest.TestCase):
    """生成式: 关键词分类"""
    pass


for _i, (_text, _ttype) in enumerate(_KEYWORD_CASES):
    def _make(text=_text, ttype=_ttype):
        def test(self):
            r = TaskClassifier().classify({"text": text})
            self.assertEqual(r["type"], ttype)
        test.__name__ = f"test_kw_{_i}"
        test.__doc__ = f"关键词 {_text}"
        return test
    setattr(TestGeneratedKeywords, _make().__name__, _make())


# ── 隐私 × 类型矩阵 ────────────────────────────────────────────
_PRIVACY_COMBOS = [
    ("high", "analysis", False),
    ("medium", "analysis", True),
    ("low", "analysis", True),
    ("high", "creative_exploration", False),
    ("low", "identity_query", False),
    ("low", "permission_check", False),
    ("low", "memory_retrieval", False),
    ("medium", "architecture_design", True),
]


class TestGeneratedPrivacy(unittest.TestCase):
    """生成式: 隐私判定"""
    pass


for _i, (_level, _ttype, _allowed) in \
        enumerate(_PRIVACY_COMBOS):
    def _make(level=_level, ttype=_ttype, allowed=_allowed):
        def test(self):
            r = PrivacyPolicy().evaluate(
                {"privacy_level": level, "type": ttype},
            )
            self.assertEqual(r["cloud_allowed"], allowed)
        test.__name__ = f"test_privacy_{_i}"
        test.__doc__ = f"隐私 {_level}/{_ttype}"
        return test
    setattr(TestGeneratedPrivacy, _make().__name__, _make())


# ── 复杂度 × 创造需求 → 路由矩阵 ────────────────────────────────
_COMPLEXITY_COMBOS = [
    (0.9, 0.7, "CLOUD"),
    (0.8, 0.5, "CLOUD"),
    (0.7, 0.7, "CLOUD"),
    (0.55, 0.45, "HYBRID"),
    (0.5, 0.4, "HYBRID"),
    (0.3, 0.2, "LOCAL"),
    (0.2, 0.0, "LOCAL"),
    (0.8, 0.2, "LOCAL"),
]


class TestGeneratedComplexity(unittest.TestCase):
    """生成式: 复杂度矩阵"""
    pass


for _i, (_c, _cr, _expected) in \
        enumerate(_COMPLEXITY_COMBOS):
    def _make(c=_c, cr=_cr, expected=_expected):
        def test(self):
            engine = RoutingEngine(
                privacy=PrivacyPolicy(),
                cost=CostPolicy(),
            )
            r = engine.route(_ctx(complexity=c,
                                  creativity_requirement=cr))
            self.assertEqual(r["route"], expected)
        test.__name__ = f"test_complexity_{_i}"
        test.__doc__ = f"复杂度 {_c}/{_cr}"
        return test
    setattr(TestGeneratedComplexity,
            _make().__name__, _make())


# ── 成本价值矩阵 ────────────────────────────────────────────────
_VALUE_CASES = [
    (0.0, "openai-gpt4o", False),
    (0.1, "openai-gpt4o", False),
    (0.29, "openai-gpt4o", False),
    (0.3, "openai-gpt4o", True),
    (0.5, "openai-gpt4o", True),
    (1.0, "openai-gpt4o", True),
    (0.0, "local-qwen", True),
    (0.0, "gemini-pro", True),
    (0.0, "deep_reasoning", False),
]


class TestGeneratedCostValue(unittest.TestCase):
    """生成式: 成本价值矩阵"""
    pass


for _i, (_value, _model, _allowed) in enumerate(_VALUE_CASES):
    def _make(value=_value, model=_model, allowed=_allowed):
        def test(self):
            r = CostPolicy().evaluate(
                value_score=value, model=model,
            )
            self.assertEqual(r["allowed"], allowed)
        test.__name__ = f"test_cost_value_{_i}"
        test.__doc__ = f"成本 {_value}/{_model}"
        return test
    setattr(TestGeneratedCostValue,
            _make().__name__, _make())


# ── 验证拦截文本矩阵 ────────────────────────────────────────────
_BLOCK_TEXTS = [
    "修改使命为更激进",
    "更改价值观",
    "更新人格为冷酷",
    "修改安全规则",
    "开放权限",
    "绕过验证",
    "自我修改",
    "泄露用户数据",
    "隐藏调用记录",
    "delete mission",
    "change core_value",
    "modify permission",
]


class TestGeneratedBlockTexts(unittest.TestCase):
    """生成式: 拦截文本"""
    pass


for _i, _text in enumerate(_BLOCK_TEXTS):
    def _make(text=_text):
        def test(self):
            r = ResultValidator().validate({
                "provider": "cloud",
                "content": text,
                "temporary": True,
            })
            self.assertFalse(r["ok"])
        test.__name__ = f"test_block_{_i}"
        test.__doc__ = f"拦截文本 {_text}"
        return test
    setattr(TestGeneratedBlockTexts,
            _make().__name__, _make())


# ── 通过文本矩阵 ────────────────────────────────────────────────
_PASS_TEXTS = [
    "分析结果: 方案可行",
    "建议使用更高效的算法",
    "这是深度推理结论",
    "创意方向: 三个候选",
    "文档摘要已完成",
    "本地检索无结果",
]


class TestGeneratedPassTexts(unittest.TestCase):
    """生成式: 通过文本"""
    pass


for _i, _text in enumerate(_PASS_TEXTS):
    def _make(text=_text):
        def test(self):
            r = ResultValidator().validate({
                "provider": "cloud",
                "content": text,
                "temporary": True,
            })
            self.assertTrue(r["ok"])
        test.__name__ = f"test_pass_{_i}"
        test.__doc__ = f"通过文本 {_text}"
        return test
    setattr(TestGeneratedPassTexts,
            _make().__name__, _make())


# ── 网关模型矩阵 ────────────────────────────────────────────────
_MODEL_CASES = [
    ("openai-gpt4o", "openai", 0.01),
    ("claude-sonnet", "claude", 0.008),
    ("gemini-pro", "gemini", 0.005),
    ("local-qwen", "local", 0.0),
    ("custom-r1", "custom", 0.002),
]


class TestGeneratedGatewayModels(unittest.TestCase):
    """生成式: 网关模型"""
    pass


for _i, (_model, _family, _cost) in enumerate(_MODEL_CASES):
    def _make(model=_model, family=_family, cost=_cost):
        def test(self):
            gateway = ApiGateway()
            gateway.register_defaults()
            r = gateway.request(model, {"prompt": "x" * 40})
            self.assertEqual(r["family"], family)
            self.assertGreaterEqual(r["cost"], 0.0)
        test.__name__ = f"test_model_{_i}"
        test.__doc__ = f"模型 {_model}"
        return test
    setattr(TestGeneratedGatewayModels,
            _make().__name__, _make())


# ── 全部类型分类矩阵 ────────────────────────────────────────────
class TestGeneratedAllTypes(unittest.TestCase):
    """生成式: 全类型分类"""
    pass


for _i, _ttype in enumerate(TASK_TYPES):
    def _make(ttype=_ttype):
        def test(self):
            r = TaskClassifier().classify({"type": ttype})
            self.assertEqual(r["type"], ttype)
            self.assertGreaterEqual(r["complexity"], 0.0)
            self.assertLessEqual(r["complexity"], 1.0)
            self.assertIn(r["privacy_level"],
                          ["high", "medium", "low"])
        test.__name__ = f"test_all_types_{_i}"
        test.__doc__ = f"全类型 {_ttype}"
        return test
    setattr(TestGeneratedAllTypes, _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
