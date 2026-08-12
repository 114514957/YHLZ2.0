"""YHLZ Embodied AI V4.3 - Experience Learner unit tests (rule-based)."""
import os
import tempfile
import unittest

from backend.embodied.experience.learner import (
    ExperienceLearner,
    ExperienceLearnerError,
)
from backend.embodied.replay import GoalStep, GoalTrace
from backend.embodied.schema import (
    EmbodiedAction,
    EmbodiedGoal,
    Feedback,
    FeedbackAnalysis,
)


def make_action(action_type="pick", target="lamp", params=None) -> EmbodiedAction:
    return EmbodiedAction.create(
        action_type=action_type, target=target, parameters=params or {},
    )


def make_failure(cause="position_mismatch", result="failure"):
    return Feedback.create(result=result), FeedbackAnalysis.create(cause=cause)


def make_trace(goal_id="g-1") -> GoalTrace:
    return GoalTrace(
        goal_id=goal_id,
        goal={"description": "test", "constraints": {"max_steps": 5}},
        steps=[GoalStep(step_index=1, action={"action_type": "scan"})],
    )


class TestLearnerInit(unittest.TestCase):

    def test_defaults(self):
        lr = ExperienceLearner()
        self.assertTrue(lr.enabled)
        self.assertTrue(lr.planning_use_recipe)
        self.assertEqual(lr.stats()["failure_threshold"], 2)
        self.assertEqual(lr.stats()["min_suggestions"], 3)

    def test_failure_threshold_zero_raises(self):
        with self.assertRaises(ExperienceLearnerError):
            ExperienceLearner(failure_threshold=0)

    def test_configure(self):
        lr = ExperienceLearner()
        lr.configure(failure_threshold=5, min_suggestions=2, min_hit_rate=0.3,
                     planning_use_recipe=False, enabled=False)
        stats = lr.stats()
        self.assertEqual(stats["failure_threshold"], 5)
        self.assertEqual(stats["min_suggestions"], 2)
        self.assertEqual(stats["min_hit_rate"], 0.3)
        self.assertFalse(lr.planning_use_recipe)
        self.assertFalse(lr.enabled)

    def test_configure_invalid_threshold(self):
        lr = ExperienceLearner()
        with self.assertRaises(ExperienceLearnerError):
            lr.configure(failure_threshold=0)


class TestOnActionResult(unittest.TestCase):

    def test_failure_below_threshold_no_policy(self):
        lr = ExperienceLearner(failure_threshold=2)
        fb, an = make_failure()
        p = lr.on_action_result(make_action("pick"), fb, an)
        self.assertIsNone(p)
        self.assertEqual(lr.table.count(), 0)
        self.assertEqual(
            lr.stats()["failure_pattern_counts"]["pick_failure_position"], 1
        )

    def test_failure_reaches_threshold_generates_policy(self):
        lr = ExperienceLearner(failure_threshold=2)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        p = lr.on_action_result(make_action("pick"), fb, an)
        self.assertIsNotNone(p)
        self.assertEqual(p.trigger, "pick_failure_position")
        self.assertEqual(p.strategy, "move_to_target_before_pick")
        self.assertEqual(p.kind, "failure")
        self.assertEqual(p.required_action, "move")

    def test_success_result_no_policy(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb = Feedback.create(result="success")
        p = lr.on_action_result(make_action("pick"), fb, None)
        self.assertIsNone(p)
        self.assertEqual(lr.table.count(), 0)

    def test_unknown_pattern_no_policy(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure(cause="mystery")
        self.assertIsNone(lr.on_action_result(make_action("pick"), fb, an))
        self.assertEqual(lr.table.count(), 0)

    def test_disabled_ignores_failures(self):
        lr = ExperienceLearner(failure_threshold=1, enabled=False)
        fb, an = make_failure()
        self.assertIsNone(lr.on_action_result(make_action("pick"), fb, an))
        self.assertEqual(lr.table.count(), 0)

    def test_none_args_safe(self):
        lr = ExperienceLearner()
        self.assertIsNone(lr.on_action_result(None, None, None))

    def test_merge_same_trigger(self):
        lr = ExperienceLearner(failure_threshold=2)
        fb, an = make_failure()
        for _ in range(4):
            lr.on_action_result(make_action("pick"), fb, an)
        self.assertIsNotNone(lr.table.get("pick_failure_position"))
        self.assertEqual(lr.table.count(), 1)


class TestOnGoalComplete(unittest.TestCase):

    def test_success_generates_recipe(self):
        lr = ExperienceLearner()
        goal = EmbodiedGoal.create(description="pick lamp", target="lamp",
                                   constraints={"max_steps": 5})
        recipe = lr.on_goal_complete(goal, make_trace(goal.goal_id), success=True,
                                     executed_actions=[
                                         {"action_type": "move", "parameters": {"dx": 1},
                                          "success": True},
                                         {"action_type": "pick", "parameters": {},
                                          "success": True},
                                     ])
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.kind, "success")
        self.assertEqual(recipe.trigger, "recipe_move")
        self.assertIn(goal.goal_id, recipe.source_goal_ids)

    def test_failure_no_recipe(self):
        lr = ExperienceLearner()
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        recipe = lr.on_goal_complete(goal, make_trace(goal.goal_id), success=False,
                                     executed_actions=[
                                         {"action_type": "pick", "parameters": {},
                                          "success": False},
                                     ])
        self.assertIsNone(recipe)

    def test_accepted_stat_suggestion_with_required_action(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        suggestions = [{
            "type": "warning", "trigger": "pick_failure_position",
            "strategy": "move_to_target_before_pick", "kind": "failure",
            "detail": "d", "hit_rate": 0.0, "degraded": False,
        }]
        lr.on_goal_complete(goal, make_trace(goal.goal_id), success=True,
                            suggestions=suggestions,
                            executed_actions=[
                                {"action_type": "move", "success": True},
                                {"action_type": "pick", "success": True},
                            ])
        p = lr.table.get("pick_failure_position")
        self.assertEqual(p.accepted_count, 1)
        self.assertEqual(p.success_count, 1)

    def test_applied_policies_direct_acceptance(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        lr.on_goal_complete(goal, make_trace(goal.goal_id), success=False,
                            applied_policies=["pick_failure_position"])
        p = lr.table.get("pick_failure_position")
        self.assertEqual(p.accepted_count, 1)
        self.assertEqual(p.success_count, 0)

    def test_goal_complete_triggers_degradation(self):
        lr = ExperienceLearner(failure_threshold=1, min_suggestions=3)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        plan = [make_action("pick")]
        for _ in range(3):
            suggestions = lr.suggest_for_goal(goal, plan)
            lr.on_goal_complete(goal, make_trace(goal.goal_id), success=True,
                                suggestions=suggestions,
                                executed_actions=[
                                    {"action_type": "scan", "success": True},
                                ])
        self.assertTrue(lr.table.get("pick_failure_position").degraded)


class TestSuggestForGoal(unittest.TestCase):

    def test_success_recipe_returns_template(self):
        lr = ExperienceLearner()
        goal = EmbodiedGoal.create(description="pick lamp", target="lamp",
                                   constraints={"max_steps": 5})
        lr.on_goal_complete(goal, make_trace(goal.goal_id), success=True,
                            executed_actions=[
                                {"action_type": "move", "success": True},
                                {"action_type": "pick", "success": True},
                            ])
        suggestions = lr.suggest_for_goal(goal, [make_action("move")])
        templates = [s for s in suggestions if s["type"] == "template"]
        self.assertGreaterEqual(len(templates), 1)
        self.assertEqual(templates[0]["trigger"], "recipe_move")
        self.assertEqual(templates[0]["kind"], "success")
        self.assertFalse(templates[0]["degraded"])

    def test_failure_policy_returns_warning(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        suggestions = lr.suggest_for_goal(goal, [make_action("pick")])
        warnings = [s for s in suggestions if s["type"] == "warning"]
        self.assertGreaterEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["trigger"], "pick_failure_position")
        self.assertEqual(warnings[0]["kind"], "failure")
        self.assertIn("detail", warnings[0])

    def test_degraded_policy_excluded(self):
        lr = ExperienceLearner(failure_threshold=1, min_suggestions=3)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        plan = [make_action("pick")]
        for _ in range(3):
            suggestions = lr.suggest_for_goal(goal, plan)
            lr.on_goal_complete(goal, make_trace(goal.goal_id), success=True,
                                suggestions=suggestions,
                                executed_actions=[{"action_type": "scan", "success": True}])
        self.assertTrue(lr.table.get("pick_failure_position").degraded)
        suggestions = lr.suggest_for_goal(goal, plan)
        self.assertEqual([s for s in suggestions if s["type"] == "warning"], [])

    def test_disabled_returns_empty(self):
        lr = ExperienceLearner(enabled=False)
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        self.assertEqual(lr.suggest_for_goal(goal, [make_action("pick")]), [])

    def test_planning_use_recipe_off(self):
        lr = ExperienceLearner(planning_use_recipe=False)
        goal = EmbodiedGoal.create(description="pick lamp", target="lamp",
                                   constraints={"max_steps": 5})
        lr.on_goal_complete(goal, make_trace(goal.goal_id), success=True,
                            executed_actions=[{"action_type": "move", "success": True}])
        suggestions = lr.suggest_for_goal(goal, [make_action("move")])
        self.assertEqual([s for s in suggestions if s["type"] == "template"], [])

    def test_no_matching_policy_empty(self):
        lr = ExperienceLearner()
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        self.assertEqual(lr.suggest_for_goal(goal, [make_action("scan")]), [])

    def test_suggest_increments_count(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        goal = EmbodiedGoal.create(description="x", constraints={"max_steps": 5})
        lr.suggest_for_goal(goal, [make_action("pick")])
        self.assertEqual(lr.table.get("pick_failure_position").suggest_count, 1)


class TestLearnerSafetyAndStats(unittest.TestCase):

    def test_mode_rule_based(self):
        """Pure rules: no neural training / black-box learning."""
        lr = ExperienceLearner()
        self.assertEqual(lr.stats()["mode"], "rule_based")
        self.assertEqual(lr.stats()["table"]["mode"], "rule_based")
        self.assertEqual(lr.stats()["patterns"]["mode"], "rule_based")

    def test_get_policy(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        self.assertIsNotNone(lr.get_policy("pick_failure_position"))
        self.assertIsNone(lr.get_policy("nope"))

    def test_report_dict(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        report = lr.report_dict()
        self.assertIn("stats", report)
        self.assertIn("policies", report)
        self.assertEqual(report["stats"]["total"], 1)

    def test_save_load_policy(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.jsonl")
            self.assertEqual(lr.save_policy(path), 1)
            lr2 = ExperienceLearner()
            self.assertEqual(lr2.load_policy(path), 1)
            self.assertIsNotNone(lr2.get_policy("pick_failure_position"))

    def test_reset(self):
        lr = ExperienceLearner(failure_threshold=1)
        fb, an = make_failure()
        lr.on_action_result(make_action("pick"), fb, an)
        lr.reset()
        self.assertEqual(lr.table.count(), 0)
        self.assertEqual(lr.stats()["failure_pattern_counts"], {})


if __name__ == "__main__":
    unittest.main()
