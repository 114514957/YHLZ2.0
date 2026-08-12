"""
YHLZ Embodied AI V9.5 - 认知监控与推理评价单元测试 (Monitor & Evaluator)

覆盖:
    - CognitiveMonitor: 记录/推理类型/置信度钳制
    - ReasoningEvaluator: 四维评价
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    CognitiveMonitor,
    ReasoningEvaluator,
)
from backend.embodied.companion.meta_cognition.cognitive_monitor import (
    REASONING_TYPES,
    MonitorError,
)


class TestCognitiveMonitor(unittest.TestCase):
    """认知监控"""

    def setUp(self):
        self.monitor = CognitiveMonitor()

    def test_record_structure(self):
        entry = self.monitor.record("任务", "deductive",
                                    confidence=0.8)
        for key in ("monitor_id", "task", "reasoning_type",
                    "confidence", "uncertainty", "resources",
                    "timestamp"):
            self.assertIn(key, entry)
        self.assertTrue(entry["monitor_id"].startswith("cm_"))

    def test_record_all_types(self):
        for t in REASONING_TYPES:
            entry = self.monitor.record("任务", t)
            self.assertEqual(entry["reasoning_type"], t)

    def test_invalid_type(self):
        with self.assertRaises(MonitorError):
            self.monitor.record("任务", "bogus")

    def test_confidence_clamp_high(self):
        entry = self.monitor.record("任务", confidence=2.0)
        self.assertEqual(entry["confidence"], 1.0)

    def test_confidence_clamp_low(self):
        entry = self.monitor.record("任务", confidence=-1.0)
        self.assertEqual(entry["confidence"], 0.0)

    def test_confidence_invalid(self):
        entry = self.monitor.record("任务",
                                    confidence="high")
        self.assertEqual(entry["confidence"], 0.5)

    def test_uncertainty_recorded(self):
        entry = self.monitor.record(
            "任务", uncertainty="部分不确定",
        )
        self.assertEqual(entry["uncertainty"], "部分不确定")

    def test_resources_recorded(self):
        entry = self.monitor.record(
            "任务", resources=["local", "cloud"],
        )
        self.assertEqual(entry["resources"],
                         ["local", "cloud"])

    def test_records(self):
        self.monitor.record("a")
        self.monitor.record("b")
        records = self.monitor.records()
        self.assertEqual(len(records), 2)

    def test_stats(self):
        self.monitor.record("a", "deductive", 0.9)
        self.monitor.record("b", "rules", 0.5)
        stats = self.monitor.stats()
        self.assertEqual(stats["record_count"], 2)
        self.assertEqual(stats["by_reasoning_type"][
            "deductive"], 1)
        self.assertAlmostEqual(stats["avg_confidence"], 0.7,
                               places=2)

    def test_disabled(self):
        monitor = CognitiveMonitor(enabled=False)
        r = monitor.record("任务")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.monitor.record("a")
        n = self.monitor.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.monitor.stats()[
            "record_count"], 0)

    def test_types_constant(self):
        self.assertEqual(REASONING_TYPES,
                         ["deductive", "inductive",
                          "analogical", "abductive",
                          "rules"])


class TestReasoningEvaluator(unittest.TestCase):
    """推理评价"""

    def setUp(self):
        self.evaluator = ReasoningEvaluator()

    def entry(self, confidence=0.5, uncertainty=""):
        return {
            "monitor_id": "cm_1", "task": "任务",
            "reasoning_type": "deductive",
            "confidence": confidence,
            "uncertainty": uncertainty,
            "resources": ["local"],
        }

    def test_evaluate_structure(self):
        r = self.evaluator.evaluate(self.entry())
        for key in ("evaluation_id", "score", "dimensions",
                    "reason", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["evaluation_id"].startswith("re_"))

    def test_four_dimensions(self):
        r = self.evaluator.evaluate(self.entry())
        dims = r["dimensions"]
        self.assertEqual(list(dims.keys()),
                         ["consistency", "evidence",
                          "completeness", "bias_risk"])

    def test_score_range(self):
        r = self.evaluator.evaluate(self.entry())
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 1.0)

    def test_evidence_signal(self):
        r = self.evaluator.evaluate(
            self.entry(), "根据数据, 结论正确",
        )
        self.assertEqual(
            r["dimensions"]["evidence"]["score"], 0.9)

    def test_logic_jump_low_consistency(self):
        r = self.evaluator.evaluate(
            self.entry(), "毫无疑问正确",
        )
        self.assertEqual(
            r["dimensions"]["consistency"]["score"], 0.2)

    def test_bias_signal(self):
        r = self.evaluator.evaluate(
            self.entry(), "所有人都这样",
        )
        self.assertEqual(
            r["dimensions"]["bias_risk"]["score"], 0.2)

    def test_uncertainty_completeness(self):
        r = self.evaluator.evaluate(
            self.entry(uncertainty="有不确定性"),
        )
        self.assertEqual(
            r["dimensions"]["completeness"]["score"], 0.9)

    def test_high_confidence_consistency(self):
        r = self.evaluator.evaluate(self.entry(confidence=1.0))
        self.assertEqual(
            r["dimensions"]["consistency"]["score"], 1.0)

    def test_resources_evidence(self):
        r = self.evaluator.evaluate(self.entry())
        self.assertEqual(
            r["dimensions"]["evidence"]["score"], 0.7)

    def test_reason_explainable(self):
        r = self.evaluator.evaluate(self.entry())
        self.assertIn("推理评价", r["reason"])

    def test_disabled(self):
        evaluator = ReasoningEvaluator(enabled=False)
        r = evaluator.evaluate(self.entry())
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_stats(self):
        self.evaluator.evaluate(self.entry())
        self.assertEqual(self.evaluator.stats()[
            "evaluation_count"], 1)

    def test_clear(self):
        self.evaluator.evaluate(self.entry())
        n = self.evaluator.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.evaluator.stats()[
            "evaluation_count"], 0)


if __name__ == "__main__":
    unittest.main()
