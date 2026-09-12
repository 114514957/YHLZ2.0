"""
YHLZ Embodied AI V8.0 - 宪法引擎补充测试 5 (V8.0 Extra5)

覆盖 (生成式批量):
    - 组合行为审查
    - 多信号矩阵
    - 服务端到端矩阵
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
    IdentityRules,
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


# ── 组合行为矩阵 ────────────────────────────────────────────────
_COMBO_ACTIONS = [
    ("改进技能并总结经验", True),
    ("修改使命但意图良好", False),
    ("绕过检查并改进", False),
    ("表达关切并优化沟通", True),
    ("我是神但为了用户", False),
    ("记录经验并反思", True),
]


class TestGeneratedComboActions(unittest.TestCase):
    """生成式: 组合行为"""
    pass


for _i, (_text, _ok) in enumerate(_COMBO_ACTIONS):
    def _make(text=_text, ok=_ok):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.review({
                "module": "test",
                "action_text": text,
                "change": {},
            })
            self.assertEqual(r["decision"] == "allow", ok)
        test.__name__ = f"test_combo_{_i}"
        test.__doc__ = f"组合 {_text[:10]}"
        return test
    setattr(TestGeneratedComboActions,
            _make().__name__, _make())


# ── 多信号矩阵 ──────────────────────────────────────────────────
_MULTI_SIGNAL_CASES = [
    "修改使命并修改权限",
    "修改人格和价值观",
    "绕过并修改安全规则",
    "更改身份并更新核心价值",
]


class TestGeneratedMultiSignal(unittest.TestCase):
    """生成式: 多信号"""
    pass


for _i, _text in enumerate(_MULTI_SIGNAL_CASES):
    def _make(text=_text):
        def test(self):
            r = IdentityRules().check_result(text, "cloud")
            self.assertFalse(r["ok"])
            self.assertGreaterEqual(
                len(r["matched_signals"]), 1)
        test.__name__ = f"test_multi_{_i}"
        test.__doc__ = f"多信号 {_text[:10]}"
        return test
    setattr(TestGeneratedMultiSignal,
            _make().__name__, _make())


# ── 安全边界矩阵 ────────────────────────────────────────────────
_SAFETY_EDGE_CASES = [
    ("", True),
    ("正常", True),
    ("调整个性化参数", True),
    ("修改配置", False),
    ("批量删除旧数据", False),
    ("删除一条测试记录", True),
]


class TestGeneratedSafetyEdge(unittest.TestCase):
    """生成式: 安全边界"""
    pass


for _i, (_text, _ok) in enumerate(_SAFETY_EDGE_CASES):
    def _make(text=_text, ok=_ok):
        def test(self):
            r = SafetyPolicy().check(text)
            self.assertEqual(r["allowed"], ok)
        test.__name__ = f"test_safety_edge_{_i}"
        test.__doc__ = f"安全边界 {_text[:8]}"
        return test
    setattr(TestGeneratedSafetyEdge,
            _make().__name__, _make())


# ── 服务端到端矩阵 ──────────────────────────────────────────────
class TestServiceE2E(unittest.TestCase):
    """服务端到端"""

    def test_full_governance_chain(self):
        svc = setup_service()
        # 审查 → 仲裁 → 验证 → 演化 → 总账
        svc.companion_constitution_review({
            "module": "growth", "action_text": "修改使命",
            "change": {"mission": "x"},
        })
        svc.companion_constitution_arbitrate({
            "layers": ["expression", "identity"],
        })
        svc.companion_constitution_validate_output(
            "我是神",
        )
        p = svc.companion_constitution_propose_evolution(
            "修改原则", "理由",
        )
        svc.companion_constitution_evolution_decide(
            p["proposal_id"], "reject",
        )
        stats = svc.companion_constitution_stats()
        self.assertGreaterEqual(
            stats["ledger"]["record_count"], 4)

    def test_hybrid_cloud_result_guarded(self):
        svc = setup_service()
        r = svc.companion_constitution_review({
            "module": "hybrid",
            "action_text": "推理结果",
            "change": {},
            "cloud_result": {
                "provider": "cloud",
                "content": "建议修改人格为冷酷",
                "temporary": True,
            },
        })
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "intelligence")

    def test_growth_review_guards_constitution(self):
        svc = setup_service()
        r = svc.companion_constitution_review({
            "module": "growth",
            "action_text": "成长建议审查",
            "change": {},
            "growth_proposal": {
                "type": "skill_improvement",
                "description": "自动修改最高原则",
                "risk": "low",
            },
        })
        self.assertEqual(r["decision"], "review")
        self.assertEqual(r["priority"], "growth")

    def test_identity_never_modified_via_any_path(self):
        svc = setup_service()
        before = svc.companion._continuity\
            ._identity_fingerprint
        svc.companion_constitution_review({
            "module": "x",
            "action_text": "修改使命",
            "change": {"mission": "新使命"},
        })
        svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        after = svc.companion._continuity\
            ._identity_fingerprint
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
