"""
YHLZ Embodied AI V6.6 - 自主成长成熟化生成式补充测试 (V6.6 Extra)

覆盖 (生成式批量用例):
    - 反思情绪: 模式/矛盾/置信度组合矩阵
    - 成长闭环: 触发条件矩阵
    - 成长趋势: 指标数值矩阵
    - 待审批决策矩阵
"""
import time
import unittest

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

# ── 模式 → 情绪上下文 矩阵 ──────────────────────────────────────
_PATTERN_CONTEXT = {
    "success_strategy": "success",
    "problem_pattern": "failure",
    "repetition": "idle",
    "unknown_type": "idle",
}

_CONFLICT_RISK = {
    "identity_conflict": "high",
    "knowledge_conflict": "medium",
    "value_conflict": "high",
    "unknown_conflict": "low",
}

_STATE_MAP = {
    "success": "positive",
    "failure": "cautious",
    "idle": "neutral",
}


def _report(patterns=None, contradictions=None,
            confidence=0.8):
    return {
        "report_id": "cr_gen",
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


class TestGeneratedPatternContext(unittest.TestCase):
    """生成式: 模式 → 情绪上下文"""
    pass


for _ptype, _ctx in _PATTERN_CONTEXT.items():
    def _make(ptype=_ptype, ctx=_ctx):
        def test(self):
            r = ReflectionEmotionIntegrator().analyze(
                _report(patterns=[_pat(ptype)]),
            )
            self.assertEqual(r["emotion_context"], ctx)
        test.__name__ = f"test_context_{ptype}"
        test.__doc__ = f"模式 {ptype} → 上下文 {ctx}"
        return test
    setattr(TestGeneratedPatternContext,
            _make().__name__, _make())


class TestGeneratedConflictRisk(unittest.TestCase):
    """生成式: 矛盾 → 风险等级"""
    pass


for _ctype, _risk in _CONFLICT_RISK.items():
    def _make(ctype=_ctype, risk=_risk):
        def test(self):
            r = ReflectionEmotionIntegrator().analyze(
                _report(contradictions=[
                    {"conflict_type": ctype},
                ]),
            )
            self.assertEqual(r["risk_level"], risk)
        test.__name__ = f"test_risk_{ctype}"
        test.__doc__ = f"矛盾 {ctype} → 风险 {risk}"
        return test
    setattr(TestGeneratedConflictRisk,
            _make().__name__, _make())


class TestGeneratedStateMap(unittest.TestCase):
    """生成式: 模式 → 情绪状态"""
    pass


for _ctx, _state in _STATE_MAP.items():
    def _make(ctx=_ctx, state=_state):
        def test(self):
            ptype = {
                "success": "success_strategy",
                "failure": "problem_pattern",
                "idle": "repetition",
            }[ctx]
            r = ReflectionEmotionIntegrator().analyze(
                _report(patterns=[_pat(ptype)]),
            )
            self.assertEqual(
                r["emotion_analysis"]["state"], state)
        test.__name__ = f"test_state_{ctx}"
        test.__doc__ = f"上下文 {ctx} → 状态 {state}"
        return test
    setattr(TestGeneratedStateMap, _make().__name__, _make())


class TestGeneratedConfidence(unittest.TestCase):
    """生成式: 报告置信度透传"""
    pass


for _conf in [0.1, 0.35, 0.5, 0.66, 0.8, 0.95, 1.0]:
    def _make(conf=_conf):
        def test(self):
            r = ReflectionEmotionIntegrator().analyze(
                _report(patterns=[_pat("success_strategy")],
                        confidence=conf),
            )
            self.assertEqual(
                r["emotion_analysis"]["confidence"], conf)
        test.__name__ = f"test_conf_{int(_conf * 100)}"
        test.__doc__ = f"置信度 {_conf}"
        return test
    setattr(TestGeneratedConfidence,
            _make().__name__, _make())


class TestGeneratedGrowthValue(unittest.TestCase):
    """生成式: 模式 → 成长值"""
    pass


for _ptype, _value in [("success_strategy", 0.85),
                       ("problem_pattern", 0.35),
                       ("repetition", 0.5)]:
    def _make(ptype=_ptype, value=_value):
        def test(self):
            r = ReflectionEmotionIntegrator().analyze(
                _report(patterns=[_pat(ptype)]),
            )
            self.assertEqual(r["growth_value"], value)
        test.__name__ = f"test_value_{ptype}"
        test.__doc__ = f"成长值 {ptype} = {value}"
        return test
    setattr(TestGeneratedGrowthValue,
            _make().__name__, _make())


class TestGeneratedCycleTriggers(unittest.TestCase):
    """生成式: 触发条件矩阵"""
    pass

# (days_since_last_run, experience_delta, min_delta,
#  期望触发, 期望原因数)
_TRIGGER_CASES = [
    (2, 0, 5, True, 1),     # 时间
    (0, 6, 5, True, 1),     # 事件
    (3, 6, 5, True, 2),     # 双触发
    (0, 4, 5, False, 0),    # 无
    (1, 5, 5, True, 2),     # 边界双
    (0, 0, 5, False, 0),    # 空
    (7, 1, 5, True, 1),     # 长时间
    (0, 10, 5, True, 1),    # 大增量
]


for _i, (_days, _delta, _min_delta, _exp, _n) in \
        enumerate(_TRIGGER_CASES):
    def _make(days=_days, delta=_delta, min_delta=_min_delta,
              exp=_exp, n=_n):
        def test(self):
            engine = GrowthCycleEngine(
                min_experience_delta=min_delta,
            )
            now = time.time()
            engine._last_run = now - days * 86400
            engine._last_experience_count = 0
            r = engine.check(experience_count=delta,
                             now=now)
            self.assertEqual(r["triggered"], exp)
            self.assertEqual(len(r["reasons"]), n)
        test.__name__ = f"test_trigger_{_i}"
        test.__doc__ = (f"触发矩阵 {_days}天/"
                        f"{_delta}增量")
        return test
    setattr(TestGeneratedCycleTriggers,
            _make().__name__, _make())


class TestGeneratedTriggerTypes(unittest.TestCase):
    """生成式: auto 运行 → 触发类型"""
    pass

# (last_run_days, records_n, 期望触发类型)
_TRIGGER_TYPE_CASES = [
    (2, 0, "time"),
    (0, 6, "event"),
    (3, 6, "time"),
    (0, 0, None),
]


for _i, (_days, _n, _expected) in \
        enumerate(_TRIGGER_TYPE_CASES):
    def _make(days=_days, n=_n, expected=_expected):
        def test(self):
            engine = GrowthCycleEngine(
                reflection=CognitiveReflectionEngine(),
                proposal=GrowthProposal(),
                evaluator=GrowthEvaluator(),
                records_fn=lambda: [{"id": "x",
                                     "type": "failure",
                                     "result": "错误"}] * n
                if n else [],
            )
            now = time.time()
            engine._last_run = now - days * 86400
            r = engine.run(trigger="auto", now=now)
            if expected is None:
                self.assertIsNone(r["cycle"])
            else:
                self.assertEqual(r["cycle"]["trigger"],
                                 expected)
        test.__name__ = f"test_auto_type_{_i}"
        test.__doc__ = f"auto 触发 {_days}天/{_n}条"
        return test
    setattr(TestGeneratedTriggerTypes,
            _make().__name__, _make())


class TestGeneratedApprovalRates(unittest.TestCase):
    """生成式: 通过率数值"""
    pass

# (evaluation_count, approved_count, 期望通过率)
_RATE_CASES = [
    (10, 10, 1.0),
    (10, 5, 0.5),
    (10, 0, 0.0),
    (4, 1, 0.25),
    (3, 2, 0.6667),
    (0, 0, 0.0),
]


for _i, (_eval_n, _appr_n, _rate) in \
        enumerate(_RATE_CASES):
    def _make(eval_n=_eval_n, appr_n=_appr_n, rate=_rate):
        def test(self):
            r = GrowthTrendAnalysis().analyze(_stats(
                evaluator={"evaluation_count": eval_n,
                           "approved_count": appr_n},
            ))
            m = next(a for a in r["analysis"]
                     if a["metric"] == "approval_rate")
            self.assertAlmostEqual(m["value"], rate,
                                   places=3)
        test.__name__ = f"test_rate_{_i}"
        test.__doc__ = f"通过率 {_appr_n}/{_eval_n}"
        return test
    setattr(TestGeneratedApprovalRates,
            _make().__name__, _make())


class TestGeneratedMemoryQuality(unittest.TestCase):
    """生成式: 记忆质量数值"""
    pass

# (confirmed, rejected, 期望质量)
_QUALITY_CASES = [
    (10, 0, 1.0),
    (9, 1, 0.9),
    (5, 5, 0.5),
    (0, 1, 0.0),
    (0, 0, 0.0),
    (1, 3, 0.25),
]


for _i, (_conf, _rej, _q) in enumerate(_QUALITY_CASES):
    def _make(conf=_conf, rej=_rej, q=_q):
        def test(self):
            r = GrowthTrendAnalysis().analyze(_stats(
                verification={"confirmed": conf,
                              "rejected": rej},
            ))
            m = next(a for a in r["analysis"]
                     if a["metric"] == "memory_quality")
            self.assertAlmostEqual(m["value"], q,
                                   places=3)
        test.__name__ = f"test_quality_{_i}"
        test.__doc__ = f"记忆质量 {_conf}/{_rej}"
        return test
    setattr(TestGeneratedMemoryQuality,
            _make().__name__, _make())


class TestGeneratedFrequency(unittest.TestCase):
    """生成式: 反思频率"""
    pass

# (count, period_days, 期望频率)
_FREQ_CASES = [
    (30, 30, 1.0),
    (15, 30, 0.5),
    (60, 30, 2.0),
    (7, 7, 1.0),
    (1, 30, 0.0333),
    (0, 30, 0.0),
]


for _i, (_c, _d, _f) in enumerate(_FREQ_CASES):
    def _make(c=_c, d=_d, f=_f):
        def test(self):
            r = GrowthTrendAnalysis().analyze(_stats(
                reflection={"reflection_count": c},
                period_days=d,
            ))
            m = next(a for a in r["analysis"]
                     if a["metric"] == "reflection_frequency")
            self.assertAlmostEqual(m["value"], f,
                                   places=3)
        test.__name__ = f"test_freq_{_i}"
        test.__doc__ = f"频率 {_c}次/{_d}天"
        return test
    setattr(TestGeneratedFrequency,
            _make().__name__, _make())


class TestGeneratedScoreMonotonic(unittest.TestCase):
    """生成式: 成长分单调性"""
    pass

# (reflection_count, 期望 growth_score 升序)
_SCORE_CASES = [
    (0,),
    (10,),
    (30,),
    (60,),
]


def _score_for(refl_count):
    return GrowthTrendAnalysis().analyze(_stats(
        reflection={"reflection_count": refl_count},
        evaluator={"evaluation_count": 50,
                   "approved_count": 50},
        applier={"applied_count": 10},
        experience={"total": 100},
        verification={"confirmed": 50, "rejected": 0},
    ))["growth_score"]


def _make_score(refl_count=_SCORE_CASES[0][0]):
    def test(self):
        r = GrowthTrendAnalysis().analyze(_stats(
            reflection={"reflection_count": refl_count},
            evaluator={"evaluation_count": 50,
                       "approved_count": 50},
            applier={"applied_count": 10},
            experience={"total": 100},
            verification={"confirmed": 50, "rejected": 0},
        ))
        self.assertGreaterEqual(r["growth_score"], 0.0)
        self.assertLessEqual(r["growth_score"], 1.0)
    test.__name__ = f"test_score_{_SCORE_CASES.index((refl_count,))}"
    return test


for _i, _case in enumerate(_SCORE_CASES):
    setattr(TestGeneratedScoreMonotonic,
            _make_score(_case[0]).__name__, _make_score(_case[0]))

# 单调性: 更高反思活跃 → 分数更高
_score_vals = [_score_for(c[0]) for c in _SCORE_CASES]
for _i in range(len(_score_vals) - 1):
    def _make(i=_i):
        def test(self):
            self.assertGreaterEqual(_score_vals[i + 1],
                                    _score_vals[i])
        test.__name__ = f"test_monotonic_{_i}"
        test.__doc__ = f"分数单调 {_i}"
        return test
    setattr(TestGeneratedScoreMonotonic,
            _make().__name__, _make())


class TestGeneratedCycleEngineCombos(unittest.TestCase):
    """生成式: 闭环引擎组合"""
    pass

# (cycle_days, min_delta, max_pending) 构造合法
_ENGINE_CFG = [
    (1, 1, 1),
    (2, 3, 5),
    (7, 10, 100),
    (30, 50, 200),
    (1, 5, 0),
]


for _i, (_days, _delta, _maxp) in enumerate(_ENGINE_CFG):
    def _make(days=_days, delta=_delta, maxp=_maxp):
        def test(self):
            engine = GrowthCycleEngine(
                reflection=CognitiveReflectionEngine(),
                proposal=GrowthProposal(),
                evaluator=GrowthEvaluator(),
                records_fn=lambda: [{"id": "x",
                                     "type": "improvement",
                                     "result": "成功"}] * delta
                if delta else [],
                cycle_days=days,
                min_experience_delta=delta,
                max_pending=maxp,
            )
            r = engine.run(trigger="manual")
            self.assertEqual(r["cycle"]["status"],
                             "completed")
            self.assertLessEqual(r["pending_count"], maxp)
        test.__name__ = f"test_engine_cfg_{_i}"
        test.__doc__ = f"引擎配置 {_days}/{_delta}/{_maxp}"
        return test
    setattr(TestGeneratedCycleEngineCombos,
            _make().__name__, _make())


class TestGeneratedTrendPeriods(unittest.TestCase):
    """生成式: 周期矩阵"""
    pass


for _period in ["day", "week", "month"]:
    def _make(period=_period):
        def test(self):
            r = GrowthTrendAnalysis().analyze(_stats(),
                                              period=period)
            self.assertEqual(r["period"], period)
            self.assertEqual(len(r["analysis"]), 9)
        test.__name__ = f"test_period_{_period}"
        test.__doc__ = f"周期 {_period}"
        return test
    setattr(TestGeneratedTrendPeriods,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
