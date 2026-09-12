"""
YHLZ Vision Action V1.0 - Service 单元测试

覆盖:
    - 默认拒绝 (action_enabled=False → denied)
    - 校验失败 (invalid)
    - 高风险待确认 (awaiting_confirm) → 确认后执行 (ok)
    - 执行成功 / 失败
    - 取消 / 状态查询 / 历史检索
    - 指标 (metrics)
    - 理解 → 行动建议 (suggest_actions)
"""
import unittest

from backend.action.logger import ActionLogger
from backend.action.manager import ActionManager
from backend.action.permission import PermissionChecker
from backend.action.schema import ActionQuery, ActionRequest, ActionStatus
from backend.action.service import ActionService
from backend.action.validator import ActionValidator


class TestActionService(unittest.TestCase):

    def setUp(self):
        self.mgr = ActionManager()
        self.mgr.register_executor("mock", self._build_mock())
        self.svc = ActionService(
            manager=self.mgr,
            permission=PermissionChecker(),
            validator=ActionValidator(),
            alog=ActionLogger(enable_logging=False),
        )
        self.svc.load_config({"action_enabled": True})

    def _build_mock(self):
        from backend.action.executors.mock_executor import MockActionExecutor
        return MockActionExecutor()

    def _req(self, **kw):
        defaults = dict(action_type="check", target="logs", reason="检查日志", confidence=0.8)
        defaults.update(kw)
        return ActionRequest.create(**defaults)

    # ── 权限 ──────────────────────────────────────────────────────
    def test_default_denied(self):
        svc = ActionService(
            manager=ActionManager(),
            permission=PermissionChecker(),
            alog=ActionLogger(enable_logging=False),
        )
        svc.load_config({})
        op = svc.execute(self._req())
        self.assertFalse(op.success)
        self.assertEqual(op.status, "denied")

    def test_update_and_reset_permission(self):
        self.svc.update_permission(action_enabled=False)
        self.assertFalse(self.svc.get_permission()["action_enabled"])
        self.svc.reset_permission()
        self.assertFalse(self.svc.get_permission()["action_enabled"])

    # ── 校验 ──────────────────────────────────────────────────────
    def test_invalid_request(self):
        op = self.svc.execute(self._req(action_type="hack"))
        self.assertFalse(op.success)
        self.assertEqual(op.status, "invalid")
        self.assertIsNotNone(op.error)

    def test_validate_request_ok(self):
        ok, err = self.svc.validate_request(self._req())
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_validate_request_invalid(self):
        ok, err = self.svc.validate_request(self._req(action_type="hack"))
        self.assertFalse(ok)
        self.assertIn("action_type", err)

    # ── 执行 ──────────────────────────────────────────────────────
    def test_execute_ok(self):
        op = self.svc.execute(self._req())
        self.assertTrue(op.success)
        self.assertEqual(op.status, "ok")
        self.assertEqual(op.result.output["executor"], "mock")
        self.assertIsNotNone(op.action_id)
        self.assertEqual(op.permission.risk_level, "low")

    def test_execute_custom_type_no_target(self):
        op = self.svc.execute(self._req(action_type="custom", target=""))
        self.assertTrue(op.success)
        self.assertEqual(op.status, "ok")

    def test_execute_awaiting_confirm_high_risk(self):
        op = self.svc.execute(self._req(action_type="execute", target="files", reason="删除文件"))
        self.assertTrue(op.success)
        self.assertEqual(op.status, "awaiting_confirm")
        self.assertTrue(op.permission.require_confirm)

    def test_execute_confirmed_high_risk(self):
        op = self.svc.execute(
            self._req(action_type="execute", target="files", reason="删除文件"),
            confirmed=True,
        )
        self.assertEqual(op.status, "ok")

    def test_execute_no_executor(self):
        svc = ActionService(
            manager=ActionManager(),  # 未注册执行器
            permission=PermissionChecker(),
            alog=ActionLogger(enable_logging=False),
        )
        svc.load_config({"action_enabled": True})
        svc.set_manager(ActionManager())  # 移除默认执行器
        op = svc.execute(self._req())
        self.assertFalse(op.success)
        self.assertEqual(op.status, "invalid")
        self.assertIn("执行器", op.error)

    # ── 创建请求 ──────────────────────────────────────────────────
    def test_create_request(self):
        r = self.svc.create_request(
            action_type="report", target="diagnosis",
            parameters={"type": "x"}, reason="生成报告", confidence=0.5,
        )
        self.assertEqual(r.action_type, "report")
        self.assertEqual(r.target, "diagnosis")

    # ── 取消 / 状态 ───────────────────────────────────────────────
    def test_cancel(self):
        from backend.action.executors.mock_executor import MockActionExecutor
        default = self.svc.manager.get_default_executor()
        req = self._req()
        default.create(req)
        op = self.svc.cancel(req.action_id)
        self.assertEqual(op.status, "cancelled")

    def test_get_status(self):
        op = self.svc.execute(self._req())
        got = self.svc.get_status(op.action_id)
        self.assertIsNotNone(got)
        self.assertEqual(got.status, "ok")

    def test_get_status_missing(self):
        self.assertIsNone(self.svc.get_status("not-exist"))

    # ── 历史 ──────────────────────────────────────────────────────
    def test_history(self):
        self.svc.execute(self._req())
        self.svc.execute(self._req(action_type="report", target="summary"))
        records = self.svc.history(ActionQuery(limit=10))
        self.assertEqual(len(records), 2)
        records_ok = self.svc.history(ActionQuery(status="ok", limit=10))
        self.assertEqual(len(records_ok), 2)

    def test_history_filter_status(self):
        self.svc.execute(self._req())
        self.svc.execute(self._req(action_type="execute", target="files", reason="删除文件"))
        denied = self.svc.history(ActionQuery(status="awaiting_confirm", limit=10))
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0]["status"], "awaiting_confirm")

    def test_clear_history(self):
        self.svc.execute(self._req())
        n = self.svc.clear_history()
        self.assertEqual(n, 1)
        self.assertEqual(len(self.svc.history(ActionQuery(limit=10))), 0)

    # ── 指标 / 日志 ───────────────────────────────────────────────
    def test_metrics(self):
        self.svc.execute(self._req())
        self.svc.execute(self._req(action_type="execute", target="files", reason="删除文件"))
        self.svc.update_permission(action_enabled=False)
        self.svc.execute(self._req())
        st = self.svc.get_log_stats()
        self.assertEqual(st["action_count"], 3)  # 2 ok 尝试 + 1 denied
        self.assertEqual(st["denied_count"], 1)
        self.assertGreaterEqual(st["success_rate"], 0.0)
        self.assertGreaterEqual(st["approval_rate"], 0.0)

    def test_logs_and_clear(self):
        self.svc.execute(self._req())
        self.assertGreaterEqual(len(self.svc.get_logs(limit=10)), 2)  # start + success
        n = self.svc.clear_logs()
        self.assertGreaterEqual(n, 2)
        self.assertEqual(self.svc.get_log_stats()["total"], 0)

    # ── 状态 ──────────────────────────────────────────────────────
    def test_status(self):
        st = self.svc.status()
        self.assertEqual(st["version"], "1.0.0")
        self.assertTrue(st["initialized"])
        self.assertEqual(st["manager"]["default_executor"], "mock")

    # ── 理解 → 行动建议 ───────────────────────────────────────────
    def test_suggest_actions_error_scene(self):
        class FakeUnderstanding:
            scene_type = "error"
            description = "浏览器报错: 连接失败"
            subjects = ["browser"]
            summary = "页面无法访问"

        suggestions = self.svc.suggest_actions(FakeUnderstanding())
        self.assertGreaterEqual(len(suggestions), 2)
        self.assertEqual(suggestions[0].action_type, "check")
        self.assertEqual(suggestions[0].target, "logs")

    def test_suggest_actions_login_scene(self):
        suggestions = self.svc.suggest_actions({
            "scene_type": "web",
            "description": "页面显示登录表单",
            "subjects": ["login"],
            "summary": "需要登录",
        })
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].target, "account")

    def test_suggest_actions_task_scene(self):
        suggestions = self.svc.suggest_actions({
            "scene_type": "document",
            "description": "生成任务报告",
            "subjects": [],
            "summary": "任务文档",
        })
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].action_type, "report")

    def test_suggest_actions_plain_web(self):
        suggestions = self.svc.suggest_actions({
            "scene_type": "web",
            "description": "普通网页",
            "subjects": [],
            "summary": "",
        })
        self.assertEqual(suggestions, [])


if __name__ == "__main__":
    unittest.main()
