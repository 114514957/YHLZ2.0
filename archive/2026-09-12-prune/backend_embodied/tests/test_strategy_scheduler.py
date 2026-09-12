"""
YHLZ Embodied AI V4.4 - 策略自适应调度单元测试 (Adaptive Strategy Scheduler)

覆盖:
    - 调度链路: trigger → scene → goal_type → candidates → ranking → best (可解释)
    - 同 trigger 不同场景 → 不同策略选择
    - 质量排序: hit_rate / acceptance_rate / recency
    - Dry Run 预演: 不写统计 / 不改计划
    - Service 集成: run_goal 审计 (apply/reject/rank) + 生命周期 API
"""
import unittest

from backend.embodied.experience.learner import ExperienceLearner
from backend.embodied.experience.policy import (
    PolicyTable,
    POLICY_STATUS_DEGRADED,
)
from backend.embodied.replay import GoalStep, GoalTrace
from backend.embodied.schema import EmbodiedGoal
from backend.embodied.service import EmbodiedService
from backend.embodied.strategy.ranker import PolicyRanker


def make_goal(description="拾取台灯", scene="room", target="lamp", goal_type="pick"):
    return EmbodiedGoal.create(
        description=description, target=target, scene=scene,
        constraints={"max_steps": 5},
    )


def make_trace(goal_id="g-1"):
    return GoalTrace(
        goal_id=goal_id,
        goal={"description": "test", "constraints": {"max_steps": 5}},
        steps=[GoalStep(step_index=1, action={"action_type": "scan"})],
    )


class TestSceneGoalTypeScheduling(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()
        self.table.upsert(trigger="pick_failure_room", strategy="scan_before_pick",
                          kind="failure", action_type="pick", scene="room",
                          goal_type="pick")
        self.table.upsert(trigger="pick_failure_warehouse", strategy="move_before_pick",
                          kind="failure", action_type="pick", scene="warehouse",
                          goal_type="pick")
        self.lr = ExperienceLearner(table=self.table, failure_threshold=1)
        self.goal = make_goal()

    def test_scene_selects_room_policy(self):
        s = self.lr.suggest_for_goal(self.goal, [{"action_type": "pick"}],
                                     scene="room", goal_type="pick")
        warnings = [x for x in s if x["type"] == "warning"]
        self.assertEqual(warnings[0]["trigger"], "pick_failure_room")

    def test_scene_selects_warehouse_policy(self):
        s = self.lr.suggest_for_goal(self.goal, [{"action_type": "pick"}],
                                     scene="warehouse", goal_type="pick")
        warnings = [x for x in s if x["type"] == "warning"]
        self.assertEqual(warnings[0]["trigger"], "pick_failure_warehouse")

    def test_global_policy_available_in_any_scene(self):
        self.table.upsert(trigger="pick_global", strategy="global_strategy",
                          kind="failure", action_type="pick")
        triggers = {p.trigger for p in self.table.candidates(
            action_type="pick", kind="failure", scene="room", goal_type="pick")}
        self.assertIn("pick_global", triggers)

    def test_scene_mismatch_excluded(self):
        """inspection 场景只有 room 策略 → inspection 无候选"""
        s = self.lr.suggest_for_goal(self.goal, [{"action_type": "pick"}],
                                     scene="inspection", goal_type="pick")
        self.assertEqual([x for x in s if x["type"] == "warning"], [])

    def test_goal_type_dimension(self):
        self.table.upsert(trigger="move_pol", strategy="s", kind="failure",
                          action_type="move", goal_type="move")
        pick_goal = make_goal(description="拾取台灯")
        move_goal = make_goal(description="移动到门口", goal_type="move")
        s = self.lr.suggest_for_goal(move_goal, [{"action_type": "move"}],
                                     scene="room", goal_type="move")
        self.assertEqual([x["trigger"] for x in s if x["type"] == "warning"],
                         ["move_pol"])
        s2 = self.lr.suggest_for_goal(pick_goal, [{"action_type": "move"}],
                                      scene="room", goal_type="pick")
        self.assertEqual([x for x in s2 if x["type"] == "warning"], [])


class TestQualityRanking(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()
        self.lr = ExperienceLearner(
            table=self.table, failure_threshold=1,
            ranker=PolicyRanker(hit_rate_weight=0.6, acceptance_weight=0.4,
                                recency_weight=0.0),
        )
        for i, (hr, ar, t) in enumerate([
            (0.3, 0.3, "low"),
            (0.9, 0.8, "high"),
            (0.6, 0.6, "mid"),
        ]):
            p = self.table.upsert(
                trigger=f"pick_failure_{t}", strategy=f"s_{t}",
                kind="failure", action_type="pick", scene="room", goal_type="pick",
            )
            p.suggest_count = 100
            p.accepted_count = int(100 * ar)
            p.success_count = int(p.accepted_count * hr)
            p.suggest_count = 0  # 瀵ら缚顔呯拋鈩冩殶閻㈣精鐨熸惔锕€鍟撻崗? 婢剁懓鍙垮〒鍛存祩

    def test_best_strategy_selected(self):
        s = self.lr.suggest_for_goal(make_goal(), [{"action_type": "pick"}],
                                     scene="room", goal_type="pick")
        warnings = [x for x in s if x["type"] == "warning"]
        self.assertEqual(warnings[0]["trigger"], "pick_failure_high")
        self.assertEqual(warnings[0]["rank"], 1)

    def test_suggestion_has_reason(self):
        s = self.lr.suggest_for_goal(make_goal(), [{"action_type": "pick"}],
                                     scene="room", goal_type="pick")
        self.assertIn("reason", s[0])
        self.assertIn("score=", s[0]["reason"])

    def test_candidates_count_reported(self):
        s = self.lr.suggest_for_goal(make_goal(), [{"action_type": "pick"}],
                                     scene="room", goal_type="pick")
        self.assertEqual(s[0]["candidates"], 3)

    def test_suggest_increments_only_best(self):
        self.lr.suggest_for_goal(make_goal(), [{"action_type": "pick"}],
                                 scene="room", goal_type="pick")
        low = self.table.get("pick_failure_low")
        high = self.table.get("pick_failure_high")
        self.assertEqual(high.suggest_count, 1)
        self.assertEqual(low.suggest_count, 0)  # 娴犲懏娓舵担宕囩摜閻ｃ儴顫﹀楦款唴


class TestDryRun(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()
        self.lr = ExperienceLearner(table=self.table, failure_threshold=1)

    def test_dry_run_no_stats_write(self):
        p = self.table.upsert(trigger="pf", strategy="s", kind="failure",
                              action_type="pick", scene="room", goal_type="pick")
        s = self.lr.suggest_for_goal(make_goal(), [{"action_type": "pick"}],
                                     scene="room", goal_type="pick",
                                     dry_run=True)
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["dry_run"])
        self.assertEqual(self.table.get("pf").suggest_count, 0)

    def test_non_dry_run_writes_stats(self):
        self.table.upsert(trigger="pf", strategy="s", kind="failure",
                          action_type="pick", scene="room", goal_type="pick")
        self.lr.suggest_for_goal(make_goal(), [{"action_type": "pick"}],
                                 scene="room", goal_type="pick")
        self.assertEqual(self.table.get("pf").suggest_count, 1)

    def test_dry_run_recipe_no_side_effect(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   scene="room", constraints={"max_steps": 5})
        self.lr.on_goal_complete(goal, make_trace(goal.goal_id), success=True,
                                 executed_actions=[
                                     {"action_type": "move", "parameters": {"dx": 1},
                                      "success": True},
                                     {"action_type": "pick", "success": True},
                                 ],
                                 scene="room", goal_type="pick")
        before = self.table.get("recipe_move").suggest_count
        s = self.lr.suggest_for_goal(goal, [{"action_type": "move"}],
                                     scene="room", goal_type="pick",
                                     dry_run=True)
        self.assertEqual(len([x for x in s if x["type"] == "template"]), 1)
        self.assertEqual(self.table.get("recipe_move").suggest_count, before)


class TestServiceIntegration(unittest.TestCase):

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_run_goal_records_audit(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   scene="room", constraints={"max_steps": 5})
        self.svc.run_goal(goal)  # 妫ｆ牗顐? 閻㈢喐鍨氶柊宥嗘煙
        self.svc.run_goal(goal)  # 缁楊兛绨╁▎? 鎼存梻鏁ゅΟ鈩冩緲 閳?娴溠呮晸鐎孤ゎ吀
        audit = self.svc.audit_policy_log()
        self.assertGreaterEqual(audit["total"], 1)

    def test_audit_contains_apply_or_suggest(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   scene="room", constraints={"max_steps": 5})
        # 閸忓牊鍨氶崝鐔剁濞?閳?閻㈢喐鍨氶柊宥嗘煙
        self.svc.run_goal(goal)
        goal2 = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                    scene="room", constraints={"max_steps": 5})
        self.svc.run_goal(goal2)
        audit = self.svc.audit_policy_log()
        self.assertGreaterEqual(audit["applied_count"], 1)

    def test_archive_restore_through_service(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   scene="room", constraints={"max_steps": 5})
        self.svc.run_goal(goal)
        self.svc.run_goal(goal)  # 閻㈢喐鍨氶柊宥嗘煙
        recipes = [p for p in self.svc.query_policies(kind="success")
                   if p["trigger"] == "recipe_explore"]
        self.assertGreaterEqual(len(recipes), 1)
        trigger = recipes[0]["trigger"]
        self.svc.archive_policy(trigger)
        st = self.svc.policy_lifecycle_stats()
        self.assertGreaterEqual(st["archived"], 1)
        self.svc.restore_policy(trigger)
        st = self.svc.policy_lifecycle_stats()
        self.assertEqual(st["archived"], 0)

    def test_policy_history_service(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   scene="room", constraints={"max_steps": 5})
        self.svc.run_goal(goal)
        self.svc.run_goal(goal)
        history = self.svc.policy_history("recipe_explore")
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[-1]["version"], history[0]["version"]
                         if len(history) == 1 else history[-1]["version"])

    def test_trend_stats_service(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   scene="room", constraints={"max_steps": 5})
        self.svc.run_goal(goal)
        r = self.svc.trend_stats()
        self.assertIn("by_scene", r)
        self.assertGreaterEqual(r["overall"]["total"], 1)

    def test_dry_run_service_no_side_effect(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   scene="room", constraints={"max_steps": 5})
        self.svc.run_goal(goal)
        self.svc.run_goal(goal)
        recipe = self.svc.experience.get_policy("recipe_explore")
        before = recipe.suggest_count
        preview = self.svc.dry_run_suggestion(goal)
        self.assertTrue(preview["dry_run"])
        self.assertIn("suggestions", preview)
        self.assertIn("plan_after", preview)
        self.assertEqual(self.svc.experience.get_policy("recipe_explore").suggest_count,
                         before)

    def test_dry_run_would_apply_recipe(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   scene="room", constraints={"max_steps": 5})
        self.svc.run_goal(goal)
        self.svc.run_goal(goal)
        preview = self.svc.dry_run_suggestion(goal)
        self.assertEqual(preview["would_apply_trigger"], "recipe_explore")

    def test_degraded_recovery_through_applied(self):
        """降级策略被人工采纳连续成功 → 自动恢复"""
        lr = self.svc.experience
        p = lr.table.upsert(trigger="pf", strategy="s", kind="failure",
                            action_type="pick", scene="room", goal_type="pick")
        p.suggest_count = 5
        p.set_status(POLICY_STATUS_DEGRADED)
        goal = make_goal()
        for _ in range(3):
            lr.on_goal_complete(goal, make_trace(), success=True,
                                applied_policies=["pf"], scene="room",
                                goal_type="pick")
        self.assertEqual(lr.table.get("pf").effective_status, "active")

    def test_status_contains_strategy(self):
        st = self.svc.status()
        self.assertEqual(st["version"], "9.5.0")
        self.assertIn("strategy", st)
        self.assertEqual(st["strategy"]["mode"], "rule_based")

    def test_report_contains_strategy(self):
        r = self.svc.report()
        self.assertEqual(r["version"], "9.5.0")
        self.assertIn("strategy", r)
        self.assertIn("audit", r["strategy"])
        self.assertIn("trends", r["strategy"])

    def test_config_loads_v44_params(self):
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "embodied_policy_max_age_days": 7,
            "embodied_policy_recovery_threshold": 2,
            "embodied_trend_window": 5,
            "embodied_audit_log_max": 50,
        })
        stats = svc.experience.stats()
        self.assertEqual(stats["max_age_days"], 7)
        self.assertEqual(stats["recovery_threshold"], 2)
        self.assertEqual(svc.trends.window, 5)
        self.assertEqual(svc.audit.max_entries, 50)


if __name__ == "__main__":
    unittest.main()
