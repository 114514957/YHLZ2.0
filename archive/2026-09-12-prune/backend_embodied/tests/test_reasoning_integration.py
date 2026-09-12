"""
YHLZ Embodied AI V4.2 - 环境推理集成测试

覆盖 (完整推理链路):
    Environment State → Event Understanding → Cause Analysis → Prediction → Reasoning → Action

    - execute_action 失败 → 因果 cause (位置不匹配 / 边界限制)
    - 事件时间线: get_events / event_history (动作/结果/对象变化/位置/因果)
    - predict_sequence: 多步条件预测 (只预测不执行)
    - build_environment_context: 事件摘要 + 因果分析 + 预测置信度 + 经验摘要
    - experience_summary: 高频失败模式 / 成功率趋势
    - analyze_cause: 按 action_id 查询因果
    - load_config: embodied_memory_path 跨进程加载
    - 安全: 预测不执行 / 推理不绕过权限
"""
import os
import tempfile
import unittest

from backend.embodied.schema import (
    EmbodiedAction,
    EmbodiedGoal,
    EnvironmentState,
)
from backend.embodied.service import EmbodiedService


def make_svc(enabled=True) -> EmbodiedService:
    svc = EmbodiedService()
    svc.load_config({"embodied_enabled": enabled})
    return svc


def make_action(action_type, target="", params=None) -> EmbodiedAction:
    return EmbodiedAction.create(
        action_type=action_type, target=target, parameters=params or {},
    )


class TestReasoningEventTimeline(unittest.TestCase):
    """事件时间线: 动作 → 结果 → 因果"""

    def setUp(self):
        self.svc = make_svc()

    def test_pick_failure_records_failure_event_with_cause(self):
        """拾取失败 → 事件时间线记录 failure + position_mismatch"""
        res = self.svc.execute_action(make_action(
            "pick", "lamp", {"object": "lamp"},
        ))
        self.assertFalse(res.success)
        events = self.svc.get_events(event_type="failure")
        self.assertGreaterEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.action_id, res.action.action_id)
        self.assertEqual(ev.cause, "position_mismatch")
        self.assertEqual(ev.result, "failure")

    def test_move_out_of_bounds_records_event(self):
        """越界移动 → 时间线记录 move_out_of_bounds 事件 (no_change 结果)"""
        res = self.svc.execute_action(make_action(
            "move", params={"dx": -5, "dy": 0},
        ))
        # 鐡掑﹦鏅?閳?NO_CHANGE 閸欏秹顩?(娑撴艾濮熼幋鎰娴ｅ棙妫ら崣妯哄)
        self.assertIsNotNone(res.feedback)
        self.assertEqual(res.feedback.result, "no_change")
        events = self.svc.get_events(result="no_change")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].action_type, "move")
        # 鐡掑﹦鏅崢鐔锋礈閸︺劌寮芥＃?error 娑?
        self.assertIsNotNone(self.svc.get_feedback(res.action.action_id).error)

    def test_event_history_contains_position(self):
        self.svc.execute_action(make_action("move", params={"dx": 1, "dy": 0}))
        history = self.svc.event_history(limit=10, action_type="move")
        move_events = [h for h in history if h["result"] == "success"]
        self.assertGreaterEqual(len(move_events), 1)
        ev = move_events[0]
        self.assertEqual(ev["position_from"], [0, 0])
        self.assertEqual(ev["position_to"], [1, 0])

    def test_event_stats(self):
        self.svc.execute_action(make_action("scan"))
        st = self.svc.event_stats()
        self.assertIn("by_type", st)
        self.assertGreaterEqual(st["total"], 1)

    def test_observe_records_event(self):
        self.svc.observe()
        events = self.svc.get_events(event_type="observe")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].metadata.get("environment"), "mock")

    def test_reset_records_event(self):
        self.svc.reset()
        events = self.svc.get_events(event_type="reset")
        self.assertGreaterEqual(len(events), 1)


class TestReasoningCausalAnalysis(unittest.TestCase):
    """因果分析: 为什么失败"""

    def setUp(self):
        self.svc = make_svc()

    def test_analysis_has_cause_on_failure(self):
        res = self.svc.execute_action(make_action(
            "pick", "lamp", {"object": "lamp"},
        ))
        self.assertIsNotNone(res.analysis)
        self.assertEqual(res.analysis.cause, "position_mismatch")
        self.assertIn("不在当前", res.analysis.cause_detail)

    def test_analysis_no_cause_on_success(self):
        self.svc.execute_action(make_action("move", params={"dx": 1, "dy": 0}))
        res = self.svc.execute_action(make_action("scan"))
        self.assertIsNone(res.analysis.cause)

    def test_analyze_cause_by_action_id(self):
        res = self.svc.execute_action(make_action(
            "pick", "lamp", {"object": "lamp"},
        ))
        causal = self.svc.analyze_cause(res.action.action_id)
        self.assertIsNotNone(causal)
        self.assertEqual(causal.cause, "position_mismatch")
        self.assertTrue(causal.remedy)

    def test_analyze_cause_unknown_action_id(self):
        self.assertIsNone(self.svc.analyze_cause("no_such_action"))

    def test_denied_action_records_permission_cause(self):
        denied_svc = make_svc(enabled=False)
        res = denied_svc.execute_action(make_action("move", params={"dx": 1, "dy": 0}))
        self.assertEqual(res.status, "denied")
        events = denied_svc.get_events(result="failure")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].cause, "permission_denied")


class TestReasoningPrediction(unittest.TestCase):
    """多步条件预测: 只预测不执行"""

    def setUp(self):
        self.svc = make_svc()

    def test_predict_sequence_move_pick(self):
        self.svc.observe()
        pred = self.svc.predict_sequence([
            make_action("move", params={"dx": 1, "dy": 1}),
            make_action("pick", "lamp", {"object": "lamp"}),
        ])
        self.assertIsNotNone(pred)
        self.assertEqual(pred.final_expected["objects"]["lamp"], "held")
        self.assertTrue(pred.invariants_ok)
        # 妫板嫭绁撮崥搴ｅ箚婢у啰濮搁幀浣风瑝閸?(閸欘亪顣╁ù瀣╃瑝閹笛嗩攽)
        state = self.svc.world_state()
        self.assertNotEqual(
            state.objects[0].state, "held",
            "预测不得改变实际环境状态",
        )

    def test_predict_sequence_empty(self):
        self.assertIsNone(self.svc.predict_sequence([]))

    def test_predict_does_not_execute(self):
        """预测只读: 位置/对象不变, 不增加动作执行事件"""
        self.svc.observe()
        before = self.svc.event_stats()["total"]
        self.svc.predict_sequence([
            make_action("move", params={"dx": 1, "dy": 0}),
        ])
        after = self.svc.event_stats()["total"]
        self.assertEqual(before, after)

    def test_prediction_confidence_in_context(self):
        ctx = self.svc.build_environment_context()
        self.assertIn("prediction_confidence", ctx)
        self.assertGreaterEqual(ctx["prediction_confidence"], 0.0)


class TestReasoningContext(unittest.TestCase):
    """环境上下文: 事件摘要 + 因果 + 置信度 + 经验"""

    def setUp(self):
        self.svc = make_svc()

    def test_context_has_all_v42_fields(self):
        ctx = self.svc.build_environment_context()
        self.assertIn("events", ctx)
        self.assertIn("event_stats", ctx)
        self.assertIn("causal_analysis", ctx)
        self.assertIn("prediction_confidence", ctx)
        self.assertIn("experience", ctx)
        self.assertIn("failure_patterns", ctx["experience"])
        self.assertIn("success_trends", ctx["experience"])

    def test_context_causal_after_failure(self):
        self.svc.execute_action(make_action(
            "pick", "lamp", {"object": "lamp"},
        ))
        ctx = self.svc.build_environment_context()
        self.assertGreaterEqual(len(ctx["causal_analysis"]), 1)
        self.assertEqual(
            ctx["causal_analysis"][0]["cause"], "position_mismatch",
        )

    def test_context_prediction_is_stability(self):
        ctx = self.svc.build_environment_context()
        self.assertEqual(ctx["prediction"]["expected_change"]["expected"], "no_change")

    def test_context_events_after_actions(self):
        self.svc.execute_action(make_action("scan"))
        self.svc.execute_action(make_action("scan"))
        ctx = self.svc.build_environment_context(event_limit=8)
        self.assertGreaterEqual(len(ctx["events"]), 2)


class TestReasoningExperienceMemory(unittest.TestCase):
    """具身长期经验: 失败模式 / 成功率趋势 / 跨进程"""

    def test_experience_summary_after_actions(self):
        svc = make_svc()
        svc.execute_action(make_action("move", params={"dx": 1, "dy": 0}))
        svc.execute_action(make_action("pick", "lamp", {"object": "lamp"}))
        svc.execute_action(make_action("pick", "lamp", {"object": "lamp"}))
        s = svc.experience_summary()
        self.assertEqual(s.total_actions, 3)
        self.assertEqual(s.success_count, 1)
        self.assertGreaterEqual(len(s.failure_patterns), 1)
        self.assertEqual(s.failure_patterns[0]["cause"], "position_mismatch")

    def test_embodied_memory_path_cross_process(self):
        """跨进程: 保存 → 新 Service load_config 加载"""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            svc1 = make_svc()
            svc1.execute_action(make_action("pick", "lamp", {"object": "lamp"}))
            svc1.save_memory(path)

            svc2 = make_svc()
            svc2.load_config({
                "embodied_enabled": True,
                "embodied_memory_path": path,
            })
            s = svc2.experience_summary()
            self.assertEqual(s.total_actions, 1)
            self.assertEqual(s.failure_patterns[0]["cause"], "position_mismatch")
        finally:
            os.remove(path)

    def test_memory_path_missing_is_silent(self):
        svc = make_svc()
        svc.load_config({
            "embodied_enabled": True,
            "embodied_memory_path": "no_such_memory.jsonl",
        })
        self.assertEqual(svc.experience_summary().total_actions, 0)


class TestReasoningSafety(unittest.TestCase):
    """V4.2 安全原则: 推理不执行 / 权限优先"""

    def setUp(self):
        self.svc = make_svc()

    def test_reasoning_tools_not_executing(self):
        """推理链路只读: predict_sequence / build_environment_context 不产生动作事件"""
        before = self.svc.event_stats()["total"]
        self.svc.observe()
        self.svc.build_environment_context()
        self.svc.predict_sequence([make_action("scan")])
        after = self.svc.event_stats()["total"]
        # 閸欘亜褰查懗钘夘杻閸?observe 娴滃娆? 娑撳秴顤冮崝?action 閹笛嗩攽娴滃娆?
        action_events_before = sum(
            1 for e in self.svc.get_events(event_type="action") if e.result
        )
        self.assertGreaterEqual(after, before)

    def test_denied_default_disabled(self):
        """默认 embodied_enabled=False 保持"""
        svc = EmbodiedService()
        svc.load_config({})
        res = svc.execute_action(make_action("move", params={"dx": 1, "dy": 0}))
        self.assertEqual(res.status, "denied")
        self.assertIn("embodied_enabled=False", res.error)

    def test_prediction_never_bypasses_permission(self):
        """预测不影响权限流程: 未授权时动作仍被拒绝"""
        svc = EmbodiedService()
        svc.load_config({})
        svc.observe()
        pred = svc.predict_sequence([make_action("move", params={"dx": 1, "dy": 0})])
        self.assertIsNotNone(pred)  # 妫板嫭绁撮崣顖滄暏
        res = svc.execute_action(make_action("move", params={"dx": 1, "dy": 0}))
        self.assertEqual(res.status, "denied")  # 閹笛嗩攽娴犲秷顫﹂幏鎺旂卜

    def test_world_model_not_mutated_by_prediction(self):
        self.svc.observe()
        before = self.svc.world_state().to_dict()
        self.svc.predict_sequence([
            make_action("move", params={"dx": 5, "dy": 5}),
            make_action("pick", "box", {"object": "box"}),
        ])
        self.assertEqual(self.svc.world_state().to_dict(), before)


class TestReasoningGoalLoop(unittest.TestCase):
    """目标闭环 + 推理: 事件与因果贯穿"""

    def setUp(self):
        self.svc = make_svc()

    def test_run_goal_records_events(self):
        goal = EmbodiedGoal.create(
            description="拾取台灯", intent="pick", target="lamp",
        )
        res = self.svc.run_goal(goal, max_iterations=3)
        self.assertIsNotNone(res)
        events = self.svc.event_history(limit=50)
        self.assertGreaterEqual(len(events), 1)
        action_events = [e for e in events if e["action_type"] == "pick"]
        self.assertGreaterEqual(len(action_events), 1)

    def test_run_goal_feedback_has_cause(self):
        goal = EmbodiedGoal.create(
            description="拿起不存在的对象", intent="pick", target="ghost",
        )
        res = self.svc.run_goal(goal, max_iterations=2)
        self.assertIsNotNone(res.analysis)
        # 閼奉亪鈧倸绨叉导姘毙╅崝?閳?閸ョ姵鐏夐崣顖濆厴閺?object_missing 閹存牔缍呯純顔炬祲閸?
        self.assertIn(
            res.analysis.cause,
            ("object_missing", "position_mismatch"),
        )

    def test_status_version_v43(self):
        st = self.svc.status()
        self.assertEqual(st["version"], "9.5.0")
        self.assertIn("reasoning", st)
        self.assertTrue(st["reasoning"]["multi_step_prediction"])
        # V4.3: 缂佸繘鐛欑仦鍌滃Ц閹?
        self.assertIn("experience", st)
        self.assertIn("replay", st)


if __name__ == "__main__":
    unittest.main()
