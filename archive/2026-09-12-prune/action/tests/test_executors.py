"""
YHLZ Vision Action V1.0 - 执行器单元测试

覆盖:
    - Mock 执行器: create / validate / execute / cancel / status
    - Mock 绝对安全 (不产生真实事件, 仅登记)
    - Real 执行器: 占位不可用, execute 返回 unsupported
"""
import unittest

from backend.action.executors.mock_executor import MockActionExecutor
from backend.action.executors.real_executor import RealActionExecutor
from backend.action.schema import ActionRequest, ActionStatus


class TestMockActionExecutor(unittest.TestCase):

    def setUp(self):
        self.ex = MockActionExecutor()

    def tearDown(self):
        self.ex.close()

    def test_name(self):
        self.assertEqual(self.ex.name, "mock")

    def test_supported_types(self):
        types = self.ex.supported_types
        self.assertIn("check", types)
        self.assertIn("report", types)
        self.assertIn("open", types)

    def test_is_available(self):
        self.assertTrue(self.ex.is_available())

    def test_create(self):
        req = ActionRequest.create(action_type="check", target="logs")
        result = self.ex.create(req)
        self.assertEqual(result.status, "pending")
        self.assertEqual(result.action_id, req.action_id)

    def test_validate_ok(self):
        req = ActionRequest.create(action_type="check", target="logs")
        ok, err = self.ex.validate(req)
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_validate_unknown_type(self):
        req = ActionRequest.create(action_type="hack", target="logs")
        ok, err = self.ex.validate(req)
        self.assertFalse(ok)
        self.assertIn("hack", err)

    def test_execute_ok(self):
        req = ActionRequest.create(action_type="check", target="logs")
        result = self.ex.execute(req)
        self.assertEqual(result.status, "ok")
        self.assertIn("模拟执行成功", result.message)
        self.assertTrue(result.output["simulated"])
        self.assertEqual(result.output["executor"], "mock")
        # 不产生任何真实事件 (只有登记记录)
        self.assertEqual(self.ex.status()["total_executed"], 1)

    def test_execute_never_touches_device(self):
        # Mock 执行的 output 必须标记 simulated=True (绝对安全)
        req = ActionRequest.create(action_type="execute", target="anything")
        result = self.ex.execute(req)
        self.assertTrue(result.output.get("simulated", False))

    def test_cancel_existing(self):
        req = ActionRequest.create(action_type="check", target="logs")
        self.ex.create(req)
        result = self.ex.cancel(req.action_id)
        self.assertEqual(result.status, "cancelled")

    def test_cancel_unknown(self):
        result = self.ex.cancel("not-exist")
        self.assertEqual(result.status, "error")

    def test_status(self):
        req = ActionRequest.create(action_type="check", target="logs")
        self.ex.create(req)
        st = self.ex.status()
        self.assertEqual(st["name"], "mock")
        self.assertEqual(st["pending"], 1)
        self.assertTrue(st["available"])


class TestRealActionExecutor(unittest.TestCase):

    def setUp(self):
        self.ex = RealActionExecutor()

    def tearDown(self):
        self.ex.close()

    def test_name(self):
        self.assertEqual(self.ex.name, "real")

    def test_is_available_false(self):
        # V1.0 禁止自动控制电脑: 真实执行器一律不可用
        self.assertFalse(self.ex.is_available())

    def test_execute_unsupported(self):
        req = ActionRequest.create(action_type="check", target="logs")
        result = self.ex.execute(req)
        self.assertEqual(result.status, "unsupported")
        self.assertIn("禁止自动控制电脑", result.message)

    def test_validate_fails(self):
        req = ActionRequest.create(action_type="check", target="logs")
        ok, err = self.ex.validate(req)
        self.assertFalse(ok)
        self.assertIn("不可用", err)

    def test_create_unsupported(self):
        req = ActionRequest.create(action_type="open", target="app")
        result = self.ex.create(req)
        self.assertEqual(result.status, "unsupported")

    def test_status(self):
        st = self.ex.status()
        self.assertEqual(st["name"], "real")
        self.assertFalse(st["available"])
        self.assertIn("占位", st["note"])


if __name__ == "__main__":
    unittest.main()
