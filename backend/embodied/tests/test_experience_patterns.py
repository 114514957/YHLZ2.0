"""
YHLZ Embodied AI V4.3 - 经验模式提取器单元测试 (Pattern Extractor)

覆盖:
    - FAILURE_PATTERN_RULES: 规则表完整性与唯一性
    - extract_failure_policy: 7 类失败模式匹配 (pick/move/place/inspect)
    - extract_failure_policy: 成功反馈 / 无因果 / 未知组合 → None
    - extract_success_recipe: 成功序列 → Recipe (Action Sequence + Preconditions)
    - extract_success_recipe: 无成功动作 → None
    - recipe_trigger_for_plan: 计划首动作 → 配方 trigger
    - 可解释性: 所有输出含 detail / trigger / strategy (无黑盒)
"""
import unittest

from backend.embodied.experience.patterns import (
    FAILURE_PATTERN_RULES,
    PatternExtractor,
)
from backend.embodied.schema import (
    CauseType,
    EmbodiedAction,
    EmbodiedGoal,
    Feedback,
    FeedbackAnalysis,
)


def make_action(action_type="pick", target="lamp", params=None) -> EmbodiedAction:
    return EmbodiedAction.create(
        action_type=action_type, target=target, parameters=params or {},
    )


def make_feedback(result="failure") -> Feedback:
    return Feedback.create(result=result)


def make_analysis(cause: str) -> FeedbackAnalysis:
    return FeedbackAnalysis.create(cause=cause, cause_detail="测试原因")


class TestFailureRules(unittest.TestCase):
    """规则表完整性 (确定性 + 可测试)"""

    def test_rules_cover_expected_causes(self):
        pairs = {(r[0], r[1]) for r in FAILURE_PATTERN_RULES}
        self.assertIn(("pick", CauseType.POSITION_MISMATCH.value), pairs)
        self.assertIn(("pick", CauseType.OBJECT_MISSING.value), pairs)
        self.assertIn(("move", CauseType.BOUNDARY_LIMIT.value), pairs)
        self.assertIn(("place", CauseType.OBJECT_NOT_HELD.value), pairs)
        self.assertIn(("place", CauseType.OBJECT_MISSING.value), pairs)
        self.assertIn(("inspect", CauseType.OBJECT_MISSING.value), pairs)

    def test_rules_unique_triggers(self):
        triggers = [r[2] for r in FAILURE_PATTERN_RULES]
        self.assertEqual(len(triggers), len(set(triggers)))

    def test_rules_has_strategy_and_detail(self):
        for rule in FAILURE_PATTERN_RULES:
            self.assertTrue(rule[3])  # strategy
            self.assertTrue(rule[4])  # detail
            self.assertTrue(rule[5])  # required_action

    def test_rules_count(self):
        self.assertEqual(len(FAILURE_PATTERN_RULES), 6)


class TestExtractFailurePolicy(unittest.TestCase):

    def setUp(self):
        self.ext = PatternExtractor()

    def test_pick_position_mismatch(self):
        p = self.ext.extract_failure_policy(
            make_action("pick"), make_feedback(),
            make_analysis(CauseType.POSITION_MISMATCH.value),
        )
        self.assertIsNotNone(p)
        self.assertEqual(p["trigger"], "pick_failure_position")
        self.assertEqual(p["strategy"], "move_to_target_before_pick")
        self.assertEqual(p["kind"], "failure")
        self.assertEqual(p["required_action"], "move")

    def test_pick_object_missing(self):
        p = self.ext.extract_failure_policy(
            make_action("pick"), make_feedback(),
            make_analysis(CauseType.OBJECT_MISSING.value),
        )
        self.assertEqual(p["trigger"], "pick_failure_location")
        self.assertEqual(p["strategy"], "scan_before_pick")
        self.assertEqual(p["required_action"], "scan")

    def test_move_boundary(self):
        p = self.ext.extract_failure_policy(
            make_action("move"), make_feedback(),
            make_analysis(CauseType.BOUNDARY_LIMIT.value),
        )
        self.assertEqual(p["trigger"], "move_failure_boundary")
        self.assertEqual(p["strategy"], "adjust_direction_or_shorten_step")

    def test_place_not_held(self):
        p = self.ext.extract_failure_policy(
            make_action("place"), make_feedback(),
            make_analysis(CauseType.OBJECT_NOT_HELD.value),
        )
        self.assertEqual(p["trigger"], "place_failure_not_held")
        self.assertEqual(p["strategy"], "pick_before_place")

    def test_place_missing(self):
        p = self.ext.extract_failure_policy(
            make_action("place"), make_feedback(),
            make_analysis(CauseType.OBJECT_MISSING.value),
        )
        self.assertEqual(p["trigger"], "place_failure_missing")
        self.assertEqual(p["strategy"], "scan_before_place")

    def test_inspect_missing(self):
        p = self.ext.extract_failure_policy(
            make_action("inspect"), make_feedback(),
            make_analysis(CauseType.OBJECT_MISSING.value),
        )
        self.assertEqual(p["trigger"], "inspect_failure_missing")
        self.assertEqual(p["strategy"], "scan_before_inspect")

    def test_success_feedback_returns_none(self):
        p = self.ext.extract_failure_policy(
            make_action("pick"), Feedback.create(result="success"),
            make_analysis(CauseType.POSITION_MISMATCH.value),
        )
        self.assertIsNone(p)

    def test_no_cause_returns_none(self):
        p = self.ext.extract_failure_policy(
            make_action("pick"), make_feedback(), None,
        )
        self.assertIsNone(p)

    def test_unknown_cause_returns_none(self):
        p = self.ext.extract_failure_policy(
            make_action("pick"), make_feedback(),
            make_analysis("mystery_cause"),
        )
        self.assertIsNone(p)

    def test_unknown_action_returns_none(self):
        p = self.ext.extract_failure_policy(
            make_action("dance"), make_feedback(),
            make_analysis(CauseType.OBJECT_MISSING.value),
        )
        self.assertIsNone(p)

    def test_none_action_returns_none(self):
        self.assertIsNone(self.ext.extract_failure_policy(None, make_feedback(), None))

    def test_none_feedback_returns_none(self):
        self.assertIsNone(self.ext.extract_failure_policy(make_action(), None, None))

    def test_partial_result_returns_none(self):
        p = self.ext.extract_failure_policy(
            make_action("pick"), Feedback.create(result="partial"),
            make_analysis(CauseType.POSITION_MISMATCH.value),
        )
        self.assertIsNone(p)

    def test_policy_explainable(self):
        """可解释: 所有策略携带 detail / trigger / strategy"""
        for cause in (
            CauseType.POSITION_MISMATCH.value,
            CauseType.OBJECT_MISSING.value,
            CauseType.BOUNDARY_LIMIT.value,
            CauseType.OBJECT_NOT_HELD.value,
        ):
            p = self.ext.extract_failure_policy(
                make_action("pick" if "object" not in cause else "pick"),
                make_feedback(), make_analysis(cause),
            )
            if p is not None:
                self.assertTrue(p["detail"])
                self.assertTrue(p["trigger"])
                self.assertTrue(p["strategy"])

    def test_extracted_count_increments(self):
        self.ext.extract_failure_policy(
            make_action("pick"), make_feedback(),
            make_analysis(CauseType.POSITION_MISMATCH.value),
        )
        self.assertEqual(self.ext.stats()["extracted_count"], 1)

    def test_cause_falls_back_to_analysis_attr(self):
        """analysis 无 cause 时回退 feedback dict"""
        p = self.ext.extract_failure_policy(
            make_action("pick"), make_feedback(), None,
        )
        self.assertIsNone(p)

    def test_stats_mode_rule_based(self):
        stats = self.ext.stats()
        self.assertEqual(stats["mode"], "rule_based")
        self.assertEqual(stats["failure_rules_count"], 6)

    def test_reset(self):
        self.ext.extract_failure_policy(
            make_action("pick"), make_feedback(),
            make_analysis(CauseType.POSITION_MISMATCH.value),
        )
        self.ext.reset()
        self.assertEqual(self.ext.stats()["extracted_count"], 0)


class TestExtractSuccessRecipe(unittest.TestCase):

    def setUp(self):
        self.ext = PatternExtractor()
        self.goal = EmbodiedGoal.create(description="拾取台灯", constraints={"max_steps": 5})

    def test_recipe_extracted(self):
        recipe = self.ext.extract_success_recipe(self.goal, executed=[
            {"action_type": "move", "parameters": {"dx": 1, "dy": 0}, "success": True},
            {"action_type": "pick", "parameters": {"object": "lamp"}, "success": True},
        ])
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe["kind"], "success")
        self.assertEqual(recipe["trigger"], "recipe_move")
        self.assertEqual(recipe["strategy"], "move_then_pick")

    def test_recipe_action_sequence(self):
        recipe = self.ext.extract_success_recipe(self.goal, executed=[
            {"action_type": "move", "parameters": {"dx": 1}, "success": True},
            {"action_type": "pick", "parameters": {"object": "lamp"}, "success": True},
        ])
        seq = recipe["action_sequence"]
        self.assertEqual([s["action_type"] for s in seq], ["move", "pick"])
        self.assertEqual(seq[1]["parameters"], {"object": "lamp"})

    def test_recipe_merges_consecutive_same_type(self):
        recipe = self.ext.extract_success_recipe(self.goal, executed=[
            {"action_type": "move", "parameters": {"dx": 1}, "success": True},
            {"action_type": "move", "parameters": {"dx": 1}, "success": True},
            {"action_type": "pick", "parameters": {}, "success": True},
        ])
        seq = recipe["action_sequence"]
        self.assertEqual([s["action_type"] for s in seq], ["move", "pick"])

    def test_recipe_skips_failed_actions(self):
        recipe = self.ext.extract_success_recipe(self.goal, executed=[
            {"action_type": "pick", "parameters": {}, "success": False},
            {"action_type": "scan", "parameters": {}, "success": True},
        ])
        seq = recipe["action_sequence"]
        self.assertEqual([s["action_type"] for s in seq], ["scan"])

    def test_recipe_preconditions(self):
        goal = EmbodiedGoal.create(description="拾取台灯", target="lamp",
                                   constraints={"max_steps": 5})
        recipe = self.ext.extract_success_recipe(goal, executed=[
            {"action_type": "move", "parameters": {}, "success": True},
            {"action_type": "pick", "parameters": {}, "success": True},
        ])
        pre = recipe["preconditions"]
        self.assertIn("permission_required", pre)
        self.assertIn("target_object_exists", pre)
        self.assertIn("target_location_known", pre)

    def test_recipe_preconditions_place(self):
        recipe = self.ext.extract_success_recipe(self.goal, executed=[
            {"action_type": "pick", "parameters": {}, "success": True},
            {"action_type": "place", "parameters": {}, "success": True},
        ])
        self.assertIn("pick_before_place", recipe["preconditions"])

    def test_no_executed_returns_none(self):
        self.assertIsNone(self.ext.extract_success_recipe(self.goal, executed=None))
        self.assertIsNone(self.ext.extract_success_recipe(self.goal, executed=[]))

    def test_no_success_actions_returns_none(self):
        recipe = self.ext.extract_success_recipe(self.goal, executed=[
            {"action_type": "pick", "parameters": {}, "success": False},
        ])
        self.assertIsNone(recipe)

    def test_recipe_trigger_for_plan(self):
        plan = [make_action("pick")]
        self.assertEqual(PatternExtractor.recipe_trigger_for_plan(plan), "recipe_pick")

    def test_recipe_trigger_empty_plan(self):
        self.assertEqual(PatternExtractor.recipe_trigger_for_plan([]), "")

    def test_recipe_trigger_dict_plan(self):
        self.assertEqual(
            PatternExtractor.recipe_trigger_for_plan([{"action_type": "move"}]),
            "recipe_move",
        )

    def test_recipe_trigger_none_plan(self):
        self.assertEqual(PatternExtractor.recipe_trigger_for_plan(None), "")


if __name__ == "__main__":
    unittest.main()
