"""
YHLZ Embodied AI V9.5 - 元认知引擎生成式补充测试 (V9.5 Extra)

覆盖 (生成式批量矩阵):
    - 错误分类矩阵
    - 评价维度矩阵
    - 验证结论矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    ErrorPatternDetector,
    ReasoningEvaluator,
    SelfVerification,
)


# ── 错误分类矩阵 ────────────────────────────────────────────────
_ERROR_CASES = [
    ("与事实不符", "fact_error"),
    ("错误事实", "fact_error"),
    ("逻辑矛盾", "logic_error"),
    ("推理错误", "logic_error"),
    ("记错了", "memory_error"),
    ("来源不明", "memory_error"),
    ("假设当作事实", "assumption_error"),
    ("错误决策", "decision_error"),
    ("wrong fact", "fact_error"),
    ("bad choice", "decision_error"),
    ("正常描述", "none"),
]


class TestGeneratedErrors(unittest.TestCase):
    """生成式: 错误分类"""
    pass


for _i, (_text, _etype) in enumerate(_ERROR_CASES):
    def _make(text=_text, etype=_etype):
        def test(self):
            r = ErrorPatternDetector().classify(text)
            self.assertEqual(r["error_type"], etype)
        test.__name__ = f"test_error_{_i}"
        test.__doc__ = f"错误 {_text[:8]}"
        return test
    setattr(TestGeneratedErrors,
            _make().__name__, _make())


# ── 评价维度矩阵 ────────────────────────────────────────────────
_EVAL_CASES = [
    ("根据数据", 0.9, "有证据信号"),
    ("毫无疑问", 0.2, "逻辑跳跃"),
    ("所有人", 0.2, "偏差"),
    ("", 0.3, "无证据信号"),
]


class TestGeneratedEvalDims(unittest.TestCase):
    """生成式: 评价维度"""
    pass


for _i, (_text, _score, _kw) in enumerate(_EVAL_CASES):
    def _make(text=_text, score=_score, kw=_kw):
        def test(self):
            entry = {
                "monitor_id": "cm_x", "task": "t",
                "reasoning_type": "rules",
                "confidence": 0.5,
                "uncertainty": "",
                "resources": [],
            }
            r = ReasoningEvaluator().evaluate(entry, text)
            dims = r["dimensions"]
            self.assertIn("score", r)
            self.assertEqual(len(dims), 4)
        test.__name__ = f"test_eval_{_i}"
        test.__doc__ = f"评价 {_kw}"
        return test
    setattr(TestGeneratedEvalDims,
            _make().__name__, _make())


# ── 验证结论矩阵 ────────────────────────────────────────────────
_VERIFY_CASES = [
    ("根据数据, 因此正确", "证据", "推理", 0.9, "fact"),
    ("结论", "根据数据", "", 0.6, "inference"),
    ("候选", "", "", 0.8, "hypothesis"),
    ("", "", "", 0.2, "uncertain"),
    ("推测", "", "因此", 0.3, "inference"),
]


class TestGeneratedVerify(unittest.TestCase):
    """生成式: 验证结论"""
    pass


for _i, (_conclusion, _evidence, _reasoning, _conf,
         _ctype) in enumerate(_VERIFY_CASES):
    def _make(conclusion=_conclusion, evidence=_evidence,
              reasoning=_reasoning, conf=_conf,
              ctype=_ctype):
        def test(self):
            r = SelfVerification().verify(
                conclusion, evidence, reasoning, conf,
            )
            self.assertEqual(r["conclusion_type"], ctype)
        test.__name__ = f"test_verify_{_i}"
        test.__doc__ = f"验证 {_ctype}"
        return test
    setattr(TestGeneratedVerify,
            _make().__name__, _make())


# ── 监控类型矩阵 ────────────────────────────────────────────────
_MONITOR_TYPES = ["deductive", "inductive", "analogical",
                  "abductive", "rules"]


class TestGeneratedMonitorTypes(unittest.TestCase):
    """生成式: 监控类型"""
    pass


for _i, _rtype in enumerate(_MONITOR_TYPES):
    def _make(rtype=_rtype):
        def test(self):
            from backend.embodied.companion.meta_cognition import (
                CognitiveMonitor,
            )
            entry = CognitiveMonitor().record(
                "任务", rtype, 0.7,
            )
            self.assertEqual(entry["reasoning_type"], rtype)
        test.__name__ = f"test_mtype_{_i}"
        test.__doc__ = f"监控类型 {_rtype}"
        return test
    setattr(TestGeneratedMonitorTypes,
            _make().__name__, _make())


# ── 重复错误矩阵 ────────────────────────────────────────────────
_REPEAT_ERROR_CASES = [
    [("记错了", "回忆"), ("记错了", "回忆")],
    [("逻辑矛盾", "推理"), ("逻辑矛盾", "推理"),
     ("逻辑矛盾", "推理")],
    [("记错了", "A"), ("记错了", "B")],
]


class TestGeneratedRepeatErrors(unittest.TestCase):
    """生成式: 重复错误"""
    pass


for _i, _entries in enumerate(_REPEAT_ERROR_CASES):
    def _make(entries=_entries):
        def test(self):
            detector = ErrorPatternDetector()
            for (text, trigger) in entries:
                detector.classify(text, trigger)
            patterns = detector.patterns()
            if len(entries) >= 2 and \
                    entries[0][1] == entries[1][1]:
                self.assertGreaterEqual(
                    len(patterns["patterns"]), 1)
        test.__name__ = f"test_repeat_{_i}"
        test.__doc__ = f"重复错误 {_i}"
        return test
    setattr(TestGeneratedRepeatErrors,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
