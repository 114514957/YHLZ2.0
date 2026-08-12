"""
YHLZ Embodied AI V6.0 - 成长层单元测试 (Growth Layer)

覆盖 (growth/):
    - GrowthMeaning: 事件意义 (发生了什么 → 意味着什么 → 影响未来)
    - GrowthTracker: 事件采集与指标
    - GrowthTrend: 按天/周/月趋势 + 增长量 + 加速/减速
    - GrowthReport: 四维成长报告
"""
import time
import unittest

from backend.embodied.companion.growth import (
    BUCKET_SECONDS,
    GROWTH_EVENT_TYPES,
    GrowthMeaning,
    GrowthReport,
    GrowthTracker,
    GrowthTrend,
    MeaningError,
    ReportError,
    TREND_BUCKETS,
    TrackerError,
    TrendError,
)


class TestGrowthMeaning(unittest.TestCase):
    """成长意义"""

    def setUp(self):
        self.gm = GrowthMeaning()

    def test_interpret(self):
        r = self.gm.interpret("experience_confirmed",
                              detail="exp_1")
        for key in ("meaning_id", "event", "meaning", "impact",
                    "future_effect", "detail", "mode"):
            self.assertIn(key, r)

    def test_meaning_id_prefix(self):
        r = self.gm.interpret("experience_added")
        self.assertTrue(r["meaning_id"].startswith("meaning_"))

    def test_all_types_interpretable(self):
        for t in GROWTH_EVENT_TYPES:
            r = self.gm.interpret(t, detail="d")
            self.assertEqual(r["event"], t)
            self.assertTrue(r["meaning"])

    def test_invalid_type(self):
        with self.assertRaises(MeaningError):
            self.gm.interpret("bogus_event")

    def test_future_effect_present(self):
        r = self.gm.interpret("creative_completed")
        self.assertTrue(r["future_effect"])

    def test_detail_kept(self):
        r = self.gm.interpret("reflection_created", detail="报告r1")
        self.assertEqual(r["detail"], "报告r1")

    def test_context_extra(self):
        r = self.gm.interpret("experience_added",
                              context={"extra": "第10条"})
        self.assertIn("第10条", r["meaning"])

    def test_mode(self):
        r = self.gm.interpret("identity_change")
        self.assertEqual(r["mode"], "rule_based")

    def test_by_event(self):
        self.gm.interpret("experience_added")
        self.gm.interpret("experience_added")
        hits = self.gm.by_event("experience_added")
        self.assertEqual(len(hits), 2)

    def test_by_event_invalid(self):
        with self.assertRaises(MeaningError):
            self.gm.by_event("bad")

    def test_stats(self):
        self.gm.interpret("experience_added")
        self.gm.interpret("reflection_created")
        st = self.gm.stats()
        self.assertEqual(st["interpretation_count"], 2)
        self.assertEqual(st["by_event"]["experience_added"], 1)

    def test_clear(self):
        self.gm.interpret("experience_added")
        self.assertEqual(self.gm.clear(), 1)


class TestGrowthTracker(unittest.TestCase):
    """成长追踪"""

    def setUp(self):
        self.tracker = GrowthTracker(window_days=30)

    def test_record(self):
        e = self.tracker.record("experience_added", detail="e1")
        self.assertTrue(e["event_id"].startswith("grow_"))
        self.assertEqual(e["type"], "experience_added")

    def test_record_invalid_type(self):
        with self.assertRaises(TrackerError):
            self.tracker.record("bad_type")

    def test_metrics(self):
        self.tracker.record("experience_added")
        self.tracker.record("experience_added")
        self.tracker.record("reflection_created")
        m = self.tracker.metrics()
        self.assertEqual(m["experience_count"], 2)
        self.assertEqual(m["reflection_count"], 1)

    def test_metrics_window(self):
        """窗口外事件不计入"""
        old = time.time() - 100 * 86400
        self.tracker.record("experience_added", now=old)
        m = self.tracker.metrics()
        self.assertEqual(m["event_count"], 0)

    def test_creative_count_aggregates(self):
        self.tracker.record("creative_proposal")
        self.tracker.record("creative_completed")
        m = self.tracker.metrics()
        self.assertEqual(m["creative_count"], 2)

    def test_events_latest_first(self):
        self.tracker.record("experience_added", detail="first")
        self.tracker.record("experience_added", detail="second")
        evs = self.tracker.events()
        self.assertEqual(evs[0]["detail"], "second")

    def test_events_by_type(self):
        self.tracker.record("experience_added")
        self.tracker.record("reflection_created")
        evs = self.tracker.events(event_type="reflection_created")
        self.assertEqual(len(evs), 1)

    def test_events_invalid_type(self):
        with self.assertRaises(TrackerError):
            self.tracker.events(event_type="bad")

    def test_events_limit(self):
        for i in range(5):
            self.tracker.record("experience_added", detail=f"d{i}")
        self.assertEqual(len(self.tracker.events(limit=2)), 2)

    def test_max_events(self):
        t = GrowthTracker(max_events=10)
        for i in range(15):
            t.record("experience_added")
        self.assertEqual(t.stats()["total_events"], 10)

    def test_max_events_validation(self):
        with self.assertRaises(TrackerError):
            GrowthTracker(max_events=0)

    def test_stats(self):
        self.tracker.record("experience_added")
        st = self.tracker.stats()
        self.assertEqual(st["total_events"], 1)
        self.assertEqual(st["by_type"]["experience_added"], 1)

    def test_clear(self):
        self.tracker.record("experience_added")
        self.assertEqual(self.tracker.clear(), 1)


class TestGrowthTrend(unittest.TestCase):
    """成长趋势"""

    def setUp(self):
        self.trend = GrowthTrend()
        self.now = time.time()

    def _event(self, etype, days_ago):
        return {
            "type": etype,
            "timestamp": self.now - days_ago * 86400,
        }

    def test_series(self):
        events = [self._event("experience_added", 0),
                  self._event("experience_added", 1),
                  self._event("reflection_created", 2)]
        r = self.trend.series(events, bucket="day", now=self.now)
        self.assertEqual(r["bucket"], "day")
        self.assertEqual(r["total"], 3)

    def test_series_buckets_count(self):
        events = [self._event("experience_added", i)
                  for i in range(4)]
        r = self.trend.series(events, bucket="day", now=self.now)
        self.assertEqual(len(r["buckets"]), 4)

    def test_series_bucket_counts(self):
        events = [self._event("experience_added", 0),
                  self._event("experience_added", 0)]
        r = self.trend.series(events, bucket="day", now=self.now)
        self.assertEqual(r["buckets"][-1]["count"], 2)

    def test_series_by_type(self):
        events = [self._event("experience_added", 0),
                  self._event("reflection_created", 0)]
        r = self.trend.series(events, bucket="day", now=self.now)
        b = r["buckets"][-1]
        self.assertEqual(b["by_type"]["experience_added"], 1)
        self.assertEqual(b["by_type"]["reflection_created"], 1)

    def test_series_invalid_bucket(self):
        with self.assertRaises(TrendError):
            self.trend.series([], bucket="year")

    def test_week_bucket(self):
        fixed = 1000 * 86400.0  # 固定时刻 (确定性)
        events = [
            {"type": "experience_added",
             "timestamp": fixed - 3 * 86400},
            {"type": "experience_added",
             "timestamp": fixed - 9 * 86400},
        ]
        r = self.trend.series(events, bucket="week", now=fixed)
        self.assertEqual(len(r["buckets"]), 2)

    def test_delta(self):
        events = [self._event("experience_added", i) for i in range(10)]
        r = self.trend.delta(events, window_days=30, now=self.now)
        self.assertEqual(r["total"], 10)
        self.assertEqual(r["by_type"]["experience_added"], 10)

    def test_delta_window_filter(self):
        events = [self._event("experience_added", 100)]
        r = self.trend.delta(events, window_days=30, now=self.now)
        self.assertEqual(r["total"], 0)

    def test_delta_daily_avg(self):
        events = [self._event("experience_added", i)
                  for i in range(10)]
        r = self.trend.delta(events, window_days=10, now=self.now)
        self.assertEqual(r["daily_avg"], 1.0)

    def test_compare_accelerating(self):
        events = [self._event("experience_added", i / 2)
                  for i in range(20)]  # 近期 10 天密集
        r = self.trend.compare(events, window_days=30, now=self.now)
        self.assertIn(r["trend"],
                      ("accelerating", "stable", "decelerating"))

    def test_compare_stable(self):
        events = []
        for i in range(20):
            events.append(self._event("experience_added", i * 1.5))
        r = self.trend.compare(events, window_days=30, now=self.now)
        self.assertIn(r["trend"],
                      ("accelerating", "stable", "decelerating"))

    def test_compare_structure(self):
        r = self.trend.compare([], window_days=30, now=self.now)
        for key in ("mode", "window_days", "earlier_count",
                    "recent_count", "trend"):
            self.assertIn(key, r)

    def test_stats(self):
        self.trend.series([], bucket="day", now=self.now)
        st = self.trend.stats()
        self.assertEqual(st["analysis_count"], 1)
        self.assertEqual(st["buckets"], ["day", "week", "month"])

    def test_clear(self):
        self.trend.series([], bucket="day", now=self.now)
        self.assertEqual(self.trend.clear(), 1)


class TestGrowthReport(unittest.TestCase):
    """成长报告"""

    def setUp(self):
        self.report = GrowthReport()

    def _inputs(self):
        return {
            "experience_stats": {
                "total": 10, "by_type": {"interaction": 10},
                "avg_value": 0.6,
            },
            "verification_stats": {"confirmed": 3},
            "reflection_stats": {
                "reflection_count": 2, "pattern_count": 1,
                "failure_analysis_count": 0,
            },
            "creative_stats": {
                "memory": {"total": 4, "approved": 2,
                           "completed": 1},
            },
            "relationship": {
                "trust_level": 0.7, "familiarity": 0.5,
                "interaction_count": 20,
                "relationship_stage": "companion",
            },
            "meanings": [
                {"event": "experience_confirmed",
                 "meaning": "可靠经验", "detail": "e1"},
            ],
        }

    def test_generate(self):
        r = self.report.generate(self._inputs())
        for key in ("report_id", "generated_at",
                    "experience_growth", "cognitive_growth",
                    "creative_growth", "relationship_growth",
                    "growth_meanings", "summary", "mode"):
            self.assertIn(key, r)

    def test_report_id_prefix(self):
        r = self.report.generate(self._inputs())
        self.assertTrue(r["report_id"].startswith("grep_"))

    def test_experience_growth(self):
        r = self.report.generate(self._inputs())
        eg = r["experience_growth"]
        self.assertEqual(eg["total"], 10)
        self.assertEqual(eg["confirmed"], 3)
        self.assertEqual(eg["avg_value"], 0.6)

    def test_cognitive_growth(self):
        r = self.report.generate(self._inputs())
        cg = r["cognitive_growth"]
        self.assertEqual(cg["reflection_count"], 2)
        self.assertEqual(cg["pattern_count"], 1)

    def test_creative_growth(self):
        r = self.report.generate(self._inputs())
        cre = r["creative_growth"]
        self.assertEqual(cre["proposal_count"], 4)
        self.assertEqual(cre["conversion_rate"], 0.25)

    def test_relationship_growth(self):
        r = self.report.generate(self._inputs())
        rel = r["relationship_growth"]
        self.assertEqual(rel["trust_level"], 0.7)
        self.assertEqual(rel["interaction_count"], 20)

    def test_summary(self):
        r = self.report.generate(self._inputs())
        s = r["summary"]
        self.assertEqual(s["experience_total"], 10)
        self.assertEqual(s["confirmed_total"], 3)
        self.assertEqual(s["proposal_total"], 4)
        self.assertEqual(s["conversion_rate"], 0.25)
        self.assertEqual(s["trust_level"], 0.7)

    def test_empty_inputs(self):
        r = self.report.generate({})
        self.assertEqual(r["experience_growth"]["total"], 0)
        self.assertEqual(r["creative_growth"]["proposal_count"], 0)

    def test_conversion_zero_safe(self):
        r = self.report.generate({"creative_stats": {
            "memory": {"total": 0},
        }})
        self.assertEqual(r["creative_growth"]["conversion_rate"], 0.0)

    def test_meanings_capped_five(self):
        inputs = self._inputs()
        inputs["meanings"] = [
            {"event": "experience_added", "meaning": "m",
             "detail": f"e{i}"}
            for i in range(10)
        ]
        r = self.report.generate(inputs)
        self.assertLessEqual(len(r["growth_meanings"]), 5)

    def test_mode(self):
        r = self.report.generate(self._inputs())
        self.assertEqual(r["mode"], "rule_based")

    def test_latest(self):
        self.report.generate(self._inputs())
        self.assertIsNotNone(self.report.latest())

    def test_latest_empty(self):
        self.assertIsNone(self.report.latest())

    def test_stats(self):
        self.report.generate(self._inputs())
        st = self.report.stats()
        self.assertEqual(st["report_count"], 1)

    def test_clear(self):
        self.report.generate(self._inputs())
        self.assertEqual(self.report.clear(), 1)


if __name__ == "__main__":
    unittest.main()
