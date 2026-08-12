"""
YHLZ Embodied AI V9.5 - 错误检测与自我验证单元测试 (Errors & Verification)

覆盖:
    - ErrorPatternDetector: 5 类错误/重复模式
    - SelfVerification: 事实/推论/假设/不确定
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    ErrorPatternDetector,
    SelfVerification,
)
from backend.embodied.companion.meta_cognition.error_detector import (
    ERROR_SIGNALS,
    ERROR_TYPES,
    DetectorError,
)
from backend.embodied.companion.meta_cognition.self_verification import (
    CONCLUSION_TYPES,
)


class TestErrorPatternDetector(unittest.TestCase):
    """错误模式检测"""

    def setUp(self):
        self.detector = ErrorPatternDetector()

    def test_fact_error(self):
        r = self.detector.classify("与事实不符的数据")
        self.assertEqual(r["error_type"], "fact_error")

    def test_logic_error(self):
        r = self.detector.classify("逻辑矛盾")
        self.assertEqual(r["error_type"], "logic_error")

    def test_memory_error(self):
        r = self.detector.classify("记错了日期")
        self.assertEqual(r["error_type"], "memory_error")

    def test_assumption_error(self):
        r = self.detector.classify("假设当作事实")
        self.assertEqual(r["error_type"],
                         "assumption_error")

    def test_decision_error(self):
        r = self.detector.classify("错误决策")
        self.assertEqual(r["error_type"],
                         "decision_error")

    def test_no_match(self):
        r = self.detector.classify("正常描述")
        self.assertEqual(r["error_type"], "none")

    def test_classify_structure(self):
        r = self.detector.classify("记错了")
        for key in ("error_id", "error_type", "reason",
                    "matched_signal", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["error_id"].startswith("ed_"))

    def test_english_signal(self):
        r = self.detector.classify("wrong fact")
        self.assertEqual(r["error_type"], "fact_error")

    def test_all_types_constant(self):
        self.assertEqual(ERROR_TYPES,
                         ["fact_error", "logic_error",
                          "memory_error",
                          "assumption_error",
                          "decision_error"])

    def test_signals_map(self):
        self.assertIn("记错了", ERROR_SIGNALS["memory_error"])
        self.assertIn("wrong inference",
                      ERROR_SIGNALS["logic_error"])

    def test_repeated_pattern(self):
        """重复错误模式 (≥2 次同类)"""
        self.detector.classify("记错了日期", "回忆")
        self.detector.classify("记错了日期", "回忆")
        patterns = self.detector.patterns()
        self.assertGreaterEqual(len(patterns["patterns"]), 1)
        self.assertEqual(
            patterns["patterns"][0]["occurrences"], 2)

    def test_no_pattern_below_threshold(self):
        self.detector.classify("记错了", "回忆")
        self.assertEqual(self.detector.patterns()[
            "patterns"], [])

    def test_pattern_by_trigger_type(self):
        self.detector.classify("记错了", "A")
        self.detector.classify("记错了", "B")
        # 不同 trigger → 不构成模式
        self.assertEqual(self.detector.patterns()[
            "patterns"], [])

    def test_stats(self):
        self.detector.classify("记错了", "回忆")
        self.detector.classify("逻辑矛盾", "推理")
        stats = self.detector.stats()
        self.assertEqual(stats["error_count"], 2)
        self.assertEqual(stats["by_type"]["memory_error"], 1)

    def test_invalid_min_pattern(self):
        with self.assertRaises(DetectorError):
            ErrorPatternDetector(min_pattern=1)

    def test_disabled(self):
        detector = ErrorPatternDetector(enabled=False)
        r = detector.classify("记错了")
        self.assertFalse(r["ok"])

    def test_clear(self):
        self.detector.classify("记错了", "回忆")
        n = self.detector.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.detector.stats()[
            "error_count"], 0)


class TestSelfVerification(unittest.TestCase):
    """自我验证"""

    def setUp(self):
        self.verifier = SelfVerification()

    def test_fact_type(self):
        r = self.verifier.verify(
            "根据数据, 因此结论正确",
            evidence="证据", reasoning="推理",
        )
        self.assertEqual(r["conclusion_type"], "fact")
        self.assertTrue(r["ok"])

    def test_inference_type(self):
        r = self.verifier.verify(
            "结论", evidence="根据数据",
        )
        self.assertEqual(r["conclusion_type"], "inference")

    def test_hypothesis_type(self):
        r = self.verifier.verify(
            "候选结论", confidence=0.8,
        )
        self.assertEqual(r["conclusion_type"],
                         "hypothesis")

    def test_uncertain_type(self):
        r = self.verifier.verify("内容", confidence=0.2)
        self.assertEqual(r["conclusion_type"], "uncertain")
        self.assertFalse(r["ok"])

    def test_ok_means_output_safe(self):
        r = self.verifier.verify("根据数据, 结论")
        self.assertTrue(r["ok"])
        self.assertIn("可输出", r["reason"])

    def test_uncertain_reason(self):
        r = self.verifier.verify("", confidence=0.1)
        self.assertIn("不确定内容需标注", r["reason"])

    def test_structure(self):
        r = self.verifier.verify("结论", evidence="e")
        for key in ("verification_id", "conclusion_type",
                    "ok", "checks", "reason", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["verification_id"].startswith(
            "sv_"))

    def test_checks_three(self):
        r = self.verifier.verify("结论", evidence="e")
        names = [c["name"] for c in r["checks"]]
        self.assertEqual(names, ["evidence", "reasoning",
                                 "confidence"])

    def test_types_constant(self):
        self.assertEqual(CONCLUSION_TYPES,
                         ["fact", "inference", "hypothesis",
                          "uncertain"])

    def test_stats(self):
        self.verifier.verify("a", evidence="e")
        self.verifier.verify("", confidence=0.1)
        stats = self.verifier.stats()
        self.assertEqual(stats["verified_count"], 2)
        self.assertEqual(stats["uncertain_count"], 1)

    def test_disabled(self):
        verifier = SelfVerification(enabled=False)
        r = verifier.verify("内容")
        self.assertTrue(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.verifier.verify("a")
        self.verifier.clear()
        self.assertEqual(self.verifier.stats()[
            "verified_count"], 0)


if __name__ == "__main__":
    unittest.main()
