"""
YHLZ Embodied AI V4.0 - 环境接口单元测试

覆盖:
    - Environment ABC 抽象强制 (不可实例化)
    - EnvironmentError 异常
    - 最小实现类可正常使用
    - 接口方法与文档契约
"""
import unittest

from backend.embodied.environment.interface import Environment, EnvironmentError
from backend.embodied.schema import EmbodiedAction, EnvironmentState, Feedback


class TestEnvironmentABC(unittest.TestCase):

    def test_abstract_cannot_instantiate(self):
        """Environment 是纯抽象接口, 禁止直接实例化"""
        with self.assertRaises(TypeError):
            Environment()  # type: ignore[abstract]

    def test_missing_methods_prevent_instantiation(self):
        """缺少抽象方法无法实例化 (防止不完整实现绕过接口)"""
        class IncompleteEnv(Environment):
            @property
            def name(self) -> str:
                return "incomplete"

        with self.assertRaises(TypeError):
            IncompleteEnv()

    def test_is_available_default(self):
        """默认可用 (子类未覆盖时)"""
        class Env(Environment):
            @property
            def name(self) -> str:
                return "env"

            @property
            def supported_actions(self) -> list:
                return ["scan"]

            def observe(self) -> EnvironmentState:
                return EnvironmentState.create()

            def step(self, action: EmbodiedAction) -> EnvironmentState:
                return EnvironmentState.create()

            def reset(self) -> EnvironmentState:
                return EnvironmentState.create()

            def get_state(self) -> EnvironmentState:
                return EnvironmentState.create()

            def feedback(self, action_id: str):
                return None

        env = Env()
        self.assertTrue(env.is_available())

    def test_close_default_noop(self):
        """close 默认无操作 (不抛异常)"""
        class Env(Environment):
            @property
            def name(self) -> str:
                return "env"

            @property
            def supported_actions(self) -> list:
                return []

            def observe(self) -> EnvironmentState:
                return EnvironmentState.create()

            def step(self, action: EmbodiedAction) -> EnvironmentState:
                return EnvironmentState.create()

            def reset(self) -> EnvironmentState:
                return EnvironmentState.create()

            def get_state(self) -> EnvironmentState:
                return EnvironmentState.create()

            def feedback(self, action_id: str):
                return None

        env = Env()
        env.close()  # 不应抛异常


class TestEnvironmentError(unittest.TestCase):

    def test_exception_subclass(self):
        err = EnvironmentError("测试错误")
        self.assertIsInstance(err, Exception)
        self.assertEqual(str(err), "测试错误")


if __name__ == "__main__":
    unittest.main()
