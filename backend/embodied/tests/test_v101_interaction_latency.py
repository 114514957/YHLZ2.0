"""
YHLZ Embodied AI V10.1 - 交互延迟追踪测试 (Latency Tracker)

覆盖:
    - 各阶段 mark/report
    - 统计 (avg/max/min/count)
    - 上限保护
    - 停用错误帧 / 参数校验
"""
import unittest

from backend.embodied.companion.interaction.latency_tracker import (
    LATENCY_STAGES,
    InteractionLatencyTracker,
    LatencyTrackerError,
)


class TestLatencyBasic(unittest.TestCase):
    """延迟追踪"""

    def setUp(self):
        self.t = InteractionLatencyTracker()

    def test_mark(self):
        r = self.t.mark("response", 300.2)
        self.assertTrue(r["ok"])
        self.assertEqual(r["stage"], "response")
        self.assertEqual(r["latency_ms"], 300.2)

    def test_report_stages(self):
        self.t.mark("user_input", 10)
        r = self.t.report()
        self.assertEqual(r["stages"]["user_input"]["count"], 1)
        self.assertEqual(r["stages"]["user_input"]["avg_ms"], 10.0)

    def test_report_empty(self):
        r = self.t.report()
        for stage in LATENCY_STAGES:
            self.assertEqual(r["stages"][stage]["count"], 0)

    def test_avg_calculation(self):
        self.t.mark("tts", 100)
        self.t.mark("tts", 300)
        r = self.t.report()
        self.assertEqual(r["stages"]["tts"]["count"], 2)
        self.assertEqual(r["stages"]["tts"]["avg_ms"], 200.0)
        self.assertEqual(r["stages"]["tts"]["max_ms"], 300.0)
        self.assertEqual(r["stages"]["tts"]["min_ms"], 100.0)

    def test_total_samples(self):
        self.t.mark("tool", 1)
        self.t.mark("tts", 2)
        self.t.mark("play", 3)
        r = self.t.report()
        self.assertEqual(r["total_samples"], 3)

    def test_all_stages_markable(self):
        for stage in LATENCY_STAGES:
            r = self.t.mark(stage, 5.0)
            self.assertTrue(r["ok"])
        r = self.t.report()
        self.assertEqual(r["total_samples"], len(LATENCY_STAGES))

    def test_invalid_stage(self):
        with self.assertRaises(LatencyTrackerError):
            self.t.mark("bad", 1.0)

    def test_negative_latency(self):
        with self.assertRaises(LatencyTrackerError):
            self.t.mark("tts", -1.0)


class TestLatencyBounded(unittest.TestCase):
    """上限"""

    def test_max_samples(self):
        t = InteractionLatencyTracker(max_samples=3)
        for i in range(10):
            t.mark("tts", float(i))
        r = t.report()
        self.assertEqual(r["stages"]["tts"]["count"], 3)

    def test_keeps_latest(self):
        t = InteractionLatencyTracker(max_samples=2)
        t.mark("tts", 1)
        t.mark("tts", 2)
        t.mark("tts", 3)
        r = t.report()
        self.assertEqual(r["stages"]["tts"]["min_ms"], 2.0)
        self.assertEqual(r["stages"]["tts"]["max_ms"], 3.0)

    def test_invalid_max(self):
        with self.assertRaises(LatencyTrackerError):
            InteractionLatencyTracker(max_samples=0)


class TestLatencyDisabled(unittest.TestCase):
    """停用"""

    def test_disabled_mark(self):
        t = InteractionLatencyTracker(enabled=False)
        r = t.mark("tts", 1.0)
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_disabled_report_ok(self):
        t = InteractionLatencyTracker(enabled=False)
        r = t.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertFalse(r["enabled"])

    def test_clear(self):
        self.t = InteractionLatencyTracker()
        self.t.mark("tts", 1)
        self.t.mark("tts", 2)
        self.assertEqual(self.t.clear(), 2)

    def test_stats_equals_report(self):
        t = InteractionLatencyTracker()
        t.mark("tts", 1)
        self.assertEqual(t.stats(), t.report())


# ── 生成式: 延迟统计矩阵 ───────────────────────────────────────
_LATENCY_CASES = [
    # (名称, 样本列表, 期望 avg)
    ("single", [100.0], 100.0),
    ("two", [100.0, 300.0], 200.0),
    ("three", [10.0, 20.0, 30.0], 20.0),
    ("zeros", [0.0, 0.0], 0.0),
    ("mixed", [1.0, 2.0, 3.0, 4.0], 2.5),
]


class TestGeneratedLatency(unittest.TestCase):
    """生成式: 平均延迟"""
    pass


for _i, (_name, _samples, _avg) in enumerate(_LATENCY_CASES):
    def _make(name=_name, samples=_samples, avg=_avg):
        def test_case(self):
            t = InteractionLatencyTracker()
            for s in samples:
                t.mark("response", s)
            r = t.report()
            self.assertEqual(
                r["stages"]["response"]["avg_ms"], avg,
            )
            self.assertEqual(
                r["stages"]["response"]["count"], len(samples),
            )
        test_case.__name__ = f"test_lat_{name}_{_i}"
        return test_case
    setattr(TestGeneratedLatency,
            f"test_lat_{_name}_{_i}", _make())


# ── 生成式: 阶段矩阵 ───────────────────────────────────────────
_STAGE_LIST_CASES = [
    ("user_input", "user_input"),
    ("understand", "understand"),
    ("context", "context"),
    ("tool", "tool"),
    ("response", "response"),
    ("tts", "tts"),
    ("play", "play"),
]


class TestGeneratedStages2(unittest.TestCase):
    """生成式: 阶段标记"""
    pass


for _i, (_name, _stage) in enumerate(_STAGE_LIST_CASES):
    def _make(name=_name, stage=_stage):
        def test_case(self):
            t = InteractionLatencyTracker()
            r = t.mark(stage, 10.0)
            self.assertTrue(r["ok"])
        test_case.__name__ = f"test_stage2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedStages2,
            f"test_stage2_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
