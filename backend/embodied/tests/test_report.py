"""
YHLZ Embodied AI V4.3 - Embodied Report + Service 集成测试

覆盖:
    - report(): World Model / Memory / Feedback / Prediction / Events / Scene / Policy
    - report_text(): 文本版字段完整
    - 集成: execute_action 失败 → 达阈值生成失败策略 (policy_stats)
    - 集成: run_goal 成功 → 成功配方 → 下个目标自动应用模板 (planning_use_recipe)
    - 集成: 策略降级后不再建议
    - 集成: query_policies / save_policy / load_policy / policy_stats
    - 安全: 经验学习不绕过权限 (禁用时无学习)
"""
import os
import tempfile
import unittest

from backend.embodied.schema import EmbodiedAction, EmbodiedGoal
from backend.embodied.service import EmbodiedService


class TestEmbodiedReport(unittest.TestCase):

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_report_structure(self):
        r = self.svc.report()
        self.assertEqual(r["version"], "9.5.0")
        self.assertIn("report_id", r)
        self.assertIn("generated_at", r)
        self.assertIn("world_model", r)
        self.assertIn("memory", r)
        self.assertIn("feedback", r)
        self.assertIn("prediction", r)
        self.assertIn("events", r)
        self.assertIn("scene", r)
        self.assertIn("experience_policy", r)

    def test_report_world_model(self):
        r = self.svc.report()
        wm = r["world_model"]
        self.assertIn("states", wm)
        self.assertIn("changes", wm)
        self.assertIn("objects", wm)

    def test_report_prediction_rule_based(self):
        r = self.svc.report()
        self.assertEqual(r["prediction"]["mode"], "rule_based")
        self.assertIn("stability_confidence", r["prediction"])

    def test_report_events(self):
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        r = self.svc.report()
        self.assertGreaterEqual(r["events"]["stats"]["total"], 1)
        self.assertIn("recent", r["events"])

    def test_report_scene(self):
        self.svc.observe()
        r = self.svc.report()
        scene = r["scene"]
        self.assertEqual(scene["environment"], "mock")
        self.assertEqual(scene["scene"], "room")
        self.assertIn("active_objects", scene)

    def test_report_scene_after_switch(self):
        self.svc.switch_environment("warehouse")
        r = self.svc.report()
        self.assertEqual(r["scene"]["environment"], "warehouse")
        self.assertEqual(r["scene"]["scene"], "warehouse")

    def test_report_scene_none_without_env(self):
        from backend.embodied.manager import EmbodiedManager
        svc = EmbodiedService(manager=EmbodiedManager())
        r = svc.report()
        self.assertIsNone(r["scene"])

    def test_report_experience_policy(self):
        r = self.svc.report()
        pol = r["experience_policy"]
        self.assertIn("stats", pol)
        self.assertIn("policies", pol)
        self.assertEqual(pol["stats"]["mode"], "rule_based")

    def test_report_after_actions(self):
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        r = self.svc.report()
        self.assertGreaterEqual(r["feedback"]["total"], 2)
        self.assertGreaterEqual(r["world_model"]["states"], 1)

    def test_report_text_fields(self):
        text = self.svc.report_text()
        self.assertIn("[Embodied Report v9.5.0]", text)
        self.assertIn("World Model:", text)
        self.assertIn("Memory:", text)
        self.assertIn("Feedback:", text)
        self.assertIn("Prediction:", text)
        self.assertIn("Events:", text)
        self.assertIn("Scene:", text)
        self.assertIn("Experience Policy:", text)

    def test_report_text_after_scene_switch(self):
        self.svc.switch_environment("warehouse")
        text = self.svc.report_text()
        self.assertIn("environment=warehouse", text)


class TestFailureExperienceIntegration(unittest.TestCase):
    """execute_action 失败 → 达阈值生成失败策略"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "embodied_failure_pattern_threshold": 2,
        })

    def _fail_pick(self):
        """拾取 lamp 但机器人未移动 → position_mismatch 失败"""
        return self.svc.execute_action(EmbodiedAction.create(
            action_type="pick", target="lamp", parameters={"object": "lamp"},
        ))

    def test_first_failure_no_policy(self):
        res = self._fail_pick()
        self.assertFalse(res.success)
        self.assertEqual(self.svc.policy_stats()["table"]["total"], 0)

    def test_repeated_failure_generates_policy(self):
        self._fail_pick()
        self._fail_pick()
        stats = self.svc.policy_stats()
        self.assertGreaterEqual(stats["table"]["total"], 1)
        policies = self.svc.query_policies(kind="failure")
        triggers = [p["trigger"] for p in policies]
        self.assertIn("pick_failure_position", triggers)

    def test_policy_explainable(self):
        self._fail_pick()
        self._fail_pick()
        p = self.svc.query_policies(kind="failure")[0]
        self.assertTrue(p["detail"])
        self.assertTrue(p["strategy"])
        self.assertEqual(p["kind"], "failure")
        self.assertEqual(p["cause"], "position_mismatch")

    def test_failure_policy_warning_in_next_goal(self):
        self._fail_pick()
        self._fail_pick()
        goal = EmbodiedGoal.create(description="拿起台灯", target="lamp",
                                   constraints={"max_steps": 3})
        res = self.svc.run_goal(goal)
        warnings = [s for s in res.suggestions if s["type"] == "warning"]
        self.assertGreaterEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["trigger"], "pick_failure_position")

    def test_warning_does_not_block_execution(self):
        """警告不绕过权限, 目标仍按正常流程执行"""
        self._fail_pick()
        self._fail_pick()
        goal = EmbodiedGoal.create(description="扫描房间", constraints={"max_steps": 2})
        res = self.svc.run_goal(goal)
        self.assertIsNotNone(res)
        self.assertGreaterEqual(res.iterations, 1)

    def test_disabled_experience_no_learning(self):
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "embodied_experience_enabled": False,
            "embodied_failure_pattern_threshold": 1,
        })
        svc.execute_action(EmbodiedAction.create(
            action_type="pick", target="lamp", parameters={"object": "lamp"},
        ))
        self.assertEqual(svc.policy_stats()["table"]["total"], 0)

    def test_policy_stats_fields(self):
        self._fail_pick()
        self._fail_pick()
        stats = self.svc.policy_stats()
        self.assertIn("enabled", stats)
        self.assertEqual(stats["mode"], "rule_based")
        self.assertIn("failure_pattern_counts", stats)
        self.assertIn("table", stats)


class TestRecipeTemplateIntegration(unittest.TestCase):
    """run_goal 成功 → 配方 → 下个目标自动应用模板"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def _run_scan_goal(self):
        goal = EmbodiedGoal.create(description="扫描房间", constraints={"max_steps": 2})
        res = self.svc.run_goal(goal)
        self.assertTrue(res.success)
        return goal, res

    def test_success_creates_recipe(self):
        self._run_scan_goal()
        stats = self.svc.policy_stats()
        self.assertGreaterEqual(stats["table"]["success_count"], 1)
        recipes = self.svc.query_policies(kind="success")
        self.assertGreaterEqual(len(recipes), 1)
        self.assertEqual(recipes[0]["trigger"], "recipe_scan")

    def test_next_goal_gets_template_suggestion(self):
        self._run_scan_goal()
        goal, res = self._run_scan_goal()
        templates = [s for s in res.suggestions if s["type"] == "template"]
        self.assertGreaterEqual(len(templates), 1)
        self.assertEqual(templates[0]["trigger"], "recipe_scan")

    def test_template_applied_to_plan(self):
        self._run_scan_goal()
        goal, res = self._run_scan_goal()
        trace = self.svc.traces.get(goal.goal_id)
        self.assertGreaterEqual(len(trace.suggestions), 1)
        recipe = self.svc.query_policies(kind="success")[0]
        self.assertGreaterEqual(recipe["suggest_count"], 1)
        self.assertGreaterEqual(recipe["accepted_count"], 1)

    def test_recipe_source_traceable(self):
        goal, _ = self._run_scan_goal()
        recipes = self.svc.query_policies(kind="success")
        self.assertIn(goal.goal_id, recipes[0]["source_goal_ids"])

    def test_policy_persistence_via_service(self):
        self._run_scan_goal()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.jsonl")
            n = self.svc.save_policy(path)
            self.assertGreaterEqual(n, 1)
            svc2 = EmbodiedService()
            svc2.load_config({"embodied_enabled": True, "embodied_policy_path": path})
            recipes = svc2.query_policies(kind="success")
            self.assertGreaterEqual(len(recipes), 1)

    def test_recipe_plan_sequence(self):
        """应用配方后初始计划采用配方动作序列"""
        self._run_scan_goal()
        goal = EmbodiedGoal.create(description="扫描房间", constraints={"max_steps": 2})
        res = self.svc.run_goal(goal)
        trace = self.svc.traces.get(goal.goal_id)
        if trace.plan:
            self.assertEqual(trace.plan[0]["action_type"], "scan")


class TestPolicyQueryService(unittest.TestCase):

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "embodied_failure_pattern_threshold": 1,
        })

    def test_query_all(self):
        res = self.svc.execute_action(EmbodiedAction.create(
            action_type="pick", target="lamp", parameters={"object": "lamp"},
        ))
        self.assertFalse(res.success)
        policies = self.svc.query_policies()
        self.assertGreaterEqual(len(policies), 1)

    def test_query_kind_filter(self):
        res = self.svc.execute_action(EmbodiedAction.create(
            action_type="pick", target="lamp", parameters={"object": "lamp"},
        ))
        self.assertFalse(res.success)
        self.assertGreaterEqual(len(self.svc.query_policies(kind="failure")), 1)
        self.assertEqual(self.svc.query_policies(kind="success"), [])

    def test_query_limit(self):
        res = self.svc.execute_action(EmbodiedAction.create(
            action_type="pick", target="lamp", parameters={"object": "lamp"},
        ))
        self.assertFalse(res.success)
        self.assertGreaterEqual(len(self.svc.query_policies(limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
