"""
YHLZ Embodied AI V4.2 - Schema 单元测试

覆盖:
    - 枚举: EmbodiedActionType / EmbodiedStatus / FeedbackResult / EventType / CauseType
    - EnvironmentObject 创建 / 序列化
    - EnvironmentState 创建 / 序列化 (V4.1: location 别名 / relations / confidence)
    - EmbodiedAction 创建 / 序列化
    - Feedback 创建 / 序列化 (V4.1: new_state / success)
    - FeedbackAnalysis (V4.1 + V4.2: cause / cause_detail)
    - WorldStateHistory (V4.1)
    - EnvironmentPrediction (V4.1)
    - EnvironmentEvent (V4.2) / CausalAnalysis (V4.2)
    - MultiStepPrediction (V4.2) / ExperienceSummary (V4.2)
    - EmbodiedGoal 创建 / 序列化
"""
import unittest

from backend.embodied.schema import (
    CausalAnalysis,
    CauseType,
    EmbodiedAction,
    EmbodiedActionType,
    EmbodiedGoal,
    EmbodiedStatus,
    EnvironmentEvent,
    EnvironmentObject,
    EnvironmentPrediction,
    EnvironmentState,
    EventType,
    ExperienceSummary,
    Feedback,
    FeedbackAnalysis,
    FeedbackResult,
    MultiStepPrediction,
    WorldStateHistory,
)


class TestEmbodiedActionType(unittest.TestCase):

    def test_values(self):
        expected = {"move", "pick", "place", "scan", "inspect", "explore", "interact", "wait", "custom"}
        self.assertEqual(set(EmbodiedActionType.values()), expected)

    def test_values_count(self):
        self.assertEqual(len(EmbodiedActionType.values()), 9)


class TestEmbodiedStatus(unittest.TestCase):

    def test_key_statuses(self):
        self.assertEqual(EmbodiedStatus.OK.value, "ok")
        self.assertEqual(EmbodiedStatus.DENIED.value, "denied")
        self.assertEqual(EmbodiedStatus.AWAITING_CONFIRM.value, "awaiting_confirm")
        self.assertEqual(EmbodiedStatus.INVALID.value, "invalid")
        self.assertEqual(EmbodiedStatus.UNSUPPORTED.value, "unsupported")


class TestFeedbackResult(unittest.TestCase):

    def test_values(self):
        self.assertEqual(
            set(FeedbackResult.values()),
            {"success", "failure", "partial", "no_change"},
        )


class TestEventType(unittest.TestCase):
    """V4.2: 事件类型枚举"""

    def test_key_types(self):
        self.assertEqual(EventType.ACTION.value, "action")
        self.assertEqual(EventType.OBJECT_CHANGE.value, "object_change")
        self.assertEqual(EventType.MOVE.value, "move")
        self.assertEqual(EventType.RESET.value, "reset")
        self.assertEqual(EventType.FAILURE.value, "failure")

    def test_values_count(self):
        self.assertEqual(len(EventType.values()), 7)


class TestCauseType(unittest.TestCase):
    """V4.2: 因果类型枚举"""

    def test_key_causes(self):
        self.assertEqual(CauseType.POSITION_MISMATCH.value, "position_mismatch")
        self.assertEqual(CauseType.BOUNDARY_LIMIT.value, "boundary_limit")
        self.assertEqual(CauseType.OBJECT_MISSING.value, "object_missing")
        self.assertEqual(CauseType.OBJECT_NOT_HELD.value, "object_not_held")
        self.assertEqual(CauseType.UNKNOWN.value, "unknown")

    def test_values_count(self):
        self.assertEqual(len(CauseType.values()), 10)


class TestEnvironmentObject(unittest.TestCase):

    def test_defaults(self):
        o = EnvironmentObject()
        self.assertTrue(o.object_id)
        self.assertEqual(o.name, "")
        self.assertEqual(o.position, {})

    def test_create(self):
        o = EnvironmentObject.create(
            name="lamp", category="light",
            position={"x": 1.0, "y": 2.0}, properties={"color": "white"},
            state="on",
        )
        self.assertEqual(o.name, "lamp")
        self.assertEqual(o.category, "light")
        self.assertEqual(o.position, {"x": 1.0, "y": 2.0})
        self.assertEqual(o.state, "on")

    def test_roundtrip(self):
        o = EnvironmentObject.create(
            name="box", category="container", position={"x": 2.0, "y": 3.0},
            properties={"material": "wood"}, state="closed",
        )
        o2 = EnvironmentObject.from_dict(o.to_dict())
        self.assertEqual(o2.object_id, o.object_id)
        self.assertEqual(o2.name, "box")
        self.assertEqual(o2.position, {"x": 2.0, "y": 3.0})
        self.assertEqual(o2.properties, {"material": "wood"})

    def test_from_dict_defaults(self):
        o = EnvironmentObject.from_dict({})
        self.assertEqual(o.name, "")
        self.assertTrue(o.object_id)


class TestEnvironmentState(unittest.TestCase):

    def test_defaults(self):
        s = EnvironmentState()
        self.assertTrue(s.state_id)
        self.assertEqual(s.objects, [])
        self.assertEqual(s.position, {})

    def test_create(self):
        objs = [EnvironmentObject.create(name="lamp", position={"x": 1.0, "y": 1.0})]
        s = EnvironmentState.create(
            objects=objs, position={"x": 0.0, "y": 0.0},
            conditions={"temperature": 24.0},
        )
        self.assertEqual(len(s.objects), 1)
        self.assertEqual(s.position, {"x": 0.0, "y": 0.0})
        self.assertEqual(s.conditions, {"temperature": 24.0})

    def test_roundtrip(self):
        objs = [EnvironmentObject.create(name="book", position={"x": 0.0, "y": 2.0})]
        s = EnvironmentState.create(objects=objs, position={"x": 1.0, "y": 1.0})
        d = s.to_dict()
        self.assertEqual(len(d["objects"]), 1)
        s2 = EnvironmentState.from_dict(d)
        self.assertEqual(s2.state_id, s.state_id)
        self.assertEqual(s2.objects[0].name, "book")
        self.assertEqual(s2.position, {"x": 1.0, "y": 1.0})

    def test_from_dict_defaults(self):
        s = EnvironmentState.from_dict({})
        self.assertEqual(s.objects, [])
        self.assertTrue(s.state_id)


class TestEmbodiedAction(unittest.TestCase):

    def test_defaults(self):
        a = EmbodiedAction()
        self.assertTrue(a.action_id)
        self.assertEqual(a.action_type, "custom")
        self.assertEqual(a.status, "pending")

    def test_create(self):
        a = EmbodiedAction.create(
            action_type="move", intent="移动到书桌",
            target="desk", parameters={"dx": 1, "dy": 0},
            risk_level="low", confidence=0.9, reason="目标规划",
        )
        self.assertEqual(a.action_type, "move")
        self.assertEqual(a.intent, "移动到书桌")
        self.assertEqual(a.parameters, {"dx": 1, "dy": 0})
        self.assertEqual(a.confidence, 0.9)

    def test_roundtrip(self):
        a = EmbodiedAction.create(
            action_type="inspect", intent="检查台灯", target="lamp",
            confidence=0.7,
        )
        d = a.to_dict()
        self.assertEqual(d["target"], "lamp")
        a2 = EmbodiedAction.from_dict(d)
        self.assertEqual(a2.action_id, a.action_id)
        self.assertEqual(a2.action_type, "inspect")
        self.assertEqual(a2.confidence, 0.7)

    def test_from_dict_defaults(self):
        a = EmbodiedAction.from_dict({"action_type": "scan"})
        self.assertEqual(a.action_type, "scan")
        self.assertEqual(a.intent, "")

    def test_uuid_unique(self):
        a = EmbodiedAction.create(action_type="scan")
        b = EmbodiedAction.create(action_type="scan")
        self.assertNotEqual(a.action_id, b.action_id)


class TestFeedback(unittest.TestCase):

    def test_defaults(self):
        f = Feedback()
        self.assertTrue(f.feedback_id)
        self.assertEqual(f.result, "success")
        self.assertIsNone(f.error)

    def test_create(self):
        f = Feedback.create(
            action_id="a1", result="failure",
            environment_change={"event": "move_out_of_bounds"},
            error="越界", latency_ms=3.2,
        )
        self.assertEqual(f.action_id, "a1")
        self.assertEqual(f.result, "failure")
        self.assertEqual(f.error, "越界")

    def test_roundtrip(self):
        f = Feedback.create(
            action_id="a2", result="success",
            environment_change={"event": "move", "to": [1, 0]},
        )
        d = f.to_dict()
        f2 = Feedback.from_dict(d)
        self.assertEqual(f2.action_id, "a2")
        self.assertEqual(f2.environment_change, {"event": "move", "to": [1, 0]})

    def test_from_dict_defaults(self):
        f = Feedback.from_dict({})
        self.assertEqual(f.result, "success")


class TestEnvironmentStateV41(unittest.TestCase):
    """V4.1: location 别名 / relations / confidence"""

    def test_location_alias(self):
        s = EnvironmentState.create(location={"x": 1.0, "y": 2.0})
        self.assertEqual(s.location, {"x": 1.0, "y": 2.0})
        self.assertEqual(s.position, {"x": 1.0, "y": 2.0})  # 兼容别名

    def test_position_kwarg_backward_compat(self):
        s = EnvironmentState.create(position={"x": 3.0, "y": 4.0})
        self.assertEqual(s.location, {"x": 3.0, "y": 4.0})

    def test_position_setter(self):
        s = EnvironmentState()
        s.position = {"x": 5.0, "y": 5.0}
        self.assertEqual(s.location, {"x": 5.0, "y": 5.0})

    def test_relations_field(self):
        s = EnvironmentState.create(
            relations=[{"type": "near", "object_a": "lamp", "object_b": "desk"}],
        )
        self.assertEqual(len(s.relations), 1)
        d = s.to_dict()
        self.assertEqual(d["relations"][0]["type"], "near")

    def test_confidence_roundtrip(self):
        s = EnvironmentState.create(confidence=0.7)
        self.assertEqual(s.confidence, 0.7)
        s2 = EnvironmentState.from_dict(s.to_dict())
        self.assertEqual(s2.confidence, 0.7)

    def test_confidence_default(self):
        self.assertEqual(EnvironmentState.create().confidence, 1.0)

    def test_from_dict_old_position_field(self):
        s = EnvironmentState.from_dict({"position": {"x": 9.0, "y": 9.0}})
        self.assertEqual(s.location, {"x": 9.0, "y": 9.0})


class TestFeedbackV41(unittest.TestCase):
    """V4.1: new_state / success 属性"""

    def test_new_state_roundtrip(self):
        st = EnvironmentState.create(location={"x": 1.0, "y": 0.0})
        f = Feedback.create(action_id="a1", result="success", new_state=st)
        d = f.to_dict()
        self.assertEqual(d["new_state"]["location"], {"x": 1.0, "y": 0.0})
        f2 = Feedback.from_dict(d)
        self.assertEqual(f2.new_state.location, {"x": 1.0, "y": 0.0})

    def test_new_state_none_by_default(self):
        f = Feedback.create(action_id="a1")
        self.assertIsNone(f.new_state)

    def test_success_property(self):
        self.assertTrue(Feedback.create(result="success").success)
        self.assertFalse(Feedback.create(result="failure").success)
        self.assertFalse(Feedback.create(result="partial").success)
        self.assertFalse(Feedback.create(result="no_change").success)

    def test_from_dict_new_state_none(self):
        f = Feedback.from_dict({"action_id": "a1"})
        self.assertIsNone(f.new_state)


class TestFeedbackAnalysis(unittest.TestCase):

    def test_defaults(self):
        a = FeedbackAnalysis()
        self.assertTrue(a.analysis_id)
        self.assertTrue(a.success)
        self.assertIsNone(a.failure_reason)

    def test_create(self):
        a = FeedbackAnalysis.create(
            action_id="a1", success=False,
            failure_reason="对象不存在", suggestion="确认目标对象",
        )
        self.assertEqual(a.action_id, "a1")
        self.assertFalse(a.success)
        self.assertEqual(a.failure_reason, "对象不存在")

    def test_roundtrip(self):
        a = FeedbackAnalysis.create(
            action_id="a1", success=False, suggestion="移动",
            environment_change={"event": "pick_not_in_reach"},
        )
        d = a.to_dict()
        a2 = FeedbackAnalysis.from_dict(d)
        self.assertEqual(a2.action_id, "a1")
        self.assertFalse(a2.success)
        self.assertEqual(a2.suggestion, "移动")

    def test_from_dict_defaults(self):
        a = FeedbackAnalysis.from_dict({})
        self.assertTrue(a.success)

    def test_v42_cause_fields(self):
        """V4.2: cause / cause_detail"""
        a = FeedbackAnalysis.create(
            action_id="a1", success=False,
            cause="position_mismatch", cause_detail="对象不在当前位置",
        )
        self.assertEqual(a.cause, "position_mismatch")
        self.assertEqual(a.cause_detail, "对象不在当前位置")

    def test_v42_cause_roundtrip(self):
        a = FeedbackAnalysis.create(
            action_id="a1", success=False,
            cause="boundary_limit", cause_detail="越界",
        )
        a2 = FeedbackAnalysis.from_dict(a.to_dict())
        self.assertEqual(a2.cause, "boundary_limit")
        self.assertEqual(a2.cause_detail, "越界")

    def test_v42_cause_default_none(self):
        a = FeedbackAnalysis.create(action_id="a1", success=True)
        self.assertIsNone(a.cause)
        self.assertIsNone(a.cause_detail)

    def test_v41_dict_without_cause_backward_compat(self):
        """V4.1 旧数据无 cause 字段 → 兼容"""
        a = FeedbackAnalysis.from_dict({
            "analysis_id": "x", "action_id": "a1", "success": False,
            "failure_reason": "旧数据", "suggestion": "s",
        })
        self.assertIsNone(a.cause)
        self.assertEqual(a.failure_reason, "旧数据")


class TestEnvironmentEvent(unittest.TestCase):
    """V4.2: 环境事件"""

    def test_defaults(self):
        e = EnvironmentEvent()
        self.assertTrue(e.event_id)
        self.assertEqual(e.event_type, EventType.ACTION.value)
        self.assertEqual(e.object_changes, [])

    def test_create(self):
        e = EnvironmentEvent.create(
            event_type=EventType.FAILURE.value, action_id="a1",
            action_type="pick", target="lamp", result="failure",
            cause="position_mismatch",
            position_from=[0, 0], position_to=[1, 1],
        )
        self.assertEqual(e.cause, "position_mismatch")
        self.assertEqual(e.position_to, [1, 1])

    def test_roundtrip(self):
        e = EnvironmentEvent.create(
            event_type=EventType.MOVE.value,
            object_changes=[{"name": "lamp", "state": {"from": "on", "to": "off"}}],
            position_from=[0, 0], position_to=[1, 0],
            summary="move 成功",
        )
        d = e.to_dict()
        self.assertIn("summary", d)
        self.assertEqual(d["position_from"], [0, 0])
        e2 = EnvironmentEvent.from_dict(d)
        self.assertEqual(e2.event_type, EventType.MOVE.value)
        self.assertEqual(e2.object_changes[0]["name"], "lamp")
        self.assertEqual(e2.summary, "move 成功")

    def test_from_dict_defaults(self):
        e = EnvironmentEvent.from_dict({})
        self.assertEqual(e.event_type, EventType.ACTION.value)
        self.assertEqual(e.result, "")


class TestCausalAnalysis(unittest.TestCase):
    """V4.2: 因果分析"""

    def test_defaults(self):
        c = CausalAnalysis()
        self.assertTrue(c.causal_id)
        self.assertEqual(c.cause, CauseType.UNKNOWN.value)

    def test_create(self):
        c = CausalAnalysis.create(
            action_id="a1", cause=CauseType.BOUNDARY_LIMIT.value,
            mechanism="越界", remedy="反向移动", confidence=0.9,
        )
        self.assertEqual(c.action_id, "a1")
        self.assertEqual(c.cause, "boundary_limit")
        self.assertEqual(c.remedy, "反向移动")
        self.assertEqual(c.confidence, 0.9)

    def test_roundtrip(self):
        c = CausalAnalysis.create(
            action_id="a1", cause=CauseType.POSITION_MISMATCH.value,
            mechanism="不在当前位置", remedy="先移动", confidence=0.85,
            evidence={"event": "pick_not_in_reach"},
        )
        c2 = CausalAnalysis.from_dict(c.to_dict())
        self.assertEqual(c2.cause, c.cause)
        self.assertEqual(c2.mechanism, c.mechanism)
        self.assertEqual(c2.confidence, 0.85)
        self.assertEqual(c2.evidence["event"], "pick_not_in_reach")


class TestMultiStepPrediction(unittest.TestCase):
    """V4.2: 多步条件预测"""

    def test_defaults(self):
        p = MultiStepPrediction()
        self.assertTrue(p.prediction_id)
        self.assertEqual(p.steps, [])
        self.assertTrue(p.invariants_ok)

    def test_create(self):
        p = MultiStepPrediction.create(
            actions=[{"action_type": "move"}],
            steps=[{"index": 0, "expected": {"expected": "position_change"}}],
            final_expected={"objects": {"lamp": "held"}},
            invariants_ok=True, confidence=0.85,
        )
        self.assertEqual(len(p.steps), 1)
        self.assertEqual(p.final_expected["objects"]["lamp"], "held")
        self.assertEqual(p.confidence, 0.85)

    def test_roundtrip(self):
        p = MultiStepPrediction.create(
            actions=[{"action_type": "move"}, {"action_type": "pick"}],
            steps=[
                {"index": 0, "expected": {"expected": "position_change"}},
                {"index": 1, "expected": {"expected": "success"}},
            ],
            final_expected={"objects": {"lamp": "held"}},
            invariants_ok=True,
            invariant_violations=[],
            confidence=0.9,
        )
        d = p.to_dict()
        self.assertEqual(len(d["steps"]), 2)
        self.assertTrue(d["invariants_ok"])
        p2 = MultiStepPrediction.from_dict(d)
        self.assertEqual(p2.final_expected["objects"]["lamp"], "held")
        self.assertEqual(p2.confidence, 0.9)


class TestExperienceSummary(unittest.TestCase):
    """V4.2: 经验摘要"""

    def test_defaults(self):
        s = ExperienceSummary()
        self.assertTrue(s.summary_id)
        self.assertEqual(s.total_actions, 0)
        self.assertEqual(s.success_rate, 0.0)

    def test_create(self):
        s = ExperienceSummary.create(
            total_actions=10, success_count=7, success_rate=0.7,
            failure_patterns=[{"cause": "boundary_limit", "count": 2}],
            success_trends=[{"bucket": 0, "success_rate": 0.7}],
            cause_stats={"boundary_limit": 2},
        )
        self.assertEqual(s.total_actions, 10)
        self.assertEqual(s.success_rate, 0.7)
        self.assertEqual(s.failure_patterns[0]["cause"], "boundary_limit")

    def test_roundtrip(self):
        s = ExperienceSummary.create(
            total_actions=5, success_count=3, success_rate=0.6,
            failure_patterns=[{"cause": "x", "count": 2}],
            success_trends=[{"bucket": 0, "success_rate": 0.6}],
            cause_stats={"x": 2}, top_failures=[{"action_id": "a1"}],
        )
        s2 = ExperienceSummary.from_dict(s.to_dict())
        self.assertEqual(s2.total_actions, 5)
        self.assertEqual(s2.success_rate, 0.6)
        self.assertEqual(s2.failure_patterns, s.failure_patterns)
        self.assertEqual(s2.cause_stats, {"x": 2})
        self.assertEqual(s2.top_failures[0]["action_id"], "a1")

    def test_to_dict_fields(self):
        s = ExperienceSummary.create(total_actions=1, success_count=1, success_rate=1.0)
        d = s.to_dict()
        for key in (
            "summary_id", "total_actions", "success_count", "success_rate",
            "failure_patterns", "success_trends", "cause_stats", "top_failures",
        ):
            self.assertIn(key, d)


class TestWorldStateHistory(unittest.TestCase):

    def test_create(self):
        prev = EnvironmentState.create(location={"x": 0.0, "y": 0.0})
        curr = EnvironmentState.create(location={"x": 1.0, "y": 0.0})
        h = WorldStateHistory.create(
            previous_state=prev, current_state=curr,
            change={"location": {"from": {"x": 0.0, "y": 0.0}, "to": {"x": 1.0, "y": 0.0}}},
        )
        self.assertTrue(h.history_id)
        self.assertEqual(h.current_state.location, {"x": 1.0, "y": 0.0})

    def test_roundtrip(self):
        prev = EnvironmentState.create()
        curr = EnvironmentState.create()
        h = WorldStateHistory.create(previous_state=prev, current_state=curr, change={"x": 1})
        d = h.to_dict()
        self.assertEqual(d["change"], {"x": 1})
        self.assertIn("previous_state", d)
        self.assertIn("current_state", d)

    def test_create_defaults(self):
        h = WorldStateHistory.create()
        self.assertEqual(h.change, {})


class TestEnvironmentPrediction(unittest.TestCase):

    def test_create(self):
        p = EnvironmentPrediction.create(
            current_state=EnvironmentState.create(),
            expected_change={"event": "move", "expected": "position_change"},
            confidence=0.9,
        )
        self.assertTrue(p.prediction_id)
        self.assertEqual(p.expected_change["expected"], "position_change")
        self.assertEqual(p.confidence, 0.9)

    def test_roundtrip(self):
        p = EnvironmentPrediction.create(
            current_state=EnvironmentState.create(),
            expected_change={"event": "scan", "expected": "no_change"},
            confidence=0.8,
        )
        d = p.to_dict()
        p2 = p.__class__.create(
            current_state=p.current_state, expected_change=p.expected_change,
            confidence=p.confidence,
        )
        self.assertEqual(p2.expected_change, p.expected_change)
        self.assertEqual(p2.confidence, 0.8)
        self.assertEqual(d["expected_change"]["event"], "scan")


class TestEmbodiedGoal(unittest.TestCase):

    def test_defaults(self):
        g = EmbodiedGoal()
        self.assertTrue(g.goal_id)
        self.assertEqual(g.priority, "medium")

    def test_create(self):
        g = EmbodiedGoal.create(
            description="检查房间里的台灯", intent="inspect",
            target="lamp", constraints={"max_steps": 3}, priority="high",
        )
        self.assertEqual(g.intent, "inspect")
        self.assertEqual(g.target, "lamp")
        self.assertEqual(g.constraints, {"max_steps": 3})

    def test_roundtrip(self):
        g = EmbodiedGoal.create(description="探索房间")
        d = g.to_dict()
        g2 = EmbodiedGoal.from_dict(d)
        self.assertEqual(g2.goal_id, g.goal_id)
        self.assertEqual(g2.description, "探索房间")

    def test_from_dict_defaults(self):
        g = EmbodiedGoal.from_dict({})
        self.assertEqual(g.description, "")


if __name__ == "__main__":
    unittest.main()
