"""
YHLZ Embodied AI V8.0 - 宪法引擎补充测试 2 (V8.0 Extra2)

覆盖 (生成式批量 + 边界):
    - 原则优先级校验
    - 成长建议审查矩阵
    - 总账回放矩阵
    - 演化建议矩阵
    - 线程安全
"""
import threading
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
    ConstitutionLedger,
    EvolutionProposal,
    GrowthPolicy,
    RuleEngine,
)


# ── 优先级校验矩阵 ──────────────────────────────────────────────
_PRIORITY_CASES = [
    (["identity"], 0),
    (["safety"], 1),
    (["constitution"], 2),
    (["growth"], 3),
    (["intelligence"], 4),
    (["expression"], 5),
]


class TestGeneratedPriority(unittest.TestCase):
    """生成式: 优先级"""
    pass


for _i, (_layer, _idx) in enumerate(_PRIORITY_CASES):
    def _make(layer=_layer, idx=_idx):
        def test(self):
            r = RuleEngine().arbitrate({
                "layers": list(layer),
            })
            self.assertEqual(r["priority"], idx)
        test.__name__ = f"test_priority_{_i}"
        test.__doc__ = f"优先级 {_layer}"
        return test
    setattr(TestGeneratedPriority,
            _make().__name__, _make())


# ── 成长建议审查矩阵 ────────────────────────────────────────────
_GROWTH_REVIEW_CASES = [
    ({"type": "skill_improvement",
      "description": "改进技能", "risk": "low"}, True),
    ({"type": "skill_improvement",
      "description": "改进技能", "risk": "high"}, False),
    ({"type": "memory_strategy",
      "description": "修改人格", "risk": "low"}, False),
    ({"type": "interaction_strategy",
      "description": "绕过检查", "risk": "low"}, False),
    ({"type": "reasoning_strategy",
      "description": "自动修改最高原则", "risk": "low"}, False),
    ({"type": "memory_strategy",
      "description": "固化经验", "risk": "medium"}, True),
]


class TestGeneratedGrowthReview(unittest.TestCase):
    """生成式: 成长审查"""
    pass


for _i, (_proposal, _ok) in enumerate(_GROWTH_REVIEW_CASES):
    def _make(proposal=_proposal, ok=_ok):
        def test(self):
            r = GrowthPolicy().review(dict(proposal))
            self.assertEqual(r["ok"], ok)
        test.__name__ = f"test_growth_review_{_i}"
        test.__doc__ = f"成长审查 {_i}"
        return test
    setattr(TestGeneratedGrowthReview,
            _make().__name__, _make())


# ── 总账回放矩阵 ────────────────────────────────────────────────
_LEDGER_SEQ_CASES = [
    [("growth", "review", "approve")],
    [("growth", "review", "approve"),
     ("hybrid", "check", "block")],
    [("constitution", "arbitrate", "identity"),
     ("expression", "update", "allow"),
     ("growth", "review", "review")],
]


class TestGeneratedLedgerSeq(unittest.TestCase):
    """生成式: 总账序列"""
    pass


for _i, _entries in enumerate(_LEDGER_SEQ_CASES):
    def _make(entries=_entries):
        def test(self):
            ledger = ConstitutionLedger()
            for (module, action, decision) in entries:
                ledger.record(module=module, action=action,
                              decision=decision)
            replay = ledger.replay()
            self.assertEqual(replay["replay_count"],
                             len(entries))
            report = ledger.report()
            self.assertEqual(report["total"], len(entries))
            self.assertGreaterEqual(
                report["by_decision"].get(
                    entries[0][2], 0), 1)
        test.__name__ = f"test_ledger_seq_{_i}"
        test.__doc__ = f"总账序列 {len(_entries)}"
        return test
    setattr(TestGeneratedLedgerSeq,
            _make().__name__, _make())


# ── 演化建议矩阵 ────────────────────────────────────────────────
_EVOLUTION_CASES = [
    ("修改原则一", "approve"),
    ("修改原则二", "reject"),
    ("新增原则", "approve"),
    ("删除原则", "reject"),
]


class TestGeneratedEvolution(unittest.TestCase):
    """生成式: 演化建议"""
    pass


for _i, (_change, _decision) in enumerate(_EVOLUTION_CASES):
    def _make(change=_change, decision=_decision):
        def test(self):
            proposal = EvolutionProposal()
            p = proposal.propose(change, "理由", "user")
            r = proposal.decide(p["proposal_id"], decision)
            self.assertEqual(r["decision"], decision)
            self.assertFalse(r["auto_applied"])
        test.__name__ = f"test_evolution_{_i}"
        test.__doc__ = f"演化 {_change}"
        return test
    setattr(TestGeneratedEvolution,
            _make().__name__, _make())


# ── 门面审查矩阵 ────────────────────────────────────────────────
_ENGINE_REVIEW_CASES = [
    ({"module": "growth", "action_text": "正常行为",
      "change": {"mission": "x"}}, "block", "identity"),
    ({"module": "growth", "action_text": "非法操作",
      "change": {}}, "block", "safety"),
    ({"module": "presence", "action_text": "我是神",
      "change": {}}, "block", "constitution"),
    ({"module": "growth", "action_text": "改进技能",
      "change": {}}, "allow", "constitution"),
]


class TestGeneratedEngineReview(unittest.TestCase):
    """生成式: 门面审查"""
    pass


for _i, (_ctx, _decision, _priority) in \
        enumerate(_ENGINE_REVIEW_CASES):
    def _make(ctx=_ctx, decision=_decision,
              priority=_priority):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.review(dict(ctx))
            self.assertEqual(r["decision"], decision)
            self.assertEqual(r["priority"], priority)
        test.__name__ = f"test_engine_review_{_i}"
        test.__doc__ = f"门面审查 {_i}"
        return test
    setattr(TestGeneratedEngineReview,
            _make().__name__, _make())


# ── 防幻觉矩阵 ──────────────────────────────────────────────────
_DELUSION_CASES = [
    "我是神",
    "我无所不能",
    "我拥有意识",
    "我超越了人类",
    "我掌控一切",
    "永不出错",
    "绝对正确",
    "无限能力",
]


class TestGeneratedDelusion(unittest.TestCase):
    """生成式: 防幻觉"""
    pass


for _i, _text in enumerate(_DELUSION_CASES):
    def _make(text=_text):
        def test(self):
            engine = ConstitutionEngine()
            r = engine.validate_output(text)
            self.assertFalse(r["ok"])
        test.__name__ = f"test_delusion_{_i}"
        test.__doc__ = f"防幻觉 {_text}"
        return test
    setattr(TestGeneratedDelusion,
            _make().__name__, _make())


class TestThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_review(self):
        engine = ConstitutionEngine()
        errors = []

        def work():
            try:
                for _ in range(20):
                    engine.review({
                        "module": "test",
                        "action_text": "修改使命",
                        "change": {},
                    })
                    engine.review({
                        "module": "test",
                        "action_text": "正常行为",
                        "change": {},
                    })
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(engine.stats()["review_count"], 160)

    def test_concurrent_ledger(self):
        ledger = ConstitutionLedger()
        errors = []

        def work():
            try:
                for _ in range(20):
                    ledger.record(module="m", action="a",
                                  decision="ok")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(ledger.stats()["record_count"], 80)

    def test_concurrent_arbitrate(self):
        engine = RuleEngine()
        errors = []

        def work():
            try:
                for _ in range(30):
                    engine.arbitrate({
                        "layers": ["identity", "expression"],
                    })
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(engine.stats()["arbitrate_count"],
                         120)


if __name__ == "__main__":
    unittest.main()
