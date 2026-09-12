"""
YHLZ Vision Action V1.0 - Validator 单元测试

覆盖:
    - 合法请求通过
    - action_type 白名单
    - target 必填 (open / navigate / execute / report)
    - confidence 范围
    - risk_level 白名单
    - 参数边界 (文本长度 / 坐标 / 嵌套)
    - reason 长度
"""
import unittest

from backend.action.schema import ActionRequest
from backend.action.validator import ActionValidator


class TestActionValidator(unittest.TestCase):

    def _valid(self, **kw):
        base = dict(action_type="check", target="logs", reason="检查日志", confidence=0.8)
        base.update(kw)
        return ActionRequest.create(**base)

    def test_valid_request(self):
        ok, errors = ActionValidator.validate(self._valid())
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_invalid_action_type(self):
        ok, errors = ActionValidator.validate(self._valid(action_type="hack"))
        self.assertFalse(ok)
        self.assertTrue(any("action_type" in e for e in errors))

    def test_target_required_for_open(self):
        ok, errors = ActionValidator.validate(self._valid(action_type="open", target=""))
        self.assertFalse(ok)
        self.assertTrue(any("target" in e for e in errors))

    def test_target_required_for_execute(self):
        ok, errors = ActionValidator.validate(self._valid(action_type="execute", target=" "))
        self.assertFalse(ok)
        self.assertTrue(any("target" in e for e in errors))

    def test_target_not_required_for_custom(self):
        ok, _ = ActionValidator.validate(self._valid(action_type="custom", target=""))
        self.assertTrue(ok)

    def test_confidence_out_of_range(self):
        ok, errors = ActionValidator.validate(self._valid(confidence=1.5))
        self.assertFalse(ok)
        self.assertTrue(any("confidence" in e for e in errors))

    def test_confidence_negative(self):
        ok, errors = ActionValidator.validate(self._valid(confidence=-0.1))
        self.assertFalse(ok)

    def test_risk_level_whitelist(self):
        ok, errors = ActionValidator.validate(self._valid(risk_level="extreme"))
        self.assertFalse(ok)
        self.assertTrue(any("risk_level" in e for e in errors))

    def test_text_param_too_long(self):
        ok, errors = ActionValidator.validate(
            self._valid(parameters={"text": "x" * 201}))
        self.assertFalse(ok)
        self.assertTrue(any("text" in e for e in errors))

    def test_text_param_empty(self):
        ok, errors = ActionValidator.validate(
            self._valid(parameters={"text": "  "}))
        self.assertFalse(ok)
        self.assertTrue(any("text" in e for e in errors))

    def test_coordinate_out_of_range(self):
        ok, errors = ActionValidator.validate(
            self._valid(parameters={"x": 20000, "y": 10}))
        self.assertFalse(ok)
        self.assertTrue(any("x" in e for e in errors))

    def test_coordinate_ok(self):
        ok, _ = ActionValidator.validate(
            self._valid(parameters={"x": 100, "y": 200}))
        self.assertTrue(ok)

    def test_too_many_parameters(self):
        params = {f"k{i}": i for i in range(21)}
        ok, errors = ActionValidator.validate(self._valid(parameters=params))
        self.assertFalse(ok)
        self.assertTrue(any("parameters" in e for e in errors))

    def test_reason_too_long(self):
        ok, errors = ActionValidator.validate(self._valid(reason="r" * 501))
        self.assertFalse(ok)
        self.assertTrue(any("reason" in e for e in errors))

    def test_parameters_must_be_dict(self):
        req = ActionRequest.create(action_type="check", target="logs")
        req.parameters = "not-a-dict"
        ok, errors = ActionValidator.validate(req)
        self.assertFalse(ok)
        self.assertTrue(any("parameters" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
