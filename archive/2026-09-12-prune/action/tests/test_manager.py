"""
YHLZ Vision Action V1.0 - Manager 单元测试

覆盖:
    - 执行器注册 / 注销 / 查询
    - 路由 (指定 / 默认)
    - 生命周期 (start / stop)
    - 默认注册 (mock + real 占位)
    - 单例 get_manager / reset_manager
"""
import unittest

from backend.action.executors.mock_executor import MockActionExecutor
from backend.action.manager import (
    ActionManager,
    ActionManagerError,
    get_manager,
    reset_manager,
)
from backend.action.schema import ActionRequest


class TestActionManager(unittest.TestCase):

    def setUp(self):
        self.mgr = ActionManager()

    def test_register_executor(self):
        ex = MockActionExecutor()
        self.mgr.register_executor("test", ex)
        self.assertTrue(self.mgr.has_executor("test"))
        self.assertEqual(self.mgr.get_executor("test"), ex)

    def test_register_duplicate_raises(self):
        self.mgr.register_executor("test", MockActionExecutor())
        with self.assertRaises(ActionManagerError):
            self.mgr.register_executor("test", MockActionExecutor())

    def test_register_duplicate_override(self):
        ex = MockActionExecutor()
        self.mgr.register_executor("test", MockActionExecutor())
        self.mgr.register_executor("test", ex, override=True)
        self.assertEqual(self.mgr.get_executor("test"), ex)

    def test_unregister(self):
        self.mgr.register_executor("test", MockActionExecutor())
        self.assertTrue(self.mgr.unregister_executor("test"))
        self.assertFalse(self.mgr.unregister_executor("test"))

    def test_default_executor_is_first(self):
        a = MockActionExecutor()
        b = MockActionExecutor()
        self.mgr.register_executor("a", a)
        self.mgr.register_executor("b", b)
        self.assertEqual(self.mgr.get_default_executor(), a)

    def test_route_default(self):
        a = MockActionExecutor()
        self.mgr.register_executor("a", a)
        req = ActionRequest.create(action_type="check", target="logs")
        self.assertEqual(self.mgr.route(req), a)

    def test_route_explicit(self):
        a = MockActionExecutor()
        b = MockActionExecutor()
        self.mgr.register_executor("a", a)
        self.mgr.register_executor("b", b)
        req = ActionRequest.create(action_type="check", target="logs",
                                   parameters={"executor": "b"})
        self.assertEqual(self.mgr.route(req), b)

    def test_route_missing_fallback(self):
        a = MockActionExecutor()
        self.mgr.register_executor("a", a)
        req = ActionRequest.create(action_type="check", target="logs",
                                   parameters={"executor": "ghost"})
        self.assertEqual(self.mgr.route(req), a)

    def test_route_no_executor(self):
        self.assertIsNone(self.mgr.route(ActionRequest.create(action_type="check")))

    def test_list_executors(self):
        self.mgr.register_executor("a", MockActionExecutor())
        info = self.mgr.list_executors()[0]
        self.assertEqual(info["name"], "a")
        self.assertTrue(info["available"])
        self.assertEqual(self.mgr.list_names(), ["a"])

    def test_start_stop(self):
        self.mgr.register_executor("a", MockActionExecutor())
        self.mgr.start()
        self.assertTrue(self.mgr.is_running)
        self.mgr.stop()
        self.assertFalse(self.mgr.is_running)
        self.assertEqual(self.mgr.list_names(), [])

    def test_register_defaults(self):
        self.mgr.register_defaults()
        names = self.mgr.list_names()
        self.assertIn("mock", names)
        self.assertIn("real", names)
        self.assertFalse(self.mgr.get_executor("real").is_available())

    def test_register_defaults_idempotent(self):
        self.mgr.register_defaults()
        first = self.mgr.get_default_executor()
        self.mgr.register_defaults()
        self.assertEqual(self.mgr.get_default_executor(), first)

    def test_reset(self):
        self.mgr.register_executor("a", MockActionExecutor())
        self.mgr.reset()
        self.assertEqual(self.mgr.list_names(), [])

    def test_status(self):
        self.mgr.register_executor("a", MockActionExecutor())
        st = self.mgr.status()
        self.assertEqual(st["executors_count"], 1)
        self.assertEqual(st["default_executor"], "mock")


class TestActionManagerSingleton(unittest.TestCase):

    def tearDown(self):
        reset_manager()

    def test_get_manager_singleton(self):
        m1 = get_manager()
        m2 = get_manager()
        self.assertIs(m1, m2)
        # 单例已注册默认执行器 (mock 可用)
        self.assertIn("mock", m1.list_names())

    def test_reset_manager(self):
        m1 = get_manager()
        reset_manager()
        m2 = get_manager()
        self.assertIsNot(m1, m2)


if __name__ == "__main__":
    unittest.main()
