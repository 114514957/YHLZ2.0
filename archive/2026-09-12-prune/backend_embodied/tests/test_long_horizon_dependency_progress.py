"""
YHLZ Embodied AI V4.7 - 依赖关系与进度跟踪单元测试
(Dependency Graph + Progress Tracker + Snapshot)

覆盖 (dependency_graph.py):
    - set_dependencies: 校验 (里程碑存在 / 循环检测)
    - dependency_graph: 前置/后续/阻塞原因/循环警告
    - compute_blocked: 阻塞计算
    - execution_order: 拓扑排序

覆盖 (progress_tracker.py):
    - get_progress: 百分比/完成数/阻塞/下一步
    - update_progress: 进度重算 + 100% 自动完成
    - progress_report: 文本报告 (Goal/Completed/Blocked/Next)
    - snapshot: Goal Snapshot (完成情况/阻塞点/下一步骤)
    - restore_from_snapshot: 断点恢复
"""
import unittest

from backend.embodied.planning import (
    DependencyGraph,
    DependencyGraphError,
    ProgressError,
    ProgressTracker,
)
from backend.embodied.planning.milestone import LongGoal, MilestoneManager


def make_decomposed(mgr, title="整理房间", phases=None):
    g = mgr.create_long_goal(title=title)
    mgr.decompose_goal(g, phases or ["收集", "分类", "整理", "检查", "维护"])
    return g


class TestDependencyGraph(unittest.TestCase):
    """依赖关系分析"""

    def setUp(self):
        self.mgr = MilestoneManager()
        self.graph = DependencyGraph()
        self.goal = make_decomposed(self.mgr)
        self.ms = [m.milestone_id for m in self.goal.milestones]

    def test_set_dependencies(self):
        """设置依赖"""
        self.graph.set_dependencies(
            self.goal, {self.ms[2]: [self.ms[0], self.ms[1]]},
        )
        self.assertEqual(self.goal.dependencies[self.ms[2]],
                         [self.ms[0], self.ms[1]])

    def test_set_dependencies_unknown_target(self):
        """目标里程碑不存在 → DependencyGraphError"""
        with self.assertRaises(DependencyGraphError):
            self.graph.set_dependencies(self.goal, {"nope": []})

    def test_set_dependencies_unknown_prereq(self):
        """前置不存在 → DependencyGraphError"""
        with self.assertRaises(DependencyGraphError):
            self.graph.set_dependencies(self.goal, {self.ms[0]: ["nope"]})

    def test_set_dependencies_cycle_raises(self):
        """循环依赖 → DependencyGraphError"""
        with self.assertRaises(DependencyGraphError):
            self.graph.set_dependencies(
                self.goal, {self.ms[0]: [self.ms[1]],
                            self.ms[1]: [self.ms[0]]},
            )

    def test_dependency_graph_nodes(self):
        """依赖图节点: 前置/后续"""
        self.graph.set_dependencies(
            self.goal, {self.ms[2]: [self.ms[0], self.ms[1]]},
        )
        r = self.graph.dependency_graph(self.goal)
        self.assertEqual(len(r["nodes"]), 5)
        n2 = next(n for n in r["nodes"] if n["milestone_id"] == self.ms[2])
        self.assertEqual(n2["prerequisites"], [self.ms[0], self.ms[1]])
        n0 = next(n for n in r["nodes"] if n["milestone_id"] == self.ms[0])
        self.assertIn(self.ms[2], n0["successors"])

    def test_blocked_reason(self):
        """前置未完成 → 阻塞原因"""
        self.graph.set_dependencies(
            self.goal, {self.ms[2]: [self.ms[0], self.ms[1]]},
        )
        r = self.graph.dependency_graph(self.goal)
        n2 = next(n for n in r["nodes"] if n["milestone_id"] == self.ms[2])
        self.assertTrue(n2["blocked"])
        self.assertIn("前置", n2["blocked_reason"])

    def test_no_block_after_complete(self):
        """前置完成后 → 不再阻塞"""
        self.graph.set_dependencies(
            self.goal, {self.ms[2]: [self.ms[0]]},
        )
        self.mgr.complete_milestone(self.goal, self.ms[0])
        r = self.graph.dependency_graph(self.goal)
        n2 = next(n for n in r["nodes"] if n["milestone_id"] == self.ms[2])
        self.assertFalse(n2["blocked"])

    def test_successors_listed(self):
        """后续任务列出"""
        self.graph.set_dependencies(
            self.goal, {self.ms[2]: [self.ms[0]]},
        )
        r = self.graph.dependency_graph(self.goal)
        n0 = next(n for n in r["nodes"] if n["milestone_id"] == self.ms[0])
        self.assertIn(self.ms[2], n0["successors"])

    def test_compute_blocked(self):
        """阻塞计算"""
        self.graph.set_dependencies(
            self.goal, {self.ms[3]: [self.ms[0], self.ms[1], self.ms[2]]},
        )
        blocked = self.graph.compute_blocked(self.goal)
        self.assertEqual(blocked, [self.ms[3]])

    def test_compute_blocked_empty(self):
        """无依赖 → 无阻塞"""
        self.assertEqual(self.graph.compute_blocked(self.goal), [])

    def test_execution_order_respects_deps(self):
        """拓扑顺序: 前置在前"""
        self.graph.set_dependencies(
            self.goal, {self.ms[4]: [self.ms[3]], self.ms[3]: [self.ms[2]]},
        )
        order = self.graph.execution_order(self.goal)
        idx = {o["milestone_id"]: i for i, o in enumerate(order)}
        self.assertLess(idx[self.ms[2]], idx[self.ms[3]])
        self.assertLess(idx[self.ms[3]], idx[self.ms[4]])

    def test_execution_order_all(self):
        """无依赖 → 全部按原顺序"""
        order = self.graph.execution_order(self.goal)
        self.assertEqual(len(order), 5)
        self.assertEqual(order[0]["milestone_id"], self.ms[0])


class TestProgressTracker(unittest.TestCase):
    """进度跟踪"""

    def setUp(self):
        self.mgr = MilestoneManager()
        self.tracker = ProgressTracker()
        self.goal = make_decomposed(self.mgr)
        self.ms = [m.milestone_id for m in self.goal.milestones]

    def test_get_progress_zero(self):
        """初始进度 0"""
        p = self.tracker.get_progress(self.goal)
        self.assertEqual(p["percent"], 0)
        self.assertEqual(p["completed"], 0)
        self.assertEqual(p["total"], 5)

    def test_get_progress_partial(self):
        """部分完成进度"""
        self.mgr.complete_milestone(self.goal, self.ms[0])
        self.mgr.complete_milestone(self.goal, self.ms[1])
        p = self.tracker.get_progress(self.goal)
        self.assertEqual(p["percent"], 40)
        self.assertEqual(p["completed"], 2)

    def test_next_milestone(self):
        """下一步骤 = 第一个 pending"""
        self.mgr.complete_milestone(self.goal, self.ms[0])
        p = self.tracker.get_progress(self.goal)
        self.assertEqual(p["next"]["title"], "分类")

    def test_update_progress(self):
        """update_progress 重算目标进度"""
        self.mgr.complete_milestone(self.goal, self.ms[0])
        self.tracker.update_progress(self.goal)
        self.assertEqual(self.goal.progress, 0.2)

    def test_update_progress_auto_complete(self):
        """100% → 自动完成"""
        for m in self.ms:
            self.mgr.complete_milestone(self.goal, m)
        self.tracker.update_progress(self.goal)
        self.assertEqual(self.goal.status, "completed")

    def test_get_progress_none_raises(self):
        """None 目标 → ProgressError"""
        with self.assertRaises(ProgressError):
            self.tracker.get_progress(None)

    def test_progress_report_format(self):
        """报告格式: Goal/Completed/Blocked/Next"""
        self.mgr.complete_milestone(self.goal, self.ms[0])
        rep = self.tracker.progress_report(self.goal)
        self.assertIn("Goal:", rep)
        self.assertIn("Completed: 1/5", rep)
        self.assertIn("Blocked: 0", rep)
        self.assertIn("Next:", rep)

    def test_progress_report_blocked(self):
        """报告含阻塞数"""
        graph = DependencyGraph()
        graph.set_dependencies(
            self.goal, {self.ms[4]: [self.ms[3]]},
        )
        tracker = ProgressTracker(graph)
        rep = tracker.progress_report(self.goal)
        self.assertIn("Blocked: 1", rep)

    def test_blocked_count_in_progress(self):
        """进度含阻塞计数"""
        graph = DependencyGraph()
        graph.set_dependencies(
            self.goal, {self.ms[2]: [self.ms[1]]},
        )
        tracker = ProgressTracker(graph)
        p = tracker.get_progress(self.goal)
        self.assertEqual(p["blocked"], 1)


class TestSnapshot(unittest.TestCase):
    """Goal Snapshot (P1, 支持恢复)"""

    def setUp(self):
        self.mgr = MilestoneManager()
        self.graph = DependencyGraph()
        self.tracker = ProgressTracker(self.graph)
        self.goal = make_decomposed(self.mgr)
        self.ms = [m.milestone_id for m in self.goal.milestones]

    def test_snapshot_structure(self):
        """快照字段完整"""
        snap = self.tracker.snapshot(self.goal)
        for key in ("snapshot_id", "goal_id", "title", "status",
                    "progress", "completed_milestones", "total_milestones",
                    "blocked_milestones", "next_step", "milestones",
                    "dependencies"):
            self.assertIn(key, snap)
        self.assertTrue(snap["snapshot_id"].startswith("snap_"))

    def test_snapshot_reflects_state(self):
        """快照反映当前状态"""
        self.mgr.complete_milestone(self.goal, self.ms[0])
        snap = self.tracker.snapshot(self.goal)
        self.assertEqual(snap["completed_milestones"], 1)
        self.assertEqual(snap["progress"], 0.2)

    def test_snapshot_blocked_points(self):
        """快照含阻塞点"""
        self.graph.set_dependencies(
            self.goal, {self.ms[2]: [self.ms[1]]},
        )
        snap = self.tracker.snapshot(self.goal)
        self.assertEqual(len(snap["blocked_milestones"]), 1)
        self.assertEqual(snap["blocked_milestones"][0]["title"], "整理")

    def test_snapshot_next_step(self):
        """快照含下一步骤"""
        self.mgr.complete_milestone(self.goal, self.ms[0])
        snap = self.tracker.snapshot(self.goal)
        self.assertEqual(snap["next_step"]["title"], "分类")

    def test_restore_from_snapshot(self):
        """从快照恢复 (断点恢复)"""
        # 完成 2 个, 保存快照
        self.mgr.complete_milestone(self.goal, self.ms[0])
        self.mgr.complete_milestone(self.goal, self.ms[1])
        snap = self.tracker.snapshot(self.goal)

        # 模拟新会话: 新目标 + 恢复
        g2 = make_decomposed(self.mgr, title="整理房间2")
        self.tracker.restore_from_snapshot(g2, snap)
        done = sum(1 for m in g2.milestones if m.status == "completed")
        self.assertEqual(done, 2)
        self.assertEqual(g2.progress, 0.4)

    def test_restore_preserves_dependencies(self):
        """恢复还原依赖关系 (按 order 映射)"""
        self.graph.set_dependencies(
            self.goal, {self.ms[2]: [self.ms[0]]},
        )
        snap = self.tracker.snapshot(self.goal)
        g2 = make_decomposed(self.mgr, title="t2")
        self.tracker.restore_from_snapshot(g2, snap)
        # 依赖被还原到 g2 的里程碑 (order 2 → order 0)
        self.assertEqual(len(g2.dependencies), 1)
        dep_mid, prereq = next(iter(g2.dependencies.items()))
        m2 = next(m for m in g2.milestones if m.milestone_id == dep_mid)
        m0 = next(m for m in g2.milestones if m.milestone_id == prereq[0])
        self.assertEqual(m2.order, 2)
        self.assertEqual(m0.order, 0)

    def test_restore_none_raises(self):
        """恢复参数校验"""
        with self.assertRaises(ProgressError):
            self.tracker.restore_from_snapshot(None, {})
        with self.assertRaises(ProgressError):
            self.tracker.restore_from_snapshot(self.goal, None)


if __name__ == "__main__":
    unittest.main()
