"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 6 (V9.5 Extra6)

覆盖 (生成式批量):
    - 推理评价全面矩阵
    - 错误信号矩阵
    - 审计容量矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    CognitionAudit,
    ErrorPatternDetector,
    ReasoningEvaluator,
)


def make_entry(confidence=0.5, uncertainty="",
               resources=None):
    return {
        "monitor_id": "cm_x", "task": "t",
        "reasoning_type": "rules",
        "confidence": confidence,
        "uncertainty": uncertainty,
        "resources": resources or [],
    }


# ── 推理评价全面矩阵 ────────────────────────────────────────────
_EVAL_FULL_CASES = [
    ("根据数据, 因此正确", 0.8, "不确定", ["local"],
     0.9, 0.9, 0.9, 0.8),
    ("", 0.5, "", [], 0.3, 0.75, 0.6, 0.8),
    ("毫无疑问正确", 0.9, "", [], 0.3, 0.2, 0.6, 0.8),
    ("所有人都如此", 0.5, "", [], 0.3, 0.75, 0.6, 0.2),
]


class TestGeneratedEvalFull(unittest.TestCase):
    """生成式: 评价全面"""
    pass


for _i, (_text, _conf, _unc, _res, _ev, _cons, _comp,
         _bias) in enumerate(_EVAL_FULL_CASES):
    def _make(text=_text, conf=_conf, unc=_unc, res=_res,
              ev=_ev, cons=_cons, comp=_comp, bias=_bias):
        def test(self):
            r = ReasoningEvaluator().evaluate(
                make_entry(conf, unc, res), text,
            )
            dims = r["dimensions"]
            self.assertEqual(dims["evidence"]["score"], ev)
            self.assertEqual(dims["consistency"]["score"],
                             cons)
            self.assertEqual(dims["completeness"]["score"],
                             comp)
            self.assertEqual(dims["bias_risk"]["score"],
                             bias)
        test.__name__ = f"test_evalfull_{_i}"
        test.__doc__ = f"评价全面 {_i}"
        return test
    setattr(TestGeneratedEvalFull,
            _make().__name__, _make())


# ── 错误信号矩阵 ────────────────────────────────────────────────
_ERROR_SIGNAL_CASES = [
    ("与事实不符的数据", "fact_error"),
    ("错误事实陈述", "fact_error"),
    ("逻辑矛盾之处", "logic_error"),
    ("因果倒置", "logic_error"),
    ("记忆混淆", "memory_error"),
    ("来源不明的信息", "memory_error"),
    ("未经验证的假设", "assumption_error"),
    ("选择失误", "decision_error"),
    ("判断错误", "decision_error"),
]


class TestGeneratedErrorSignals(unittest.TestCase):
    """生成式: 错误信号"""
    pass


for _i, (_text, _etype) in enumerate(_ERROR_SIGNAL_CASES):
    def _make(text=_text, etype=_etype):
        def test(self):
            r = ErrorPatternDetector().classify(text)
            self.assertEqual(r["error_type"], etype)
        test.__name__ = f"test_esignal_{_i}"
        test.__doc__ = f"错误信号 {_text[:6]}"
        return test
    setattr(TestGeneratedErrorSignals,
            _make().__name__, _make())


# ── 审计容量矩阵 ────────────────────────────────────────────────
_AUDIT_CAP_CASES = [1, 5, 20]


class TestGeneratedAuditCap(unittest.TestCase):
    """生成式: 审计容量"""
    pass


for _i, _cap in enumerate(_AUDIT_CAP_CASES):
    def _make(cap=_cap):
        def test(self):
            audit = CognitionAudit(max_records=cap)
            for j in range(cap * 2):
                audit.record(task=f"t{j}")
            self.assertEqual(audit.stats()[
                "record_count"], cap)
        test.__name__ = f"test_auditcap_{_i}"
        test.__doc__ = f"审计容量 {_cap}"
        return test
    setattr(TestGeneratedAuditCap,
            _make().__name__, _make())


# ── 评价统计矩阵 ────────────────────────────────────────────────
class TestEvaluatorStats(unittest.TestCase):
    """评价统计"""

    def test_eval_count(self):
        evaluator = ReasoningEvaluator()
        for _ in range(3):
            evaluator.evaluate(make_entry())
        self.assertEqual(evaluator.stats()[
            "evaluation_count"], 3)

    def test_clear(self):
        evaluator = ReasoningEvaluator()
        evaluator.evaluate(make_entry())
        n = evaluator.clear()
        self.assertEqual(n, 1)
        self.assertEqual(evaluator.stats()[
            "evaluation_count"], 0)

    def test_evaluation_id_unique(self):
        evaluator = ReasoningEvaluator()
        r1 = evaluator.evaluate(make_entry())
        r2 = evaluator.evaluate(make_entry())
        self.assertNotEqual(r1["evaluation_id"],
                            r2["evaluation_id"])


# ── 错误统计矩阵 ────────────────────────────────────────────────
class TestErrorStats(unittest.TestCase):
    """错误统计"""

    def test_error_count(self):
        detector = ErrorPatternDetector()
        detector.classify("记错了")
        detector.classify("逻辑矛盾")
        self.assertEqual(detector.stats()[
            "error_count"], 2)

    def test_by_type(self):
        detector = ErrorPatternDetector()
        detector.classify("记错了")
        detector.classify("记错了")
        detector.classify("逻辑矛盾")
        stats = detector.stats()
        self.assertEqual(stats["by_type"][
            "memory_error"], 2)
        self.assertEqual(stats["by_type"][
            "logic_error"], 1)

    def test_min_pattern_config(self):
        detector = ErrorPatternDetector(min_pattern=3)
        detector.classify("记错了", "回忆")
        detector.classify("记错了", "回忆")
        self.assertEqual(detector.patterns()[
            "patterns"], [])


if __name__ == "__main__":
    unittest.main()
