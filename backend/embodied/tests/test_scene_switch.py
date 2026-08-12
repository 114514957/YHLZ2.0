"""
YHLZ Embodied AI V4.3 - 场景生命周期单元测试 (Scene Lifecycle)

覆盖:
    - list_environments: 只读查询
    - switch_environment: 切换前 (Observe → 记录状态 → RESET Event)
    - switch_environment: 切换后 (WorldModel Reset → 建立新场景状态)
    - 内置场景自动注册 (room / warehouse)
    - 同名对象状态变化检测 (P1 场景迁移认知)
    - 场景摘要 (Scene Summary / Events Count / Failures / Active Objects)
    - 构建上下文 (scene_summary / scene_migration)
    - 权限层不受影响 (切换不绕过权限)
"""
import os
import tempfile
import unittest

from backend.embodied.manager import EmbodiedManager
from backend.embodied.schema import EmbodiedAction, EmbodiedGoal
from backend.embodied.service import (
    EmbodiedService,
    EmbodiedServiceError,
)


class TestListEnvironments(unittest.TestCase):
    """list_environments: 只读查询"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_list_environments_returns_entries(self):
        envs = self.svc.list_environments()
        names = [e["name"] for e in envs]
        self.assertIn("mock", names)
        self.assertIn("hardware", names)

    def test_list_environments_has_metadata(self):
        for e in self.svc.list_environments():
            self.assertIn("name", e)
            self.assertIn("available", e)
            self.assertIn("supported_actions", e)
            self.assertIn("is_default", e)
            self.assertIn("scene", e)

    def test_list_environments_default_marked(self):
        envs = self.svc.list_environments()
        default = [e for e in envs if e["is_default"]]
        self.assertEqual(len(default), 1)
        self.assertEqual(default[0]["name"], "mock")

    def test_list_environments_mock_scene(self):
        envs = self.svc.list_environments()
        mock = [e for e in envs if e["name"] == "mock"][0]
        self.assertEqual(mock["scene"], "room")
        self.assertTrue(mock["available"])

    def test_list_environments_hardware_unavailable(self):
        envs = self.svc.list_environments()
        hw = [e for e in envs if e["name"] == "hardware"][0]
        self.assertFalse(hw["available"])

    def test_list_environments_readonly_no_mutation(self):
        before = self.svc.list_environments()
        self.svc.list_environments()
        after = self.svc.list_environments()
        self.assertEqual(before, after)

    def test_list_environments_manager_path(self):
        self.assertEqual(
            len(self.svc.list_environments()),
            self.svc.manager.list_environments().__len__(),
        )


class TestSwitchEnvironmentLifecycle(unittest.TestCase):
    """switch_environment: 场景生命周期"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_switch_to_warehouse_registers_env(self):
        migration = self.svc.switch_environment("warehouse")
        self.assertEqual(migration["to"], "warehouse")
        self.assertEqual(migration["from"], "mock")
        env = self.svc.manager.get_environment("warehouse")
        self.assertIsNotNone(env)
        self.assertEqual(env.scene, "warehouse")

    def test_switch_sets_default(self):
        self.svc.switch_environment("warehouse")
        self.assertEqual(self.svc.manager.get_default_name(), "warehouse")

    def test_switch_before_observe_recorded(self):
        """切换前: Observe → 记录当前状态"""
        self.svc.observe()
        states_before = self.svc.world_model.count()
        self.svc.switch_environment("warehouse")
        # 切换过程必须观察过原环境 (事件日志有 reset + observe 事件)
        events = self.svc.event_history(limit=10)
        types = [e["event_type"] for e in events]
        self.assertIn("reset", types)
        self.assertIn("observe", types)

    def test_switch_generates_reset_event(self):
        self.svc.switch_environment("warehouse")
        events = self.svc.event_history(limit=10)
        reset_events = [
            e for e in events
            if e["event_type"] == "reset"
            and e["metadata"].get("event") == "environment_switch"
        ]
        self.assertGreaterEqual(len(reset_events), 1)
        self.assertEqual(reset_events[0]["metadata"]["from"], "mock")
        self.assertEqual(reset_events[0]["metadata"]["to"], "warehouse")

    def test_switch_resets_world_model(self):
        """切换后: WorldModel Reset"""
        self.svc.execute_action(EmbodiedAction.create(action_type="move", parameters={"dx": 1, "dy": 0}))
        self.svc.observe()
        self.assertGreaterEqual(self.svc.world_model.count(), 1)
        self.svc.switch_environment("warehouse")
        # 世界模型已重置, 仅保留新场景的一次观察
        self.assertEqual(self.svc.world_model.count(), 1)

    def test_switch_establishes_new_scene_state(self):
        """切换后: 建立新场景状态"""
        self.svc.switch_environment("warehouse")
        latest = self.svc.world_state()
        self.assertIsNotNone(latest)
        names = {o.name for o in latest.objects}
        self.assertIn("pallet", names)
        self.assertIn("crate", names)
        self.assertEqual(latest.metadata["scene"], "warehouse")

    def test_switch_to_unknown_raises(self):
        with self.assertRaises(EmbodiedServiceError):
            self.svc.switch_environment("nope")

    def test_switch_to_registered_hardware_allowed(self):
        migration = self.svc.switch_environment("hardware")
        self.assertEqual(migration["to"], "hardware")
        self.assertIsNone(migration["new_scene"])  # 不可用环境无新场景状态
        self.assertEqual(self.svc.manager.get_default_name(), "hardware")

    def test_switch_records_migration(self):
        self.svc.switch_environment("warehouse")
        self.assertEqual(self.svc.scene_manager.count(), 1)
        latest = self.svc.scene_manager.latest()
        self.assertEqual(latest["from"], "mock")
        self.assertEqual(latest["to"], "warehouse")
        self.assertIn("migration_id", latest)

    def test_switch_previous_scene_summary(self):
        self.svc.switch_environment("warehouse")
        latest = self.svc.scene_manager.latest()
        prev = latest["previous_scene"]
        self.assertEqual(prev["environment"], "mock")
        self.assertIn("lamp", prev["active_objects"])
        self.assertEqual(prev["object_count"], 4)

    def test_switch_active_objects_new_scene(self):
        migration = self.svc.switch_environment("warehouse")
        self.assertIn("pallet", migration["active_objects"])
        self.assertEqual(len(migration["active_objects"]), 4)

    def test_switch_events_count_accumulates(self):
        self.svc.execute_action(EmbodiedAction.create(action_type="scan"))
        migration = self.svc.switch_environment("warehouse")
        self.assertGreaterEqual(migration["events_count"], 1)

    def test_switch_multiple_times(self):
        self.svc.switch_environment("warehouse")
        m2 = self.svc.switch_environment("room")
        self.assertEqual(m2["from"], "warehouse")
        self.assertEqual(m2["to"], "room")
        self.assertEqual(self.svc.scene_manager.count(), 2)
        self.assertEqual(self.svc.manager.get_default_name(), "room")

    def test_switch_same_environment(self):
        migration = self.svc.switch_environment("mock")
        self.assertEqual(migration["from"], "mock")
        self.assertEqual(migration["to"], "mock")

    def test_switch_no_environment_raises(self):
        mgr = EmbodiedManager()
        svc = EmbodiedService(manager=mgr)
        with self.assertRaises(EmbodiedServiceError):
            svc.switch_environment("warehouse")

    def test_switch_does_not_change_permission(self):
        """切换不得绕过/修改权限层"""
        svc = EmbodiedService()
        svc.load_config({})  # embodied_enabled=False
        svc.switch_environment("warehouse")
        self.assertFalse(svc.get_permission()["embodied_enabled"])
        # 权限仍然拦截动作
        res = svc.execute_action(EmbodiedAction.create(action_type="scan"))
        self.assertFalse(res.success)
        self.assertEqual(res.status, "denied")

    def test_switch_route_after_switch(self):
        """切换后动作路由到新环境"""
        self.svc.switch_environment("warehouse")
        res = self.svc.execute_action(EmbodiedAction.create(
            action_type="pick", target="crate", parameters={"object": "crate"},
        ))
        # 已路由到 warehouse 场景 (crate 位于 (4,2), 拾取失败但世界状态场景为 warehouse)
        self.assertFalse(res.success)
        latest = self.svc.world_state()
        self.assertEqual(latest.metadata["scene"], "warehouse")
        events = self.svc.event_history(limit=10)
        pick_events = [e for e in events if e.get("action_type") == "pick"]
        self.assertGreaterEqual(len(pick_events), 1)
        self.assertEqual(pick_events[0]["target"], "crate")

    def test_switch_run_goal_on_new_scene(self):
        self.svc.switch_environment("warehouse")
        goal = EmbodiedGoal.create(description="扫描仓库", constraints={"max_steps": 3})
        res = self.svc.run_goal(goal)
        self.assertTrue(res.success)


class TestSameNameObjectChanges(unittest.TestCase):
    """P1 场景迁移认知: 同名对象状态变化检测"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def test_same_name_change_detected(self):
        """room 的 door=open vs warehouse 的 door=closed"""
        migration = self.svc.switch_environment("warehouse")
        changes = migration["same_name_changes"]
        door_changes = [c for c in changes if c["name"] == "door"]
        self.assertGreaterEqual(len(door_changes), 1)
        self.assertEqual(door_changes[0]["state"]["from"], "open")
        self.assertEqual(door_changes[0]["state"]["to"], "closed")

    def test_no_same_name_change_same_scene(self):
        migration = self.svc.switch_environment("mock")
        self.assertEqual(migration["same_name_changes"], [])

    def test_change_contains_positions(self):
        migration = self.svc.switch_environment("warehouse")
        changes = migration["same_name_changes"]
        for c in changes:
            self.assertIn("position", c)
            self.assertIn("from", c["position"])
            self.assertIn("to", c["position"])

    def test_change_count_matches(self):
        migration = self.svc.switch_environment("warehouse")
        # door 状态变化 (room=open → warehouse=closed); 其余同名对象位置不同
        names = {c["name"] for c in migration["same_name_changes"]}
        self.assertIn("door", names)

    def test_context_includes_migration(self):
        self.svc.switch_environment("warehouse")
        ctx = self.svc.build_environment_context()
        self.assertIn("scene_migration", ctx)
        self.assertIsNotNone(ctx["scene_migration"])
        self.assertEqual(ctx["scene_migration"]["to"], "warehouse")
        self.assertIn("scene_object_changes", ctx)
        self.assertGreaterEqual(len(ctx["scene_object_changes"]), 1)

    def test_context_scene_summary(self):
        self.svc.switch_environment("warehouse")
        ctx = self.svc.build_environment_context()
        scene = ctx["scene_summary"]
        self.assertEqual(scene["environment"], "warehouse")
        self.assertEqual(scene["scene"], "warehouse")
        self.assertIn("pallet", scene["active_objects"])
        self.assertIn("events_count", scene)
        self.assertIn("failures", scene)

    def test_context_scene_key(self):
        ctx = self.svc.build_environment_context()
        self.assertIn("scene", ctx)
        self.assertEqual(ctx["scene"]["environment"], "mock")

    def test_context_no_migration_before_switch(self):
        ctx = self.svc.build_environment_context()
        self.assertIsNone(ctx["scene_migration"])
        self.assertEqual(ctx["scene_object_changes"], [])

    def test_scene_manager_clear(self):
        self.svc.switch_environment("warehouse")
        self.assertEqual(self.svc.scene_manager.clear(), 1)
        self.assertIsNone(self.svc.scene_manager.latest())

    def test_scene_migrations_history(self):
        self.svc.switch_environment("warehouse")
        self.svc.switch_environment("room")
        hist = self.svc.scene_manager.migrations(limit=5)
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["to"], "room")  # 最新在前


class TestSceneManagerUnit(unittest.TestCase):

    def setUp(self):
        from backend.embodied.scene import SceneManager
        from backend.embodied.schema import EnvironmentObject
        self.mgr = SceneManager(max_migrations=3)
        self.obj_cls = EnvironmentObject

    def test_record_and_latest(self):
        mid = self.mgr.record_migration({"from": "a", "to": "b"})
        self.assertTrue(mid)
        self.assertEqual(self.mgr.latest()["to"], "b")

    def test_record_none_raises(self):
        from backend.embodied.scene import SceneManagerError
        with self.assertRaises(SceneManagerError):
            self.mgr.record_migration(None)

    def test_max_migrations(self):
        for i in range(5):
            self.mgr.record_migration({"from": str(i), "to": str(i + 1)})
        self.assertEqual(self.mgr.count(), 3)

    def test_same_name_changes_detection(self):
        a = self.obj_cls.create(name="door", state="open", position={"x": 1.0, "y": 1.0})
        b = self.obj_cls.create(name="door", state="closed", position={"x": 2.0, "y": 2.0})
        changes = self.mgr.same_name_object_changes([a], [b])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["state"]["from"], "open")
        self.assertEqual(changes[0]["state"]["to"], "closed")

    def test_same_name_changes_same_state(self):
        a = self.obj_cls.create(name="door", state="open")
        b = self.obj_cls.create(name="door", state="open")
        self.assertEqual(self.mgr.same_name_object_changes([a], [b]), [])

    def test_same_name_changes_missing_ignored(self):
        a = self.obj_cls.create(name="door")
        b = self.obj_cls.create(name="lamp")
        self.assertEqual(self.mgr.same_name_object_changes([a], [b]), [])

    def test_build_summary(self):
        from backend.embodied.scene import SceneManager
        from backend.embodied.schema import EnvironmentState
        state = EnvironmentState.create(objects=[
            self.obj_cls.create(name="lamp"),
            self.obj_cls.create(name="box"),
        ], location={"x": 0.0, "y": 0.0})
        summary = SceneManager.build_summary(
            "mock", "room", state,
            {"total": 5, "by_result": {"failure": 2}},
        )
        self.assertEqual(summary["environment"], "mock")
        self.assertEqual(summary["object_count"], 2)
        self.assertEqual(summary["events_count"], 5)
        self.assertEqual(summary["failures"], 2)
        self.assertIn("lamp", summary["active_objects"])


if __name__ == "__main__":
    unittest.main()
