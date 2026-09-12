"""
YHLZ Embodied AI V4.0 - 环境注册中心单元测试

覆盖:
    - 注册 / 注销 / 重复注册
    - 查询 (按名 / 默认 / 列表)
    - 路由 (指定环境 / 默认回退 / 不存在回退)
    - 重置
"""
import unittest

from backend.embodied.environment import EnvironmentRegistry, EnvironmentRegistryError
from backend.embodied.environment.interface import Environment
from backend.embodied.schema import EmbodiedAction, EnvironmentState


class StubEnvironment(Environment):
    """测试用最小环境"""

    def __init__(self, name: str = "stub"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

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


class TestRegistryRegister(unittest.TestCase):

    def setUp(self):
        self.reg = EnvironmentRegistry()

    def test_register_and_get(self):
        env = StubEnvironment("mock")
        self.reg.register("mock", env)
        self.assertIs(self.reg.get("mock"), env)

    def test_register_duplicate_raises(self):
        self.reg.register("mock", StubEnvironment())
        with self.assertRaises(EnvironmentRegistryError):
            self.reg.register("mock", StubEnvironment())

    def test_register_duplicate_override(self):
        self.reg.register("mock", StubEnvironment("a"))
        self.reg.register("mock", StubEnvironment("b"), override=True)
        self.assertEqual(self.reg.get("mock").name, "b")

    def test_unregister(self):
        self.reg.register("mock", StubEnvironment())
        self.assertTrue(self.reg.unregister("mock"))
        self.assertIsNone(self.reg.get("mock"))

    def test_unregister_missing(self):
        self.assertFalse(self.reg.unregister("missing"))

    def test_has(self):
        self.reg.register("mock", StubEnvironment())
        self.assertTrue(self.reg.has("mock"))
        self.assertFalse(self.reg.has("other"))

    def test_count(self):
        self.reg.register("a", StubEnvironment("a"))
        self.reg.register("b", StubEnvironment("b"))
        self.assertEqual(self.reg.count(), 2)


class TestRegistryQuery(unittest.TestCase):

    def setUp(self):
        self.reg = EnvironmentRegistry()
        self.mock = StubEnvironment("mock")
        self.reg.register("mock", self.mock)
        self.reg.register("sim", StubEnvironment("sim"))

    def test_get_default_first_registered(self):
        self.assertIs(self.reg.get_default(), self.mock)

    def test_get_default_empty(self):
        reg = EnvironmentRegistry()
        self.assertIsNone(reg.get_default())

    def test_list(self):
        items = self.reg.list()
        names = {i["name"] for i in items}
        self.assertEqual(names, {"mock", "sim"})
        self.assertTrue(all("class" in i and "available" in i for i in items))

    def test_list_names(self):
        self.assertEqual(set(self.reg.list_names()), {"mock", "sim"})


class TestRegistryRoute(unittest.TestCase):

    def setUp(self):
        self.reg = EnvironmentRegistry()
        self.mock = StubEnvironment("mock")
        self.sim = StubEnvironment("sim")
        self.reg.register("mock", self.mock)
        self.reg.register("sim", self.sim)

    def test_route_default(self):
        env = self.reg.route(EmbodiedAction.create(action_type="scan"))
        self.assertIs(env, self.mock)

    def test_route_explicit(self):
        action = EmbodiedAction.create(action_type="scan", parameters={"environment": "sim"})
        self.assertIs(self.reg.route(action), self.sim)

    def test_route_missing_environment_falls_back(self):
        action = EmbodiedAction.create(action_type="scan", parameters={"environment": "nope"})
        self.assertIs(self.reg.route(action), self.mock)

    def test_route_empty_registry(self):
        reg = EnvironmentRegistry()
        self.assertIsNone(reg.route(EmbodiedAction.create(action_type="scan")))

    def test_route_bad_parameters(self):
        action = EmbodiedAction.create(action_type="scan")
        action.parameters = None  # 边界: parameters 为 None
        self.assertIs(self.reg.route(action), self.mock)


class TestRegistryReset(unittest.TestCase):

    def test_reset_clears(self):
        reg = EnvironmentRegistry()
        reg.register("mock", StubEnvironment())
        reg.reset()
        self.assertEqual(reg.count(), 0)
        self.assertIsNone(reg.get_default())


if __name__ == "__main__":
    unittest.main()
