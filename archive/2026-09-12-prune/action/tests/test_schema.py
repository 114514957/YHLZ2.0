"""
YHLZ Vision Action V1.0 - Schema 单元测试

覆盖:
    - 枚举: ActionType / ActionStatus / RiskLevel
    - ActionRequest 创建 / 序列化
    - ActionResult 序列化
    - ActionQuery 序列化
"""
import unittest

from backend.action.schema import (
    ActionQuery,
    ActionRequest,
    ActionResult,
    ActionStatus,
    ActionType,
    RiskLevel,
)


class TestActionType(unittest.TestCase):

    def test_values(self):
        expected = {"open", "navigate", "check", "query", "report", "execute", "custom"}
        self.assertEqual(set(ActionType.values()), expected)

    def test_values_method(self):
        self.assertEqual(len(ActionType.values()), 7)


class TestActionStatus(unittest.TestCase):

    def test_key_statuses(self):
        self.assertEqual(ActionStatus.OK.value, "ok")
        self.assertEqual(ActionStatus.DENIED.value, "denied")
        self.assertEqual(ActionStatus.AWAITING_CONFIRM.value, "awaiting_confirm")
        self.assertEqual(ActionStatus.INVALID.value, "invalid")
        self.assertEqual(ActionStatus.UNSUPPORTED.value, "unsupported")


class TestRiskLevel(unittest.TestCase):

    def test_values(self):
        self.assertEqual(set(RiskLevel.values()), {"low", "medium", "high"})


class TestActionRequest(unittest.TestCase):

    def test_defaults(self):
        r = ActionRequest()
        self.assertTrue(r.action_id)
        self.assertEqual(r.action_type, "custom")
        self.assertEqual(r.target, "")
        self.assertEqual(r.parameters, {})
        self.assertEqual(r.risk_level, "low")

    def test_create(self):
        r = ActionRequest.create(
            action_type="check", target="logs",
            parameters={"scope": "recent"},
            reason="检查日志", confidence=0.8, risk_level="low",
        )
        self.assertEqual(r.action_type, "check")
        self.assertEqual(r.target, "logs")
        self.assertEqual(r.parameters, {"scope": "recent"})
        self.assertEqual(r.confidence, 0.8)

    def test_roundtrip(self):
        r = ActionRequest.create(
            action_type="report", target="diagnosis",
            parameters={"type": "error_summary"},
            reason="生成诊断报告", confidence=0.6,
        )
        d = r.to_dict()
        self.assertEqual(d["target"], "diagnosis")
        r2 = ActionRequest.from_dict(d)
        self.assertEqual(r2.action_id, r.action_id)
        self.assertEqual(r2.action_type, "report")
        self.assertEqual(r2.parameters, {"type": "error_summary"})
        self.assertEqual(r2.confidence, 0.6)

    def test_from_dict_defaults(self):
        r = ActionRequest.from_dict({"action_type": "check"})
        self.assertEqual(r.target, "")
        self.assertTrue(r.action_id)

    def test_uuid_unique(self):
        a = ActionRequest.create(action_type="check")
        b = ActionRequest.create(action_type="check")
        self.assertNotEqual(a.action_id, b.action_id)


class TestActionResult(unittest.TestCase):

    def test_defaults(self):
        r = ActionResult()
        self.assertEqual(r.status, "pending")
        self.assertIsNone(r.error)

    def test_roundtrip(self):
        r = ActionResult(
            action_id="a1", status="ok", message="成功",
            output={"executor": "mock"},
        )
        d = r.to_dict()
        self.assertEqual(d["status"], "ok")
        r2 = ActionResult.from_dict(d)
        self.assertEqual(r2.action_id, "a1")
        self.assertEqual(r2.output, {"executor": "mock"})

    def test_from_dict_defaults(self):
        r = ActionResult.from_dict({})
        self.assertEqual(r.status, "pending")


class TestActionQuery(unittest.TestCase):

    def test_defaults(self):
        q = ActionQuery()
        self.assertEqual(q.limit, 50)
        self.assertEqual(q.offset, 0)

    def test_roundtrip(self):
        q = ActionQuery(action_type="check", status="ok", risk_level="low", limit=5, offset=10)
        q2 = ActionQuery.from_dict(q.to_dict())
        self.assertEqual(q2.action_type, "check")
        self.assertEqual(q2.status, "ok")
        self.assertEqual(q2.limit, 5)
        self.assertEqual(q2.offset, 10)


if __name__ == "__main__":
    unittest.main()
