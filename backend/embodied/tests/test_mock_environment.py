"""
YHLZ Embodied AI V4.0 - Mock 环境单元测试

覆盖:
    - observe / get_state / reset
    - move (成功 / 越界 / 原地)
    - pick (成功 / 不在范围 / 对象不存在)
    - place (成功 / 未持有 / 对象不存在)
    - inspect (成功 / 不存在)
    - scan / explore / wait / custom
    - feedback 查询
    - 不支持动作类型
    - 状态快照完整性 (history / metadata)
"""
import unittest

from backend.embodied.environment.mock import MockEnvironment
from backend.embodied.schema import (
    EmbodiedAction,
    EmbodiedActionType,
    FeedbackResult,
)


class TestMockBasic(unittest.TestCase):

    def setUp(self):
        self.env = MockEnvironment(scene="room")

    def test_name(self):
        self.assertEqual(self.env.name, "mock")

    def test_supported_actions(self):
        self.assertEqual(set(self.env.supported_actions), set(EmbodiedActionType.values()))

    def test_is_available(self):
        self.assertTrue(self.env.is_available())

    def test_observe_initial_state(self):
        s = self.env.observe()
        self.assertEqual(len(s.objects), 4)
        self.assertEqual(s.position, {"x": 0.0, "y": 0.0})
        self.assertIn("temperature", s.conditions)

    def test_get_state_equals_observe(self):
        self.assertEqual(self.env.get_state().position, self.env.observe().position)

    def test_reset_restores(self):
        self.env.step(EmbodiedAction.create(
            action_type="move", parameters={"dx": 1, "dy": 1},
        ))
        s = self.env.reset()
        self.assertEqual(s.position, {"x": 0.0, "y": 0.0})
        self.assertEqual(s.history[-1]["event"], "reset")

    def test_status(self):
        st = self.env.status()
        self.assertEqual(st["name"], "mock")
        self.assertEqual(st["grid_size"], [5, 5])
        self.assertEqual(st["objects"], 4)

    def test_observe_updates_after_step(self):
        self.env.step(EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0}))
        self.assertEqual(self.env.observe().position, {"x": 1.0, "y": 0.0})


class TestMockMove(unittest.TestCase):

    def setUp(self):
        self.env = MockEnvironment()

    def test_move_success(self):
        a = EmbodiedAction.create(action_type="move", intent="向前移动", parameters={"dx": 1, "dy": 0})
        s = self.env.step(a)
        self.assertEqual(s.position, {"x": 1.0, "y": 0.0})
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.SUCCESS.value)
        self.assertEqual(fb.environment_change["event"], "move")
        self.assertEqual(fb.environment_change["to"], [1, 0])

    def test_move_out_of_bounds(self):
        a = EmbodiedAction.create(action_type="move", parameters={"dx": -1, "dy": 0})
        s = self.env.step(a)
        self.assertEqual(s.position, {"x": 0.0, "y": 0.0})
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.NO_CHANGE.value)
        self.assertIn("越界", fb.error)

    def test_move_stationary(self):
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 0, "dy": 0})
        s = self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.NO_CHANGE.value)
        self.assertEqual(fb.environment_change["event"], "move_stationary")

    def test_move_grid_boundary(self):
        env = MockEnvironment(grid_size=(2, 2))
        env.step(EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 1}))
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 1})
        env.step(a)
        fb = env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.NO_CHANGE.value)


class TestMockPickPlace(unittest.TestCase):

    def setUp(self):
        self.env = MockEnvironment(scene="room")

    def _move_to(self, x, y):
        self.env.step(EmbodiedAction.create(action_type="move", parameters={"dx": x, "dy": y}))

    def test_pick_success(self):
        self._move_to(1, 1)  # lamp 在 (1,1)
        a = EmbodiedAction.create(action_type="pick", target="lamp", parameters={"object": "lamp"})
        s = self.env.step(a)
        lamp = [o for o in s.objects if o.name == "lamp"][0]
        self.assertEqual(lamp.state, "held")
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.SUCCESS.value)
        self.assertEqual(fb.environment_change["object"], "lamp")

    def test_pick_not_in_reach(self):
        # 主体在 (0,0), lamp 在 (1,1)
        a = EmbodiedAction.create(action_type="pick", target="lamp", parameters={"object": "lamp"})
        s = self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.FAILURE.value)
        self.assertEqual(fb.environment_change["event"], "pick_not_in_reach")
        lamp = [o for o in s.objects if o.name == "lamp"][0]
        self.assertNotEqual(lamp.state, "held")

    def test_pick_missing_object(self):
        a = EmbodiedAction.create(action_type="pick", target="ghost", parameters={"object": "ghost"})
        self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.FAILURE.value)
        self.assertEqual(fb.environment_change["event"], "pick_missing")

    def test_pick_no_target(self):
        a = EmbodiedAction.create(action_type="pick")
        self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.FAILURE.value)

    def test_place_after_pick(self):
        self._move_to(1, 1)
        self.env.step(EmbodiedAction.create(action_type="pick", target="lamp", parameters={"object": "lamp"}))
        self._move_to(2, 2)
        a = EmbodiedAction.create(action_type="place", target="lamp", parameters={"object": "lamp"})
        s = self.env.step(a)
        lamp = [o for o in s.objects if o.name == "lamp"][0]
        self.assertEqual(lamp.state, "on_ground")
        self.assertEqual(lamp.position, {"x": 3.0, "y": 3.0})
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.SUCCESS.value)

    def test_place_without_hold(self):
        a = EmbodiedAction.create(action_type="place", target="box", parameters={"object": "box"})
        self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.FAILURE.value)
        self.assertEqual(fb.environment_change["event"], "place_not_held")

    def test_place_missing_object(self):
        a = EmbodiedAction.create(action_type="place", target="ghost", parameters={"object": "ghost"})
        self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.FAILURE.value)


class TestMockInspectScan(unittest.TestCase):

    def setUp(self):
        self.env = MockEnvironment(scene="room")

    def test_inspect_success(self):
        a = EmbodiedAction.create(action_type="inspect", target="lamp", parameters={"object": "lamp"})
        self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.SUCCESS.value)
        self.assertEqual(fb.environment_change["category"], "light")

    def test_inspect_missing(self):
        a = EmbodiedAction.create(action_type="inspect", target="ghost", parameters={"object": "ghost"})
        self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.FAILURE.value)

    def test_scan_success(self):
        a = EmbodiedAction.create(action_type="scan", intent="扫描环境")
        s = self.env.step(a)
        self.assertEqual(len(s.objects), 4)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.SUCCESS.value)
        self.assertEqual(fb.environment_change["event"], "scan")

    def test_explore_success(self):
        a = EmbodiedAction.create(action_type="explore")
        self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.SUCCESS.value)

    def test_wait_success(self):
        a = EmbodiedAction.create(action_type="wait")
        self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.SUCCESS.value)

    def test_custom_success(self):
        a = EmbodiedAction.create(action_type="custom", target="note")
        s = self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.SUCCESS.value)
        self.assertTrue(fb.environment_change["simulated"])


class TestMockFeedbackAndSafety(unittest.TestCase):

    def setUp(self):
        self.env = MockEnvironment(scene="room")

    def test_feedback_missing(self):
        self.assertIsNone(self.env.feedback("no_such_action"))

    def test_unsupported_action_type(self):
        a = EmbodiedAction.create(action_type="fly")
        s = self.env.step(a)
        fb = self.env.feedback(a.action_id)
        self.assertEqual(fb.result, FeedbackResult.FAILURE.value)
        self.assertIn("不支持", fb.error)
        # 状态未变化
        self.assertEqual(s.position, {"x": 0.0, "y": 0.0})

    def test_state_history_tracks_events(self):
        self.env.step(EmbodiedAction.create(action_type="scan"))
        self.env.step(EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0}))
        s = self.env.observe()
        events = [e["event"] for e in s.history]
        self.assertIn("scan", events)
        self.assertIn("move", events)

    def test_step_count_in_metadata(self):
        self.env.step(EmbodiedAction.create(action_type="scan"))
        s = self.env.observe()
        self.assertEqual(s.metadata["steps"], 1)

    def test_close_clears(self):
        a = EmbodiedAction.create(action_type="scan")
        self.env.step(a)
        self.env.close()
        self.assertIsNone(self.env.feedback(a.action_id))

    def test_deterministic(self):
        env2 = MockEnvironment()
        a1 = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 1})
        a2 = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 1})
        s1 = self.env.step(a1)
        s2 = env2.step(a2)
        self.assertEqual(s1.position, s2.position)


class TestMockCustomObjects(unittest.TestCase):

    def test_custom_initial_objects(self):
        from backend.embodied.schema import EnvironmentObject
        obj = EnvironmentObject.create(
            name="cup", category="item", position={"x": 4.0, "y": 4.0}, state="on_table",
        )
        env = MockEnvironment(objects=[obj])
        s = env.observe()
        self.assertEqual(len(s.objects), 1)
        self.assertEqual(s.objects[0].name, "cup")

    def test_custom_grid_size(self):
        env = MockEnvironment(grid_size=(10, 10))
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 9, "dy": 9})
        s = env.step(a)
        self.assertEqual(s.position, {"x": 9.0, "y": 9.0})


if __name__ == "__main__":
    unittest.main()
