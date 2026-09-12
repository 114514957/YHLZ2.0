"""
YHLZ Embodied AI V6.6 - 自主成长成熟化补充测试 3 (V6.6 Extra3)

覆盖 (生成式批量 + 持久化):
    - 反思情绪: 调整矩阵 (模式 × 引擎)
    - 成长闭环: 多轮统计 / 审计矩阵
    - 趋势: 组合输入矩阵
    - 快照持久化: growth_state / reflection_state 域
"""
import os
import tempfile
import time
import unittest

from backend.embodied.companion.emotion import EmotionEngine
from backend.embodied.companion.growth import (
    GrowthCycleEngine,
    GrowthEvaluator,
    GrowthProposal,
    GrowthTrendAnalysis,
)
from backend.embodied.companion.reflection import (
    CognitiveReflectionEngine,
    ReflectionEmotionIntegrator,
)


def _report(patterns=None, contradictions=None,
            confidence=0.8):
    return {
        "report_id": "cr_gen3",
        "confidence": confidence,
        "patterns": patterns or [],
        "contradictions": contradictions or [],
    }


def _pat(ptype, conf=0.8):
    return {"type": ptype, "trigger": "t",
            "confidence": conf, "meaning": "m"}


def _stats(**over):
    data = {
        "reflection": {"reflection_count": 10},
        "proposal": {"proposal_count": 8},
        "evaluator": {"evaluation_count": 8,
                      "approved_count": 6},
        "applier": {"applied_count": 3},
        "identity_guard": {"intercept_count": 1,
                           "approval_count": 2},
        "experience": {"total": 40},
        "verification": {"confirmed": 20, "rejected": 2},
        "period_days": 30,
    }
    data.update(over)
    return data


def _tri_records():
    return [
        {"id": f"{trig}{i}", "type": "failure",
         "trigger": trig, "result": "错误"}
        for trig in ("t1", "t2", "t3")
        for i in range(4)
    ]


class TestAdjustMatrix(unittest.TestCase):
    """生成式: 调整矩阵 (模式 × 引擎)"""
    pass

# (pattern_type, 有引擎, 期望 applied)
_ADJUST_CASES = [
    ("success_strategy", True, True),
    ("success_strategy", False, False),
    ("problem_pattern", True, True),
    ("problem_pattern", False, False),
    ("repetition", True, False),
    ("repetition", False, False),
    (None, True, False),
    (None, False, False),
]


for _i, (_ptype, _with_engine, _applied) in \
        enumerate(_ADJUST_CASES):
    def _make(ptype=_ptype, with_engine=_with_engine,
              applied=_applied):
        def test(self):
            emotion = EmotionEngine() if with_engine else None
            integrator = ReflectionEmotionIntegrator(
                emotion=emotion,
            )
            patterns = [_pat(ptype)] if ptype else []
            r = integrator.adjust(_report(
                patterns=patterns,
            ))
            self.assertEqual(r["adjustment"]["applied"],
                             applied)
        test.__name__ = f"test_adjust_{_i}"
        test.__doc__ = f"调整矩阵 {_ptype}/{_with_engine}"
        return test
    setattr(TestAdjustMatrix, _make().__name__, _make())


class TestMultiRunStats(unittest.TestCase):
    """多轮运行统计"""

    def setUp(self):
        self.engine = GrowthCycleEngine(
            reflection=CognitiveReflectionEngine(),
            proposal=GrowthProposal(),
            evaluator=GrowthEvaluator(),
            records_fn=lambda: _tri_records(),
        )

    def test_three_manual_runs(self):
        for _ in range(3):
            r = self.engine.run(trigger="manual")
            self.assertEqual(r["cycle"]["status"],
                             "completed")
        stats = self.engine.stats()
        self.assertEqual(stats["cycle_count"], 3)
        self.assertEqual(stats["run_count"], 3)
        self.assertEqual(stats["by_status"]["completed"], 3)

    def test_run_then_event_trigger_available(self):
        self.engine.run(trigger="manual")
        r = self.engine.run(trigger="auto")
        self.assertIsNone(r["cycle"])

    def test_run_then_time_trigger(self):
        self.engine.run(trigger="manual")
        now = time.time()
        self.engine._last_run = now - 2 * 86400
        r = self.engine.run(trigger="auto", now=now)
        self.assertEqual(r["cycle"]["trigger"], "time")

    def test_pending_grows_with_runs(self):
        self.engine.run(trigger="manual")
        n1 = self.engine.stats()["pending_count"]
        self.engine.run(trigger="manual")
        n2 = self.engine.stats()["pending_count"]
        self.assertGreater(n2, n1)


class TestCycleAuditMatrix(unittest.TestCase):
    """审计矩阵"""

    def test_audit_after_decisions(self):
        audit = __import__(
            "backend.embodied.companion.growth.growth_audit",
            fromlist=["GrowthAudit"],
        ).GrowthAudit()
        engine = GrowthCycleEngine(
            reflection=CognitiveReflectionEngine(),
            proposal=GrowthProposal(),
            evaluator=GrowthEvaluator(),
            audit=audit,
            records_fn=lambda: _tri_records(),
        )
        engine.run(trigger="manual")
        items = engine.pending()["items"]
        for item in items:
            engine.decide(item["pending_id"], "approve")
        report = audit.report(limit=0)
        self.assertIn("cycle_completed",
                      report["by_decision"])
        self.assertIn("cycle_approve",
                      report["by_decision"])
        self.assertEqual(
            report["by_decision"]["cycle_approve"],
            len(items))

    def test_audit_never_records_apply(self):
        audit = __import__(
            "backend.embodied.companion.growth.growth_audit",
            fromlist=["GrowthAudit"],
        ).GrowthAudit()
        engine = GrowthCycleEngine(
            reflection=CognitiveReflectionEngine(),
            proposal=GrowthProposal(),
            evaluator=GrowthEvaluator(),
            audit=audit,
            records_fn=lambda: _tri_records(),
        )
        engine.run(trigger="manual")
        items = engine.pending()["items"]
        for item in items:
            engine.decide(item["pending_id"], "approve")
        report = audit.report(limit=0)
        self.assertNotIn("applied",
                         report["by_decision"])
        self.assertNotIn("cycle_apply",
                         report["by_decision"])


class TestTrendMatrix(unittest.TestCase):
    """生成式: 趋势组合矩阵"""
    pass

# (reflection, eval_n, appr_n, applied, exp_total, 期望下限)
_TREND_CASES = [
    (0, 0, 0, 0, 9, 0.0),
    (10, 10, 10, 5, 9, 0.5),
    (30, 20, 15, 10, 9, 0.6),
    (60, 50, 50, 20, 9, 0.75),
    (1, 2, 0, 0, 9, 0.1),
]


for _i, (_refl, _evaln, _apprn, _applied,
         _total, _min_score) in enumerate(_TREND_CASES):
    def _make(refl=_refl, evaln=_evaln, apprn=_apprn,
              applied=_applied, total=_total,
              min_score=_min_score):
        def test(self):
            r = GrowthTrendAnalysis().analyze(_stats(
                reflection={"reflection_count": refl},
                evaluator={"evaluation_count": evaln,
                           "approved_count": apprn},
                applier={"applied_count": applied},
            ))
            self.assertEqual(len(r["analysis"]), total)
            self.assertGreaterEqual(r["growth_score"],
                                    min_score)
        test.__name__ = f"test_trend_case_{_i}"
        test.__doc__ = f"趋势矩阵 {_refl}/{_evaln}/{_apprn}"
        return test
    setattr(TestTrendMatrix, _make().__name__, _make())


class TestSnapshotPersistence(unittest.TestCase):
    """快照持久化 (growth_state / reflection_state 域)"""

    def setUp(self):
        from backend.embodied.service import EmbodiedService
        cfg = {
            "embodied_enabled": True,
            "companion_enabled": True,
            "companion_persistence_enabled": True,
        }
        self.svc = EmbodiedService()
        self.svc.load_config(cfg)
        mgr = self.svc.companion_experience
        for _ in range(4):
            mgr.store_from_event(
                success=True, trigger="生成工程Prompt",
                source="v660_persist", action="a",
                result="成功",
            )
        # 触发成长闭环产生待审批
        self.svc.companion_growth_cycle_run(trigger="manual")
        self.svc.companion_growth_trend_analysis()

    def test_collect_includes_growth_state(self):
        states = self.svc.companion._continuity\
            .collect_states()
        self.assertIn("growth_state", states)
        self.assertIn("pending", states["growth_state"])
        self.assertGreaterEqual(
            len(states["growth_state"]["pending"]), 0)

    def test_collect_includes_reflection_state(self):
        states = self.svc.companion._continuity\
            .collect_states()
        self.assertIn("reflection_state", states)
        self.assertIn("reflection_count",
                      states["reflection_state"])

    def test_save_load_roundtrip(self):
        continuity = self.svc.companion._continuity
        path = os.path.join(
            tempfile.gettempdir(), "v660_snapshot.jsonl")
        if os.path.exists(path):
            os.remove(path)
        try:
            continuity.save(path)
            self.assertTrue(os.path.exists(path))
            # 清空后加载
            result = continuity.load(path)
            self.assertTrue(result["success"])
            self.assertIn("growth_state",
                          result["activated"])
            self.assertIn("reflection_state",
                          result["activated"])
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_restored_growth_state_pending(self):
        continuity = self.svc.companion._continuity
        path = os.path.join(
            tempfile.gettempdir(), "v660_snapshot2.jsonl")
        if os.path.exists(path):
            os.remove(path)
        try:
            continuity.save(path)
            n_before = len(self.svc.companion_growth_cycle
                           ._pending)
            self.svc.companion_growth_cycle.clear()
            continuity.load(path)
            n_after = len(self.svc.companion_growth_cycle
                          ._pending)
            self.assertEqual(n_before, n_after)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_restored_trend_results(self):
        continuity = self.svc.companion._continuity
        path = os.path.join(
            tempfile.gettempdir(), "v660_snapshot3.jsonl")
        if os.path.exists(path):
            os.remove(path)
        try:
            continuity.save(path)
            n_before = len(
                self.svc.companion_growth_trend_analyzer
                ._results)
            self.svc.companion_growth_trend_analyzer.clear()
            continuity.load(path)
            n_after = len(
                self.svc.companion_growth_trend_analyzer
                ._results)
            self.assertEqual(n_before, n_after)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_snapshot_domains_twelve(self):
        from backend.embodied.companion.persistence import (
            SNAPSHOT_DOMAINS,
        )
        self.assertIn("growth_state", SNAPSHOT_DOMAINS)
        self.assertIn("reflection_state", SNAPSHOT_DOMAINS)
        self.assertGreaterEqual(len(SNAPSHOT_DOMAINS), 12)

    def test_pending_survives_restore_approval(self):
        continuity = self.svc.companion._continuity
        path = os.path.join(
            tempfile.gettempdir(), "v660_snapshot4.jsonl")
        if os.path.exists(path):
            os.remove(path)
        try:
            continuity.save(path)
            self.svc.companion_growth_cycle.clear()
            continuity.load(path)
            items = self.svc.companion_growth_cycle\
                .pending()["items"]
            self.assertGreater(len(items), 0)
            r = self.svc.companion_growth_cycle.decide(
                items[0]["pending_id"], "approve")
            self.assertFalse(r["applied"])
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestGeneratedCycleComponentCombos(unittest.TestCase):
    """生成式: 组件缺失组合"""
    pass

# (reflection, proposal, evaluator, 期望 status)
_COMPONENT_CASES = [
    (True, True, True, "completed"),
    (True, True, False, "completed"),
    (True, False, True, "completed"),
    (False, True, True, "completed"),
    (True, False, False, "completed"),
    (False, False, False, "completed"),
]


for _i, (_refl, _prop, _eval, _status) in \
        enumerate(_COMPONENT_CASES):
    def _make(refl=_refl, prop=_prop, ev=_eval,
              status=_status):
        def test(self):
            kwargs = {}
            if refl:
                kwargs["reflection"] = \
                    CognitiveReflectionEngine()
            if prop:
                kwargs["proposal"] = GrowthProposal()
            if ev:
                kwargs["evaluator"] = GrowthEvaluator()
            engine = GrowthCycleEngine(
                records_fn=lambda: _tri_records(),
                **kwargs,
            )
            r = engine.run(trigger="manual")
            self.assertEqual(r["cycle"]["status"], status)
        test.__name__ = f"test_components_{_i}"
        test.__doc__ = f"组件组合 {_refl}/{_prop}/{_eval}"
        return test
    setattr(TestGeneratedCycleComponentCombos,
            _make().__name__, _make())


class TestGeneratedPendingFiltering(unittest.TestCase):
    """生成式: 待审批项决策状态"""
    pass

for _i, _decision in enumerate(
        ["approve", "reject", "approve", "reject"]):
    def _make(decision=_decision):
        def test(self):
            from backend.embodied.companion.growth import (
                GrowthEvaluator,
                GrowthProposal,
            )
            from backend.embodied.companion.reflection import (
                CognitiveReflectionEngine,
            )
            engine = GrowthCycleEngine(
                reflection=CognitiveReflectionEngine(),
                proposal=GrowthProposal(),
                evaluator=GrowthEvaluator(),
                records_fn=lambda: _tri_records(),
            )
            engine.run(trigger="manual")
            items = engine.pending()["items"]
            pid = items[_i % len(items)]["pending_id"]
            r = engine.decide(pid, decision)
            self.assertEqual(r["decision"], decision)
            self.assertFalse(r["applied"])
        test.__name__ = f"test_pending_state_{_i}"
        test.__doc__ = f"待审批状态 {_decision}"
        return test
    setattr(TestGeneratedPendingFiltering,
            _make().__name__, _make())


class TestGeneratedCycleThresholds(unittest.TestCase):
    """生成式: 阈值配置矩阵"""
    pass

# (cycle_days, min_delta, max_pending) 构造+运行
_THRESHOLD_CFG = [
    (1, 1, 10),
    (2, 2, 20),
    (3, 3, 30),
    (7, 5, 50),
    (30, 10, 100),
]


for _i, (_d, _m, _p) in enumerate(_THRESHOLD_CFG):
    def _make(d=_d, m=_m, p=_p):
        def test(self):
            engine = GrowthCycleEngine(
                cycle_days=d, min_experience_delta=m,
                max_pending=p,
            )
            t = engine.stats()["thresholds"]
            self.assertEqual(t["cycle_days"], d)
            self.assertEqual(t["min_experience_delta"], m)
            self.assertEqual(t["max_pending"], p)
        test.__name__ = f"test_threshold_{_i}"
        test.__doc__ = f"阈值 {_d}/{_m}/{_p}"
        return test
    setattr(TestGeneratedCycleThresholds,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
