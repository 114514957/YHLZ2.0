"""
YHLZ Embodied AI V4.6 - 目标关系分析单元测试 (Goal Dependency Analysis)

覆盖 (dependency.py):
    - plan_action_sequence: 目标 → 动作序列 (关键词规则, 多动作收集)
    - infer_goal_type_of: 目标类型推断
    - 目标分组: 相同 scene × goal_type × action_sequence → 目标组
    - 批量规划标记: member_count > 1 → batch_plan
    - 共享步骤: 组内共同前置 scan/observe → 只执行一次 (节省步骤)
    - 信息复用: 感知目标 (scan) 一次执行, 同场景目标复用信息
    - 参数校验: min_group_size <= 0 → DependencyError

设计原则验证:
    - 只读分析 (不修改任何状态)
    - 纯规则 + 可解释输出
"""
import unittest

from backend.embodied.planning import (
    DependencyError,
    GoalDependencyAnalyzer,
    SHARABLE_ACTION_TYPES,
    infer_goal_type_of,
    plan_action_sequence,
)
from backend.embodied.schema import EmbodiedGoal


def make_goal(description="拿起台灯", intent="pick", target="lamp",
              scene="room", priority="medium", **kw):
    return EmbodiedGoal.create(
        description=description, intent=intent, target=target,
        scene=scene, priority=priority, **kw,
    )


class TestPlanActionSequence(unittest.TestCase):
    """目标 → 动作序列映射"""

    def test_single_keyword(self):
        """单关键词 → 单动作"""
        g = make_goal(description="拿起台灯", intent="pick")
        seq = plan_action_sequence(g)
        self.assertEqual(seq, [{"action_type": "pick", "target": "lamp"}])

    def test_scan_keyword(self):
        """扫描 → scan"""
        g = make_goal(description="扫描房间", intent="scan")
        seq = plan_action_sequence(g)
        self.assertEqual(seq[0]["action_type"], "scan")

    def test_move_keyword(self):
        """移动 → move"""
        g = make_goal(description="移动到门口", intent="move")
        seq = plan_action_sequence(g)
        self.assertEqual(seq[0]["action_type"], "move")

    def test_inspect_keyword(self):
        """检查 → inspect"""
        g = make_goal(description="检查台灯", intent="inspect")
        seq = plan_action_sequence(g)
        self.assertEqual(seq[0]["action_type"], "inspect")

    def test_chinese_keywords(self):
        """中文关键词支持"""
        g = make_goal(description="拿起台灯", intent="")
        seq = plan_action_sequence(g)
        self.assertEqual(seq[0]["action_type"], "pick")

    def test_multi_action_sequence(self):
        """多关键词 → 多动作 (scan + pick)"""
        g = make_goal(description="扫描房间再拿起台灯", intent="scan pick")
        seq = plan_action_sequence(g)
        types = [s["action_type"] for s in seq]
        self.assertEqual(types, ["scan", "pick"])

    def test_no_keyword_explore(self):
        """无关键词 → explore 兜底"""
        g = make_goal(description="随便逛逛", intent="")
        seq = plan_action_sequence(g)
        self.assertEqual(seq[0]["action_type"], "explore")

    def test_none_goal(self):
        """None 目标 → 空序列"""
        self.assertEqual(plan_action_sequence(None), [])

    def test_target_preserved(self):
        """target 保留在动作中"""
        g = make_goal(target="cup")
        seq = plan_action_sequence(g)
        self.assertEqual(seq[0]["target"], "cup")


class TestInferGoalType(unittest.TestCase):
    """目标类型推断"""

    def test_intent_wins(self):
        """intent 优先"""
        g = make_goal(intent="pick")
        self.assertEqual(infer_goal_type_of(g, [{"action_type": "scan"}]), "pick")

    def test_main_action_fallback(self):
        """无 intent 无 target → 主动作 (序列最后一步)"""
        g = make_goal(intent="", target="")
        seq = [{"action_type": "scan"}, {"action_type": "pick"}]
        self.assertEqual(infer_goal_type_of(g, seq), "pick")

    def test_target_custom(self):
        """有 target 无 intent → custom"""
        g = make_goal(intent="", target="lamp")
        self.assertEqual(infer_goal_type_of(g, []), "custom")

    def test_none_goal(self):
        """None 目标 → 空"""
        self.assertEqual(infer_goal_type_of(None, []), "")


class TestGoalGroups(unittest.TestCase):
    """目标分组: 相同 scene × goal_type × action_sequence"""

    def setUp(self):
        self.analyzer = GoalDependencyAnalyzer(min_group_size=2)

    def test_same_scene_type_group(self):
        """同 scene + 同 goal_type + 同动作 → 成组"""
        g1 = make_goal(description="拿起台灯", intent="pick", scene="room")
        g2 = make_goal(description="拿起杯子", intent="pick", scene="room")
        r = self.analyzer.analyze_groups([g1, g2])
        self.assertEqual(r["total"], 1)
        g = r["groups"][0]
        self.assertEqual(g["member_count"], 2)
        self.assertEqual(g["scene"], "room")
        self.assertEqual(g["goal_type"], "pick")
        self.assertTrue(g["batch_plan"])

    def test_different_scene_not_grouped(self):
        """不同 scene → 不分组"""
        g1 = make_goal(scene="room")
        g2 = make_goal(scene="warehouse")
        r = self.analyzer.analyze_groups([g1, g2])
        self.assertEqual(r["total"], 0)

    def test_different_goal_type_not_grouped(self):
        """不同 goal_type → 不分组"""
        g1 = make_goal(intent="pick")
        g2 = make_goal(intent="move")
        r = self.analyzer.analyze_groups([g1, g2])
        self.assertEqual(r["total"], 0)

    def test_different_action_sequence_not_grouped(self):
        """不同动作序列 → 不分组"""
        g1 = make_goal(description="扫描再拿起", intent="scan pick")
        g2 = make_goal(description="直接拿起", intent="pick")
        r = self.analyzer.analyze_groups([g1, g2])
        self.assertEqual(r["total"], 0)

    def test_same_target_different_scene_separate(self):
        """同内容不同场景 → 独立组 (各自不足 2)"""
        g1 = make_goal(scene="room")
        g2 = make_goal(scene="warehouse")
        r = self.analyzer.analyze_groups([g1, g2])
        self.assertEqual(r["total"], 0)

    def test_three_members_group(self):
        """3 个同组目标 → member_count=3"""
        goals = [
            make_goal(description=f"拿起对象{i}", intent="pick", scene="room")
            for i in range(3)
        ]
        r = self.analyzer.analyze_groups(goals)
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["groups"][0]["member_count"], 3)
        self.assertEqual(r["batched_goals"], 3)

    def test_min_group_size_1(self):
        """min_group_size=1 → 单目标也成组"""
        a = GoalDependencyAnalyzer(min_group_size=1)
        g = make_goal()
        r = a.analyze_groups([g])
        self.assertEqual(r["total"], 1)

    def test_goal_ids_listed(self):
        """组输出含 goal_ids"""
        g1 = make_goal()
        g2 = make_goal()
        r = self.analyzer.analyze_groups([g1, g2])
        self.assertEqual(set(r["groups"][0]["goal_ids"]), {g1.goal_id, g2.goal_id})

    def test_batched_goals_count(self):
        """batched_goals 统计参与批量目标数"""
        g1 = make_goal()
        g2 = make_goal()
        g3 = make_goal(intent="scan", description="扫描")
        r = self.analyzer.analyze_groups([g1, g2, g3])
        self.assertEqual(r["batched_goals"], 2)

    def test_invalid_min_group_size(self):
        """min_group_size <= 0 → DependencyError"""
        with self.assertRaises(DependencyError):
            GoalDependencyAnalyzer(min_group_size=0)


class TestSharedSteps(unittest.TestCase):
    """共享步骤识别: 组内共同前置 scan → 只执行一次"""

    def setUp(self):
        self.analyzer = GoalDependencyAnalyzer(min_group_size=2)

    def _group_with_scan(self):
        g1 = make_goal(description="扫描再拿起台灯", intent="scan pick", scene="room")
        g2 = make_goal(description="扫描再拿起杯子", intent="scan pick", scene="room")
        return self.analyzer.analyze_groups([g1, g2])

    def test_scan_shared(self):
        """组内共同前置 scan → 共享步骤"""
        groups = self._group_with_scan()
        r = self.analyzer.shared_steps(groups)
        self.assertEqual(r["total_saved"], 1)
        s = r["shared_steps"][0]
        self.assertEqual(s["action_type"], "scan")
        self.assertEqual(s["member_count"], 2)
        self.assertEqual(s["saved_steps"], 1)
        self.assertIn("服务 2 个目标", s["reason"])

    def test_pick_not_shared(self):
        """主动作 (pick) 不共享"""
        groups = self._group_with_scan()
        r = self.analyzer.shared_steps(groups)
        for s in r["shared_steps"]:
            self.assertNotEqual(s["action_type"], "pick")

    def test_single_action_no_shared(self):
        """单动作序列 (无前置) → 无共享"""
        g1 = make_goal(description="拿起台灯", intent="pick")
        g2 = make_goal(description="拿起杯子", intent="pick")
        groups = self.analyzer.analyze_groups([g1, g2])
        r = self.analyzer.shared_steps(groups)
        self.assertEqual(r["total_saved"], 0)

    def test_three_members_saved_two(self):
        """3 成员共享 scan → 节省 2 步"""
        goals = [
            make_goal(description=f"扫描再拿起{i}", intent="scan pick", scene="room")
            for i in range(3)
        ]
        groups = self.analyzer.analyze_groups(goals)
        r = self.analyzer.shared_steps(groups)
        self.assertEqual(r["total_saved"], 2)

    def test_no_groups_no_shared(self):
        """无组 → 无共享"""
        r = self.analyzer.shared_steps({"groups": []})
        self.assertEqual(r["total_saved"], 0)

    def test_goal_ids_in_shared(self):
        """共享步骤携带组内 goal_ids"""
        groups = self._group_with_scan()
        r = self.analyzer.shared_steps(groups)
        self.assertEqual(len(r["shared_steps"][0]["goal_ids"]), 2)


class TestInformationReuse(unittest.TestCase):
    """信息复用: 感知目标一次执行服务多目标"""

    def setUp(self):
        self.analyzer = GoalDependencyAnalyzer(min_group_size=2)

    def test_scan_provides_info(self):
        """scan 目标 + 同场景消费目标 → 复用组"""
        scan = make_goal(description="扫描房间", intent="scan", scene="room")
        pick1 = make_goal(description="拿起台灯", intent="pick", scene="room")
        pick2 = make_goal(description="拿起杯子", intent="pick", scene="room")
        r = self.analyzer.information_reuse([scan, pick1, pick2])
        self.assertEqual(r["total"], 1)
        g = r["reuse_groups"][0]
        self.assertEqual(g["provider_action"], "scan")
        self.assertEqual(g["consumer_count"], 2)

    def test_no_consumer_no_reuse(self):
        """无同场景消费者 → 无复用"""
        scan = make_goal(description="扫描", intent="scan", scene="room")
        pick = make_goal(description="拿起", intent="pick", scene="warehouse")
        r = self.analyzer.information_reuse([scan, pick])
        self.assertEqual(r["total"], 0)

    def test_no_provider_no_reuse(self):
        """无感知目标 → 无复用"""
        g1 = make_goal(intent="pick")
        g2 = make_goal(intent="move")
        r = self.analyzer.information_reuse([g1, g2])
        self.assertEqual(r["total"], 0)

    def test_sharable_types(self):
        """可共享动作类型 = scan/observe/explore"""
        self.assertEqual(set(SHARABLE_ACTION_TYPES),
                         {"scan", "observe", "explore"})

    def test_reason_explainable(self):
        """复用原因可解释"""
        scan = make_goal(description="扫描", intent="scan", scene="room")
        pick = make_goal(description="拿起", intent="pick", scene="room")
        r = self.analyzer.information_reuse([scan, pick])
        self.assertIn("复用", r["reuse_groups"][0]["reason"])


class TestReadOnly(unittest.TestCase):
    """只读分析验证"""

    def setUp(self):
        self.analyzer = GoalDependencyAnalyzer(min_group_size=2)

    def test_analysis_does_not_modify_goals(self):
        """分析不修改目标对象"""
        g1 = make_goal()
        g2 = make_goal()
        before1 = g1.to_dict()
        before2 = g2.to_dict()
        self.analyzer.analyze_groups([g1, g2])
        self.analyzer.shared_steps({"groups": []})
        self.analyzer.information_reuse([g1, g2])
        self.assertEqual(g1.to_dict(), before1)
        self.assertEqual(g2.to_dict(), before2)


if __name__ == "__main__":
    unittest.main()
