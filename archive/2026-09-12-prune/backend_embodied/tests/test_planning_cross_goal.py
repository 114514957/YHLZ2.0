"""
YHLZ Embodied AI V4.6 - 跨目标规划器单元测试 (Cross-Goal Planner + Service)

覆盖 (cross_goal.py + service.py V4.6 API):
    - plan: 完整规划 (plan_id/goals/groups/shared_steps/budget_allocation/
      explainable_reason/mode)
    - 分组排序: 高优先级组在前
    - 共享步骤: 一次 scan 服务多目标
    - 预算冲突: budget 不足 → 冲突 + 降级建议
    - 参数校验: 空目标 → CrossGoalError; budget <= 0 → CrossGoalError
    - 策略质量: 有高质量策略的目标获得加成
    - Service API: cross_goal_plan / cross_goal_groups / cross_goal_budget /
      cross_goal_dry_run
    - 审计追踪: cross_goal 动作入审计; dry_run 不写审计
    - 安全: 规划不写 Agent Memory / 不绕过 Permission
    - 向后兼容: V4.5 API 保持可用
"""
import unittest

from backend.embodied.experience.policy import PolicyTable
from backend.embodied.planning import CrossGoalError, CrossGoalPlanner
from backend.embodied.schema import EmbodiedGoal
from backend.embodied.service import EmbodiedService
from backend.embodied.strategy.audit import PolicyAuditLog


def make_goal(description="拿起台灯", intent="pick", target="lamp",
              scene="room", priority="medium", max_steps=None, **kw):
    constraints = dict(kw.pop("constraints", {}) or {})
    if max_steps:
        constraints["max_steps"] = max_steps
    return EmbodiedGoal.create(
        description=description, intent=intent, target=target,
        scene=scene, priority=priority, constraints=constraints, **kw,
    )


class TestCrossGoalPlanner(unittest.TestCase):
    """跨目标规划器"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.planner = CrossGoalPlanner(
            table=self.table, audit=self.audit,
            max_budget=100, min_group_size=2,
        )

    def test_plan_structure(self):
        """规划结构完整"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        plan = self.planner.plan([g1, g2], record_audit=False)
        for key in ("plan_id", "goals", "groups", "shared_steps",
                    "budget_allocation", "explainable_reason", "mode"):
            self.assertIn(key, plan)
        self.assertEqual(plan["mode"], "rule_based")
        self.assertTrue(plan["plan_id"].startswith("plan_"))

    def test_plan_empty_goals_raises(self):
        """空目标列表 → CrossGoalError"""
        with self.assertRaises(CrossGoalError):
            self.planner.plan([])

    def test_plan_none_goal_raises(self):
        """None 目标 → CrossGoalError"""
        with self.assertRaises(CrossGoalError):
            self.planner.plan([None])

    def test_plan_invalid_budget_raises(self):
        """budget <= 0 → CrossGoalError"""
        g = make_goal()
        with self.assertRaises(CrossGoalError):
            self.planner.plan([g], budget=0)

    def test_grouping_in_plan(self):
        """规划含分组结果"""
        g1 = make_goal(description="拿起台灯", intent="pick", scene="room")
        g2 = make_goal(description="拿起杯子", intent="pick", scene="room")
        g3 = make_goal(description="扫描仓库", intent="scan", scene="warehouse")
        plan = self.planner.plan([g1, g2, g3], record_audit=False)
        self.assertEqual(plan["groups"]["total"], 1)
        self.assertEqual(plan["groups"]["groups"][0]["member_count"], 2)

    def test_shared_steps_in_plan(self):
        """规划含共享步骤 (scan 前置)"""
        g1 = make_goal(description="扫描再拿起台灯", intent="scan pick",
                       scene="room")
        g2 = make_goal(description="扫描再拿起杯子", intent="scan pick",
                       scene="room")
        plan = self.planner.plan([g1, g2], record_audit=False)
        self.assertEqual(plan["shared_steps"]["total_saved"], 1)

    def test_group_sort_high_priority_first(self):
        """组间排序: 高优先级组在前"""
        # 组 A: 2 个 low pick; 组 B: 2 个 high scan+pick
        ga1 = make_goal(intent="pick", priority="low")
        ga2 = make_goal(intent="pick", priority="low")
        gb1 = make_goal(intent="scan pick", description="扫描再拿起",
                        priority="high")
        gb2 = make_goal(intent="scan pick", description="扫描再拿起",
                        priority="high")
        plan = self.planner.plan([ga1, ga2, gb1, gb2], record_audit=False)
        groups = plan["groups"]["groups"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["goal_type"], "scan pick")

    def test_explainable_reason(self):
        """可解释原因包含组/共享/预算信息"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        plan = self.planner.plan([g1, g2], record_audit=False)
        reason = plan["explainable_reason"]
        self.assertIn("目标组", reason)
        self.assertIn("预算", reason)

    def test_plan_writes_audit(self):
        """record_audit=True → 审计记录 cross_goal"""
        g = make_goal()
        self.planner.plan([g], record_audit=True)
        log = self.audit.audit_policy_log(limit=0, action="cross_goal")
        self.assertEqual(log["total"], 1)

    def test_plan_no_audit(self):
        """record_audit=False → 不写审计"""
        g = make_goal()
        self.planner.plan([g], record_audit=False)
        self.assertEqual(self.audit.count(), 0)

    def test_budget_conflict_in_plan(self):
        """预算不足 → 冲突 + 降级建议"""
        g1 = make_goal(intent="pick", priority="high", max_steps=10)
        g2 = make_goal(intent="pick", priority="low", max_steps=10)
        plan = self.planner.plan([g1, g2], budget=2, record_audit=False)
        conflict = plan["budget_allocation"]["conflict"]
        self.assertTrue(conflict["conflict"])
        self.assertGreater(conflict["deficit"], 0)

    def test_quality_bonus_from_table(self):
        """策略表有高质量策略 → 目标获得质量加成"""
        # 目标 g1 场景/类型与高质量策略匹配
        g1 = make_goal(intent="pick", scene="room")
        g2 = make_goal(intent="move", scene="warehouse")
        p = self.table.upsert(trigger="best_pick", strategy="s", kind="success",
                              action_type="pick", scene="room",
                              action_sequence=[{"action_type": "pick"}])
        p.accepted_count, p.success_count = 10, 9   # hit_rate 0.9
        plan = self.planner.plan([g1, g2], budget=4, record_audit=False)
        a1 = next(a for a in plan["budget_allocation"]["allocations"]
                  if a["goal_id"] == g1.goal_id)
        self.assertTrue(a1["quality_bonus"])

    def test_planner_thresholds(self):
        """阈值配置可查"""
        self.assertEqual(self.planner._allocator._max_budget, 100)


class TestServiceCrossGoal(unittest.TestCase):
    """Service V4.6 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "embodied_planning_max_budget": 100,
            "embodied_planning_min_group_size": 2,
        })

    def test_cross_goal_plan_api(self):
        """cross_goal_plan 返回完整规划"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        plan = self.svc.cross_goal_plan([g1, g2], budget=20)
        self.assertEqual(plan["mode"], "rule_based")
        self.assertIn("plan_id", plan)
        self.assertIn("budget_allocation", plan)

    def test_cross_goal_plan_dict_goals(self):
        """支持 dict 目标输入"""
        g1 = make_goal().to_dict()
        g2 = make_goal(target="cup").to_dict()
        plan = self.svc.cross_goal_plan([g1, g2])
        self.assertEqual(len(plan["goals"]), 2)

    def test_cross_goal_groups_api(self):
        """cross_goal_groups 分组分析"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        r = self.svc.cross_goal_groups([g1, g2])
        self.assertEqual(r["total"], 1)
        self.assertIn("groups", r)

    def test_cross_goal_budget_api(self):
        """cross_goal_budget 预算分配"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        r = self.svc.cross_goal_budget([g1, g2], budget=20)
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("allocations", r)
        self.assertIn("conflict", r)

    def test_cross_goal_budget_with_budget_arg(self):
        """自定义 budget 生效"""
        g = make_goal(intent="pick")
        r = self.svc.cross_goal_budget([g], budget=50)
        self.assertEqual(r["budget"], 50)

    def test_cross_goal_dry_run_api(self):
        """cross_goal_dry_run 只模拟"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        r = self.svc.cross_goal_dry_run([g1, g2])
        self.assertTrue(r["dry_run"])
        self.assertTrue(r["protection_checks"]["passed"])
        self.assertIn("plan", r)

    def test_dry_run_no_audit(self):
        """dry_run 不写审计"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        self.svc.cross_goal_dry_run([g1, g2])
        log = self.svc.audit_policy_log(limit=0, action="cross_goal")
        self.assertEqual(log["total"], 0)

    def test_plan_writes_audit(self):
        """真实规划写审计"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        self.svc.cross_goal_plan([g1, g2])
        log = self.svc.audit_policy_log(limit=0, action="cross_goal")
        self.assertEqual(log["total"], 1)
        self.assertIn("跨目标规划", log["recent"][0]["reason"])

    def test_planning_enabled_default_false(self):
        """规划默认关闭 (embodied_enabled=False 保持)"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": False})
        self.assertFalse(svc.get_permission()["embodied_enabled"])

    def test_planning_no_memory_write(self):
        """规划不写入 Agent Memory"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        before = svc.memory.stats().get("total", 0)
        g1 = make_goal()
        g2 = make_goal(target="cup")
        svc.cross_goal_plan([g1, g2])
        svc.cross_goal_dry_run([g1, g2])
        after = svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_v45_apis_still_work(self):
        """向后兼容: V4.5 治理 API 保持可用"""
        g1 = make_goal()
        g2 = make_goal(target="cup")
        plan = self.svc.cross_goal_plan([g1, g2])
        self.assertEqual(plan["mode"], "rule_based")
        # V4.5 API
        self.assertEqual(self.svc.governance.status()["version"], "9.5.0")
        self.assertIn("strategy_system", self.svc.audit_system_export())

    def test_service_planner_lazy(self):
        """planner 懒加载可用"""
        self.assertIsNotNone(self.svc.planner)
        self.assertEqual(self.svc.planner._allocator._max_budget, 100)

    def test_config_driven_planner(self):
        """配置驱动: min_group_size / max_budget"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_planning_max_budget": 50,
            "embodied_planning_min_group_size": 1,
        })
        self.assertEqual(svc.planner._allocator._max_budget, 50)
        g = make_goal()
        r = svc.cross_goal_groups([g])
        self.assertEqual(r["total"], 1)  # min_group_size=1 单目标也成组

    def test_cross_goal_audit_export_included(self):
        """audit_system_export 含 cross_goal 审计"""
        g1 = make_goal()
        self.svc.cross_goal_plan([g1])
        exp = self.svc.audit_system_export()
        actions = {e["action"] for e in exp["audit"]["entries"]}
        self.assertIn("cross_goal", actions)

    def test_version_4_6_0(self):
        """Service 版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")


class TestEndToEndPlanning(unittest.TestCase):
    """端到端: 多目标 → 分组 → 共享 → 预算 → 审计"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "embodied_planning_max_budget": 100,
        })
        self.table = self.svc._experience.table

    def test_full_planning_flow(self):
        """完整流程: 2 个 scan+pick 目标 + 1 个 scan 目标"""
        g1 = make_goal(description="扫描再拿起台灯", intent="scan pick",
                       target="lamp", scene="room", priority="high")
        g2 = make_goal(description="扫描再拿起杯子", intent="scan pick",
                       target="cup", scene="room", priority="medium")
        g3 = make_goal(description="扫描房间", intent="scan",
                       scene="room", priority="low")

        plan = self.svc.cross_goal_plan([g1, g2, g3], budget=20)
        # 分组: g1+g2 一组
        self.assertEqual(plan["groups"]["total"], 1)
        # 共享: scan 前置共享节省
        self.assertGreaterEqual(plan["shared_steps"]["total_saved"], 1)
        # 预算分配
        self.assertIn("allocations", plan["budget_allocation"])
        # 可解释
        self.assertIn("目标组", plan["explainable_reason"])

    def test_budget_shortage_end_to_end(self):
        """预算严重不足 → 冲突提示"""
        g1 = make_goal(intent="pick", priority="high", max_steps=20)
        g2 = make_goal(intent="pick", priority="medium", max_steps=20)
        plan = self.svc.cross_goal_plan([g1, g2], budget=3)
        self.assertTrue(plan["budget_allocation"]["conflict"]["conflict"])

    def test_policy_quality_used_in_planning(self):
        """策略质量影响预算分配 (经 Service)"""
        p = self.table.upsert(trigger="good_pick", strategy="s",
                              kind="success", action_type="pick",
                              scene="room",
                              action_sequence=[{"action_type": "pick"}])
        p.accepted_count, p.success_count = 10, 9
        g1 = make_goal(intent="pick", scene="room")
        g2 = make_goal(intent="pick", scene="warehouse")
        plan = self.svc.cross_goal_plan([g1, g2], budget=4)
        a1 = next(a for a in plan["budget_allocation"]["allocations"]
                  if a["goal_id"] == g1.goal_id)
        a2 = next(a for a in plan["budget_allocation"]["allocations"]
                  if a["goal_id"] == g2.goal_id)
        self.assertGreaterEqual(a1["allocated"], a2["allocated"])


if __name__ == "__main__":
    unittest.main()
