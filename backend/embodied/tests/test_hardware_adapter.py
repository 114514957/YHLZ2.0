"""
YHLZ Embodied AI V4.0 - 硬件适配器单元测试

覆盖:
    - 占位语义: 默认不可用
    - step / reset 拒绝 (EnvironmentError)
    - observe 返回占位状态 (不崩溃)
    - 无真实控制 (supported_actions 为空)
"""
import unittest

from backend.embodied.environment.adapter import HardwareEnvironment
from backend.embodied.environment.interface import EnvironmentError
from backend.embodied.schema import EmbodiedAction


class TestHardwareAdapter(unittest.TestCase):

    def setUp(self):
        self.env = HardwareEnvironment()

    def test_name(self):
        self.assertEqual(self.env.name, "hardware")

    def test_not_available_by_default(self):
        """本版本硬件适配器默认不可用 (防止误控制真实设备)"""
        self.assertFalse(self.env.is_available())

    def test_supported_actions_empty(self):
        """占位适配器不声明任何真实动作"""
        self.assertEqual(self.env.supported_actions, [])

    def test_step_raises(self):
        """step 必须拒绝: 禁止控制真实设备"""
        a = EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0})
        with self.assertRaises(EnvironmentError) as ctx:
            self.env.step(a)
        self.assertIn("HARDWARE_NOT_AVAILABLE", str(ctx.exception))

    def test_reset_raises(self):
        with self.assertRaises(EnvironmentError):
            self.env.reset()

    def test_observe_placeholder(self):
        """observe 返回占位状态, 不崩溃"""
        s = self.env.observe()
        self.assertEqual(s.objects, [])
        self.assertFalse(s.metadata["available"])

    def test_feedback_none(self):
        self.assertIsNone(self.env.feedback("a1"))

    def test_status(self):
        st = self.env.status()
        self.assertEqual(st["name"], "hardware")
        self.assertFalse(st["available"])


if __name__ == "__main__":
    unittest.main()
