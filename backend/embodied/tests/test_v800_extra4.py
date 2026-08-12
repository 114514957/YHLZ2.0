"""
YHLZ Embodied AI V8.0 - 宪法引擎补充测试 4 (V8.0 Extra4)

覆盖 (生成式批量 + 服务级联动):
    - 全模块审查矩阵
    - 服务级宪法 × HIL × Growth 联动
    - 边界与恢复
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
    ConstitutionLedger,
    EvolutionProposal,
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


# ── 全模块审查矩阵 ──────────────────────────────────────────────
_MODULE_CASES = [
    ("memory", "修改记忆内容", True),
    ("memory", "查询记忆", True),
    ("growth", "改进技能", True),
    ("growth", "修改使命", False),
    ("hybrid", "云端推理", True),
    ("hybrid", "修改权限", False),
    ("presence", "表达关切", True),
    ("presence", "我是神", False),
    ("agent", "执行任务", True),
    ("agent", "绕过审批", False),
]


class TestGeneratedModuleReview(unittest.TestCase):
    """生成式: 全模块审查"""
    pass


for _i, (_module, _text, _ok) in enumerate(_MODULE_CASES):
    def _make(module=_module, text=_text, ok=_ok):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.review({
                "module": module,
                "action_text": text,
                "change": {},
            })
            self.assertEqual(r["decision"] == "allow", ok)
        test.__name__ = f"test_module_{_i}"
        test.__doc__ = f"模块 {_module}"
        return test
    setattr(TestGeneratedModuleReview,
            _make().__name__, _make())


# ── 总账上限矩阵 ────────────────────────────────────────────────
_LEDGER_CAP_CASES = [1, 3, 10, 100]


class TestGeneratedLedgerCap(unittest.TestCase):
    """生成式: 总账上限"""
    pass


for _i, _cap in enumerate(_LEDGER_CAP_CASES):
    def _make(cap=_cap):
        def test(self):
            ledger = ConstitutionLedger(max_records=cap)
            for j in range(cap * 2):
                ledger.record(module=f"m{j}", action="a",
                              decision="ok")
            self.assertEqual(ledger.stats()[
                "record_count"], cap)
        test.__name__ = f"test_ledger_cap_{_i}"
        test.__doc__ = f"总账上限 {_cap}"
        return test
    setattr(TestGeneratedLedgerCap,
            _make().__name__, _make())


# ── 演化建议生命周期矩阵 ────────────────────────────────────────
_EVOLUTION_LIFE = [
    (["approve"], "approved"),
    (["reject"], "rejected"),
    (["approve", "reject"], "rejected"),
    (["reject", "approve"], "approved"),
]


class TestGeneratedEvolutionLife(unittest.TestCase):
    """生成式: 演化生命周期"""
    pass


for _i, (_decisions, _final) in enumerate(_EVOLUTION_LIFE):
    def _make(decisions=_decisions, final=_final):
        def test(self):
            proposal = EvolutionProposal()
            p = proposal.propose("修改原则X")
            for decision in decisions:
                proposal.decide(p["proposal_id"], decision)
            stats = proposal.stats()
            self.assertEqual(stats["by_status"][final], 1)
        test.__name__ = f"test_evo_life_{_i}"
        test.__doc__ = f"演化生命周期 {_decisions}"
        return test
    setattr(TestGeneratedEvolutionLife,
            _make().__name__, _make())


# ── 服务级联动矩阵 ──────────────────────────────────────────────
class TestServiceLinkage(unittest.TestCase):
    """服务级联动"""

    def test_hybrid_review_in_ledger(self):
        svc = setup_service()
        svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        report = svc.companion_constitution_ledger()
        self.assertIn("hybrid", report["by_module"])

    def test_growth_review_in_ledger(self):
        svc = setup_service()
        mgr = svc.companion_experience
        for _ in range(4):
            mgr.store_from_event(
                success=True, trigger="生成工程Prompt",
                source="v800", action="a", result="成功",
            )
        svc.companion_growth_cycle_run(trigger="manual")
        report = svc.companion_constitution_ledger()
        self.assertIn("growth", report["by_module"])

    def test_validate_in_ledger(self):
        svc = setup_service()
        svc.companion_constitution_validate_output("正常")
        report = svc.companion_constitution_ledger()
        self.assertIn("validator", report["by_module"])

    def test_evolution_in_ledger(self):
        svc = setup_service()
        svc.companion_constitution_propose_evolution(
            "修改X", "理由",
        )
        report = svc.companion_constitution_ledger()
        self.assertIn("constitution", report["by_module"])

    def test_replay_after_mixed_actions(self):
        svc = setup_service()
        svc.companion_constitution_review({
            "module": "growth", "action_text": "正常",
            "change": {},
        })
        svc.companion_constitution_arbitrate({
            "layers": ["identity"],
        })
        replay = svc.companion_constitution_stats()[
            "ledger"]
        self.assertGreaterEqual(replay["record_count"], 2)


# ── 恢复矩阵 ────────────────────────────────────────────────────
class TestRecovery(unittest.TestCase):
    """恢复与降级"""

    def test_disabled_engine_still_returns(self):
        svc = setup_service(
            companion_constitution_enabled=False,
        )
        r = svc.companion_constitution_review({
            "module": "growth",
            "action_text": "修改使命",
            "change": {"mission": "x"},
        })
        self.assertEqual(r["decision"], "allow")

    def test_hybrid_link_off_no_constitution(self):
        svc = setup_service(
            companion_constitution_hybrid_link=False,
        )
        r = svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        self.assertNotIn("constitution", r)

    def test_growth_link_off_no_reviews(self):
        svc = setup_service(
            companion_constitution_growth_link=False,
        )
        mgr = svc.companion_experience
        for _ in range(4):
            mgr.store_from_event(
                success=True, trigger="生成工程Prompt",
                source="v800", action="a", result="成功",
            )
        r = svc.companion_growth_cycle_run(trigger="manual")
        self.assertNotIn("constitution_reviews", r)

    def test_constitution_after_clear(self):
        engine = ConstitutionEngine()
        engine.review({"module": "m", "action_text": "x",
                       "change": {}})
        engine.clear()
        r = engine.review({"module": "m",
                           "action_text": "x",
                           "change": {}})
        self.assertEqual(r["decision"], "allow")


# ── 身份稳定矩阵 ────────────────────────────────────────────────
class TestIdentityStability(unittest.TestCase):
    """身份稳定"""

    def test_personality_stable_after_reviews(self):
        svc = setup_service()
        before = svc.companion_personality_engine\
            .personality()["base"]
        svc.companion_constitution_review({
            "module": "growth", "action_text": "修改使命",
            "change": {"mission": "x"},
        })
        svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        after = svc.companion_personality_engine\
            .personality()["base"]
        self.assertEqual(before, after)

    def test_constitution_blocks_identity_change(self):
        svc = setup_service()
        r = svc.companion_constitution_review({
            "module": "growth",
            "action_text": "正常",
            "change": {"core_value": "新价值"},
        })
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "identity")


if __name__ == "__main__":
    unittest.main()
