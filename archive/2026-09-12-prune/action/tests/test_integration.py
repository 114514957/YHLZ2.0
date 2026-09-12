"""
YHLZ Vision Action V1.0 - 集成测试

覆盖:
    - 单例 Service + Manager 组合
    - 理解 → 行动建议 → 执行 全链路
    - 权限全链路 (默认拒绝 → 开启 → 拒绝重置)
    - 全链路: 提交请求 → 高风险确认 → 执行 → 历史 → 指标
"""
import unittest

from backend.action.manager import ActionManager
from backend.action.permission import PermissionChecker
from backend.action.schema import ActionQuery, ActionRequest
from backend.action.service import (
    ActionService,
    get_service,
    reset_service,
)
from backend.action.validator import ActionValidator


class TestActionFullFlowIntegration(unittest.TestCase):

    def setUp(self):
        from backend.action.executors.mock_executor import MockActionExecutor
        self.svc = ActionService(
            manager=ActionManager(),
            permission=PermissionChecker(),
            validator=ActionValidator(),
        )
        self.svc.manager.register_executor("mock", MockActionExecutor())
        self.svc.load_config({"action_enabled": True})

    def test_permission_chain(self):
        # 默认拒绝
        self.svc.reset_permission()
        op = self.svc.execute(ActionRequest.create(action_type="check", target="logs"))
        self.assertEqual(op.status, "denied")
        # 开启
        self.svc.update_permission(action_enabled=True)
        op = self.svc.execute(ActionRequest.create(action_type="check", target="logs"))
        self.assertEqual(op.status, "ok")
        # 再拒绝
        self.svc.update_permission(action_enabled=False)
        op = self.svc.execute(ActionRequest.create(action_type="check", target="logs"))
        self.assertEqual(op.status, "denied")

    def test_full_cycle(self):
        # 1. 提交普通行动
        op = self.svc.execute(ActionRequest.create(
            action_type="check", target="logs", reason="检查日志", confidence=0.8))
        self.assertEqual(op.status, "ok")
        action_id = op.action_id
        # 2. 状态查询
        got = self.svc.get_status(action_id)
        self.assertEqual(got.status, "ok")
        # 3. 高风险行动需确认
        op2 = self.svc.execute(ActionRequest.create(
            action_type="execute", target="cache", reason="删除缓存", confidence=0.9))
        self.assertEqual(op2.status, "awaiting_confirm")
        # 4. 确认后执行
        op3 = self.svc.execute(
            ActionRequest.create(
                action_type="execute", target="cache", reason="删除缓存", confidence=0.9),
            confirmed=True,
        )
        self.assertEqual(op3.status, "ok")
        # 5. 历史记录
        records = self.svc.history(ActionQuery(limit=10))
        self.assertGreaterEqual(len(records), 3)
        # 6. 指标
        st = self.svc.get_log_stats()
        self.assertGreaterEqual(st["action_count"], 3)
        self.assertGreaterEqual(st["success_rate"], 0.0)
        self.assertGreaterEqual(st["approval_rate"], 0.0)

    def test_understanding_to_action_chain(self):
        # 理解结果 → 行动建议 → 执行
        understanding = {
            "scene_type": "error",
            "description": "浏览器报错: 无法连接服务器",
            "subjects": ["browser"],
            "summary": "页面加载失败",
        }
        suggestions = self.svc.suggest_actions(understanding)
        self.assertGreaterEqual(len(suggestions), 1)
        op = self.svc.execute(suggestions[0])
        self.assertEqual(op.status, "ok")
        self.assertEqual(op.action.target, "logs")


class TestActionSingletonIntegration(unittest.TestCase):

    def tearDown(self):
        reset_service()

    def test_get_service_singleton(self):
        s1 = get_service()
        s2 = get_service()
        self.assertIs(s1, s2)
        # 单例已注册默认执行器 (mock)
        self.assertEqual(s1.manager.get_default_executor().name, "mock")

    def test_reset_service(self):
        s1 = get_service()
        reset_service()
        s2 = get_service()
        self.assertIsNot(s1, s2)

    def test_singleton_full_flow(self):
        svc = get_service()
        svc.load_config({"action_enabled": True})
        op = svc.execute(ActionRequest.create(action_type="report", target="diagnosis"))
        self.assertEqual(op.status, "ok")


if __name__ == "__main__":
    unittest.main()
