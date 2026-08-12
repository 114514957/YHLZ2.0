"""
YHLZ Embodied AI V6.6 - 成长趋势分析与报告扩展单元测试 (Trend & Report)

覆盖:
    - GrowthTrendAnalysis: 四类指标 (反思/成长/身份/记忆)
    - 成长分 (加权) 与趋势档位
    - GrowthReport 扩展: growth_trend 段
    - 周期/停用/边界
"""
import threading
import unittest

from backend.embodied.companion.growth import (
    ANALYSIS_PERIODS,
    GROWTH_WEIGHTS,
    GrowthReport,
    GrowthTrendAnalysis,
    TREND_LEVELS,
    TrendAnalysisError,
)


def make_stats(**over):
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


class TestAnalysisStructure(unittest.TestCase):
    """分析结构"""

    def setUp(self):
        self.analysis = GrowthTrendAnalysis()

    def test_result_structure(self):
        r = self.analysis.analyze(make_stats())
        for key in ("analysis_id", "period", "growth_score",
                    "trend", "analysis", "mode"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")
        self.assertTrue(r["analysis_id"].startswith("ta_"))

    def test_period_default_day(self):
        r = self.analysis.analyze(make_stats())
        self.assertEqual(r["period"], "day")

    def test_period_week(self):
        r = self.analysis.analyze(make_stats(), period="week")
        self.assertEqual(r["period"], "week")

    def test_period_month(self):
        r = self.analysis.analyze(make_stats(), period="month")
        self.assertEqual(r["period"], "month")

    def test_invalid_period(self):
        with self.assertRaises(TrendAnalysisError):
            self.analysis.analyze(make_stats(), period="year")

    def test_periods_constant(self):
        self.assertEqual(ANALYSIS_PERIODS,
                         ["day", "week", "month"])

    def test_analysis_nine_metrics(self):
        r = self.analysis.analyze(make_stats())
        metrics = [a["metric"] for a in r["analysis"]]
        self.assertEqual(len(metrics), 9)
        expected = [
            "reflection_count", "reflection_frequency",
            "proposal_count", "approval_rate", "applied_count",
            "identity_change_attempt", "identity_guard_block",
            "experience_growth", "memory_quality",
        ]
        for m in expected:
            self.assertIn(m, metrics)

    def test_metric_structure(self):
        r = self.analysis.analyze(make_stats())
        item = r["analysis"][0]
        for key in ("metric", "category", "value", "unit",
                    "reason"):
            self.assertIn(key, item)


class TestMetrics(unittest.TestCase):
    """指标计算"""

    def setUp(self):
        self.analysis = GrowthTrendAnalysis()

    def test_reflection_count(self):
        r = self.analysis.analyze(make_stats(
            reflection={"reflection_count": 7},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "reflection_count")
        self.assertEqual(m["value"], 7)

    def test_reflection_frequency(self):
        r = self.analysis.analyze(make_stats(
            reflection={"reflection_count": 30},
            period_days=30,
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "reflection_frequency")
        self.assertEqual(m["value"], 1.0)

    def test_reflection_frequency_zero_days(self):
        r = self.analysis.analyze(make_stats(
            reflection={"reflection_count": 5},
            period_days=0,
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "reflection_frequency")
        self.assertEqual(m["value"], 0.0)

    def test_proposal_count(self):
        r = self.analysis.analyze(make_stats(
            proposal={"proposal_count": 12},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "proposal_count")
        self.assertEqual(m["value"], 12)

    def test_approval_rate(self):
        r = self.analysis.analyze(make_stats(
            evaluator={"evaluation_count": 10,
                       "approved_count": 7},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "approval_rate")
        self.assertEqual(m["value"], 0.7)

    def test_approval_rate_no_evaluations(self):
        r = self.analysis.analyze(make_stats(
            evaluator={"evaluation_count": 0,
                       "approved_count": 0},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "approval_rate")
        self.assertEqual(m["value"], 0.0)

    def test_applied_count(self):
        r = self.analysis.analyze(make_stats(
            applier={"applied_count": 5},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "applied_count")
        self.assertEqual(m["value"], 5)

    def test_identity_change_attempt(self):
        r = self.analysis.analyze(make_stats(
            identity_guard={"attempt_count": 4,
                            "intercept_count": 1},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "identity_change_attempt")
        self.assertEqual(m["value"], 4)

    def test_identity_guard_block(self):
        r = self.analysis.analyze(make_stats(
            identity_guard={"intercept_count": 3},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "identity_guard_block")
        self.assertEqual(m["value"], 3)

    def test_experience_growth(self):
        r = self.analysis.analyze(make_stats(
            experience={"total": 55},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "experience_growth")
        self.assertEqual(m["value"], 55)

    def test_memory_quality(self):
        r = self.analysis.analyze(make_stats(
            verification={"confirmed": 9, "rejected": 1},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "memory_quality")
        self.assertEqual(m["value"], 0.9)

    def test_memory_quality_no_verification(self):
        r = self.analysis.analyze(make_stats(
            verification={"confirmed": 0, "rejected": 0},
        ))
        m = next(a for a in r["analysis"]
                 if a["metric"] == "memory_quality")
        self.assertEqual(m["value"], 0.0)

    def test_categories(self):
        r = self.analysis.analyze(make_stats())
        cats = {a["category"] for a in r["analysis"]}
        self.assertEqual(cats,
                         {"Reflection", "Growth", "Identity",
                          "Memory"})


class TestGrowthScore(unittest.TestCase):
    """成长分"""

    def setUp(self):
        self.analysis = GrowthTrendAnalysis()

    def test_high_activity_score(self):
        r = self.analysis.analyze(make_stats(
            reflection={"reflection_count": 60},
            evaluator={"evaluation_count": 50,
                       "approved_count": 50},
            applier={"applied_count": 20},
            experience={"total": 200},
            verification={"confirmed": 50, "rejected": 0},
            period_days=30,
        ))
        self.assertGreaterEqual(r["growth_score"], 0.75)

    def test_low_activity_score(self):
        r = self.analysis.analyze(make_stats(
            reflection={"reflection_count": 0},
            evaluator={"evaluation_count": 0,
                       "approved_count": 0},
            applier={"applied_count": 0},
            experience={"total": 0},
            verification={"confirmed": 0, "rejected": 0},
            period_days=30,
        ))
        self.assertLessEqual(r["growth_score"], 0.4)

    def test_score_range(self):
        r = self.analysis.analyze(make_stats())
        self.assertGreaterEqual(r["growth_score"], 0.0)
        self.assertLessEqual(r["growth_score"], 1.0)

    def test_weights_sum(self):
        total = sum(GROWTH_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_weights_keys(self):
        for key in ("reflection", "approval_rate", "applied",
                    "identity", "experience", "memory_quality"):
            self.assertIn(key, GROWTH_WEIGHTS)

    def test_approval_rate_drives_score(self):
        low = self.analysis.analyze(make_stats(
            evaluator={"evaluation_count": 10,
                       "approved_count": 1},
        ))
        high = self.analysis.analyze(make_stats(
            evaluator={"evaluation_count": 10,
                       "approved_count": 10},
        ))
        self.assertGreater(high["growth_score"],
                           low["growth_score"])

    def test_applied_drives_score(self):
        low = self.analysis.analyze(make_stats(
            applier={"applied_count": 0},
        ))
        high = self.analysis.analyze(make_stats(
            applier={"applied_count": 15},
        ))
        self.assertGreater(high["growth_score"],
                           low["growth_score"])


class TestTrendLevel(unittest.TestCase):
    """趋势档位"""

    def setUp(self):
        self.analysis = GrowthTrendAnalysis()

    def test_accelerating(self):
        r = self.analysis.analyze(make_stats(
            reflection={"reflection_count": 60},
            evaluator={"evaluation_count": 50,
                       "approved_count": 50},
            applier={"applied_count": 20},
            experience={"total": 200},
            verification={"confirmed": 50, "rejected": 0},
            period_days=30,
        ))
        self.assertEqual(r["trend"], "accelerating")

    def test_decelerating(self):
        r = self.analysis.analyze(make_stats(
            reflection={"reflection_count": 0},
            evaluator={"evaluation_count": 0,
                       "approved_count": 0},
            applier={"applied_count": 0},
            experience={"total": 0},
            verification={"confirmed": 0, "rejected": 0},
            period_days=30,
        ))
        self.assertEqual(r["trend"], "decelerating")

    def test_stable(self):
        r = self.analysis.analyze(make_stats())
        self.assertEqual(r["trend"], "stable")

    def test_trend_levels_constant(self):
        self.assertEqual(TREND_LEVELS,
                         ["accelerating", "stable",
                          "decelerating"])


class TestDisabledAndEmpty(unittest.TestCase):
    """停用与空输入"""

    def test_disabled(self):
        analysis = GrowthTrendAnalysis(enabled=False)
        r = analysis.analyze(make_stats())
        self.assertEqual(r["growth_score"], 0.0)
        self.assertEqual(r["analysis"], [])
        self.assertEqual(r["trend"], "stable")

    def test_empty_input(self):
        r = self._fresh().analyze({})
        self.assertEqual(len(r["analysis"]), 9)
        self.assertEqual(r["growth_score"], 0.1)

    def test_partial_input(self):
        r = self._fresh().analyze({
            "reflection": {"reflection_count": 3},
        })
        self.assertEqual(len(r["analysis"]), 9)

    def _fresh(self):
        return GrowthTrendAnalysis()


class TestLifecycle(unittest.TestCase):
    """生命周期"""

    def setUp(self):
        self.analysis = GrowthTrendAnalysis()

    def test_latest(self):
        self.analysis.analyze(make_stats())
        latest = self.analysis.latest()
        self.assertEqual(latest["period"], "day")

    def test_latest_empty(self):
        self.assertIsNone(self.analysis.latest())

    def test_stats_count(self):
        self.analysis.analyze(make_stats())
        self.analysis.analyze(make_stats(), period="week")
        stats = self.analysis.stats()
        self.assertEqual(stats["analysis_count"], 2)
        self.assertEqual(stats["periods"], ANALYSIS_PERIODS)

    def test_clear(self):
        self.analysis.analyze(make_stats())
        n = self.analysis.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.analysis.stats()[
            "analysis_count"], 0)

    def test_stats_enabled(self):
        self.assertTrue(self.analysis.stats()["enabled"])


class TestThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_analyze(self):
        analysis = GrowthTrendAnalysis()
        errors = []

        def work():
            try:
                for _ in range(20):
                    analysis.analyze(make_stats())
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(analysis.stats()["analysis_count"],
                         80)


class TestGrowthReportExtension(unittest.TestCase):
    """GrowthReport 趋势扩展 (V6.6)"""

    def setUp(self):
        self.report = GrowthReport()

    def test_report_without_trend_input(self):
        r = self.report.generate({})
        self.assertIn("growth_trend", r)
        self.assertFalse(r["growth_trend"]["available"])

    def test_report_with_trend_input(self):
        r = self.report.generate({
            "growth_trend_input": {
                "period": "day",
                "proposal_count": 5,
                "evaluation_count": 4,
                "approved_count": 3,
                "applied_count": 1,
                "growth_score": 0.62,
            },
        })
        trend = r["growth_trend"]
        self.assertTrue(trend["available"])
        self.assertEqual(trend["period"], "day")
        self.assertEqual(trend["growth_score"], 0.62)

    def test_report_trend_analysis_three_items(self):
        r = self.report.generate({
            "growth_trend_input": {
                "proposal_count": 5,
                "evaluation_count": 4,
                "approved_count": 2,
                "applied_count": 1,
            },
        })
        metrics = [a["metric"]
                   for a in r["growth_trend"]["analysis"]]
        self.assertEqual(metrics, ["proposal_count",
                                   "approval_rate",
                                   "applied_count"])

    def test_report_trend_approval_rate(self):
        r = self.report.generate({
            "growth_trend_input": {
                "evaluation_count": 4,
                "approved_count": 3,
            },
        })
        item = next(
            a for a in r["growth_trend"]["analysis"]
            if a["metric"] == "approval_rate"
        )
        self.assertEqual(item["value"], 0.75)

    def test_report_trend_approval_rate_zero(self):
        r = self.report.generate({
            "growth_trend_input": {
                "evaluation_count": 0,
                "approved_count": 0,
            },
        })
        item = next(
            a for a in r["growth_trend"]["analysis"]
            if a["metric"] == "approval_rate"
        )
        self.assertEqual(item["value"], 0.0)

    def test_report_compat_other_sections(self):
        r = self.report.generate({
            "experience_stats": {"total": 5, "by_type": {}},
            "verification_stats": {"confirmed": 3},
        })
        self.assertIn("experience_growth", r)
        self.assertIn("summary", r)
        self.assertIn("growth_meanings", r)

    def test_report_latest(self):
        self.report.generate({"growth_trend_input": {
            "proposal_count": 1,
        }})
        latest = self.report.latest()
        self.assertTrue(latest["growth_trend"]["available"])

    def test_report_clear(self):
        self.report.generate({})
        n = self.report.clear()
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
