"""
YHLZ Embodied AI V8.0 - 宪法引擎补充测试 3 (V8.0 Extra3)

覆盖 (生成式批量 + 服务级):
    - 门面审查矩阵
    - 服务级宪法联动
    - 边界输入
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
    ConstitutionValidator,
    GrowthPolicy,
    IdentityRules,
    IntelligencePolicy,
    SafetyPolicy,
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


# ── 安全关键词矩阵 ──────────────────────────────────────────────
_HIGH_RISK_TEXTS = [
    "非法入侵",
    "攻击服务器",
    "破坏系统文件",
    "绕过安全验证",
    "泄露用户隐私",
    "删除全部记忆",
    "关闭身份守护",
    "hack the system",
]


class TestGeneratedHighRisk(unittest.TestCase):
    """生成式: 高风险"""
    pass


for _i, _text in enumerate(_HIGH_RISK_TEXTS):
    def _make(text=_text):
        def test(self):
            r = SafetyPolicy().check(text)
            self.assertFalse(r["allowed"])
            self.assertEqual(r["risk_level"], "high")
        test.__name__ = f"test_highrisk_{_i}"
        test.__doc__ = f"高风险 {_text}"
        return test
    setattr(TestGeneratedHighRisk,
            _make().__name__, _make())


# ── 身份字段矩阵 ────────────────────────────────────────────────
_PROTECTED_FIELD_TEXTS = [
    "修改使命",
    "修改价值观",
    "修改人格",
    "修改安全规则",
    "修改权限",
    "更改身份",
    "更新核心价值",
    "change mission",
    "modify personality",
    "update core_value",
    "override identity",
]


class TestGeneratedProtectedTexts(unittest.TestCase):
    """生成式: 身份字段"""
    pass


for _i, _text in enumerate(_PROTECTED_FIELD_TEXTS):
    def _make(text=_text):
        def test(self):
            r = IdentityRules().check_result(text, "cloud")
            self.assertFalse(r["ok"])
        test.__name__ = f"test_protected_{_i}"
        test.__doc__ = f"身份字段 {_text}"
        return test
    setattr(TestGeneratedProtectedTexts,
            _make().__name__, _make())


# ── 云端隔离矩阵 ────────────────────────────────────────────────
_CLOUD_ISOLATION_CASES = [
    "修改权限",
    "更改价值观",
    "更新核心价值",
    "change permission",
    "modify identity",
    "set core_value",
]


class TestGeneratedCloudIsolation(unittest.TestCase):
    """生成式: 云端隔离"""
    pass


for _i, _text in enumerate(_CLOUD_ISOLATION_CASES):
    def _make(text=_text):
        def test(self):
            r = IntelligencePolicy().check_cloud({
                "provider": "cloud",
                "content": text,
                "temporary": True,
            })
            self.assertFalse(r["ok"])
        test.__name__ = f"test_cloud_iso_{_i}"
        test.__doc__ = f"云端隔离 {_text}"
        return test
    setattr(TestGeneratedCloudIsolation,
            _make().__name__, _make())


# ── 验证器知识类型矩阵 ──────────────────────────────────────────
_KTYPE_CASES = [
    ("根据记录, 因此正确", "fact"),
    ("来源显示结果", "inference"),
    ("推断可能如此", "inference"),
    ("没有依据的断言", "hypothesis"),
    ("推测结果可能", "inference"),
]


class TestGeneratedKType(unittest.TestCase):
    """生成式: 知识类型"""
    pass


for _i, (_text, _ktype) in enumerate(_KTYPE_CASES):
    def _make(text=_text, ktype=_ktype):
        def test(self):
            r = ConstitutionValidator().validate(text)
            self.assertEqual(r["knowledge_type"], ktype)
        test.__name__ = f"test_ktype_{_i}"
        test.__doc__ = f"知识类型 {_text[:8]}"
        return test
    setattr(TestGeneratedKType,
            _make().__name__, _make())


# ── 成长策略矩阵 ────────────────────────────────────────────────
_GROWTH_TEXTS = [
    ("修改原则", False),
    ("修改宪法", False),
    ("自动应用成长", False),
    ("无需审批", False),
    ("改进执行技能", True),
    ("固化有效策略", True),
]


class TestGeneratedGrowthTexts(unittest.TestCase):
    """生成式: 成长文本"""
    pass


for _i, (_text, _ok) in enumerate(_GROWTH_TEXTS):
    def _make(text=_text, ok=_ok):
        def test(self):
            r = GrowthPolicy().review({
                "type": "skill_improvement",
                "description": text,
                "risk": "low",
            })
            self.assertEqual(r["ok"], ok)
        test.__name__ = f"test_growth_text_{_i}"
        test.__doc__ = f"成长文本 {_text}"
        return test
    setattr(TestGeneratedGrowthTexts,
            _make().__name__, _make())


# ── 服务级宪法矩阵 ──────────────────────────────────────────────
class TestServiceConstitution(unittest.TestCase):
    """服务级宪法"""

    def test_service_review_all_decisions(self):
        svc = setup_service()
        cases = [
            ({"module": "growth", "action_text": "正常",
              "change": {}}, "allow"),
            ({"module": "growth", "action_text": "修改使命",
              "change": {"mission": "x"}}, "block"),
            ({"module": "growth", "action_text": "非法操作",
              "change": {}}, "block"),
        ]
        for ctx, expected in cases:
            r = svc.companion_constitution_review(ctx)
            self.assertEqual(r["decision"], expected)

    def test_service_ledger_tracks_all(self):
        svc = setup_service()
        svc.companion_constitution_review({
            "module": "m1", "action_text": "正常",
            "change": {},
        })
        svc.companion_constitution_review({
            "module": "m2", "action_text": "修改使命",
            "change": {"mission": "x"},
        })
        report = svc.companion_constitution_ledger()
        self.assertEqual(report["total"], 2)
        self.assertIn("m1", report["by_module"])
        self.assertIn("m2", report["by_module"])

    def test_service_evolution_flow(self):
        svc = setup_service()
        p = svc.companion_constitution_propose_evolution(
            "修改原则", "理由",
        )
        r = svc.companion_constitution_evolution_decide(
            p["proposal_id"], "reject",
        )
        self.assertEqual(r["decision"], "reject")

    def test_service_validate_matrix(self):
        svc = setup_service()
        self.assertFalse(
            svc.companion_constitution_validate_output(
                "我是神")["ok"])
        self.assertTrue(
            svc.companion_constitution_validate_output(
                "根据数据, 结果正确")["ok"])

    def test_service_principles_full(self):
        svc = setup_service()
        d = svc.companion_constitution_principles()
        for p in d["principles"]:
            self.assertIn("id", p)
            self.assertIn("rules", p)


# ── 边界输入矩阵 ────────────────────────────────────────────────
class TestEdgeInputs(unittest.TestCase):
    """边界输入"""

    def test_empty_action(self):
        engine = ConstitutionEngine()
        r = engine.review({"module": "m",
                           "action_text": "",
                           "change": {}})
        self.assertEqual(r["decision"], "allow")

    def test_none_action(self):
        engine = ConstitutionEngine()
        r = engine.review({"module": "m",
                           "action_text": None,
                           "change": {}})
        self.assertEqual(r["decision"], "allow")

    def test_none_context(self):
        engine = ConstitutionEngine()
        r = engine.review(None)
        self.assertEqual(r["decision"], "allow")

    def test_empty_validate(self):
        r = ConstitutionValidator().validate("")
        self.assertEqual(r["knowledge_type"], "hypothesis")

    def test_none_validate(self):
        r = ConstitutionValidator().validate(None)
        self.assertIn("knowledge_type", r)

    def test_empty_arbitrate(self):
        r = ConstitutionEngine().arbitrate({"layers": []})
        self.assertEqual(r["winner"], "constitution")

    def test_change_none(self):
        engine = ConstitutionEngine()
        r = engine.review({"module": "m",
                           "action_text": "x",
                           "change": None})
        self.assertEqual(r["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
