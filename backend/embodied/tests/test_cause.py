"""
YHLZ Embodied AI V4.2 - 因果分析器单元测试

覆盖:
    - 成功 → 无因果
    - 位置不匹配 (pick_not_in_reach) → position_mismatch + 补救
    - 边界限制 (move_out_of_bounds) → boundary_limit
    - 对象缺失 (pick_missing / place_missing) → object_missing
    - 对象未持有 (place_not_held) → object_not_held
    - 不支持动作 → unsupported_action
    - 环境不可用 → env_unavailable
    - 权限拒绝 → permission_denied
    - 参数不合法 → invalid_parameter
    - 状态推断兜底 (文本无匹配 → 状态差异推断)
    - 未知 → unknown
    - 确定性 / 批量 / 统计
"""
import unittest

from backend.embodied.reasoning import CausalAnalyzer, CausalAnalyzerError
from backend.embodied.schema import (
    CauseType,
    EmbodiedAction,
    EnvironmentObject,
    EnvironmentState,
    Feedback,
    FeedbackResult,
)


def make_action(action_type="move", target="", params=None) -> EmbodiedAction:
    return EmbodiedAction.create(
        action_type=action_type, target=target, parameters=params or {},
    )


def make_feedback(result, error=None, change=None) -> Feedback:
    return Feedback.create(
        result=result, error=error, environment_change=change or {},
    )


def make_state(objects=None, location=None) -> EnvironmentState:
    return EnvironmentState.create(
        objects=objects or [], location=location or {"x": 0.0, "y": 0.0},
    )


class TestCausalSuccess(unittest.TestCase):

    def setUp(self):
        self.analyzer = CausalAnalyzer()

    def test_success_no_cause(self):
        fb = make_feedback(FeedbackResult.SUCCESS.value, change={"event": "move"})
        causal = self.analyzer.analyze(fb, action=make_action("move"))
        self.assertEqual(causal.cause, "")
        self.assertIn("成功", causal.mechanism)
        self.assertGreaterEqual(causal.confidence, 0.9)

    def test_no_change_without_error_no_cause(self):
        fb = make_feedback(FeedbackResult.NO_CHANGE.value)
        causal = self.analyzer.analyze(fb, action=make_action("move"))
        self.assertEqual(causal.cause, "")


class TestCausalFailure(unittest.TestCase):

    def setUp(self):
        self.analyzer = CausalAnalyzer()

    def test_position_mismatch(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value,
            error="对象 lamp 不在当前位置, 无法拾取",
            change={"event": "pick_not_in_reach", "object": "lamp"},
        )
        causal = self.analyzer.analyze(
            fb, action=make_action("pick", "lamp", {"object": "lamp"}),
        )
        self.assertEqual(causal.cause, CauseType.POSITION_MISMATCH.value)
        self.assertIn("不在当前", causal.mechanism)
        self.assertIn("移动", causal.remedy)
        self.assertGreaterEqual(causal.confidence, 0.9)

    def test_boundary_limit(self):
        fb = make_feedback(
            FeedbackResult.NO_CHANGE.value,
            error="移动越界: (5, 0) 超出网格 (5, 5)",
            change={"event": "move_out_of_bounds", "dx": 1, "dy": 0},
        )
        causal = self.analyzer.analyze(
            fb, action=make_action("move", params={"dx": 1, "dy": 0}),
        )
        self.assertEqual(causal.cause, CauseType.BOUNDARY_LIMIT.value)
        self.assertIn("边界", causal.remedy)

    def test_object_missing(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value,
            error="对象不存在: ghost",
            change={"event": "pick_missing"},
        )
        causal = self.analyzer.analyze(
            fb, action=make_action("pick", "ghost", {"object": "ghost"}),
        )
        self.assertEqual(causal.cause, CauseType.OBJECT_MISSING.value)
        self.assertIn("确认", causal.remedy)

    def test_object_not_held(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value,
            error="对象 cup 未被持有, 无法放置",
            change={"event": "place_not_held", "object": "cup"},
        )
        causal = self.analyzer.analyze(
            fb, action=make_action("place", "cup", {"object": "cup"}),
        )
        self.assertEqual(causal.cause, CauseType.OBJECT_NOT_HELD.value)
        self.assertIn("拾取", causal.remedy)

    def test_unsupported_action(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value,
            error="不支持的动作类型: fly",
            change={"event": "unsupported"},
        )
        causal = self.analyzer.analyze(fb, action=make_action("fly"))
        self.assertEqual(causal.cause, CauseType.UNSUPPORTED_ACTION.value)

    def test_env_unavailable(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value,
            error="环境不可用: hardware (本版本仅 Mock 可执行)",
            change={"event": "unavailable"},
        )
        causal = self.analyzer.analyze(fb, action=make_action("move"))
        self.assertEqual(causal.cause, CauseType.ENV_UNAVAILABLE.value)

    def test_permission_denied(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value,
            error="具身总开关未开启 (embodied_enabled=False)",
        )
        causal = self.analyzer.analyze(fb, action=make_action("move"))
        self.assertEqual(causal.cause, CauseType.PERMISSION_DENIED.value)

    def test_invalid_parameter(self):
        fb = make_feedback(
            FeedbackResult.NO_CHANGE.value,
            error="dx/dy 不合法",
            change={"event": "move"},
        )
        causal = self.analyzer.analyze(fb, action=make_action("move"))
        self.assertEqual(causal.cause, CauseType.INVALID_PARAMETER.value)

    def test_unknown_cause(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value,
            error="奇异错误码 0xDEAD",
            change={"event": "weird"},
        )
        causal = self.analyzer.analyze(fb, action=make_action("custom"))
        self.assertEqual(causal.cause, CauseType.UNKNOWN.value)
        self.assertLess(causal.confidence, 0.5)


class TestCausalStateInference(unittest.TestCase):
    """文本无匹配时, 用状态差异推断因果"""

    def setUp(self):
        self.analyzer = CausalAnalyzer()

    def test_infer_pick_position_mismatch(self):
        lamp = EnvironmentObject.create(name="lamp", position={"x": 2.0, "y": 2.0}, state="on")
        prev = make_state(objects=[lamp])
        curr = make_state(objects=[lamp])  # 对象仍在原位
        fb = make_feedback(FeedbackResult.FAILURE.value, change={"event": "pick"})
        causal = self.analyzer.analyze(
            fb, action=make_action("pick", "lamp", {"object": "lamp"}),
            state=curr, previous_state=prev,
        )
        self.assertEqual(causal.cause, CauseType.POSITION_MISMATCH.value)

    def test_infer_place_not_held(self):
        cup = EnvironmentObject.create(name="cup", position={"x": 0.0, "y": 0.0}, state="held")
        prev = make_state(objects=[cup])
        curr = make_state(objects=[cup])  # 仍 held
        fb = make_feedback(FeedbackResult.FAILURE.value, change={"event": "place"})
        causal = self.analyzer.analyze(
            fb, action=make_action("place", "cup", {"object": "cup"}),
            state=curr, previous_state=prev,
        )
        self.assertEqual(causal.cause, CauseType.OBJECT_NOT_HELD.value)

    def test_infer_move_boundary(self):
        prev = make_state(location={"x": 0.0, "y": 0.0})
        curr = make_state(location={"x": 0.0, "y": 0.0})  # 位置未变
        # error 不命中规则表 → 走状态推断路径
        fb = make_feedback(
            FeedbackResult.NO_CHANGE.value,
            error="执行异常: 无法完成移动",
            change={"event": "move"},
        )
        causal = self.analyzer.analyze(
            fb, action=make_action("move", params={"dx": 1, "dy": 0}),
            state=curr, previous_state=prev,
        )
        self.assertEqual(causal.cause, CauseType.BOUNDARY_LIMIT.value)

    def test_no_state_unknown(self):
        fb = make_feedback(FeedbackResult.FAILURE.value, change={"event": "custom"})
        causal = self.analyzer.analyze(fb, action=make_action("custom"))
        self.assertEqual(causal.cause, CauseType.UNKNOWN.value)


class TestCausalEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer = CausalAnalyzer()

    def test_none_feedback_raises(self):
        with self.assertRaises(CausalAnalyzerError):
            self.analyzer.analyze(None)

    def test_partial_result(self):
        fb = make_feedback(FeedbackResult.PARTIAL.value, change={"event": "move"})
        causal = self.analyzer.analyze(fb, action=make_action("move"))
        self.assertEqual(causal.cause, "")

    def test_analyze_many(self):
        fbs = [
            make_feedback(FeedbackResult.SUCCESS.value),
            make_feedback(
                FeedbackResult.FAILURE.value, error="对象 lamp 不在当前位置",
                change={"event": "pick_not_in_reach"},
            ),
        ]
        causals = self.analyzer.analyze_many(fbs)
        self.assertEqual(len(causals), 2)
        self.assertEqual(causals[1].cause, CauseType.POSITION_MISMATCH.value)

    def test_evidence_recorded(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value, error="对象不存在: x",
            change={"event": "pick_missing"},
        )
        causal = self.analyzer.analyze(fb, action=make_action("pick", "x"))
        self.assertEqual(causal.evidence["result"], "failure")
        self.assertEqual(causal.evidence["action_type"], "pick")

    def test_determinism(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value, error="越界: (5,0)",
            change={"event": "move_out_of_bounds"},
        )
        a1 = self.analyzer.analyze(fb, action=make_action("move"))
        a2 = self.analyzer.analyze(fb, action=make_action("move"))
        self.assertEqual(a1.cause, a2.cause)
        self.assertEqual(a1.remedy, a2.remedy)
        self.assertEqual(a1.confidence, a2.confidence)

    def test_stats(self):
        st = self.analyzer.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertGreater(st["cause_rules_count"], 0)
        self.assertIn(CauseType.POSITION_MISMATCH.value, st["supported_causes"])

    def test_reset(self):
        self.analyzer.analyze(
            make_feedback(FeedbackResult.SUCCESS.value),
        )
        self.analyzer.reset()
        self.assertEqual(self.analyzer.stats()["analyzed_count"], 0)

    def test_causal_serialization(self):
        fb = make_feedback(
            FeedbackResult.FAILURE.value, error="对象 lamp 不在当前位置",
            change={"event": "pick_not_in_reach"},
        )
        causal = self.analyzer.analyze(
            fb, action=make_action("pick", "lamp", {"object": "lamp"}),
        )
        d = causal.to_dict()
        restored = causal.__class__.from_dict(d)
        self.assertEqual(restored.cause, causal.cause)
        self.assertEqual(restored.remedy, causal.remedy)
        self.assertEqual(restored.confidence, causal.confidence)


if __name__ == "__main__":
    unittest.main()
