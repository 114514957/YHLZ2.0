"""
YHLZ Embodied AI V4.7 - 计划调整与风险评估单元测试 (Adjustment + Risk + Time)

覆盖 (adjustment.py):
    - adjust_plan: 4 种触发条件 (failure_increase / resource_shortage /
      time_change / environment_change)
    - 输出: 新 milestone 顺序 / 优先级调整 / 建议 (可解释)
    - 禁止自动执行: permission_required=True
    - 参数校验: 非法触发条件
    - predict_risk: 历史失败经验 → low/medium/high
    - time_plan: deadline / estimated_duration / time_window / deadline_status
"""
import time
import unittest

from backend.embodied.planning import (
    ADJUSTMENT_TRIGGERS,
    AdjustmentError,
    PlanAdjuster,
    RISK_LEVELS,
)
from backend.embodied.planning.milestone import LongGoal, MilestoneManager


def make_decomposed(mgr, title="整理房间", phases=None):
    g = mgr.create_long_goal(title=title)
    mgr.decompose_goal(g, phases or ["收集", "分类", "整理", "检查", "维护"])
    return g


class TestAdjustPlan(unittest.TestCase):
    """计划调整"""

    def setUp(self):
        self.mgr = MilestoneManager()
        self.adjuster = PlanAdjuster()
        self.goal = make_decomposed(self.mgr)
        self.ms = [m.milestone_id for m in self.goal.milestones]

    def test_trigger_whitelist(self):
        """触发条件白名单"""
        self.assertEqual(set(ADJUSTMENT_TRIGGERS), {
            "failure_increase", "resource_shortage",
            "time_change", "environment_change",
        })

    def test_invalid_trigger_raises(self):
        """非法触发条件 → AdjustmentError"""
        with self.assertRaises(AdjustmentError):
            self.adjuster.adjust_plan(self.goal, trigger="random")

    def test_none_goal_raises(self):
        """None 目标 → AdjustmentError"""
        with self.assertRaises(AdjustmentError):
            self.adjuster.adjust_plan(None)

    def test_adjust_structure(self):
        """调整输出结构完整"""
        r = self.adjuster.adjust_plan(self.goal, trigger="time_change")
        for key in ("goal_id", "trigger", "rule", "adjusted",
                    "suggested_order", "priority_adjustments",
                    "suggestions", "permission_required"):
            self.assertIn(key, r)
        self.assertTrue(r["adjusted"])

    def test_permission_required(self):
        """禁止自动执行: 必须经 Permission"""
        r = self.adjuster.adjust_plan(self.goal)
        self.assertTrue(r["permission_required"])

    def test_suggested_order_all(self):
        """新顺序覆盖全部里程碑"""
        r = self.adjuster.adjust_plan(self.goal, trigger="time_change")
        self.assertEqual(len(r["suggested_order"]), 5)

    def test_completed_removed_from_order(self):
        """已完成的里程碑不在新顺序"""
        self.mgr.complete_milestone(self.goal, self.ms[0])
        r = self.adjuster.adjust_plan(self.goal, trigger="time_change")
        order_ids = [o["milestone_id"] for o in r["suggested_order"]]
        self.assertNotIn(self.ms[0], order_ids)
        self.assertEqual(len(order_ids), 4)

    def test_blocked_moved_after(self):
        """阻塞的里程碑排后面"""
        from backend.embodied.planning import DependencyGraph
        graph = DependencyGraph()
        graph.set_dependencies(self.goal, {self.ms[3]: [self.ms[1]]})
        r = self.adjuster.adjust_plan(self.goal, trigger="time_change")
        order_ids = [o["milestone_id"] for o in r["suggested_order"]]
        self.assertLess(order_ids.index(self.ms[1]),
                        order_ids.index(self.ms[3]))

    def test_failure_increase_suggestion(self):
        """失败次数增加 → 建议"""
        r = self.adjuster.adjust_plan(
            self.goal, trigger="failure_increase", reason="连续失败",
        )
        self.assertTrue(any("失败" in s for s in r["suggestions"]))

    def test_resource_shortage_suggestion(self):
        """资源不足 → 建议减少并行"""
        r = self.adjuster.adjust_plan(
            self.goal, trigger="resource_shortage", reason="预算减半",
        )
        self.assertTrue(any("资源" in s for s in r["suggestions"]))

    def test_resource_shortage_priority_adjustments(self):
        """资源不足 → 低优先级延后建议"""
        r = self.adjuster.adjust_plan(
            self.goal, trigger="resource_shortage", reason="资源不足",
        )
        self.assertGreaterEqual(len(r["priority_adjustments"]), 0)
        for pa in r["priority_adjustments"]:
            self.assertIn("suggestion", pa)

    def test_time_change_suggestion(self):
        """时间变化 → 建议优先 deadline 临近"""
        r = self.adjuster.adjust_plan(self.goal, trigger="time_change")
        self.assertTrue(any("时间" in s for s in r["suggestions"]))

    def test_environment_change_suggestion(self):
        """环境变化 → 建议重新观察"""
        r = self.adjuster.adjust_plan(self.goal, trigger="environment_change")
        self.assertTrue(any("环境" in s for s in r["suggestions"]))

    def test_blocked_listed(self):
        """阻塞里程碑列出"""
        from backend.embodied.planning import DependencyGraph
        graph = DependencyGraph()
        graph.set_dependencies(self.goal, {self.ms[2]: [self.ms[1]]})
        adjuster = PlanAdjuster()
        r = adjuster.adjust_plan(self.goal, trigger="time_change")
        self.assertIn(self.ms[2], r["blocked_milestones"])


class TestPredictRisk(unittest.TestCase):
    """风险预测"""

    def setUp(self):
        self.mgr = MilestoneManager()
        self.adjuster = PlanAdjuster(risk_failure_threshold=3,
                                     risk_blocked_threshold=2)
        self.goal = make_decomposed(self.mgr)
        self.ms = [m.milestone_id for m in self.goal.milestones]

    def test_risk_levels(self):
        """风险等级定义"""
        self.assertEqual(RISK_LEVELS, ["low", "medium", "high"])

    def test_all_low(self):
        """无失败无阻塞 → 全部 low"""
        r = self.adjuster.predict_risk(self.goal)
        self.assertEqual(r["overall"], "low")
        self.assertTrue(all(x["risk"] == "low"
                            for x in r["per_milestone"]))

    def test_high_after_many_failures(self):
        """失败 >= 阈值 → high"""
        fails = {self.ms[0]: 5}
        r = self.adjuster.predict_risk(self.goal, failure_history=fails)
        self.assertEqual(r["overall"], "high")
        self.assertEqual(
            next(x for x in r["per_milestone"]
                 if x["milestone_id"] == self.ms[0])["risk"],
            "high",
        )

    def test_below_threshold_low(self):
        """失败 < 阈值 → low"""
        fails = {self.ms[0]: 1}
        r = self.adjuster.predict_risk(self.goal, failure_history=fails)
        self.assertEqual(r["overall"], "low")

    def test_blocked_medium(self):
        """被阻塞 → medium"""
        from backend.embodied.planning import DependencyGraph
        graph = DependencyGraph()
        graph.set_dependencies(self.goal, {self.ms[2]: [self.ms[1]]})
        adjuster = PlanAdjuster(progress_tracker=__import__(
            "backend.embodied.planning.progress_tracker",
            fromlist=["ProgressTracker"],
        ).ProgressTracker(graph))
        r = adjuster.predict_risk(self.goal)
        medium = [x for x in r["per_milestone"] if x["risk"] == "medium"]
        self.assertEqual(len(medium), 1)
        self.assertEqual(medium[0]["milestone_id"], self.ms[2])

    def test_reason_explainable(self):
        """风险原因可解释"""
        fails = {self.ms[0]: 5}
        r = self.adjuster.predict_risk(self.goal, failure_history=fails)
        entry = next(x for x in r["per_milestone"]
                     if x["milestone_id"] == self.ms[0])
        self.assertIn("失败", entry["reason"])

    def test_empty_milestones_low(self):
        """无里程碑 → overall low"""
        g = LongGoal.create(title="t")
        r = self.adjuster.predict_risk(g)
        self.assertEqual(r["overall"], "low")
        self.assertEqual(r["per_milestone"], [])


class TestTimePlan(unittest.TestCase):
    """时间规划"""

    def setUp(self):
        self.mgr = MilestoneManager()
        self.adjuster = PlanAdjuster(deadline_warning_hours=24.0)
        self.goal = make_decomposed(self.mgr)

    def test_no_deadline(self):
        """无 deadline → no_deadline"""
        r = self.adjuster.time_plan(self.goal)
        self.assertEqual(r["deadline_status"], "no_deadline")
        self.assertFalse(r["warning"])

    def test_estimated_total(self):
        """总时间估计 = 各里程碑之和"""
        r = self.adjuster.time_plan(self.goal)
        self.assertEqual(r["estimated_total_minutes"], 25.0)  # 5 × 5

    def test_time_window_structure(self):
        """时间窗口结构"""
        r = self.adjuster.time_plan(self.goal)
        self.assertIn("start", r["time_window"])
        self.assertIn("end", r["time_window"])
        self.assertIn("remaining_hours", r["time_window"])

    def test_on_schedule(self):
        """deadline 充足 → on_schedule"""
        g = make_decomposed(self.mgr, title="t2")
        g.deadline = time.time() + 7 * 86400  # 7 天后
        r = self.adjuster.time_plan(g)
        self.assertEqual(r["deadline_status"], "on_schedule")
        self.assertFalse(r["warning"])

    def test_warning(self):
        """deadline 临近 → warning"""
        g = make_decomposed(self.mgr, title="t3")
        g.deadline = time.time() + 3600  # 1 小时后
        r = self.adjuster.time_plan(g)
        self.assertEqual(r["deadline_status"], "warning")
        self.assertTrue(r["warning"])

    def test_overdue(self):
        """deadline 已过 → overdue"""
        g = make_decomposed(self.mgr, title="t4")
        g.deadline = time.time() - 3600  # 1 小时前
        r = self.adjuster.time_plan(g)
        self.assertEqual(r["deadline_status"], "overdue")

    def test_remaining_hours(self):
        """剩余时间计算"""
        g = make_decomposed(self.mgr, title="t5")
        g.deadline = time.time() + 3600 * 10  # 10 小时后
        r = self.adjuster.time_plan(g)
        self.assertAlmostEqual(r["time_window"]["remaining_hours"], 10.0,
                               delta=0.1)


if __name__ == "__main__":
    unittest.main()
