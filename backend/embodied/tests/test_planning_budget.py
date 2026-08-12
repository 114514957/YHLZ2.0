"""
YHLZ Embodied AI V4.6 - 跨目标预算分配单元测试 (Cross-Goal Budget Allocation)

覆盖 (budget.py):
    - 单目标基础需求: 计划长度 / max_steps 约束 / 关键词默认
    - 需求计算: 基础需求 - 共享节省 → 最终需求
    - 预算分配: 需求 <= 预算 → 按需; 需求 > 预算 → 权重比例 (高优先级优先)
    - 策略质量加成: hit_rate >= 阈值 → 权重加成
    - 预算冲突检测: 需求 > 预算 → 降级建议 (低优先级)
    - 参数校验: max_budget <= 0 / min_steps <= 0 → BudgetError
    - 可解释输出: 每条分配含 reason

设计原则验证:
    - 纯函数式分配 (不修改任何状态)
    - 规则 + 权重 + 阈值
"""
import unittest

from backend.embodied.planning import (
    BudgetAllocator,
    BudgetError,
    PRIORITY_WEIGHTS,
)
from backend.embodied.schema import EmbodiedGoal


def make_goal(description="拿起台灯", intent="pick", priority="medium",
              max_steps=None, **kw):
    constraints = {}
    if max_steps:
        constraints["max_steps"] = max_steps
    return EmbodiedGoal.create(
        description=description, intent=intent, priority=priority,
        constraints=constraints, **kw,
    )


class TestBaseDemand(unittest.TestCase):
    """单目标基础需求"""

    def setUp(self):
        self.alloc = BudgetAllocator(max_budget=100)

    def test_default_pick_demand(self):
        """pick 目标默认需求 (无序列长度 → 按关键词默认 3)"""
        g = make_goal(intent="pick")
        d = self.alloc._base_demand(g, 0)
        self.assertEqual(d, 3)

    def test_sequence_length(self):
        """有动作序列 → 需求 = 序列长度"""
        g = make_goal()
        d = self.alloc._base_demand(g, 2)
        self.assertEqual(d, 2)

    def test_max_steps_greater(self):
        """max_steps 约束 > 序列长度 → 取 max_steps"""
        g = make_goal(max_steps=5)
        d = self.alloc._base_demand(g, 2)
        self.assertEqual(d, 5)

    def test_max_steps_smaller(self):
        """max_steps < 序列长度 → 取序列长度"""
        g = make_goal(max_steps=2)
        d = self.alloc._base_demand(g, 4)
        self.assertEqual(d, 4)

    def test_min_one(self):
        """需求至少 1"""
        g = make_goal()
        d = self.alloc._base_demand(g, 0)
        self.assertGreaterEqual(d, 1)


class TestDemands(unittest.TestCase):
    """需求计算 (含共享节省)"""

    def setUp(self):
        self.alloc = BudgetAllocator(max_budget=100)

    def test_total_demand_sum(self):
        """总需求 = 各目标最终需求之和"""
        g1 = make_goal(intent="pick")
        g2 = make_goal(intent="move")
        r = self.alloc.demands([g1, g2])
        self.assertEqual(r["total_demand"],
                         sum(x["final_demand"] for x in r["per_goal"]))

    def test_shared_saved_reduces(self):
        """共享节省减少最终需求"""
        g = make_goal()
        r = self.alloc.demands([g], shared_saved={g.goal_id: 1})
        self.assertEqual(r["per_goal"][0]["shared_saved"], 1)

    def test_shared_saved_floor(self):
        """最终需求不低于 min_steps"""
        g = make_goal(intent="move")  # 默认 2
        r = self.alloc.demands([g], shared_saved={g.goal_id: 5})
        self.assertEqual(r["per_goal"][0]["final_demand"], 1)

    def test_priority_recorded(self):
        """需求条目记录优先级"""
        g = make_goal(priority="high")
        r = self.alloc.demands([g])
        self.assertEqual(r["per_goal"][0]["priority"], "high")

    def test_total_saved(self):
        """总节省统计"""
        g1 = make_goal()
        g2 = make_goal()
        r = self.alloc.demands(
            [g1, g2], shared_saved={g1.goal_id: 1, g2.goal_id: 0},
        )
        self.assertEqual(r["total_saved"], 1)


class TestAllocate(unittest.TestCase):
    """预算分配"""

    def setUp(self):
        self.alloc = BudgetAllocator(max_budget=20)

    def test_sufficient_budget_by_demand(self):
        """需求 <= 预算 → 按需分配"""
        g1 = make_goal(intent="pick")   # 3
        g2 = make_goal(intent="move")   # 2
        r = self.alloc.allocate([g1, g2])
        alloc_map = {a["goal_id"]: a["allocated"] for a in r["allocations"]}
        self.assertEqual(alloc_map[g1.goal_id], 3)
        self.assertEqual(alloc_map[g2.goal_id], 2)
        self.assertEqual(r["total_allocated"], 5)

    def test_high_priority_more_budget(self):
        """预算不足 → 高优先级获得更多"""
        g1 = make_goal(intent="pick", priority="high")
        g2 = make_goal(intent="pick", priority="low")
        r = self.alloc.allocate([g1, g2], demands=self.alloc.demands(
            [g1, g2], sequences={g1.goal_id: 15, g2.goal_id: 15},
        ))
        alloc_map = {a["goal_id"]: a["allocated"] for a in r["allocations"]}
        self.assertGreater(alloc_map[g1.goal_id], alloc_map[g2.goal_id])

    def test_quality_bonus(self):
        """策略质量达标 → quality_bonus=True"""
        g = make_goal()
        r = self.alloc.allocate(
            [g], strategy_quality={g.goal_id: 0.9},
        )
        self.assertTrue(r["allocations"][0]["quality_bonus"])

    def test_quality_bonus_weighted_more(self):
        """质量加成 → 有效权重更高"""
        g1 = make_goal(intent="pick", priority="medium")
        g2 = make_goal(intent="pick", priority="medium")
        r = self.alloc.allocate(
            [g1, g2],
            demands=self.alloc.demands([g1, g2], sequences={
                g1.goal_id: 15, g2.goal_id: 15,
            }),
            strategy_quality={g1.goal_id: 0.9, g2.goal_id: 0.1},
        )
        a1 = next(a for a in r["allocations"] if a["goal_id"] == g1.goal_id)
        a2 = next(a for a in r["allocations"] if a["goal_id"] == g2.goal_id)
        self.assertGreater(a1["allocated"], a2["allocated"])

    def test_reason_explainable(self):
        """每条分配含可解释 reason"""
        g = make_goal(priority="high")
        r = self.alloc.allocate([g])
        self.assertIn("reason", r["allocations"][0])
        self.assertTrue(r["allocations"][0]["reason"])

    def test_mode_rule_based(self):
        """输出 mode=rule_based"""
        g = make_goal()
        r = self.alloc.allocate([g])
        self.assertEqual(r["mode"], "rule_based")

    def test_allocated_not_exceed_budget(self):
        """总分配不超过预算 (需求不足时按需)"""
        g = make_goal(intent="pick")
        r = self.alloc.allocate([g])
        self.assertLessEqual(r["total_allocated"], 20)

    def test_min_steps_floor(self):
        """分配不低于 min_steps"""
        g = make_goal(intent="move")
        r = self.alloc.allocate([g])
        self.assertGreaterEqual(r["allocations"][0]["allocated"], 1)

    def test_saved_by_sharing_reported(self):
        """共享节省数上报"""
        g = make_goal()
        r = self.alloc.allocate([g])
        self.assertIn("saved_by_sharing", r)


class TestBudgetConflict(unittest.TestCase):
    """预算冲突检测"""

    def setUp(self):
        self.alloc = BudgetAllocator(max_budget=5)

    def test_no_conflict_sufficient(self):
        """需求 <= 预算 → 无冲突"""
        g = make_goal(intent="move")  # 2
        r = self.alloc.demands([g])
        c = self.alloc.detect_conflict(r)
        self.assertFalse(c["conflict"])
        self.assertEqual(c["deficit"], 0)

    def test_conflict_detected(self):
        """需求 > 预算 → 冲突 + 缺口"""
        g1 = make_goal(intent="pick", priority="low")
        g2 = make_goal(intent="pick", priority="medium")
        r = self.alloc.demands(
            [g1, g2], sequences={g1.goal_id: 10, g2.goal_id: 10},
        )
        c = self.alloc.detect_conflict(r)
        self.assertTrue(c["conflict"])
        self.assertGreater(c["deficit"], 0)

    def test_degration_suggestion_low_priority_first(self):
        """降级建议: 低优先级目标在前"""
        g1 = make_goal(intent="pick", priority="high")
        g2 = make_goal(intent="pick", priority="low")
        r = self.alloc.demands(
            [g1, g2], sequences={g1.goal_id: 10, g2.goal_id: 10},
        )
        c = self.alloc.detect_conflict(r)
        self.assertEqual(c["suggestions"][0]["priority"], "low")
        self.assertIn("降低", c["suggestions"][0]["reason"])

    def test_rule_explainable(self):
        """冲突规则可解释"""
        g = make_goal(intent="pick")
        r = self.alloc.demands([g], sequences={g.goal_id: 10})
        c = self.alloc.detect_conflict(r)
        self.assertIn("rule", c)


class TestBudgetValidation(unittest.TestCase):
    """参数校验"""

    def test_invalid_max_budget(self):
        """max_budget <= 0 → BudgetError"""
        with self.assertRaises(BudgetError):
            BudgetAllocator(max_budget=0)

    def test_invalid_min_steps(self):
        """min_steps_per_goal <= 0 → BudgetError"""
        with self.assertRaises(BudgetError):
            BudgetAllocator(min_steps_per_goal=0)

    def test_priority_weights_defaults(self):
        """优先级权重默认 high > medium > low"""
        self.assertEqual(PRIORITY_WEIGHTS["high"], 2.0)
        self.assertEqual(PRIORITY_WEIGHTS["medium"], 1.5)
        self.assertEqual(PRIORITY_WEIGHTS["low"], 1.0)

    def test_custom_weights(self):
        """自定义优先级权重"""
        a = BudgetAllocator(
            priority_weight_high=3.0, priority_weight_medium=2.0,
            priority_weight_low=1.0,
        )
        self.assertEqual(a.thresholds()["priority_weights"]["high"], 3.0)

    def test_thresholds_exposed(self):
        """阈值暴露"""
        a = BudgetAllocator(max_budget=50, min_steps_per_goal=2,
                            quality_bonus_threshold=0.6)
        th = a.thresholds()
        self.assertEqual(th["max_budget"], 50)
        self.assertEqual(th["min_steps_per_goal"], 2)
        self.assertEqual(th["quality_bonus_threshold"], 0.6)


if __name__ == "__main__":
    unittest.main()
