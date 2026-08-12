"""
YHLZ Embodied AI V6.6 - 自主成长成熟化补充测试 4 (V6.6 Extra4)

覆盖 (生成式批量矩阵):
    - 反思情绪: 置信度 × 模式组合
    - 成长闭环: 触发 × 数据量组合
    - 趋势: 指标输入组合
"""
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
        "report_id": "cr_gen4",
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


# ── 模式 × 置信度矩阵 ───────────────────────────────────────────
_CONFIDENCE_MATRIX = [
    ("success_strategy", 0.5, "success"),
    ("success_strategy", 0.9, "success"),
    ("problem_pattern", 0.4, "failure"),
    ("problem_pattern", 0.95, "failure"),
    ("repetition", 0.3, "idle"),
    ("repetition", 1.0, "idle"),
]


class TestGeneratedConfidenceMatrix(unittest.TestCase):
    """生成式: 模式 × 置信度"""
    pass


for _i, (_ptype, _conf, _ctx) in \
        enumerate(_CONFIDENCE_MATRIX):
    def _make(ptype=_ptype, conf=_conf, ctx=_ctx):
        def test(self):
            r = ReflectionEmotionIntegrator().analyze(
                _report(patterns=[_pat(ptype, conf)]),
            )
            self.assertEqual(r["emotion_context"], ctx)
        test.__name__ = f"test_conf_matrix_{_i}"
        test.__doc__ = f"置信矩阵 {_ptype}/{_conf}"
        return test
    setattr(TestGeneratedConfidenceMatrix,
            _make().__name__, _make())


# ── 情绪调整后状态不变量矩阵 ────────────────────────────────────
class TestGeneratedEmotionInvariants(unittest.TestCase):
    """生成式: 调整后状态不变量"""
    pass


for _i, _ptype in enumerate(["success_strategy",
                             "problem_pattern",
                             "repetition", "success_strategy"]):
    def _make(ptype=_ptype):
        def test(self):
            emotion = EmotionEngine()
            integrator = ReflectionEmotionIntegrator(
                emotion=emotion,
            )
            integrator.adjust(_report(
                patterns=[_pat(ptype)],
            ))
            state = emotion.get_state()
            for dim in ("positivity", "energy", "warmth"):
                self.assertGreaterEqual(state[dim], 0.0)
                self.assertLessEqual(state[dim], 1.0)
        test.__name__ = f"test_invariant_{_i}"
        test.__doc__ = f"状态不变量 {_ptype}"
        return test
    setattr(TestGeneratedEmotionInvariants,
            _make().__name__, _make())


# ── 闭环触发 × 数据量矩阵 ───────────────────────────────────────
_DATA_MATRIX = [
    (0, 0, None),      # 空
    (2, 0, "time"),    # 时间
    (0, 8, "event"),   # 事件
    (5, 20, "time"),   # 双触发 → 时间优先
    (0, 3, None),      # 低于事件阈值
    (1, 5, "time"),    # 双触发边界 → 时间优先
]


class TestGeneratedTriggerDataMatrix(unittest.TestCase):
    """生成式: 触发 × 数据量"""
    pass


for _i, (_days, _n, _expected) in enumerate(_DATA_MATRIX):
    def _make(days=_days, n=_n, expected=_expected):
        def test(self):
            engine = GrowthCycleEngine(
                reflection=CognitiveReflectionEngine(),
                proposal=GrowthProposal(),
                evaluator=GrowthEvaluator(),
                records_fn=lambda: [
                    {"id": f"r{j}", "type": "failure",
                     "trigger": f"t{j % 3}",
                     "result": "错误"}
                    for j in range(n)
                ],
            )
            now = time.time()
            engine._last_run = now - days * 86400
            r = engine.run(trigger="auto", now=now)
            if expected is None:
                self.assertIsNone(r["cycle"])
            else:
                self.assertEqual(r["cycle"]["trigger"],
                                 expected)
        test.__name__ = f"test_data_matrix_{_i}"
        test.__doc__ = f"数据矩阵 {_days}天/{_n}条"
        return test
    setattr(TestGeneratedTriggerDataMatrix,
            _make().__name__, _make())


# ── 建议产出矩阵 ────────────────────────────────────────────────
_PROPOSAL_MATRIX = [
    (0, 0),     # 无记录
    (4, 4),     # 只有成功
    (4, 0),     # 只有失败
    (4, 4),     # 混合
]


class TestGeneratedProposalOutput(unittest.TestCase):
    """生成式: 建议产出"""
    pass


for _i, (_ok, _fail) in enumerate(_PROPOSAL_MATRIX):
    def _make(ok=_ok, fail=_fail):
        def test(self):
            records = []
            for j in range(ok):
                records.append({
                    "id": f"s{j}", "type": "improvement",
                    "trigger": "成功触发",
                    "result": "成功",
                })
            for j in range(fail):
                records.append({
                    "id": f"f{j}", "type": "failure",
                    "trigger": "失败触发",
                    "result": "错误",
                })
            engine = GrowthCycleEngine(
                reflection=CognitiveReflectionEngine(),
                proposal=GrowthProposal(),
                evaluator=GrowthEvaluator(),
                records_fn=lambda: records,
            )
            r = engine.run(trigger="manual")
            self.assertEqual(r["cycle"]["status"],
                             "completed")
            self.assertEqual(
                r["cycle"]["experience_count"],
                ok + fail,
            )
        test.__name__ = f"test_proposal_out_{_i}"
        test.__doc__ = f"建议产出 {_ok}成功/{_fail}失败"
        return test
    setattr(TestGeneratedProposalOutput,
            _make().__name__, _make())


# ── 趋势输入组合矩阵 ────────────────────────────────────────────
_INPUT_MATRIX = [
    ({"evaluator": {"evaluation_count": 10,
                    "approved_count": 10}}, 0.35),
    ({"applier": {"applied_count": 20}}, 0.25),
    ({"reflection": {"reflection_count": 60}}, 0.3),
    ({"experience": {"total": 200}}, 0.25),
    ({"verification": {"confirmed": 40,
                       "rejected": 0}}, 0.25),
]


class TestGeneratedInputMatrix(unittest.TestCase):
    """生成式: 输入组合 → 分数下界"""
    pass


for _i, (_extra, _min_score) in enumerate(_INPUT_MATRIX):
    def _make(extra=_extra, min_score=_min_score):
        def test(self):
            stats = {
                "reflection": {"reflection_count": 0},
                "proposal": {"proposal_count": 0},
                "evaluator": {"evaluation_count": 0,
                              "approved_count": 0},
                "applier": {"applied_count": 0},
                "identity_guard": {"intercept_count": 0,
                                   "approval_count": 0},
                "experience": {"total": 0},
                "verification": {"confirmed": 0,
                                 "rejected": 0},
                "period_days": 30,
            }
            stats.update(extra)
            r = GrowthTrendAnalysis().analyze(stats)
            self.assertGreaterEqual(r["growth_score"],
                                    min_score)
        test.__name__ = f"test_input_matrix_{_i}"
        test.__doc__ = f"输入矩阵 {_i}"
        return test
    setattr(TestGeneratedInputMatrix,
            _make().__name__, _make())


# ── 周期 × 数据矩阵 ─────────────────────────────────────────────
_PERIOD_MATRIX = [
    ("day", 5),
    ("day", 30),
    ("week", 5),
    ("week", 30),
    ("month", 5),
    ("month", 30),
]


class TestGeneratedPeriodData(unittest.TestCase):
    """生成式: 周期 × 数据"""
    pass


for _i, (_period, _days) in enumerate(_PERIOD_MATRIX):
    def _make(period=_period, days=_days):
        def test(self):
            r = GrowthTrendAnalysis().analyze(_stats(
                reflection={"reflection_count": 60},
                period_days=days,
            ), period=period)
            m = next(a for a in r["analysis"]
                     if a["metric"] == "reflection_frequency")
            self.assertAlmostEqual(
                m["value"], round(60 / days, 4), places=3)
        test.__name__ = f"test_period_data_{_i}"
        test.__doc__ = f"周期数据 {_period}/{_days}"
        return test
    setattr(TestGeneratedPeriodData,
            _make().__name__, _make())


# ── 闭环审计记录数矩阵 ──────────────────────────────────────────
_AUDIT_MATRIX = [(1, 1), (2, 1), (3, 1)]


class TestGeneratedAuditCount(unittest.TestCase):
    """生成式: 审计记录数"""
    pass


for _i, (_runs, _decisions_per_run) in \
        enumerate(_AUDIT_MATRIX):
    def _make(runs=_runs):
        def test(self):
            audit = __import__(
                "backend.embodied.companion.growth."
                "growth_audit",
                fromlist=["GrowthAudit"],
            ).GrowthAudit()
            engine = GrowthCycleEngine(
                reflection=CognitiveReflectionEngine(),
                proposal=GrowthProposal(),
                evaluator=GrowthEvaluator(),
                audit=audit,
                records_fn=lambda: [
                    {"id": f"{trig}{i}",
                     "type": "failure",
                     "trigger": trig,
                     "result": "错误"}
                    for trig in ("t1", "t2", "t3")
                    for i in range(4)
                ],
            )
            for _ in range(runs):
                engine.run(trigger="manual")
            report = audit.report(limit=0)
            self.assertEqual(
                report["by_decision"]["cycle_completed"],
                runs)
        test.__name__ = f"test_audit_count_{_i}"
        test.__doc__ = f"审计计数 {_runs}"
        return test
    setattr(TestGeneratedAuditCount,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
