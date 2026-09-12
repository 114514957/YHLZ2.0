"""
YHLZ Embodied AI V4.4 - 趋势统计系统单元测试 (Trend Stats)

覆盖:
    - 趋势统计: overall / by_scene / by_goal_type (success/failure/duration)
    - 滚动窗口: 每维度最近 N 次 (window=10)
    - 数据源: GoalTraceStore 轨迹
    - 目标类型推断: 关键字规则表 (pick/move/place/inspect/scan)
    - 边界: 空数据 / 窗口校验
"""
import unittest

from backend.embodied.replay import GoalTrace
from backend.embodied.strategy.trends import (
    GOAL_TYPES,
    TrendStats,
    TrendStatsError,
    infer_goal_type,
)


def make_trace(goal_id, environment, goal=None, plan=None, success=True,
               duration_ms=100.0, failures=0):
    return GoalTrace(
        goal_id=goal_id,
        goal=goal or {"description": "x", "intent": "", "constraints": {}},
        plan=plan or [],
        success=success,
        environment=environment,
        duration_ms=duration_ms,
        failures=failures,
    )


class TestInferGoalType(unittest.TestCase):

    def test_explicit_goal_type(self):
        self.assertEqual(
            infer_goal_type({"goal_type": "pick", "description": "x"}), "pick"
        )

    def test_pick_keywords(self):
        for kw in ("pick", "拾取", "拿起", "抓取"):
            self.assertEqual(
                infer_goal_type({"description": f"去{kw}台灯"}), "pick"
            )

    def test_inspect_keywords(self):
        for kw in ("检查", "查看", "inspect"):
            self.assertEqual(
                infer_goal_type({"description": f"任务: {kw}台灯"}), "inspect"
            )

    def test_scan_keywords(self):
        for kw in ("扫描", "探索", "scan"):
            self.assertEqual(
                infer_goal_type({"description": f"去{kw}房间"}), "scan"
            )

    def test_fallback_to_plan_first_action(self):
        self.assertEqual(
            infer_goal_type({"description": "随便做点什么"}, [{"action_type": "move"}]),
            "move",
        )

    def test_unknown_returns_empty(self):
        self.assertEqual(infer_goal_type({}, []), "")
        self.assertEqual(infer_goal_type(None, None), "")

    def test_goal_types_whitelist(self):
        self.assertEqual(GOAL_TYPES, ["pick", "move", "place", "inspect", "scan"])


class TestTrendStats(unittest.TestCase):

    def setUp(self):
        self.trends = TrendStats(window=10)

    def test_empty(self):
        r = self.trends.trend_stats([])
        self.assertEqual(r["overall"]["total"], 0)
        self.assertEqual(r["by_scene"], {})
        self.assertEqual(r["by_goal_type"], {})
        self.assertEqual(r["mode"], "rule_based")

    def test_overall_success_rate(self):
        traces = [
            make_trace("a", "room", success=True),
            make_trace("b", "room", success=True),
            make_trace("c", "room", success=False),
        ]
        r = self.trends.trend_stats(traces)
        self.assertEqual(r["overall"]["total"], 3)
        self.assertEqual(r["overall"]["success"], 2)
        self.assertEqual(r["overall"]["failure"], 1)
        self.assertEqual(r["overall"]["success_rate"], 0.6667)

    def test_by_scene(self):
        traces = [
            make_trace("a", "room", success=True),
            make_trace("b", "room", success=False),
            make_trace("c", "warehouse", success=True),
        ]
        r = self.trends.trend_stats(traces)
        self.assertIn("room", r["by_scene"])
        self.assertIn("warehouse", r["by_scene"])
        self.assertEqual(r["by_scene"]["room"]["success"], 1)
        self.assertEqual(r["by_scene"]["room"]["failure"], 1)
        self.assertEqual(r["by_scene"]["warehouse"]["success"], 1)

    def test_by_goal_type(self):
        traces = [
            make_trace("a", "room", goal={"description": "拾取台灯"}, success=True),
            make_trace("b", "room", goal={"description": "拾取箱子"}, success=False),
            make_trace("c", "room", goal={"description": "检查台灯"}, success=True),
        ]
        r = self.trends.trend_stats(traces)
        self.assertIn("pick", r["by_goal_type"])
        self.assertIn("inspect", r["by_goal_type"])
        self.assertEqual(r["by_goal_type"]["pick"]["success"], 1)
        self.assertEqual(r["by_goal_type"]["pick"]["failure"], 1)

    def test_avg_duration(self):
        traces = [
            make_trace("a", "room", duration_ms=200.0),
            make_trace("b", "room", duration_ms=400.0),
        ]
        r = self.trends.trend_stats(traces)
        self.assertEqual(r["overall"]["avg_duration_ms"], 300.0)

    def test_duration_zero_excluded(self):
        traces = [
            make_trace("a", "room", duration_ms=0.0),
            make_trace("b", "room", duration_ms=100.0),
        ]
        r = self.trends.trend_stats(traces)
        self.assertEqual(r["overall"]["avg_duration_ms"], 100.0)

    def test_rolling_window_scene(self):
        """每场景最近 10 次滚动"""
        traces = [
            make_trace(f"r{i}", "room", success=(i % 2 == 0))
            for i in range(15)
        ]
        r = self.trends.trend_stats(traces)
        room = r["by_scene"]["room"]
        self.assertEqual(room["total"], 10)  # 15 条只取最近 10

    def test_rolling_window_goal_type(self):
        traces = [
            make_trace(f"p{i}", "room", goal={"description": "拾取台灯"},
                       success=(i % 2 == 0))
            for i in range(12)
        ]
        r = self.trends.trend_stats(traces)
        self.assertEqual(r["by_goal_type"]["pick"]["total"], 10)

    def test_window_custom(self):
        trends = TrendStats(window=3)
        traces = [
            make_trace(f"a{i}", "room", success=True) for i in range(6)
        ]
        r = trends.trend_stats(traces)
        self.assertEqual(r["overall"]["total"], 3)

    def test_window_zero_raises(self):
        with self.assertRaises(TrendStatsError):
            TrendStats(window=0)

    def test_scene_success_rate(self):
        traces = [
            make_trace("a", "room", success=True),
            make_trace("b", "warehouse", success=False),
        ]
        r = self.trends.scene_success_rate(traces, "room")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["success_rate"], 1.0)

    def test_goal_type_success_rate(self):
        traces = [
            make_trace("a", "room", goal={"description": "拾取台灯"}, success=True),
            make_trace("b", "room", goal={"description": "检查台灯"}, success=False),
        ]
        r = self.trends.goal_type_success_rate(traces, "pick")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["success_rate"], 1.0)

    def test_goal_type_success_rate_unknown(self):
        r = self.trends.goal_type_success_rate([], "nope")
        self.assertEqual(r["total"], 0)

    def test_total_failures(self):
        traces = [
            make_trace("a", "room", success=True, failures=0),
            make_trace("b", "room", success=False, failures=2),
        ]
        r = self.trends.trend_stats(traces)
        self.assertEqual(r["overall"]["total_failures"], 2)


if __name__ == "__main__":
    unittest.main()
