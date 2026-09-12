"""
YHLZ Embodied AI V4.7 - 长期目标与里程碑单元测试 (Long Goal & Milestone)

覆盖 (milestone.py):
    - LongGoal 数据模型: 字段 / to_dict / from_dict / create
    - 状态机: pending → active → paused / completed / failed / archived
    - Milestone 数据模型: 字段 / 状态机 (pending/running/completed/failed/blocked)
    - MilestoneManager: 创建 / 分解 (decompose_goal → 任务树) / 子目标
    - 里程碑生命周期: complete_milestone / rollback_milestone / query_progress
    - 参数校验: 非法状态 / 重复分解 / 空阶段

设计原则验证:
    - 状态机校验 (非法迁移拒绝)
    - 可解释 reason
"""
import unittest

from backend.embodied.planning import (
    LONG_GOAL_STATUSES,
    MILESTONE_STATUSES,
    LongGoal,
    LongHorizonError,
    Milestone,
    MilestoneManager,
)


class TestLongGoalModel(unittest.TestCase):
    """LongGoal 数据模型"""

    def test_create_defaults(self):
        """创建默认: pending / medium / progress 0"""
        g = LongGoal.create(title="整理房间")
        self.assertEqual(g.status, "pending")
        self.assertEqual(g.priority, "medium")
        self.assertEqual(g.progress, 0.0)
        self.assertEqual(g.milestones, [])
        self.assertTrue(g.goal_id)

    def test_create_fields(self):
        """创建字段完整"""
        g = LongGoal.create(title="学习", description="学 Python",
                            priority="high", deadline=100.0)
        self.assertEqual(g.title, "学习")
        self.assertEqual(g.description, "学 Python")
        self.assertEqual(g.priority, "high")
        self.assertEqual(g.deadline, 100.0)

    def test_to_dict_structure(self):
        """to_dict 含全部字段"""
        g = LongGoal.create(title="t")
        d = g.to_dict()
        for key in ("goal_id", "title", "description", "created_at",
                    "status", "milestones", "dependencies", "progress",
                    "priority", "deadline", "explainable_reason"):
            self.assertIn(key, d)

    def test_from_dict_roundtrip(self):
        """from_dict 往返一致"""
        g = LongGoal.create(title="t", priority="high")
        g.set_status("active", "测试")
        d = g.to_dict()
        g2 = LongGoal.from_dict(d)
        self.assertEqual(g2.goal_id, g.goal_id)
        self.assertEqual(g2.title, g.title)
        self.assertEqual(g2.status, "active")
        self.assertEqual(g2.priority, "high")

    def test_from_dict_with_milestones(self):
        """from_dict 还原里程碑"""
        g = LongGoal.create(title="t")
        m = Milestone.create(title="m1", goal_id=g.goal_id)
        g.milestones.append(m)
        g2 = LongGoal.from_dict(g.to_dict())
        self.assertEqual(len(g2.milestones), 1)
        self.assertEqual(g2.milestones[0].title, "m1")

    def test_status_valid(self):
        """合法状态全部可用"""
        g = LongGoal.create(title="t")
        for s in LONG_GOAL_STATUSES:
            g.set_status(s)
            self.assertEqual(g.status, s)

    def test_status_invalid_raises(self):
        """非法状态 → LongHorizonError"""
        g = LongGoal.create(title="t")
        with self.assertRaises(LongHorizonError):
            g.set_status("unknown")

    def test_status_sets_reason(self):
        """状态变更记录可解释 reason"""
        g = LongGoal.create(title="t")
        g.set_status("active", "开始执行")
        self.assertEqual(g.explainable_reason, "开始执行")


class TestMilestoneModel(unittest.TestCase):
    """Milestone 数据模型"""

    def test_create_defaults(self):
        """创建默认: pending / completion_rate 0"""
        m = Milestone.create(title="阶段1")
        self.assertEqual(m.status, "pending")
        self.assertEqual(m.completion_rate, 0.0)
        self.assertEqual(m.sub_goals, [])

    def test_add_sub_goal(self):
        """添加子目标"""
        m = Milestone.create(title="阶段1")
        m.add_sub_goal(title="变量", description="学变量")
        self.assertEqual(len(m.sub_goals), 1)
        self.assertEqual(m.sub_goals[0]["title"], "变量")
        self.assertIn("sub_goal_id", m.sub_goals[0])

    def test_set_status_valid(self):
        """合法迁移: pending → running → completed"""
        m = Milestone.create(title="m")
        m.set_status("running")
        self.assertEqual(m.status, "running")
        m.set_status("completed")
        self.assertEqual(m.status, "completed")
        self.assertEqual(m.completion_rate, 1.0)

    def test_set_status_invalid_raises(self):
        """非法迁移: pending → failed 不允许"""
        m = Milestone.create(title="m")
        with self.assertRaises(LongHorizonError):
            m.set_status("failed")

    def test_completed_rollback(self):
        """completed → failed (回滚)"""
        m = Milestone.create(title="m")
        m.set_status("running")
        m.set_status("completed")
        m.set_status("failed")
        self.assertEqual(m.status, "failed")

    def test_blocked_transition(self):
        """pending → blocked → running"""
        m = Milestone.create(title="m")
        m.set_status("blocked")
        m.set_status("running")
        self.assertEqual(m.status, "running")

    def test_to_dict_fields(self):
        """to_dict 字段完整"""
        m = Milestone.create(title="m", order=2)
        d = m.to_dict()
        for key in ("milestone_id", "goal_id", "title", "sub_goals",
                    "order", "status", "completion_rate",
                    "estimated_duration"):
            self.assertIn(key, d)
        self.assertEqual(d["order"], 2)


class TestMilestoneManager(unittest.TestCase):
    """MilestoneManager 生命周期"""

    def setUp(self):
        self.mgr = MilestoneManager()

    def test_create_long_goal(self):
        """创建长期目标"""
        g = self.mgr.create_long_goal(title="整理房间")
        self.assertEqual(g.status, "pending")
        self.assertIsNotNone(self.mgr.get(g.goal_id))

    def test_get_missing(self):
        """不存在的目标 → None"""
        self.assertIsNone(self.mgr.get("nope"))

    def test_all(self):
        """全部目标"""
        self.mgr.create_long_goal(title="a")
        self.mgr.create_long_goal(title="b")
        self.assertEqual(len(self.mgr.all()), 2)

    def test_decompose_goal(self):
        """分解 → 里程碑 + 状态 active"""
        g = self.mgr.create_long_goal(title="整理房间")
        self.mgr.decompose_goal(g, ["收集", "分类", "整理", "检查", "维护"])
        self.assertEqual(len(g.milestones), 5)
        self.assertEqual(g.status, "active")
        self.assertEqual(g.milestones[0].order, 0)
        self.assertEqual(g.milestones[4].order, 4)

    def test_decompose_with_sub_goals(self):
        """分解 + 子目标"""
        g = self.mgr.create_long_goal(title="学习")
        self.mgr.decompose_goal(
            g, ["基础", "进阶"],
            sub_goals_map={"基础": ["变量", "函数"], "进阶": ["类"]},
        )
        self.assertEqual(len(g.milestones[0].sub_goals), 2)
        self.assertEqual(len(g.milestones[1].sub_goals), 1)

    def test_decompose_empty_phases_raises(self):
        """空阶段 → LongHorizonError"""
        g = self.mgr.create_long_goal(title="t")
        with self.assertRaises(LongHorizonError):
            self.mgr.decompose_goal(g, [])

    def test_decompose_unknown_goal_raises(self):
        """未注册目标 → LongHorizonError"""
        g = LongGoal.create(title="t")
        with self.assertRaises(LongHorizonError):
            self.mgr.decompose_goal(g, ["a"])

    def test_decompose_twice_raises(self):
        """重复分解 → LongHorizonError"""
        g = self.mgr.create_long_goal(title="t")
        self.mgr.decompose_goal(g, ["a", "b"])
        with self.assertRaises(LongHorizonError):
            self.mgr.decompose_goal(g, ["c"])

    def test_complete_milestone_progress(self):
        """完成里程碑 → 进度更新"""
        g = self.mgr.create_long_goal(title="t")
        self.mgr.decompose_goal(g, ["a", "b", "c", "d"])
        self.mgr.complete_milestone(g, g.milestones[0].milestone_id)
        self.assertEqual(g.progress, 0.25)
        self.assertEqual(g.milestones[0].status, "completed")

    def test_complete_all_goal_completed(self):
        """全部完成 → 目标 completed"""
        g = self.mgr.create_long_goal(title="t")
        self.mgr.decompose_goal(g, ["a", "b"])
        for m in g.milestones:
            self.mgr.complete_milestone(g, m.milestone_id)
        self.assertEqual(g.status, "completed")
        self.assertEqual(g.progress, 1.0)

    def test_rollback_milestone(self):
        """回滚 → completed 变 failed + 目标重激活"""
        g = self.mgr.create_long_goal(title="t")
        self.mgr.decompose_goal(g, ["a", "b"])
        self.mgr.complete_milestone(g, g.milestones[0].milestone_id)
        self.mgr.complete_milestone(g, g.milestones[1].milestone_id)
        self.assertEqual(g.status, "completed")
        self.mgr.rollback_milestone(g, g.milestones[1].milestone_id)
        self.assertEqual(g.milestones[1].status, "failed")
        self.assertEqual(g.status, "active")
        self.assertEqual(g.progress, 0.5)

    def test_rollback_updates_reason(self):
        """回滚记录可解释原因"""
        g = self.mgr.create_long_goal(title="t")
        self.mgr.decompose_goal(g, ["a"])
        mid = g.milestones[0].milestone_id
        self.mgr.complete_milestone(g, mid)
        self.mgr.rollback_milestone(g, mid)
        self.assertIn("回滚", g.explainable_reason)

    def test_query_progress(self):
        """进度查询结构"""
        g = self.mgr.create_long_goal(title="t")
        self.mgr.decompose_goal(g, ["a", "b", "c"])
        self.mgr.complete_milestone(g, g.milestones[0].milestone_id)
        r = self.mgr.query_progress(g)
        self.assertEqual(r["completed"], 1)
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["next"]["title"], "b")
        self.assertEqual(r["goal_status"], "active")

    def test_query_progress_next_none(self):
        """全部完成 → next=None"""
        g = self.mgr.create_long_goal(title="t")
        self.mgr.decompose_goal(g, ["a"])
        self.mgr.complete_milestone(g, g.milestones[0].milestone_id)
        r = self.mgr.query_progress(g)
        self.assertIsNone(r["next"])

    def test_get_milestone_missing_raises(self):
        """不存在的里程碑 → LongHorizonError"""
        g = self.mgr.create_long_goal(title="t")
        self.mgr.decompose_goal(g, ["a"])
        with self.assertRaises(LongHorizonError):
            self.mgr.get_milestone(g, "nope")

    def test_clear(self):
        """清理全部"""
        self.mgr.create_long_goal(title="a")
        self.mgr.create_long_goal(title="b")
        self.assertEqual(self.mgr.clear(), 2)
        self.assertEqual(len(self.mgr.all()), 0)

    def test_remove(self):
        """移除单个"""
        g = self.mgr.create_long_goal(title="a")
        self.assertTrue(self.mgr.remove(g.goal_id))
        self.assertFalse(self.mgr.remove(g.goal_id))


if __name__ == "__main__":
    unittest.main()
