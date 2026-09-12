"""
YHLZ Embodied AI V4.1 - 状态预测器单元测试

覆盖:
    - 稳定性预测 (无动作: door=open → remains open)
    - move 预测 (位置变化 / 越界 / 原地 / 非法参数)
    - pick 预测 (成功 / 不在位置 / 对象不存在)
    - place 预测 (成功 / 未持有 / 对象不存在)
    - inspect 预测 (成功 / 不存在)
    - scan / explore / wait → 无变化预期
    - verify 对照 (匹配 / 不匹配)
    - 确定性 (相同输入 → 相同输出)
"""
import unittest

from backend.embodied.schema import (
    EmbodiedAction,
    EmbodiedActionType,
    EnvironmentObject,
    EnvironmentState,
)
from backend.embodied.world_model import StatePredictor


def make_state(objects=None, location=None, grid=(5, 5)) -> EnvironmentState:
    s = EnvironmentState.create(
        objects=objects or [], location=location or {"x": 0.0, "y": 0.0},
        metadata={"grid_size": list(grid)},
    )
    return s


class TestStabilityPrediction(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_no_action_state_stays(self):
        """door=open → 无动作时保持 open"""
        door = EnvironmentObject.create(name="door", state="open", position={"x": 4.0, "y": 4.0})
        state = make_state(objects=[door])
        pred = self.predictor.predict(None, state)
        self.assertEqual(pred.expected_change["event"], "stability")
        self.assertEqual(pred.expected_change["expected"], "no_change")
        self.assertEqual(pred.expected_change["objects"], [{"name": "door", "state": "open"}])
        self.assertGreaterEqual(pred.confidence, 0.9)

    def test_no_state_falls_back_empty(self):
        pred = self.predictor.predict(None, None)
        self.assertEqual(pred.expected_change["expected"], "no_change")

    def test_serialization(self):
        pred = self.predictor.predict(None, make_state())
        d = pred.to_dict()
        self.assertEqual(d["expected_change"]["event"], "stability")
        pred2 = pred.__class__.create(
            current_state=pred.current_state, expected_change=pred.expected_change,
            confidence=pred.confidence,
        )
        self.assertEqual(pred2.expected_change, pred.expected_change)


class TestMovePrediction(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_move_success(self):
        state = make_state(location={"x": 1.0, "y": 1.0})
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        pred = self.predictor.predict(a, state)
        self.assertEqual(pred.expected_change["event"], "move")
        self.assertEqual(pred.expected_change["expected"], "position_change")
        self.assertEqual(pred.expected_change["to"], [2, 1])

    def test_move_stationary(self):
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 0, "dy": 0})
        pred = self.predictor.predict(a, make_state())
        self.assertEqual(pred.expected_change["expected"], "no_change")

    def test_move_out_of_bounds(self):
        state = make_state(location={"x": 0.0, "y": 0.0}, grid=(5, 5))
        a = EmbodiedAction.create(action_type="move", parameters={"dx": -1, "dy": 0})
        pred = self.predictor.predict(a, state)
        self.assertEqual(pred.expected_change["expected"], "no_change")
        self.assertIn("超出环境边界", pred.expected_change["reason"])

    def test_move_bad_parameters(self):
        a = EmbodiedAction.create(action_type="move", parameters={"dx": "abc"})
        pred = self.predictor.predict(a, make_state())
        self.assertEqual(pred.expected_change["expected"], "unknown")
        self.assertLess(pred.confidence, 0.5)

    def test_move_without_grid_metadata(self):
        state = EnvironmentState.create(location={"x": 0.0, "y": 0.0})
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        pred = self.predictor.predict(a, state)
        self.assertEqual(pred.expected_change["expected"], "position_change")


class TestPickPrediction(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_pick_success(self):
        lamp = EnvironmentObject.create(name="lamp", position={"x": 1.0, "y": 1.0})
        state = make_state(objects=[lamp], location={"x": 1.0, "y": 1.0})
        a = EmbodiedAction.create(action_type="pick", target="lamp", parameters={"object": "lamp"})
        pred = self.predictor.predict(a, state)
        self.assertEqual(pred.expected_change["expected"], "success")
        self.assertEqual(pred.expected_change["state"], "held")

    def test_pick_not_in_reach(self):
        lamp = EnvironmentObject.create(name="lamp", position={"x": 2.0, "y": 2.0})
        state = make_state(objects=[lamp], location={"x": 0.0, "y": 0.0})
        a = EmbodiedAction.create(action_type="pick", target="lamp", parameters={"object": "lamp"})
        pred = self.predictor.predict(a, state)
        self.assertEqual(pred.expected_change["expected"], "failure")
        self.assertIn("suggestion", pred.expected_change)

    def test_pick_missing_object(self):
        a = EmbodiedAction.create(action_type="pick", target="ghost", parameters={"object": "ghost"})
        pred = self.predictor.predict(a, make_state())
        self.assertEqual(pred.expected_change["expected"], "failure")

    def test_pick_no_target(self):
        pred = self.predictor.predict(EmbodiedAction.create(action_type="pick"), make_state())
        self.assertEqual(pred.expected_change["expected"], "failure")


class TestPlacePrediction(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_place_success(self):
        lamp = EnvironmentObject.create(name="lamp", position={"x": 1.0, "y": 1.0}, state="held")
        state = make_state(objects=[lamp])
        a = EmbodiedAction.create(action_type="place", target="lamp", parameters={"object": "lamp"})
        pred = self.predictor.predict(a, state)
        self.assertEqual(pred.expected_change["expected"], "success")
        self.assertEqual(pred.expected_change["state"], "on_ground")

    def test_place_not_held(self):
        lamp = EnvironmentObject.create(name="lamp", position={"x": 1.0, "y": 1.0}, state="on")
        state = make_state(objects=[lamp])
        a = EmbodiedAction.create(action_type="place", target="lamp", parameters={"object": "lamp"})
        pred = self.predictor.predict(a, state)
        self.assertEqual(pred.expected_change["expected"], "failure")
        self.assertIn("先拾取", pred.expected_change["suggestion"])

    def test_place_missing(self):
        a = EmbodiedAction.create(action_type="place", target="ghost", parameters={"object": "ghost"})
        pred = self.predictor.predict(a, make_state())
        self.assertEqual(pred.expected_change["expected"], "failure")


class TestOtherActionsPrediction(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_scan_no_change(self):
        pred = self.predictor.predict(
            EmbodiedAction.create(action_type="scan"), make_state(),
        )
        self.assertEqual(pred.expected_change["expected"], "no_change")
        self.assertEqual(pred.expected_change["event"], "scan")

    def test_explore_no_change(self):
        pred = self.predictor.predict(
            EmbodiedAction.create(action_type="explore"), make_state(),
        )
        self.assertEqual(pred.expected_change["expected"], "no_change")

    def test_wait_no_change(self):
        pred = self.predictor.predict(
            EmbodiedAction.create(action_type="wait"), make_state(),
        )
        self.assertEqual(pred.expected_change["expected"], "no_change")

    def test_custom_no_change(self):
        pred = self.predictor.predict(
            EmbodiedAction.create(action_type="custom"), make_state(),
        )
        self.assertEqual(pred.expected_change["expected"], "no_change")

    def test_inspect_success(self):
        lamp = EnvironmentObject.create(name="lamp", position={"x": 1.0, "y": 1.0})
        state = make_state(objects=[lamp])
        pred = self.predictor.predict(
            EmbodiedAction.create(action_type="inspect", target="lamp", parameters={"object": "lamp"}),
            state,
        )
        self.assertEqual(pred.expected_change["event"], "inspect")
        self.assertEqual(pred.expected_change["expected"], "no_change")

    def test_inspect_missing(self):
        pred = self.predictor.predict(
            EmbodiedAction.create(action_type="inspect", target="ghost", parameters={"object": "ghost"}),
            make_state(),
        )
        self.assertEqual(pred.expected_change["expected"], "failure")

    def test_action_none_with_state(self):
        state = make_state()
        pred = self.predictor.predict(None, state)
        self.assertEqual(pred.expected_change["event"], "stability")


class TestVerify(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_verify_matched(self):
        pred = self.predictor.predict(
            EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0}),
            make_state(),
        )
        v = self.predictor.verify(pred, {"event": "position_change"})
        self.assertTrue(v["matched"])
        self.assertEqual(v["expected"], "position_change")
        self.assertEqual(v["actual"], "position_change")

    def test_verify_mismatched(self):
        pred = self.predictor.predict(
            EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0}),
            make_state(),
        )
        v = self.predictor.verify(pred, {"event": "move_out_of_bounds"})
        self.assertFalse(v["matched"])

    def test_verify_empty_actual(self):
        pred = self.predictor.predict(EmbodiedAction.create(action_type="scan"), make_state())
        v = self.predictor.verify(pred, {})
        self.assertFalse(v["matched"])
        self.assertEqual(v["actual"], "unknown")


class TestDeterminism(unittest.TestCase):

    def test_same_input_same_output(self):
        predictor = StatePredictor()
        state = make_state(location={"x": 2.0, "y": 2.0})
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 1})
        p1 = predictor.predict(a, state)
        p2 = predictor.predict(a, make_state(location={"x": 2.0, "y": 2.0}))
        self.assertEqual(p1.expected_change, p2.expected_change)
        self.assertEqual(p1.confidence, p2.confidence)

    def test_status(self):
        st = StatePredictor().status()
        self.assertEqual(st["mode"], "rule_based")
        self.assertIn("supported_actions", st)

    def test_reset_noop(self):
        predictor = StatePredictor()
        predictor.reset()  # 不应抛异常
        self.assertEqual(predictor.status()["mode"], "rule_based")


if __name__ == "__main__":
    unittest.main()
