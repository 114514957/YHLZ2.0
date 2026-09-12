"""
YHLZ Vision Action V1.0 - Interface 单元测试

覆盖:
    - ActionExecutor 抽象接口方法完整性
    - ActionExecutorError 异常
"""
import unittest
from abc import ABC

from backend.action.interface import ActionExecutor, ActionExecutorError


class TestActionExecutorInterface(unittest.TestCase):

    def test_is_abstract(self):
        self.assertTrue(issubclass(ActionExecutor, ABC))

    def test_cannot_instantiate(self):
        with self.assertRaises(TypeError):
            ActionExecutor()

    def test_abstract_methods(self):
        abstract = ActionExecutor.__abstractmethods__
        expected = {"name", "supported_types", "create", "validate", "execute", "cancel", "status"}
        self.assertEqual(set(abstract), expected)

    def test_error_is_exception(self):
        err = ActionExecutorError("测试错误")
        self.assertIsInstance(err, Exception)
        self.assertIn("测试错误", str(err))

    def test_concrete_executor_instantiable(self):
        from backend.action.executors.mock_executor import MockActionExecutor
        ex = MockActionExecutor()
        self.assertEqual(ex.name, "mock")
        self.assertTrue(ex.is_available())
        ex.close()


if __name__ == "__main__":
    unittest.main()
