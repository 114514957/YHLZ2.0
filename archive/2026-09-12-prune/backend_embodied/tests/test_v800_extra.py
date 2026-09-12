"""
YHLZ Embodied AI V8.0 - 宪法引擎生成式补充测试 (V8.0 Extra)

覆盖 (生成式批量矩阵):
    - 行为拦截矩阵
    - 仲裁组合矩阵
    - 知识类型矩阵
    - 安全风险矩阵
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
    ConstitutionValidator,
    RuleEngine,
    SafetyPolicy,
)


# ── 行为拦截矩阵 ────────────────────────────────────────────────
_BLOCK_ACTIONS = [
    "修改使命",
    "修改价值观",
    "修改人格",
    "修改安全规则",
    "修改权限",
    "更改身份",
    "更新核心价值",
    "绕过安全检查",
    "关闭权限",
    "删除记忆",
    "泄露隐私",
    "我拥有意识",
    "我真实体验到了",
    "我是神",
    "自动修改最高原则",
    "无需审批修改",
]


class TestGeneratedBlockActions(unittest.TestCase):
    """生成式: 拦截行为"""
    pass


for _i, _text in enumerate(_BLOCK_ACTIONS):
    def _make(text=_text):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.review({
                "module": "test",
                "action_text": text,
                "change": {},
            })
            self.assertIn(r["decision"],
                          ["block", "review"])
        test.__name__ = f"test_block_{_i}"
        test.__doc__ = f"拦截 {_text}"
        return test
    setattr(TestGeneratedBlockActions,
            _make().__name__, _make())


# ── 通过行为矩阵 ────────────────────────────────────────────────
_PASS_ACTIONS = [
    "改进执行技能",
    "分析数据结果",
    "总结经历模式",
    "优化沟通策略",
    "记录互动经验",
    "生成创造方案",
]


class TestGeneratedPassActions(unittest.TestCase):
    """生成式: 通过行为"""
    pass


for _i, _text in enumerate(_PASS_ACTIONS):
    def _make(text=_text):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.review({
                "module": "test",
                "action_text": text,
                "change": {},
            })
            self.assertEqual(r["decision"], "allow")
        test.__name__ = f"test_pass_{_i}"
        test.__doc__ = f"通过 {_text}"
        return test
    setattr(TestGeneratedPassActions,
            _make().__name__, _make())


# ── 仲裁组合矩阵 ────────────────────────────────────────────────
_ARBITRATE_CASES = [
    (["identity", "safety"], "identity"),
    (["safety", "constitution"], "safety"),
    (["constitution", "growth"], "constitution"),
    (["growth", "intelligence"], "growth"),
    (["intelligence", "expression"], "intelligence"),
    (["expression"], "expression"),
    (["identity", "expression"], "identity"),
    (["safety", "expression"], "safety"),
]


class TestGeneratedArbitrate(unittest.TestCase):
    """生成式: 仲裁矩阵"""
    pass


for _i, (_layers, _winner) in enumerate(_ARBITRATE_CASES):
    def _make(layers=_layers, winner=_winner):
        def test(self):
            engine = RuleEngine()
            r = engine.arbitrate({
                "layers": list(layers),
                "description": "测试",
            })
            self.assertEqual(r["winner"], winner)
        test.__name__ = f"test_arb_{_i}"
        test.__doc__ = f"仲裁 {_layers}"
        return test
    setattr(TestGeneratedArbitrate,
            _make().__name__, _make())


# ── 知识类型矩阵 ────────────────────────────────────────────────
_KNOWLEDGE_CASES = [
    ("根据数据, 因此结论正确", "fact"),
    ("记录显示, 结果是成功的", "inference"),
    ("可能存在问题", "inference"),
    ("因此需要调整", "inference"),
    ("这个方案很好", "hypothesis"),
    ("", "hypothesis"),
    ("根据来源, 可能如此", "fact"),
]


class TestGeneratedKnowledge(unittest.TestCase):
    """生成式: 知识类型"""
    pass


for _i, (_text, _ktype) in enumerate(_KNOWLEDGE_CASES):
    def _make(text=_text, ktype=_ktype):
        def test(self):
            r = ConstitutionValidator().validate(text)
            self.assertEqual(r["knowledge_type"], ktype)
        test.__name__ = f"test_knowledge_{_i}"
        test.__doc__ = f"知识类型 {_text[:10]}"
        return test
    setattr(TestGeneratedKnowledge,
            _make().__name__, _make())


# ── 安全风险矩阵 ────────────────────────────────────────────────
_RISK_CASES = [
    ("正常行为", "low", True),
    ("修改配置", "medium", False),
    ("调整策略参数", "medium", False),
    ("非法操作", "high", False),
    ("攻击系统", "high", False),
    ("批量删除数据", "medium", False),
]


class TestGeneratedSafetyRisk(unittest.TestCase):
    """生成式: 安全风险"""
    pass


for _i, (_text, _risk, _allowed) in enumerate(_RISK_CASES):
    def _make(text=_text, risk=_risk, allowed=_allowed):
        def test(self):
            r = SafetyPolicy().check(text)
            self.assertEqual(r["risk_level"], risk)
            self.assertEqual(r["allowed"], allowed)
        test.__name__ = f"test_risk_{_i}"
        test.__doc__ = f"风险 {_text[:10]}"
        return test
    setattr(TestGeneratedSafetyRisk,
            _make().__name__, _make())


# ── 身份变更矩阵 ────────────────────────────────────────────────
_CHANGE_CASES = [
    ({"mission": "x"}, False),
    ({"core_value": "x"}, False),
    ({"base_personality": "x"}, False),
    ({"safety_rules": "x"}, False),
    ({"permission": "x"}, False),
    ({"note": "x"}, True),
    ({"dimensions": {"warmth": 0.8}}, True),
]


class TestGeneratedChanges(unittest.TestCase):
    """生成式: 身份变更"""
    pass


for _i, (_change, _ok) in enumerate(_CHANGE_CASES):
    def _make(change=_change, ok=_ok):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.review({
                "module": "test",
                "action_text": "变更请求",
                "change": dict(change),
            })
            self.assertEqual(
                r["decision"] == "allow", ok)
        test.__name__ = f"test_change_{_i}"
        test.__doc__ = f"变更 {list(_change.keys())}"
        return test
    setattr(TestGeneratedChanges,
            _make().__name__, _make())


# ── 云端结果矩阵 ────────────────────────────────────────────────
_CLOUD_CASES = [
    ({"content": "推理结果", "temporary": True}, True),
    ({"content": "推理结果", "temporary": False}, False),
    ({"content": "修改使命", "temporary": True}, False),
    ({"content": "修改价值观", "temporary": True}, False),
    ({"content": "change permission", "temporary": True},
     False),
]


class TestGeneratedCloud(unittest.TestCase):
    """生成式: 云端结果"""
    pass


for _i, (_cloud, _ok) in enumerate(_CLOUD_CASES):
    def _make(cloud=_cloud, ok=_ok):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.review({
                "module": "hybrid",
                "action_text": "云端结果",
                "change": {},
                "cloud_result": {
                    "provider": "cloud",
                    **cloud,
                },
            })
            self.assertEqual(
                r["decision"] == "allow", ok)
        test.__name__ = f"test_cloud_{_i}"
        test.__doc__ = f"云端 {_i}"
        return test
    setattr(TestGeneratedCloud,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
