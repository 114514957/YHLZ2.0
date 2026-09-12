"""
YHLZ Embodied AI V8.0 - 宪法引擎补充测试 6 (V8.0 Extra6)

覆盖 (生成式批量):
    - 治理审查多样性
    - 服务级宪法完整性
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
    ConstitutionLedger,
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


# ── 审查多样性矩阵 ──────────────────────────────────────────────
_REVIEW_TEXTS = [
    "总结本周经历",
    "分析失败模式",
    "优化互动策略",
    "固化有效经验",
    "生成创造方案",
    "更新记忆索引",
]


class TestGeneratedReviewDiversity(unittest.TestCase):
    """生成式: 审查多样性"""
    pass


for _i, _text in enumerate(_REVIEW_TEXTS):
    def _make(text=_text):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.review({
                "module": "growth",
                "action_text": text,
                "change": {},
            })
            self.assertEqual(r["decision"], "allow")
            self.assertGreaterEqual(
                len(r["checked_rules"]), 3)
        test.__name__ = f"test_review_div_{_i}"
        test.__doc__ = f"审查 {_text[:8]}"
        return test
    setattr(TestGeneratedReviewDiversity,
            _make().__name__, _make())


# ── 总账结构矩阵 ────────────────────────────────────────────────
class TestLedgerStructure(unittest.TestCase):
    """总账结构"""

    def test_entry_all_fields(self):
        ledger = ConstitutionLedger()
        entry = ledger.record(module="m", action="a",
                              decision="d", rule="r",
                              reason="why")
        for key in ("ledger_id", "time", "module", "action",
                    "decision", "rule", "reason"):
            self.assertIn(key, entry)

    def test_replay_structure(self):
        ledger = ConstitutionLedger()
        ledger.record(module="m", action="a",
                      decision="d", rule="r")
        seq = ledger.replay()["sequence"][0]
        for key in ("ledger_id", "time", "module", "action",
                    "decision", "rule"):
            self.assertIn(key, seq)

    def test_report_aggregates(self):
        ledger = ConstitutionLedger()
        ledger.record(module="g", action="x",
                      decision="approve")
        ledger.record(module="h", action="y",
                      decision="block")
        report = ledger.report()
        self.assertEqual(report["by_decision"]["approve"], 1)
        self.assertEqual(report["by_decision"]["block"], 1)


# ── 服务完整性矩阵 ──────────────────────────────────────────────
class TestServiceIntegrity(unittest.TestCase):
    """服务完整性"""

    def test_service_ledger_aggregates(self):
        svc = setup_service()
        svc.companion_constitution_review({
            "module": "growth", "action_text": "正常",
            "change": {},
        })
        svc.companion_constitution_validate_output("正常")
        stats = svc.companion_constitution_stats()
        self.assertGreaterEqual(
            stats["ledger"]["record_count"], 2)

    def test_service_replay_available(self):
        svc = setup_service()
        svc.companion_constitution_review({
            "module": "growth", "action_text": "正常",
            "change": {},
        })
        replay = svc.companion_constitution_stats()
        self.assertIn("ledger", replay)

    def test_service_priority_consistent(self):
        svc = setup_service()
        r1 = svc.companion_constitution_arbitrate({
            "layers": ["expression", "identity"],
        })
        r2 = svc.companion_constitution_arbitrate({
            "layers": ["identity", "expression"],
        })
        self.assertEqual(r1["winner"], r2["winner"])
        self.assertEqual(r1["winner"], "identity")


if __name__ == "__main__":
    unittest.main()
