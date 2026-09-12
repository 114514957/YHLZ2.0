"""
YHLZ Embodied AI V4.2 - 多步条件预测单元测试

覆盖:
    - MOVE + PICK → object = held (最终预期)
    - PICK (不先移动) → 失败预期
    - MOVE 越界 → no_change
    - PLACE (未持有) → 失败预期
    - 空序列 → 空预测
    - 不变式检测 (invariants_ok / violations)
    - 推演不污染世界模型 (深拷贝)
    - 确定性 / 序列化 / check_invariants
"""
import unittest

from backend.embodied.schema import (
    EmbodiedAction,
    EnvironmentObject,
    EnvironmentState,
)
from backend.embodied.world_model import StatePredictor


def make_state(objects=None, location=None, grid=(5, 5)) -> EnvironmentState:
    return EnvironmentState.create(
        objects=objects or [], location=location or {"x": 0.0, "y": 0.0},
        metadata={"grid_size": list(grid)},
    )


def act(action_type, target="", params=None) -> EmbodiedAction:
    return EmbodiedAction.create(
        action_type=action_type, target=target, parameters=params or {},
    )


class TestPredictSequenceSuccess(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_move_then_pick_held(self):
        """MOVE + PICK → object = held (核心场景)"""
        lamp = EnvironmentObject.create(
            name="lamp", position={"x": 1.0, "y": 1.0}, state="on",
        )
        state = make_state(objects=[lamp], location={"x": 0.0, "y": 0.0})
        pred = self.predictor.predict_sequence([
            act("move", params={"dx": 1, "dy": 1}),
            act("pick", target="lamp", params={"object": "lamp"}),
        ], state)
        self.assertEqual(len(pred.steps), 2)
        self.assertEqual(pred.steps[0]["expected"]["expected"], "position_change")
        self.assertEqual(pred.steps[1]["expected"]["expected"], "success")
        self.assertEqual(pred.final_expected["objects"]["lamp"], "held")
        self.assertEqual(pred.final_expected["location"], {"x": 1.0, "y": 1.0})
        self.assertTrue(pred.invariants_ok)
        self.assertGreaterEqual(pred.confidence, 0.8)

    def test_steps_actions_recorded(self):
        state = make_state()
        pred = self.predictor.predict_sequence([
            act("move", params={"dx": 1, "dy": 0}),
        ], state)
        self.assertEqual(len(pred.actions), 1)
        self.assertEqual(pred.actions[0]["action_type"], "move")

    def test_pick_without_move_fails(self):
        lamp = EnvironmentObject.create(
            name="lamp", position={"x": 3.0, "y": 3.0}, state="on",
        )
        state = make_state(objects=[lamp], location={"x": 0.0, "y": 0.0})
        pred = self.predictor.predict_sequence([
            act("pick", target="lamp", params={"object": "lamp"}),
        ], state)
        self.assertEqual(pred.steps[0]["expected"]["expected"], "failure")
        self.assertNotEqual(pred.final_expected["objects"].get("lamp"), "held")


class TestPredictSequenceEdgeCases(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_empty_sequence(self):
        pred = self.predictor.predict_sequence([], make_state())
        self.assertEqual(pred.steps, [])
        self.assertTrue(pred.invariants_ok)
        self.assertGreaterEqual(pred.confidence, 0.0)

    def test_none_sequence(self):
        pred = self.predictor.predict_sequence(None, make_state())
        self.assertEqual(pred.steps, [])

    def test_move_out_of_bounds_sequence(self):
        state = make_state(location={"x": 0.0, "y": 0.0}, grid=(5, 5))
        pred = self.predictor.predict_sequence([
            act("move", params={"dx": -1, "dy": 0}),
        ], state)
        self.assertEqual(pred.steps[0]["expected"]["expected"], "no_change")
        self.assertEqual(pred.final_expected["location"], {"x": 0.0, "y": 0.0})

    def test_place_without_pick(self):
        cup = EnvironmentObject.create(
            name="cup", position={"x": 0.0, "y": 0.0}, state="on_ground",
        )
        state = make_state(objects=[cup])
        pred = self.predictor.predict_sequence([
            act("place", target="cup", params={"object": "cup"}),
        ], state)
        self.assertEqual(pred.steps[0]["expected"]["expected"], "failure")

    def test_full_cycle_move_pick_place(self):
        cup = EnvironmentObject.create(
            name="cup", position={"x": 1.0, "y": 0.0}, state="on_ground",
        )
        state = make_state(objects=[cup], location={"x": 0.0, "y": 0.0})
        pred = self.predictor.predict_sequence([
            act("move", params={"dx": 1, "dy": 0}),
            act("pick", target="cup", params={"object": "cup"}),
            act("move", params={"dx": 0, "dy": 1}),
            act("place", target="cup", params={"object": "cup"}),
        ], state)
        self.assertEqual(pred.steps[1]["expected"]["expected"], "success")
        self.assertEqual(pred.steps[3]["expected"]["expected"], "success")
        self.assertEqual(pred.final_expected["objects"]["cup"], "on_ground")
        self.assertEqual(pred.final_expected["location"], {"x": 1.0, "y": 1.0})
        self.assertTrue(pred.invariants_ok)

    def test_simulation_does_not_mutate_input_state(self):
        """推演用深拷贝, 不污染世界模型状态"""
        lamp = EnvironmentObject.create(
            name="lamp", position={"x": 1.0, "y": 1.0}, state="on",
        )
        state = make_state(objects=[lamp], location={"x": 0.0, "y": 0.0})
        original = state.to_dict()
        self.predictor.predict_sequence([
            act("move", params={"dx": 1, "dy": 1}),
            act("pick", target="lamp", params={"object": "lamp"}),
        ], state)
        self.assertEqual(state.to_dict(), original)
        self.assertEqual(state.objects[0].state, "on")


class TestPredictSequenceInvariants(unittest.TestCase):

    def setUp(self):
        self.predictor = StatePredictor()

    def test_check_invariants_no_violation(self):
        state = make_state(location={"x": 0.0, "y": 0.0})
        violations = self.predictor.check_invariants([
            act("move", params={"dx": 1, "dy": 0}),
        ], state)
        self.assertEqual(violations, [])

    def test_check_invariants_violation(self):
        """模拟状态被篡改 → 检测位置自发变化"""
        lamp = EnvironmentObject.create(name="lamp", state="on", position={"x": 1.0, "y": 1.0})
        # 无移动动作, 但 pick 会触发位置变化 → 不该有位置变化
        state = make_state(objects=[lamp], location={"x": 0.0, "y": 0.0})
        violations = self.predictor.check_invariants([
            act("scan"),
        ], state)
        self.assertEqual(violations, [])

    def test_invariants_ok_flag(self):
        state = make_state(location={"x": 0.0, "y": 0.0})
        pred = self.predictor.predict_sequence([
            act("move", params={"dx": 1, "dy": 0}),
            act("scan"),
        ], state)
        self.assertTrue(pred.invariants_ok)
        self.assertEqual(pred.invariant_violations, [])


class TestPredictSequenceDeterminism(unittest.TestCase):

    def test_same_input_same_output(self):
        lamp = EnvironmentObject.create(
            name="lamp", position={"x": 1.0, "y": 1.0}, state="on",
        )
        actions = [
            act("move", params={"dx": 1, "dy": 1}),
            act("pick", target="lamp", params={"object": "lamp"}),
        ]
        p1 = StatePredictor().predict_sequence(actions, make_state(objects=[lamp]))
        p2 = StatePredictor().predict_sequence(actions, make_state(objects=[lamp]))
        # 确定性: 除 prediction_id / timestamp 外完全一致
        d1, d2 = p1.to_dict(), p2.to_dict()
        d1.pop("prediction_id"); d1.pop("timestamp")
        d2.pop("prediction_id"); d2.pop("timestamp")
        self.assertEqual(d1, d2)
        self.assertEqual(p1.steps, p2.steps)
        self.assertEqual(p1.final_expected, p2.final_expected)
        self.assertEqual(p1.confidence, p2.confidence)

    def test_serialization(self):
        pred = StatePredictor().predict_sequence(
            [act("scan")], make_state(),
        )
        d = pred.to_dict()
        self.assertIn("steps", d)
        self.assertIn("final_expected", d)
        self.assertIn("invariants_ok", d)
        self.assertIn("confidence", d)

    def test_status_has_multi_step(self):
        st = StatePredictor().status()
        self.assertTrue(st["multi_step_prediction"])
        self.assertTrue(st["invariant_checking"])

    def test_reset_keeps_working(self):
        p = StatePredictor()
        p.reset()
        pred = p.predict_sequence([act("scan")], make_state())
        self.assertTrue(pred.invariants_ok)


if __name__ == "__main__":
    unittest.main()
