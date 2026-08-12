"""
YHLZ Embodied AI V4.1 - Service 单元测试

覆盖:
    - 默认拒绝 (embodied_enabled=False)
    - 单动作执行 (执行 / 权限 / 高风险确认 / 环境不可用)
    - 目标闭环 (Observe → Think → Plan → Act → Evaluate)
    - 规划器 (Plan 规则)
    - 目标校验
    - 世界模型写入 / 反馈记录
    - 查询 (feedback / world history)
    - V4.1: 反馈分析 / 状态预测 / 具身上下文 / 环境记忆 / 自适应规划
    - 单例 + 重置
"""
import unittest

from backend.embodied.manager import EmbodiedManager
from backend.embodied.permission import PermissionChecker
from backend.embodied.schema import (
    EmbodiedAction,
    EmbodiedActionType,
    EmbodiedGoal,
    EmbodiedStatus,
    FeedbackResult,
)
from backend.embodied.service import (
    EmbodiedOperationResult,
    EmbodiedService,
    EmbodiedServiceError,
    get_service,
    reset_service,
)


class TestServiceDefaultDeny(unittest.TestCase):

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({})

    def test_default_deny_action(self):
        """默认关闭: 动作被拒绝"""
        a = EmbodiedAction.create(action_type="scan")
        res = self.svc.execute_action(a)
        self.assertFalse(res.success)
        self.assertEqual(res.status, EmbodiedStatus.DENIED.value)
        self.assertIn("embodied_enabled=False", res.error)

    def test_default_deny_goal(self):
        g = EmbodiedGoal.create(description="扫描环境")
        res = self.svc.run_goal(g)
        self.assertFalse(res.success)
        self.assertEqual(res.status, EmbodiedStatus.DENIED.value)

    def test_action_does_not_reach_environment_when_denied(self):
        """动作不得绕过安全层: 拒绝时环境不得被调用"""
        a = EmbodiedAction.create(action_type="scan")
        self.svc.execute_action(a)
        # 閺冪姳鎹㈡担鏇炲冀妫?/ 閻樿埖鈧礁鍟撻崗?(閻滎垰顣ㄩ張顏囶潶鐟欙妇顫?
        self.assertEqual(self.svc.feedback_store.count(), 0)
        self.assertEqual(self.svc.world_model.count(), 0)

    def test_load_config_enabled(self):
        self.svc.load_config({"embodied_enabled": True})
        self.assertTrue(self.svc.get_permission()["embodied_enabled"])


class TestServiceExecuteAction(unittest.TestCase):

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_execute_scan_success(self):
        a = EmbodiedAction.create(action_type="scan", intent="扫描环境")
        res = self.svc.execute_action(a)
        self.assertTrue(res.success)
        self.assertEqual(res.status, EmbodiedStatus.OK.value)
        self.assertEqual(res.feedback.result, FeedbackResult.SUCCESS.value)
        self.assertIsNotNone(res.state)

    def test_execute_writes_world_model(self):
        a = EmbodiedAction.create(action_type="scan")
        self.svc.execute_action(a)
        self.assertEqual(self.svc.world_model.count(), 1)
        self.assertIsNotNone(self.svc.world_state())

    def test_execute_writes_feedback(self):
        a = EmbodiedAction.create(action_type="scan")
        self.svc.execute_action(a)
        self.assertEqual(self.svc.feedback_store.count(), 1)
        fb = self.svc.get_feedback(a.action_id)
        self.assertIsNotNone(fb)

    def test_execute_failure_result(self):
        a = EmbodiedAction.create(action_type="pick", target="ghost", parameters={"object": "ghost"})
        res = self.svc.execute_action(a)
        self.assertFalse(res.success)
        self.assertEqual(res.status, EmbodiedStatus.ERROR.value)
        self.assertEqual(res.feedback.result, FeedbackResult.FAILURE.value)

    def test_execute_high_risk_needs_confirm(self):
        a = EmbodiedAction.create(action_type="custom", intent="shutdown")
        res = self.svc.execute_action(a)
        self.assertEqual(res.status, EmbodiedStatus.AWAITING_CONFIRM.value)
        # 閺堫亞鈥樼拋?閳?閻滎垰顣ㄦ稉宥呯繁閹笛嗩攽
        self.assertEqual(self.svc.feedback_store.count(), 0)

    def test_execute_high_risk_confirmed(self):
        a = EmbodiedAction.create(action_type="custom", intent="shutdown")
        res = self.svc.execute_action(a, confirmed=True)
        self.assertTrue(res.success)
        self.assertEqual(res.status, EmbodiedStatus.OK.value)

    def test_execute_hardware_unsupported(self):
        a = EmbodiedAction.create(action_type="move", parameters={"environment": "hardware"})
        res = self.svc.execute_action(a)
        self.assertFalse(res.success)
        self.assertEqual(res.status, EmbodiedStatus.UNSUPPORTED.value)

    def test_execute_no_environment(self):
        mgr = EmbodiedManager()
        svc = EmbodiedService(manager=mgr)
        from backend.embodied.permission import EmbodiedPermissionConfig
        svc.load_permission(EmbodiedPermissionConfig(embodied_enabled=True))
        a = EmbodiedAction.create(action_type="scan")
        res = svc.execute_action(a)
        self.assertFalse(res.success)
        self.assertEqual(res.status, EmbodiedStatus.ERROR.value)
        self.assertIn("无可用环境", res.error)

    def test_execute_result_to_dict(self):
        a = EmbodiedAction.create(action_type="scan")
        res = self.svc.execute_action(a)
        d = res.to_dict()
        self.assertEqual(d["status"], "ok")
        self.assertIn("action", d)
        self.assertIn("feedback", d)


class TestServicePlanning(unittest.TestCase):

    def test_plan_scan(self):
        g = EmbodiedGoal.create(description="扫描整个房间")
        plan = EmbodiedService.plan_actions(g)
        self.assertEqual(plan[0].action_type, "scan")

    def test_plan_pick(self):
        g = EmbodiedGoal.create(description="拿起杯子", target="cup")
        plan = EmbodiedService.plan_actions(g)
        self.assertEqual(plan[0].action_type, "pick")
        self.assertEqual(plan[0].target, "cup")

    def test_plan_inspect(self):
        g = EmbodiedGoal.create(description="检查台灯", intent="inspect", target="lamp")
        plan = EmbodiedService.plan_actions(g)
        self.assertEqual(plan[0].action_type, "inspect")

    def test_plan_move(self):
        g = EmbodiedGoal.create(description="移动到门口")
        plan = EmbodiedService.plan_actions(g)
        self.assertEqual(plan[0].action_type, "move")

    def test_plan_place(self):
        g = EmbodiedGoal.create(description="放置箱子", target="box")
        plan = EmbodiedService.plan_actions(g)
        self.assertEqual(plan[0].action_type, "place")

    def test_plan_default_explore(self):
        g = EmbodiedGoal.create(description="随便看看")
        plan = EmbodiedService.plan_actions(g)
        self.assertEqual(plan[0].action_type, "explore")

    def test_plan_none(self):
        self.assertEqual(EmbodiedService.plan_actions(None), [])

    def test_plan_has_reason(self):
        g = EmbodiedGoal.create(description="扫描环境")
        plan = EmbodiedService.plan_actions(g)
        self.assertTrue(plan[0].reason)


class TestServiceValidateGoal(unittest.TestCase):

    def test_valid(self):
        ok, err = EmbodiedService.validate_goal(EmbodiedGoal.create(description="扫描环境"))
        self.assertTrue(ok)

    def test_valid_intent_only(self):
        ok, err = EmbodiedService.validate_goal(EmbodiedGoal.create(intent="inspect"))
        self.assertTrue(ok)

    def test_none(self):
        ok, err = EmbodiedService.validate_goal(None)
        self.assertFalse(ok)

    def test_empty(self):
        ok, err = EmbodiedService.validate_goal(EmbodiedGoal.create())
        self.assertFalse(ok)

    def test_bad_priority(self):
        g = EmbodiedGoal.create(description="x", priority="urgent")
        ok, err = EmbodiedService.validate_goal(g)
        self.assertFalse(ok)

    def test_bad_max_steps(self):
        g = EmbodiedGoal.create(description="x", constraints={"max_steps": 0})
        ok, err = EmbodiedService.validate_goal(g)
        self.assertFalse(ok)

    def test_non_numeric_max_steps(self):
        g = EmbodiedGoal.create(description="x", constraints={"max_steps": "abc"})
        ok, err = EmbodiedService.validate_goal(g)
        self.assertFalse(ok)


class TestServiceRunGoal(unittest.TestCase):

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_run_goal_success(self):
        g = EmbodiedGoal.create(description="扫描房间", constraints={"max_steps": 3})
        res = self.svc.run_goal(g)
        self.assertTrue(res.success)
        self.assertEqual(res.status, EmbodiedStatus.OK.value)
        self.assertEqual(res.goal.goal_id, g.goal_id)
        self.assertGreaterEqual(res.iterations, 1)

    def test_run_goal_writes_history(self):
        g = EmbodiedGoal.create(description="扫描房间")
        self.svc.run_goal(g)
        self.assertGreaterEqual(self.svc.feedback_store.count(), 1)
        self.assertGreaterEqual(self.svc.world_model.count(), 1)

    def test_run_goal_invalid(self):
        res = self.svc.run_goal(EmbodiedGoal.create())
        self.assertEqual(res.status, EmbodiedStatus.INVALID.value)

    def test_run_goal_max_iterations(self):
        g = EmbodiedGoal.create(description="移动", constraints={"max_steps": 2})
        res = self.svc.run_goal(g, max_iterations=1)
        self.assertLessEqual(res.iterations, 1)

    def test_run_goal_environment_missing(self):
        g = EmbodiedGoal.create(description="扫描房间")
        res = self.svc.run_goal(g, environment="nope")
        self.assertEqual(res.status, EmbodiedStatus.ERROR.value)

    def test_run_goal_high_risk_unconfirmed(self):
        g = EmbodiedGoal.create(description="重置环境", intent="reset")
        res = self.svc.run_goal(g)
        self.assertEqual(res.status, EmbodiedStatus.AWAITING_CONFIRM.value)

    def test_feedback_history_query(self):
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        entries = self.svc.feedback_history(limit=10)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["result"], "success")

    def test_feedback_history_filter(self):
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        entries = self.svc.feedback_history(result="failure", limit=10)
        self.assertEqual(entries, [])

    def test_world_history(self):
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        states = self.svc.world_history()
        self.assertEqual(len(states), 1)

    def test_observe_direct(self):
        state = self.svc.observe()
        self.assertEqual(len(state.objects), 4)
        self.assertEqual(self.svc.world_model.count(), 1)

    def test_reset_environment(self):
        self.svc.execute_action(EmbodiedAction.create(
            action_type="move", parameters={"dx": 2, "dy": 2},
        ))
        state = self.svc.reset()
        self.assertEqual(state.position, {"x": 0.0, "y": 0.0})

    def test_status(self):
        st = self.svc.status()
        self.assertEqual(st["version"], "9.5.0")
        self.assertIn("permission", st)
        self.assertIn("feedback_stats", st)
        # V4.2: 閹恒劎鎮婄仦鍌滃Ц閹?
        self.assertIn("event_stats", st)
        self.assertIn("reasoning", st)
        self.assertEqual(st["reasoning"]["causal"], "rule_based")
        # V4.3: 閸︾儤娅?/ 缂佸繘鐛?/ 閸ョ偞鏂侀悩鑸碘偓?
        self.assertIn("scene", st)
        self.assertIn("experience", st)
        self.assertIn("replay", st)


class TestServiceSingleton(unittest.TestCase):

    def tearDown(self):
        reset_service()

    def test_get_service_singleton(self):
        s1 = get_service()
        s2 = get_service()
        self.assertIs(s1, s2)

    def test_reset_service(self):
        s1 = get_service()
        reset_service()
        s2 = get_service()
        self.assertIsNot(s1, s2)


class TestServiceV41AnalysisPrediction(unittest.TestCase):
    """V4.1: 反馈分析 / 状态预测 / 具身上下文 / 环境记忆"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_execute_returns_analysis(self):
        a = EmbodiedAction.create(action_type="scan", intent="扫描环境")
        res = self.svc.execute_action(a)
        self.assertIsNotNone(res.analysis)
        self.assertTrue(res.analysis.success)

    def test_execute_failure_has_analysis(self):
        a = EmbodiedAction.create(action_type="pick", target="ghost", parameters={"object": "ghost"})
        res = self.svc.execute_action(a)
        self.assertIsNotNone(res.analysis)
        self.assertFalse(res.analysis.success)
        self.assertTrue(res.analysis.suggestion)

    def test_execute_returns_prediction(self):
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        res = self.svc.execute_action(a)
        self.assertIsNotNone(res.prediction)
        self.assertEqual(res.prediction.expected_change["event"], "move")

    def test_execute_writes_memory(self):
        a = EmbodiedAction.create(action_type="scan")
        self.svc.execute_action(a)
        self.assertGreaterEqual(self.svc.memory.count(), 2)  # action + change

    def test_execute_denied_no_memory(self):
        svc = EmbodiedService()
        svc.load_config({})  # 姒涙顓婚崗鎶芥４
        a = EmbodiedAction.create(action_type="scan")
        svc.execute_action(a)
        self.assertEqual(svc.memory.count(), 0)

    def test_predict_direct(self):
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        pred = self.svc.predict(a)
        self.assertIsNotNone(pred)
        self.assertEqual(pred.expected_change["event"], "move")

    def test_predict_auto_observes(self):
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        a = EmbodiedAction.create(action_type="scan")
        pred = svc.predict(a)  # 娑撴牜鏅Ο鈥崇€烽弮鐘靛Ц閹?閳?閼奉亜濮╃憴鍌氱檪
        self.assertIsNotNone(pred)
        self.assertGreaterEqual(svc.world_model.count(), 1)

    def test_verify_prediction_direct(self):
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        pred = self.svc.predict(a)
        v = self.svc.verify_prediction(pred, {"event": "position_change"})
        self.assertTrue(v["matched"])


class TestServiceV41Context(unittest.TestCase):
    """V4.1: 具身上下文 (Agent 推理)"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_build_context_structure(self):
        ctx = self.svc.build_environment_context()
        self.assertIn("current_state", ctx)
        self.assertIn("environments", ctx)
        self.assertIn("feedback_stats", ctx)
        self.assertIn("memory_stats", ctx)
        self.assertIn("recent_changes", ctx)
        self.assertIn("prediction", ctx)

    def test_build_context_state_has_objects(self):
        ctx = self.svc.build_environment_context()
        self.assertEqual(len(ctx["current_state"]["objects"]), 4)
        names = {o["name"] for o in ctx["current_state"]["objects"]}
        self.assertIn("lamp", names)
        self.assertIn("door", names)

    def test_build_context_prediction_stability(self):
        ctx = self.svc.build_environment_context()
        self.assertEqual(ctx["prediction"]["expected_change"]["event"], "stability")

    def test_build_context_without_history(self):
        ctx = self.svc.build_environment_context(include_history=False)
        self.assertNotIn("recent_changes", ctx)

    def test_build_context_tracks_feedback(self):
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        ctx = self.svc.build_environment_context()
        self.assertEqual(ctx["feedback_stats"]["total"], 1)

    def test_memory_query(self):
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        entries = self.svc.memory_query(type="action")
        self.assertEqual(len(entries), 1)
        entries2 = self.svc.memory_query(type="change")
        self.assertEqual(len(entries2), 1)

    def test_state_changes_query(self):
        self.svc.observe()  # 閸忓牆缂撶粩瀣灥婵濮搁幀? 閸氬海鐢婚崝銊ょ稊閹靛秳楠囬悽鐔峰綁閸栨牕宸婚崣?
        self.svc.execute_action(EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0}))
        changes = self.svc.state_changes(limit=3)
        self.assertGreaterEqual(len(changes), 1)


class TestServiceV41AdaptiveLoop(unittest.TestCase):
    """V4.1: 自适应闭环 (失败建议 → 调整规划)"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_adaptive_pick_goal(self):
        """拾取目标: 主体不在对象位置 → 自适应插入移动 → 成功"""
        goal = EmbodiedGoal.create(
            description="拿起台灯", intent="pick", target="lamp",
            constraints={"max_steps": 6},
        )
        res = self.svc.run_goal(goal, adaptive=True)
        self.assertTrue(res.success)
        self.assertEqual(res.status, EmbodiedStatus.OK.value)

    def test_adaptive_disabled_still_works_scan(self):
        goal = EmbodiedGoal.create(description="扫描房间", constraints={"max_steps": 3})
        res = self.svc.run_goal(goal, adaptive=False)
        self.assertTrue(res.success)

    def test_adaptive_abandons_after_repeated_failure(self):
        """连续失败 → 放弃 (不无限循环)"""
        goal = EmbodiedGoal.create(
            description="拿起幽灵对象", intent="pick", target="ghost",
            constraints={"max_steps": 10},
        )
        res = self.svc.run_goal(goal, adaptive=True)
        self.assertLessEqual(res.iterations, 6)


class TestServiceResolve(unittest.TestCase):

    def test_environment_missing_raises(self):
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        with self.assertRaises(EmbodiedServiceError):
            svc.get_state(environment="nonexistent")

    def test_get_state_default(self):
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        state = svc.get_state()
        self.assertEqual(state.metadata["environment"], "mock")


if __name__ == "__main__":
    unittest.main()
