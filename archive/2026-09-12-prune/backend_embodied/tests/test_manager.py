"""
YHLZ Embodied AI V4.1 - Manager 单元测试

覆盖:
    - 环境注册 / 注销 / 查询
    - 路由
    - 默认注册 (mock 可用 / hardware 占位不可用)
    - 生命周期 (start / stop / is_running)
    - 基础设施 (WorldModel / FeedbackStore / Memory / Analyzer / Predictor)
    - V4.1: predict / verify_prediction / process_feedback
    - 全局单例 + 重置
"""
import unittest

from backend.embodied.environment import EnvironmentRegistryError
from backend.embodied.manager import (
    EmbodiedManager,
    EmbodiedManagerError,
    get_manager,
    reset_manager,
)
from backend.embodied.schema import (
    EmbodiedAction,
    EnvironmentState,
    Feedback,
    FeedbackResult,
)
from backend.embodied.tests.test_environment import StubEnvironment


class TestManagerRegistry(unittest.TestCase):

    def setUp(self):
        self.mgr = EmbodiedManager()

    def test_register_and_get(self):
        env = StubEnvironment("myenv")
        self.mgr.register_environment("myenv", env)
        self.assertIs(self.mgr.get_environment("myenv"), env)

    def test_register_duplicate_raises(self):
        self.mgr.register_environment("myenv", StubEnvironment())
        with self.assertRaises(EnvironmentRegistryError):
            self.mgr.register_environment("myenv", StubEnvironment())

    def test_register_override(self):
        self.mgr.register_environment("myenv", StubEnvironment("a"))
        self.mgr.register_environment("myenv", StubEnvironment("b"), override=True)
        self.assertEqual(self.mgr.get_environment("myenv").name, "b")

    def test_unregister(self):
        self.mgr.register_environment("myenv", StubEnvironment())
        self.assertTrue(self.mgr.unregister_environment("myenv"))
        self.assertIsNone(self.mgr.get_environment("myenv"))

    def test_default_environment(self):
        self.mgr.register_environment("a", StubEnvironment("a"))
        self.mgr.register_environment("b", StubEnvironment("b"))
        self.assertEqual(self.mgr.get_default_environment().name, "a")

    def test_route_to_explicit(self):
        env = StubEnvironment("sim")
        self.mgr.register_environment("sim", env)
        a = EmbodiedAction.create(action_type="scan", parameters={"environment": "sim"})
        self.assertIs(self.mgr.route(a), env)

    def test_route_empty(self):
        self.assertIsNone(self.mgr.route(EmbodiedAction.create(action_type="scan")))

    def test_list_names(self):
        self.mgr.register_environment("a", StubEnvironment("a"))
        self.assertEqual(self.mgr.list_names(), ["a"])


class TestManagerDefaults(unittest.TestCase):

    def setUp(self):
        self.mgr = EmbodiedManager()

    def test_register_defaults_mock_available(self):
        self.mgr.register_defaults()
        mock = self.mgr.get_environment("mock")
        self.assertIsNotNone(mock)
        self.assertTrue(mock.is_available())

    def test_register_defaults_hardware_placeholder(self):
        self.mgr.register_defaults()
        hw = self.mgr.get_environment("hardware")
        self.assertIsNotNone(hw)
        self.assertFalse(hw.is_available())

    def test_register_defaults_idempotent(self):
        self.mgr.register_defaults()
        self.mgr.register_defaults()
        self.assertEqual(len(self.mgr.list_names()), 2)

    def test_default_route_mock(self):
        self.mgr.register_defaults()
        env = self.mgr.route(EmbodiedAction.create(action_type="scan"))
        self.assertEqual(env.name, "mock")

    def test_status(self):
        self.mgr.register_defaults()
        st = self.mgr.status()
        self.assertEqual(st["environments_count"], 2)
        self.assertEqual(st["default_environment"], "mock")
        self.assertFalse(st["running"])


class TestManagerLifecycle(unittest.TestCase):

    def setUp(self):
        self.mgr = EmbodiedManager()
        self.mgr.register_defaults()

    def test_start_stop(self):
        self.mgr.start()
        self.assertTrue(self.mgr.is_running)
        self.mgr.stop()
        self.assertFalse(self.mgr.is_running)
        self.assertEqual(self.mgr.list_names(), [])

    def test_stop_closes_and_clears(self):
        self.mgr.start()
        self.mgr.stop()
        self.assertIsNone(self.mgr.get_environment("mock"))

    def test_reset(self):
        self.mgr.register_environment("custom", StubEnvironment())
        self.mgr.world_model.update(EnvironmentState.create())
        self.mgr.reset()
        self.assertEqual(self.mgr.list_names(), [])
        self.assertEqual(self.mgr.world_model.count(), 0)
        self.assertFalse(self.mgr.is_running)


class TestManagerInfrastructure(unittest.TestCase):

    def test_world_model_shared(self):
        mgr = EmbodiedManager()
        self.assertEqual(mgr.world_model.count(), 0)
        mgr.world_model.update(EnvironmentState.create())
        self.assertEqual(mgr.world_model.count(), 1)

    def test_feedback_shared(self):
        mgr = EmbodiedManager()
        self.assertEqual(mgr.feedback.count(), 0)


class TestManagerV41(unittest.TestCase):
    """V4.1: 状态预测 / 反馈处理 / 记忆"""

    def setUp(self):
        self.mgr = EmbodiedManager()
        self.mgr.register_defaults()

    def test_predict_move(self):
        self.mgr.world_model.update(EnvironmentState.create(location={"x": 0.0, "y": 0.0}))
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        pred = self.mgr.predict(a)
        self.assertIsNotNone(pred)
        self.assertEqual(pred.expected_change["event"], "move")

    def test_predict_without_state(self):
        mgr = EmbodiedManager()
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        self.assertIsNone(mgr.predict(a))

    def test_predict_disabled(self):
        mgr = EmbodiedManager(predictor_enabled=False)
        self.assertIsNone(mgr.predictor)
        a = EmbodiedAction.create(action_type="move")
        self.assertIsNone(mgr.predict(a))

    def test_verify_prediction(self):
        self.mgr.world_model.update(EnvironmentState.create(location={"x": 0.0, "y": 0.0}))
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        pred = self.mgr.predict(a)
        v = self.mgr.verify_prediction(pred, {"event": "position_change"})
        self.assertTrue(v["matched"])

    def test_process_feedback_success(self):
        self.mgr.world_model.update(EnvironmentState.create(location={"x": 0.0, "y": 0.0}))
        fb = Feedback.create(
            action_id="a1", result="success",
            environment_change={"event": "move", "to": [1, 0]},
        )
        analysis = self.mgr.process_feedback(fb, state=EnvironmentState.create(location={"x": 1.0, "y": 0.0}))
        self.assertTrue(analysis.success)
        self.assertEqual(self.mgr.feedback.count(), 1)
        self.assertGreaterEqual(self.mgr.memory.count(), 2)  # action + change

    def test_process_feedback_failure(self):
        fb = Feedback.create(
            action_id="a2", result="failure",
            error="对象 lamp 不在当前位置, 无法拾取",
        )
        analysis = self.mgr.process_feedback(fb)
        self.assertFalse(analysis.success)
        self.assertIn("移动到", analysis.suggestion)

    def test_process_feedback_no_memory(self):
        fb = Feedback.create(action_id="a3", result="success")
        self.mgr.process_feedback(fb, record_memory=False)
        self.assertEqual(self.mgr.memory.count(), 0)
        self.assertEqual(self.mgr.feedback.count(), 1)

    def test_memory_and_analyzer_exposed(self):
        self.assertIsNotNone(self.mgr.memory)
        self.assertIsNotNone(self.mgr.analyzer)
        self.assertIsNotNone(self.mgr.predictor)

    def test_status_includes_v41(self):
        st = self.mgr.status()
        self.assertIn("memory", st)
        self.assertIn("predictor", st)
        self.assertIn("world_model", st)
        self.assertTrue(st["predictor"]["enabled"])

    def test_reset_clears_memory(self):
        self.mgr.process_feedback(Feedback.create(action_id="a1", result="success"))
        self.mgr.reset()
        self.assertEqual(self.mgr.memory.count(), 0)
        self.assertEqual(self.mgr.feedback.count(), 0)


class TestManagerSingleton(unittest.TestCase):

    def tearDown(self):
        reset_manager()

    def test_get_manager_singleton(self):
        m1 = get_manager()
        m2 = get_manager()
        self.assertIs(m1, m2)

    def test_reset_manager(self):
        m1 = get_manager()
        reset_manager()
        m2 = get_manager()
        self.assertIsNot(m1, m2)


if __name__ == "__main__":
    unittest.main()
