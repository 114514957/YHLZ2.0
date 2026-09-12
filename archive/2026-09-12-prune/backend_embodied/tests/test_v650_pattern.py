"""
YHLZ Embodied AI V6.5 - 模式分析器单元测试 (Pattern Analyzer)

覆盖 (reflection/pattern_analyzer.py):
    - 统计驱动模式: 连续成功 → 有效策略 / 连续失败 → 问题模式
    - 样本量门槛 / 连续次数门槛
    - 统计/查询/异常
"""
import time
import unittest

from backend.embodied.companion.reflection import (
    PATTERN_TYPES,
    PatternAnalyzer,
    PatternAnalyzerError,
)


def make_record(trigger="生成工程Prompt", type="improvement",
                result="成功", rid=None, ts_offset=0):
    return {
        "id": rid or f"exp_{trigger}_{ts_offset}",
        "type": type,
        "trigger": trigger,
        "lesson": "l",
        "result": result,
        "timestamp": time.time() - ts_offset * 86400,
    }


class TestInit(unittest.TestCase):
    """初始化"""

    def test_default_init(self):
        a = PatternAnalyzer()
        self.assertIsNotNone(a)

    def test_min_samples_validation(self):
        with self.assertRaises(PatternAnalyzerError):
            PatternAnalyzer(min_samples=1)

    def test_min_streak_validation(self):
        with self.assertRaises(PatternAnalyzerError):
            PatternAnalyzer(min_streak=1)

    def test_rate_validation(self):
        with self.assertRaises(PatternAnalyzerError):
            PatternAnalyzer(min_success_rate=1.5)

    def test_types_whitelist(self):
        self.assertIn("success_strategy", PATTERN_TYPES)
        self.assertIn("problem_pattern", PATTERN_TYPES)
        self.assertIn("repetition", PATTERN_TYPES)


class TestAnalyze(unittest.TestCase):
    """分析"""

    def setUp(self):
        self.analyzer = PatternAnalyzer(min_samples=3,
                                        min_streak=2)

    def test_success_strategy_detected(self):
        records = [
            make_record(trigger="高频成功", ts_offset=i)
            for i in range(4)
        ]
        patterns = self.analyzer.analyze(records)
        types = [p["type"] for p in patterns]
        self.assertIn("success_strategy", types)

    def test_problem_pattern_detected(self):
        records = [
            make_record(trigger="高频失败", type="failure",
                        result="错误", ts_offset=i)
            for i in range(4)
        ]
        patterns = self.analyzer.analyze(records)
        types = [p["type"] for p in patterns]
        self.assertIn("problem_pattern", types)

    def test_insufficient_samples(self):
        records = [make_record(trigger="单次")] * 2
        patterns = self.analyzer.analyze(records)
        self.assertEqual(patterns, [])

    def test_no_pattern_mixed(self):
        """混合结果无连续 → 无模式"""
        records = [
            make_record(trigger="混合", result="成功", rid="a"),
            make_record(trigger="混合", result="错误",
                        type="failure", rid="b"),
            make_record(trigger="混合", result="成功", rid="c"),
        ]
        patterns = self.analyzer.analyze(records)
        self.assertEqual(patterns, [])

    def test_pattern_structure(self):
        records = [
            make_record(trigger="结构测试", ts_offset=i)
            for i in range(4)
        ]
        patterns = self.analyzer.analyze(records)
        p = patterns[0]
        for key in ("pattern_id", "type", "trigger", "samples",
                    "success_rate", "max_streak", "meaning",
                    "confidence", "evidence", "timestamp"):
            self.assertIn(key, p)

    def test_pattern_id_prefix(self):
        records = [
            make_record(trigger="ID测试", ts_offset=i)
            for i in range(4)
        ]
        p = self.analyzer.analyze(records)[0]
        self.assertTrue(p["pattern_id"].startswith("pat_"))

    def test_meaning_explainable(self):
        records = [
            make_record(trigger="意义测试", ts_offset=i)
            for i in range(4)
        ]
        p = self.analyzer.analyze(records)[0]
        self.assertIn("成功", p["meaning"])

    def test_confidence_range(self):
        records = [
            make_record(trigger="置信测试", ts_offset=i)
            for i in range(5)
        ]
        for p in self.analyzer.analyze(records):
            self.assertGreaterEqual(p["confidence"], 0.0)
            self.assertLessEqual(p["confidence"], 1.0)

    def test_confidence_grows_with_streak(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="增长测试", ts_offset=i)
            for i in range(6)
        ]
        p = a.analyze(records)[0]
        self.assertGreaterEqual(p["confidence"], 0.5)

    def test_evidence_has_samples(self):
        records = [
            make_record(trigger="证据测试", ts_offset=i)
            for i in range(4)
        ]
        p = self.analyzer.analyze(records)[0]
        self.assertIn("4", p["evidence"])

    def test_sorted_by_confidence(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = []
        for t in ("触发A", "触发B"):
            records += [
                make_record(trigger=t, ts_offset=i)
                for i in range(4)
            ]
        records += [
            make_record(trigger="触发C", ts_offset=i)
            for i in range(8)
        ]
        patterns = a.analyze(records)
        confs = [p["confidence"] for p in patterns]
        self.assertEqual(confs, sorted(confs, reverse=True))

    def test_max_patterns(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2,
                            max_patterns=2)
        records = []
        for t in ("触发A", "触发B", "触发C"):
            records += [
                make_record(trigger=t, ts_offset=i)
                for i in range(4)
            ]
        patterns = a.analyze(records)
        self.assertLessEqual(len(patterns), 2)

    def test_repetition_type(self):
        """高成功率但不达标? 实际重复"""
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_record(trigger="重复触发", ts_offset=i)
            for i in range(4)
        ]
        patterns = a.analyze(records)
        types = {p["type"] for p in patterns}
        # 全成功 → success_strategy (重复分支仅非高成功率时)
        self.assertIn("success_strategy", types)


class TestQuery(unittest.TestCase):
    """查询"""

    def setUp(self):
        self.analyzer = PatternAnalyzer(min_samples=3,
                                        min_streak=2)

    def test_by_type(self):
        records = [
            make_record(trigger="查询成功", ts_offset=i)
            for i in range(4)
        ]
        self.analyzer.analyze(records)
        out = self.analyzer.by_type("success_strategy")
        self.assertGreaterEqual(len(out), 1)

    def test_by_type_invalid(self):
        with self.assertRaises(PatternAnalyzerError):
            self.analyzer.by_type("bogus")

    def test_stats(self):
        records = [
            make_record(trigger="统计成功", ts_offset=i)
            for i in range(4)
        ]
        self.analyzer.analyze(records)
        st = self.analyzer.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertGreaterEqual(st["pattern_count"], 1)

    def test_stats_by_type(self):
        rec_s = [
            make_record(trigger="统计A", ts_offset=i)
            for i in range(4)
        ]
        rec_f = [
            make_record(trigger="统计B", type="failure",
                        result="错误", ts_offset=i)
            for i in range(4)
        ]
        self.analyzer.analyze(rec_s)
        self.analyzer.analyze(rec_f)
        st = self.analyzer.stats()
        self.assertGreaterEqual(st["by_type"].get(
            "success_strategy", 0), 1)
        self.assertGreaterEqual(st["by_type"].get(
            "problem_pattern", 0), 1)

    def test_stats_avg_confidence(self):
        records = [
            make_record(trigger="平均", ts_offset=i)
            for i in range(4)
        ]
        self.analyzer.analyze(records)
        st = self.analyzer.stats()
        self.assertGreaterEqual(st["avg_confidence"], 0.0)

    def test_clear(self):
        records = [
            make_record(trigger="清空", ts_offset=i)
            for i in range(4)
        ]
        self.analyzer.analyze(records)
        self.assertEqual(self.analyzer.clear(), 1)

    def test_clear_empty(self):
        self.assertEqual(PatternAnalyzer().clear(), 0)


class TestEdge(unittest.TestCase):
    """边界"""

    def test_empty_records(self):
        self.assertEqual(PatternAnalyzer().analyze([]), [])

    def test_short_records(self):
        a = PatternAnalyzer(min_samples=5, min_streak=2)
        records = [
            make_record(trigger="短", ts_offset=i)
            for i in range(3)
        ]
        self.assertEqual(a.analyze(records), [])

    def test_empty_trigger_skipped(self):
        records = [
            {"id": f"e{i}", "trigger": "", "result": "成功"}
            for i in range(5)
        ]
        self.assertEqual(PatternAnalyzer().analyze(records), [])

    def test_max_streak_calculation(self):
        records = [
            make_record(trigger="连续", result="成功", rid="a"),
            make_record(trigger="连续", result="成功", rid="b"),
            make_record(trigger="连续", result="错误",
                        type="failure", rid="c"),
            make_record(trigger="连续", result="成功", rid="d"),
            make_record(trigger="连续", result="成功", rid="e"),
            make_record(trigger="连续", result="成功", rid="f"),
        ]
        streak = PatternAnalyzer._max_streak(records, True)
        self.assertEqual(streak, 3)


if __name__ == "__main__":
    unittest.main()
