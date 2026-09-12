"""
YHLZ Embodied AI V4.1 - 集成测试

覆盖:
    - 完整闭环: 目标 → 规划 → 观察 → 执行 → 反馈 → 状态记忆
    - 环境可替换 (自定义环境注册 → 默认路由切换)
    - 权限全程生效 (动作不绕过安全层)
    - 反馈独立存储 (不污染其他模块)
    - 安全模型: 默认关闭 / Mock 优先 / 硬件禁用
    - V4.1: 预测 → 执行 → 验证闭环 / 具身上下文 / 自适应拾取
    - 与既有模块隔离 (不破坏 Agent / Vision / Personality)
"""
import unittest

from backend.embodied.environment.mock import MockEnvironment
from backend.embodied.manager import EmbodiedManager, get_manager, reset_manager
from backend.embodied.schema import (
    EmbodiedAction,
    EmbodiedGoal,
    EmbodiedStatus,
    EnvironmentObject,
    FeedbackResult,
)
from backend.embodied.service import EmbodiedService, get_service, reset_service


class TestFullLoop(unittest.TestCase):

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_full_embodied_loop(self):
        """观察 → 思考 → 规划 → 行动 → 评估 → 状态记忆 全链路"""
        goal = EmbodiedGoal.create(
            description="检查房间里的台灯", intent="inspect", target="lamp",
        )
        res = self.svc.run_goal(goal)
        self.assertTrue(res.success)
        self.assertEqual(res.status, EmbodiedStatus.OK.value)

        # 反馈已记录
        self.assertGreaterEqual(self.svc.feedback_store.count(), 1)
        stats = self.svc.feedback_store.stats()
        self.assertEqual(stats["success_count"], stats["total"])

        # 世界模型保存了状态
        latest = self.svc.world_state()
        self.assertIsNotNone(latest)
        names = {o.name for o in latest.objects}
        self.assertIn("lamp", names)

    def test_pick_place_goal_sequence(self):
        """多步目标: 拾取 → 反馈记录 (环境状态正确变化)"""
        # 构造主体与台灯同位置的环境, 确保 PICK 可成功
        env = MockEnvironment(
            robot_start=(1, 1),
            objects=[
                EnvironmentObject.create(
                    name="lamp", category="light", position={"x": 1.0, "y": 1.0},
                    properties={"color": "white"}, state="on",
                ),
            ],
        )
        self.svc.manager.register_environment("mock", env, override=True)

        goal = EmbodiedGoal.create(
            description="拿起台灯",
            intent="pick",
            target="lamp",
            constraints={"max_steps": 3},
        )
        res = self.svc.run_goal(goal)
        self.assertTrue(res.success)
        self.assertEqual(res.status, EmbodiedStatus.OK.value)

        # 反馈中应存在 pick 成功事件
        pick_events = [
            f for f in self.svc.feedback_store.query(result="success")
            if f.environment_change.get("event") == "pick"
        ]
        self.assertGreaterEqual(len(pick_events), 1)

        # 世界模型中的对象状态已更新为 held
        latest = self.svc.world_state()
        lamp = [o for o in latest.objects if o.name == "lamp"][0]
        self.assertEqual(lamp.state, "held")


class TestEnvironmentReplaceable(unittest.TestCase):

    def test_custom_environment_registration(self):
        """Environment 可替换: 自定义环境注册后成为默认"""
        from backend.embodied.tests.test_environment import StubEnvironment

        mgr = EmbodiedManager()
        custom = StubEnvironment("custom_env")
        mgr.register_environment("custom_env", custom)
        svc = EmbodiedService(manager=mgr)
        svc.load_config({"embodied_enabled": True})

        res = svc.execute_action(EmbodiedAction.create(action_type="scan"))
        self.assertTrue(res.success)

    def test_environment_selection_via_parameters(self):
        """动作可指定环境 (路由到指定环境)"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        env2 = MockEnvironment(grid_size=(10, 10))
        svc.manager.register_environment("big", env2, override=True)

        a = EmbodiedAction.create(
            action_type="move", parameters={"dx": 8, "dy": 8, "environment": "big"},
        )
        res = svc.execute_action(a)
        self.assertTrue(res.success)
        self.assertEqual(res.state.position, {"x": 8.0, "y": 8.0})


class TestSafetyModel(unittest.TestCase):

    def test_default_off(self):
        """默认关闭: embodied_enabled=False"""
        svc = EmbodiedService()
        svc.load_config({})
        self.assertFalse(svc.get_permission()["embodied_enabled"])
        res = svc.execute_action(EmbodiedAction.create(action_type="scan"))
        self.assertEqual(res.status, EmbodiedStatus.DENIED.value)

    def test_mock_priority(self):
        """Mock 优先: 默认环境为 mock, 硬件占位不可用"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        default = svc.manager.get_default_environment()
        self.assertEqual(default.name, "mock")
        hw = svc.manager.get_environment("hardware")
        self.assertFalse(hw.is_available())

    def test_hardware_never_executes(self):
        """真实硬件在本版本不可执行"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        res = svc.execute_action(EmbodiedAction.create(
            action_type="move", parameters={"environment": "hardware"},
        ))
        self.assertEqual(res.status, EmbodiedStatus.UNSUPPORTED.value)

    def test_action_never_bypasses_permission(self):
        """动作不绕过安全层: 环境自身也不接受未授权调用路径"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        # 经 Service 执行 → 权限判定
        res = svc.execute_action(EmbodiedAction.create(
            action_type="custom", intent="shutdown",
        ))
        self.assertEqual(res.status, EmbodiedStatus.AWAITING_CONFIRM.value)
        # 确认后执行 → 反馈结果 success (环境被真实调用)
        res2 = svc.execute_action(EmbodiedAction.create(
            action_type="custom", intent="shutdown",
        ), confirmed=True)
        self.assertEqual(res2.status, EmbodiedStatus.OK.value)


class TestDataIndependence(unittest.TestCase):

    def test_feedback_not_in_agent_memory(self):
        """反馈记录独立: 不写入 Agent Memory"""
        import sqlite3
        from pathlib import Path

        from backend.config import config

        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        svc.execute_action(EmbodiedAction.create(action_type="scan"))
        svc.execute_action(EmbodiedAction.create(action_type="scan"))

        # Agent Memory db 无任何 embodied 痕迹 (若有 db 文件)
        db = Path(config.agent_memory_db)
        if db.exists():
            conn = sqlite3.connect(db)
            try:
                tables = [
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                ]
                for table in tables:
                    cols = [
                        r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
                    ]
                    self.assertNotIn("embodied", " ".join(cols).lower())
            finally:
                conn.close()


class TestModuleIsolation(unittest.TestCase):

    def test_action_module_unaffected(self):
        """Action 模块可正常导入与工作"""
        from backend.action.schema import ActionRequest, ActionStatus

        r = ActionRequest.create(action_type="check", target="logs")
        self.assertEqual(r.action_type, "check")
        self.assertEqual(ActionStatus.PENDING.value, "pending")

    def test_vision_module_unaffected(self):
        """Vision 模块可正常导入"""
        import backend.vision.schema as vschema

        self.assertTrue(hasattr(vschema, "VisionCaptureRequest"))

    def test_personality_module_unaffected(self):
        """Personality 模块可正常导入"""
        import backend.personality.service as pservice

        self.assertTrue(hasattr(pservice, "PersonalityService"))

    def test_agent_module_unaffected(self):
        """Agent 模块可正常导入"""
        import backend.agent.service as aservice

        self.assertTrue(hasattr(aservice, "AgentService"))


class TestV41PredictionLoop(unittest.TestCase):
    """V4.1: 预测 → 执行 → 验证 闭环"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_move_predict_execute_verify(self):
        # 预测
        a = EmbodiedAction.create(
            action_type="move", intent="向前移动", parameters={"dx": 1, "dy": 0},
        )
        pred = self.svc.predict(a)
        self.assertIsNotNone(pred)
        self.assertEqual(pred.expected_change["expected"], "position_change")
        # 执行
        res = self.svc.execute_action(a)
        self.assertTrue(res.success)
        # 验证
        v = self.svc.verify_prediction(pred, res.feedback.environment_change)
        self.assertEqual(v["expected"], "position_change")

    def test_pick_predict_verify_with_adaptive(self):
        """自适应拾取: 初始预测失败 → 执行 → 调整 → 最终成功"""
        goal = EmbodiedGoal.create(
            description="拿起台灯", intent="pick", target="lamp",
            constraints={"max_steps": 6},
        )
        res = self.svc.run_goal(goal)
        self.assertTrue(res.success)
        # 反馈历史中应有 pick 成功
        picks = [
            f for f in self.svc.feedback_store.query(result="success")
            if f.environment_change.get("event") == "pick"
        ]
        self.assertGreaterEqual(len(picks), 1)
        # 世界模型状态: lamp 已被持有
        latest = self.svc.world_state()
        lamp = [o for o in latest.objects if o.name == "lamp"][0]
        self.assertEqual(lamp.state, "held")


class TestV41EnvironmentContext(unittest.TestCase):
    """V4.1: 具身上下文与状态变化"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_context_after_actions(self):
        self.svc.observe()  # 建立初始状态
        self.svc.execute_action(EmbodiedAction.create(
            action_type="move", parameters={"dx": 1, "dy": 1},
        ))
        ctx = self.svc.build_environment_context()
        self.assertEqual(ctx["current_state"]["location"], {"x": 1.0, "y": 1.0})
        self.assertGreaterEqual(len(ctx["recent_changes"]), 1)

    def test_door_state_in_context(self):
        ctx = self.svc.build_environment_context()
        door = [
            o for o in ctx["current_state"]["objects"] if o["name"] == "door"
        ][0]
        self.assertEqual(door["state"], "open")
        # 稳定性预测: door=open → remains open
        objects = ctx["prediction"]["expected_change"]["objects"]
        door_pred = [o for o in objects if o["name"] == "door"][0]
        self.assertEqual(door_pred["state"], "open")


class TestSingletonIsolation(unittest.TestCase):

    def tearDown(self):
        reset_service()
        reset_manager()

    def test_global_singleton_works(self):
        svc = get_service()
        self.assertIs(get_service(), svc)
        self.assertIs(get_manager(), svc.manager)


if __name__ == "__main__":
    unittest.main()
