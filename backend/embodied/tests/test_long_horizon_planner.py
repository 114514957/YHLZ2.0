"""
YHLZ Embodied AI V4.7 - 长期任务规划器与 Service 集成测试
(Long Horizon Planner + Service API)

覆盖 (long_horizon.py + service.py V4.7 API):
    - create_long_goal / decompose_goal / generate_milestones
    - track_progress / progress_report
    - complete_milestone / rollback_milestone
    - set_dependencies / dependency_graph
    - pause / resume / fail / archive
    - adjust_plan / predict_risk / time_plan / snapshot
    - plan_milestone_goals (V4.6 集成)
    - long_horizon_dry_run (保护规则 / 不落地)
    - Service API: long_horizon_plan / decompose / progress / report /
      milestone / dependencies / status / adjust / risk / time / snapshot /
      plan_milestones / dry_run / list
    - 审计追踪: 7 个 V4.7 审计动作
    - 安全: 不写 Agent Memory / 不绕过 Permission / 只读 Experience Memory
"""
import unittest

from backend.embodied.planning import (
    LongHorizonPlanner,
    LongHorizonPlannerError,
    MilestoneManager,
)
from backend.embodied.service import EmbodiedService
from backend.embodied.strategy.audit import AUDIT_ACTIONS, PolicyAuditLog


def make_goal(planner, title="整理房间", desc="收拾整理房间物品",
              phases=None, priority="medium"):
    g = planner.create_long_goal(
        title=title, description=desc, priority=priority,
    )
    phases = phases or ["收集", "分类", "整理", "检查", "维护"]
    tree = planner.decompose_goal(g["goal_id"], phases)
    return g["goal_id"], tree


class TestLongHorizonPlanner(unittest.TestCase):
    """长期任务规划器门面"""

    def setUp(self):
        self.audit = PolicyAuditLog()
        self.planner = LongHorizonPlanner(audit=self.audit)

    def test_create_long_goal(self):
        """创建长期目标 + 审计"""
        g = self.planner.create_long_goal(title="整理房间")
        self.assertEqual(g["status"], "pending")
        log = self.audit.audit_policy_log(limit=0, action="create_long_goal")
        self.assertEqual(log["total"], 1)

    def test_create_no_audit(self):
        """record_audit=False 不写审计"""
        self.planner.create_long_goal(title="t", record_audit=False)
        self.assertEqual(self.audit.count(), 0)

    def test_decompose_goal(self):
        """分解 → 任务树"""
        gid, tree = make_goal(self.planner)
        self.assertEqual(len(tree["milestones"]), 5)
        self.assertEqual(tree["status"], "active")
        log = self.audit.audit_policy_log(limit=0, action="decompose_goal")
        self.assertEqual(log["total"], 1)

    def test_decompose_unknown_goal(self):
        """不存在的目标 → LongHorizonPlannerError"""
        with self.assertRaises(LongHorizonPlannerError):
            self.planner.decompose_goal("nope", ["a"])

    def test_generate_milestones_templates(self):
        """自动生成里程碑模板"""
        gid = self.planner.create_long_goal(
            title="整理房间", description="收拾", record_audit=False,
        )["goal_id"]
        r = self.planner.generate_milestones(gid)
        self.assertEqual(r["template_used"],
                         ["收集物品", "分类", "整理", "检查", "维护"])
        self.assertEqual(len(r["milestones"]), 5)

    def test_generate_learning_template(self):
        """学习模板"""
        gid = self.planner.create_long_goal(
            title="学习 Python", record_audit=False,
        )["goal_id"]
        r = self.planner.generate_milestones(gid)
        self.assertEqual(r["template_used"][0], "基础阶段")

    def test_generate_patrol_template(self):
        """巡逻模板"""
        gid = self.planner.create_long_goal(
            title="夜间巡逻", record_audit=False,
        )["goal_id"]
        r = self.planner.generate_milestones(gid)
        self.assertEqual(r["template_used"][0], "感知环境")

    def test_generate_default_template(self):
        """默认模板"""
        gid = self.planner.create_long_goal(
            title="随便任务", record_audit=False,
        )["goal_id"]
        r = self.planner.generate_milestones(gid)
        self.assertEqual(r["template_used"], ["准备", "执行", "检查", "收尾"])

    def test_track_progress(self):
        """进度跟踪"""
        gid, tree = make_goal(self.planner)
        p = self.planner.track_progress(gid)
        self.assertEqual(p["percent"], 0)
        self.assertEqual(p["total"], 5)

    def test_progress_report(self):
        """进度报告"""
        gid, tree = make_goal(self.planner)
        rep = self.planner.progress_report(gid)
        self.assertIn("Goal:", rep)
        self.assertIn("Completed: 0/5", rep)

    def test_complete_milestone(self):
        """完成里程碑 + 审计"""
        gid, tree = make_goal(self.planner)
        mid = tree["milestones"][0]["milestone_id"]
        self.planner.complete_milestone(gid, mid)
        p = self.planner.track_progress(gid)
        self.assertEqual(p["completed"], 1)
        log = self.audit.audit_policy_log(limit=0,
                                          action="milestone_complete")
        self.assertEqual(log["total"], 1)

    def test_complete_all_completes_goal(self):
        """全部完成 → 目标 completed"""
        gid, tree = make_goal(self.planner)
        for m in tree["milestones"]:
            self.planner.complete_milestone(gid, m["milestone_id"])
        self.assertEqual(self.planner.track_progress(gid)["status"],
                         "completed")

    def test_rollback_milestone(self):
        """回滚 + 审计 plan_adjust"""
        gid, tree = make_goal(self.planner)
        mid = tree["milestones"][0]["milestone_id"]
        self.planner.complete_milestone(gid, mid)
        self.planner.rollback_milestone(gid, mid)
        p = self.planner.track_progress(gid)
        self.assertEqual(p["completed"], 0)

    def test_set_dependencies(self):
        """设置依赖"""
        gid, tree = make_goal(self.planner)
        ms = [m["milestone_id"] for m in tree["milestones"]]
        r = self.planner.set_dependencies(gid, {ms[2]: [ms[0], ms[1]]})
        self.assertEqual(len(r["nodes"]), 5)

    def test_dependency_graph_query(self):
        """依赖图查询"""
        gid, tree = make_goal(self.planner)
        r = self.planner.dependency_graph(gid)
        self.assertEqual(r["goal_id"], gid)
        self.assertIn("rule", r)

    def test_pause_resume(self):
        """暂停/恢复 + 审计"""
        gid, _ = make_goal(self.planner)
        self.planner.pause_goal(gid, "等用户")
        self.assertEqual(self.planner.track_progress(gid)["status"], "paused")
        self.planner.resume_goal(gid)
        self.assertEqual(self.planner.track_progress(gid)["status"], "active")
        for action in ("goal_pause", "goal_resume"):
            log = self.audit.audit_policy_log(limit=0, action=action)
            self.assertEqual(log["total"], 1)

    def test_fail_goal(self):
        """失败标记 + 审计"""
        gid, _ = make_goal(self.planner)
        self.planner.fail_goal(gid, "执行失败")
        self.assertEqual(self.planner.track_progress(gid)["status"], "failed")
        log = self.audit.audit_policy_log(limit=0, action="goal_fail")
        self.assertEqual(log["total"], 1)

    def test_archive_goal(self):
        """归档"""
        gid, _ = make_goal(self.planner)
        self.planner.archive_goal(gid, "任务归档")
        self.assertEqual(self.planner.track_progress(gid)["status"],
                         "archived")

    def test_adjust_plan(self):
        """计划调整 + 审计"""
        gid, _ = make_goal(self.planner)
        r = self.planner.adjust_plan(gid, trigger="time_change", reason="延期")
        self.assertTrue(r["adjusted"])
        self.assertTrue(r["permission_required"])
        log = self.audit.audit_policy_log(limit=0, action="plan_adjust")
        self.assertEqual(log["total"], 1)

    def test_predict_risk(self):
        """风险预测"""
        gid, tree = make_goal(self.planner)
        mid = tree["milestones"][0]["milestone_id"]
        r = self.planner.predict_risk(gid, {mid: 5})
        self.assertEqual(r["overall"], "high")

    def test_time_plan(self):
        """时间规划"""
        gid, _ = make_goal(self.planner)
        r = self.planner.time_plan(gid)
        self.assertEqual(r["deadline_status"], "no_deadline")

    def test_snapshot(self):
        """快照"""
        gid, tree = make_goal(self.planner)
        mid = tree["milestones"][0]["milestone_id"]
        self.planner.complete_milestone(gid, mid)
        snap = self.planner.snapshot(gid)
        self.assertEqual(snap["completed_milestones"], 1)

    def test_plan_milestone_goals(self):
        """里程碑 → V4.6 跨目标规划"""
        gid, tree = make_goal(self.planner)
        r = self.planner.plan_milestone_goals(gid)
        self.assertEqual(len(r["milestone_plans"]), 5)
        self.assertIn("milestone_id", r["milestone_plans"][0])

    def test_plan_milestone_goals_with_planner(self):
        """里程碑 + CrossGoalPlanner 衔接"""
        from backend.embodied.planning import CrossGoalPlanner
        gid, tree = make_goal(
            self.planner, title="多目标任务", desc="拾取多个物品",
            phases=["收集物品"],
        )
        r = self.planner.plan_milestone_goals(
            gid, cross_goal_planner=CrossGoalPlanner(),
        )
        self.assertEqual(len(r["milestone_plans"]), 1)

    def test_long_horizon_dry_run(self):
        """预演: 拆解/时间/风险/依赖 + 保护规则"""
        r = self.planner.long_horizon_dry_run("巡逻仓库")
        self.assertTrue(r["dry_run"])
        self.assertTrue(r["protection_checks"]["passed"])
        self.assertIn("task_breakdown", r)
        self.assertIn("time_estimate", r)
        self.assertIn("risk_points", r)
        self.assertIn("dependencies", r)

    def test_dry_run_phases_param(self):
        """预演指定阶段"""
        r = self.planner.long_horizon_dry_run(
            "整理房间", phases=["收集", "整理"],
        )
        self.assertEqual(len(r["task_breakdown"]["milestones"]), 2)

    def test_dry_run_no_persist(self):
        """预演不落地: 不创建真实目标"""
        before = len(self.planner.list_goals())
        self.planner.long_horizon_dry_run("测试")
        self.assertEqual(len(self.planner.list_goals()), before)

    def test_list_goals(self):
        """目标列表"""
        make_goal(self.planner)
        make_goal(self.planner, title="学习", phases=["基础", "进阶"])
        goals = self.planner.list_goals()
        self.assertEqual(len(goals), 2)
        self.assertIn("milestone_count", goals[0])

    def test_thresholds(self):
        """阈值暴露"""
        th = self.planner.thresholds()
        self.assertIn("risk_failure_threshold", th)


class TestServiceLongHorizon(unittest.TestCase):
    """Service V4.7 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})
        self.lh = self.svc.long_horizon

    def test_long_horizon_plan_auto(self):
        """long_horizon_plan 自动拆解"""
        r = self.svc.long_horizon_plan(title="整理房间", description="收拾")
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(len(r["task_tree"]["milestones"]), 5)

    def test_long_horizon_plan_manual_phases(self):
        """long_horizon_plan 指定阶段"""
        r = self.svc.long_horizon_plan(
            title="整理", phases=["收集", "整理", "检查"],
        )
        self.assertEqual(len(r["task_tree"]["milestones"]), 3)

    def test_long_horizon_decompose(self):
        """手动分解 (先创建未分解目标)"""
        gid = self.svc.long_horizon.create_long_goal(
            title="t", record_audit=False,
        )["goal_id"]
        tree = self.svc.long_horizon_decompose(gid, ["x", "y", "z"])
        self.assertEqual(len(tree["milestones"]), 3)
        self.assertEqual(tree["status"], "active")

    def test_long_horizon_progress_api(self):
        """进度 API"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        p = self.svc.long_horizon_progress(gid)
        self.assertIn("percent", p)
        self.assertIn("completed", p)

    def test_long_horizon_report_api(self):
        """报告 API"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        rep = self.svc.long_horizon_report(gid)
        self.assertIn("Goal:", rep)

    def test_long_horizon_milestone_api(self):
        """里程碑 API (complete/rollback)"""
        plan = self.svc.long_horizon_plan(title="t", phases=["a", "b"])
        gid = plan["goal"]["goal_id"]
        mid = plan["task_tree"]["milestones"][0]["milestone_id"]
        self.svc.long_horizon_milestone(gid, mid, "complete")
        self.assertEqual(
            self.svc.long_horizon_progress(gid)["completed"], 1,
        )
        self.svc.long_horizon_milestone(gid, mid, "rollback")
        self.assertEqual(
            self.svc.long_horizon_progress(gid)["completed"], 0,
        )

    def test_long_horizon_milestone_invalid_action(self):
        """非法里程碑动作 → EmbodiedServiceError"""
        plan = self.svc.long_horizon_plan(title="t")
        gid = plan["goal"]["goal_id"]
        from backend.embodied.service import EmbodiedServiceError
        with self.assertRaises(EmbodiedServiceError):
            self.svc.long_horizon_milestone(gid, "x", "hack")

    def test_long_horizon_dependencies_api(self):
        """依赖 API (设置/查询)"""
        plan = self.svc.long_horizon_plan(title="t", phases=["a", "b", "c"])
        gid = plan["goal"]["goal_id"]
        ms = [m["milestone_id"] for m in plan["task_tree"]["milestones"]]
        r = self.svc.long_horizon_dependencies(
            gid, {ms[2]: [ms[0]]},
        )
        self.assertEqual(len(r["nodes"]), 3)
        q = self.svc.long_horizon_dependencies(gid)
        self.assertEqual(q["goal_id"], gid)

    def test_long_horizon_status_api(self):
        """状态 API"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        self.svc.long_horizon_status(gid, "pause", "等待")
        self.assertEqual(
            self.svc.long_horizon_progress(gid)["status"], "paused",
        )
        self.svc.long_horizon_status(gid, "resume")
        self.assertEqual(
            self.svc.long_horizon_progress(gid)["status"], "active",
        )
        self.svc.long_horizon_status(gid, "fail", "失败")
        self.assertEqual(
            self.svc.long_horizon_progress(gid)["status"], "failed",
        )
        self.svc.long_horizon_status(gid, "archive")
        self.assertEqual(
            self.svc.long_horizon_progress(gid)["status"], "archived",
        )

    def test_long_horizon_status_invalid(self):
        """非法状态动作 → EmbodiedServiceError"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        from backend.embodied.service import EmbodiedServiceError
        with self.assertRaises(EmbodiedServiceError):
            self.svc.long_horizon_status(gid, "explode")

    def test_long_horizon_adjust_api(self):
        """调整 API"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        r = self.svc.long_horizon_adjust(
            gid, trigger="failure_increase", reason="失败",
        )
        self.assertTrue(r["adjusted"])
        self.assertTrue(r["permission_required"])

    def test_long_horizon_risk_api(self):
        """风险 API"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        r = self.svc.long_horizon_risk(gid)
        self.assertEqual(r["overall"], "low")

    def test_long_horizon_time_api(self):
        """时间 API"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        r = self.svc.long_horizon_time(gid)
        self.assertIn("deadline_status", r)

    def test_long_horizon_snapshot_api(self):
        """快照 API"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        snap = self.svc.long_horizon_snapshot(gid)
        self.assertIn("snapshot_id", snap)

    def test_long_horizon_plan_milestones_api(self):
        """里程碑子规划 API"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        r = self.svc.long_horizon_plan_milestones(gid)
        self.assertEqual(len(r["milestone_plans"]),
                         len(self.lh._milestones.get(gid).milestones))

    def test_long_horizon_dry_run_api(self):
        """预演 API"""
        r = self.svc.long_horizon_dry_run("巡逻仓库")
        self.assertTrue(r["dry_run"])
        self.assertTrue(r["protection_checks"]["passed"])

    def test_long_horizon_list_api(self):
        """列表 API"""
        self.svc.long_horizon_plan(title="t1")
        self.svc.long_horizon_plan(title="t2")
        self.assertEqual(len(self.svc.long_horizon_list()), 2)

    def test_audit_actions_whitelist(self):
        """V4.7 审计动作在白名单"""
        for action in ("create_long_goal", "decompose_goal",
                       "milestone_complete", "plan_adjust", "goal_pause",
                       "goal_resume", "goal_fail"):
            self.assertIn(action, AUDIT_ACTIONS)

    def test_plan_writes_audit_trail(self):
        """完整流程审计追踪"""
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        self.svc.long_horizon_adjust(gid, trigger="time_change")
        self.svc.long_horizon_status(gid, "pause")
        exp = self.svc.audit_system_export()
        actions = {e["action"] for e in exp["audit"]["entries"]}
        self.assertIn("create_long_goal", actions)
        self.assertIn("decompose_goal", actions)
        self.assertIn("plan_adjust", actions)
        self.assertIn("goal_pause", actions)

    def test_no_memory_write(self):
        """长期任务不写入 Agent Memory"""
        before = self.svc.memory.stats().get("total", 0)
        gid = self.svc.long_horizon_plan(title="t")["goal"]["goal_id"]
        self.svc.long_horizon_adjust(gid, trigger="time_change")
        self.svc.long_horizon_dry_run("测试")
        after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_version_4_7_0(self):
        """Service 版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_v46_apis_still_work(self):
        """向后兼容: V4.6 API 保持可用"""
        from backend.embodied.schema import EmbodiedGoal
        g1 = EmbodiedGoal.create(description="拿起台灯", intent="pick",
                                 scene="room")
        g2 = EmbodiedGoal.create(description="拿起杯子", intent="pick",
                                 scene="room")
        plan = self.svc.cross_goal_plan([g1, g2])
        self.assertEqual(plan["mode"], "rule_based")


class TestLongHorizonEndToEnd(unittest.TestCase):
    """端到端: 长期任务完整生命周期"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_full_lifecycle(self):
        """创建 → 分解 → 依赖 → 进度 → 调整 → 快照 → 完成"""
        gid = self.svc.long_horizon_plan(
            title="整理仓库", description="整理仓库物品",
            phases=["收集", "分类", "整理", "检查"],
        )["goal"]["goal_id"]

        # 依赖: 分类依赖收集
        mgr = self.svc.long_horizon._milestones
        goal = mgr.get(gid)
        ms = [m.milestone_id for m in goal.milestones]
        self.svc.long_horizon_dependencies(
            gid, {ms[1]: [ms[0]], ms[2]: [ms[1]]},
        )

        # 进度: 完成前 2 个
        self.svc.long_horizon_milestone(gid, ms[0], "complete")
        self.svc.long_horizon_milestone(gid, ms[1], "complete")
        p = self.svc.long_horizon_progress(gid)
        self.assertEqual(p["completed"], 2)
        self.assertEqual(p["percent"], 50)

        # 调整
        adj = self.svc.long_horizon_adjust(
            gid, trigger="resource_shortage", reason="预算减半",
        )
        self.assertTrue(adj["adjusted"])

        # 快照
        snap = self.svc.long_horizon_snapshot(gid)
        self.assertEqual(snap["completed_milestones"], 2)

        # 完成全部
        self.svc.long_horizon_milestone(gid, ms[2], "complete")
        self.svc.long_horizon_milestone(gid, ms[3], "complete")
        p = self.svc.long_horizon_progress(gid)
        self.assertEqual(p["status"], "completed")
        self.assertEqual(p["percent"], 100)

    def test_snapshot_resume_flow(self):
        """快照断点恢复流程"""
        gid = self.svc.long_horizon_plan(
            title="t", phases=["a", "b", "c"],
        )["goal"]["goal_id"]
        mgr = self.svc.long_horizon._milestones
        goal = mgr.get(gid)
        ms = [m.milestone_id for m in goal.milestones]
        self.svc.long_horizon_milestone(gid, ms[0], "complete")
        snap = self.svc.long_horizon_snapshot(gid)

        # 新目标恢复
        gid2 = self.svc.long_horizon_plan(
            title="t2", phases=["a", "b", "c"],
        )["goal"]["goal_id"]
        goal2 = mgr.get(gid2)
        from backend.embodied.planning import ProgressTracker
        ProgressTracker().restore_from_snapshot(goal2, snap)
        self.assertEqual(
            sum(1 for m in goal2.milestones if m.status == "completed"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
