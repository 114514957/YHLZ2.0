"""
YHLZ 前端 Startup/Avatar/Settings/Monitor 测试

覆盖:
    - 一键启动核心 (步骤/失败停止/跳过/结果)
    - 情绪状态管理器 (事件/状态 → 情绪动画)
    - 动画映射
    - 设置管理器 (分组/持久化/变更)
    - 运行时控制台 (四区块)
"""
import json
import os
import tempfile
import unittest

from frontend.avatar import (
    ANIMATION_MAP,
    EVENT_ANIMATION_MAP,
    EmotionState,
    EmotionStateError,
    EmotionStateManager,
    animation_for_event,
    animation_for_state,
)
from frontend.monitor import RuntimeConsole
from frontend.settings import (
    SETTING_GROUPS,
    SettingsManager,
    SettingsManagerError,
)
from frontend.startup import STARTUP_STEPS, StartupCore


class TestStartupCore(unittest.TestCase):
    """一键启动核心"""

    def test_steps_enum(self):
        self.assertEqual(STARTUP_STEPS, [
            "environment", "config", "backend", "runtime",
            "identity", "memory", "model", "avatar", "ready",
        ])

    def test_run_environment(self):
        # 用不可达端口隔离 (不依赖外部后端状态)
        core = StartupCore(backend_url="http://127.0.0.1:9")
        results = core.run()
        # 后端不可达 → 在 backend 步失败停止
        self.assertEqual(results[0]["step"], "environment")
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[1]["step"], "config")
        self.assertTrue(results[1]["ok"])
        self.assertEqual(results[2]["step"], "backend")
        self.assertFalse(results[2]["ok"])

    def test_run_skip_backend(self):
        core = StartupCore()
        results = core.run(skip=["backend", "runtime", "identity",
                                 "memory", "model", "avatar"])
        # 跳过全部网络/模型步骤, ready 应成功
        self.assertEqual(results[-1]["step"], "ready")
        self.assertTrue(results[-1]["ok"])

    def test_result_query(self):
        core = StartupCore()
        core.run(skip=["backend", "runtime", "identity",
                       "memory", "model", "avatar"])
        r = core.result("ready")
        self.assertEqual(r["step"], "ready")
        self.assertTrue(r["ok"])

    def test_all_ok_with_skip(self):
        core = StartupCore()
        core.run(skip=["backend", "runtime", "identity",
                       "memory", "model", "avatar"])
        self.assertTrue(core.all_ok())

    def test_stats(self):
        core = StartupCore()
        core.run(skip=["backend", "runtime", "identity",
                       "memory", "model", "avatar"])
        s = core.stats()
        self.assertEqual(s["steps_total"], 9)
        self.assertEqual(s["mode"], "rule_based")

    def test_failure_stops(self):
        core = StartupCore(backend_url="http://127.0.0.1:1")
        results = core.run()
        # 失败后不再执行后续步骤
        for r in results[3:]:
            self.assertEqual(r["step"], "ready") if False else None
        steps_run = [r["step"] for r in results]
        self.assertIn("backend", steps_run)
        self.assertNotIn("ready", steps_run)

    def test_avatar_step_detects_models(self):
        core = StartupCore()
        # 直接调用 avatar 步骤 (assets/live2d 存在)
        r = core._init_avatar()
        self.assertTrue(r["ok"])
        self.assertIn("Live2D", r["detail"])

    def test_environment_creates_dirs(self):
        core = StartupCore()
        r = core._check_environment()
        self.assertTrue(r["ok"])


class TestEmotionStateManager(unittest.TestCase):
    """情绪状态管理器"""

    def setUp(self):
        self.esm = EmotionStateManager()

    def test_initial(self):
        snap = self.esm.snapshot()
        self.assertEqual(snap["emotion"], "neutral")

    def test_event_system_ready(self):
        r = self.esm.on_runtime_event("SYSTEM_READY")
        self.assertTrue(r["ok"])
        self.assertEqual(r["emotion"], "happy")
        self.assertTrue(r["changed"])

    def test_event_error(self):
        r = self.esm.on_runtime_event("ERROR")
        self.assertEqual(r["emotion"], "sad")

    def test_event_task_end(self):
        r = self.esm.on_runtime_event("TASK_END")
        self.assertEqual(r["emotion"], "happy")

    def test_event_unknown_keeps(self):
        self.esm.on_runtime_event("SYSTEM_READY")
        r = self.esm.on_runtime_event("UNKNOWN_EVENT")
        self.assertFalse(r["changed"])
        self.assertEqual(r["emotion"], "happy")

    def test_state_thinking(self):
        r = self.esm.on_companion_state("thinking")
        self.assertEqual(r["emotion"], "neutral")
        self.assertEqual(r["animation"]["motion_group"], "Think")

    def test_state_online(self):
        r = self.esm.on_companion_state("online")
        self.assertEqual(r["emotion"], "happy")

    def test_state_error(self):
        r = self.esm.on_companion_state("error")
        self.assertEqual(r["emotion"], "sad")

    def test_state_unknown_keeps(self):
        self.esm.on_companion_state("online")
        r = self.esm.on_companion_state("weird")
        self.assertFalse(r["changed"])

    def test_listener(self):
        got = []
        self.esm.on_change(lambda snap: got.append(snap["emotion"]))
        self.esm.on_runtime_event("SYSTEM_READY")
        self.assertEqual(got, ["happy"])

    def test_stats(self):
        self.esm.on_runtime_event("SYSTEM_READY")
        s = self.esm.stats()
        self.assertEqual(s["current_emotion"], "happy")
        self.assertEqual(s["event_count"]["SYSTEM_READY"], 1)

    def test_disabled(self):
        esm = EmotionStateManager(enabled=False)
        r = esm.on_runtime_event("SYSTEM_READY")
        self.assertEqual(r["mode"], "error_frame")

    def test_clear(self):
        self.esm.on_change(lambda snap: None)
        self.esm.on_runtime_event("SYSTEM_READY")
        self.assertEqual(self.esm.clear(), 1)
        self.assertEqual(self.esm.snapshot()["emotion"], "neutral")


class TestAnimation(unittest.TestCase):
    """动画映射"""

    def test_animation_map_states(self):
        for state in ("idle", "initializing", "online", "thinking",
                      "learning", "waiting", "error"):
            self.assertIn(state, ANIMATION_MAP)
            self.assertIn("reason", ANIMATION_MAP[state].to_dict())

    def test_event_map(self):
        for evt in ("SYSTEM_READY", "MEMORY_SYNC", "MODEL_SWITCH",
                    "TASK_START", "TASK_END", "ERROR"):
            self.assertIn(evt, EVENT_ANIMATION_MAP)

    def test_animation_for_state(self):
        spec = animation_for_state("thinking")
        self.assertEqual(spec.motion_group, "Think")

    def test_animation_for_event(self):
        spec = animation_for_event("SYSTEM_READY")
        self.assertEqual(spec.emotion, "happy")

    def test_animation_unknown(self):
        self.assertIsNone(animation_for_state("nope"))
        self.assertIsNone(animation_for_event("nope"))

    def test_animation_to_dict(self):
        spec = animation_for_state("error")
        d = spec.to_dict()
        for key in ("emotion", "motion_group", "motion_no",
                    "priority", "reason"):
            self.assertIn(key, d)


class TestEmotionState(unittest.TestCase):
    """情绪状态对象"""

    def test_create(self):
        s = EmotionState("happy", "原因")
        self.assertEqual(s.emotion, "happy")
        self.assertEqual(s.reason, "原因")

    def test_invalid_emotion(self):
        with self.assertRaises(EmotionStateError):
            EmotionState("weird")

    def test_to_dict(self):
        s = EmotionState("sad")
        d = s.to_dict()
        self.assertEqual(d["emotion"], "sad")
        self.assertIsNone(d["animation"])


class TestSettingsManager(unittest.TestCase):
    """设置管理器"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sm = SettingsManager(
            path=os.path.join(self._tmp.name, "settings.json"),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_groups(self):
        self.assertEqual(SETTING_GROUPS,
                         ["basic", "ai", "memory", "developer"])

    def test_defaults(self):
        self.assertFalse(self.sm.get("basic", "auto_start"))
        self.assertEqual(self.sm.get("ai", "model"), "auto")
        self.assertTrue(self.sm.get("memory", "auto_memory"))
        self.assertFalse(self.sm.get("developer", "debug_mode"))

    def test_set(self):
        r = self.sm.set("basic", "volume", 0.9)
        self.assertTrue(r["ok"])
        self.assertEqual(r["new"], 0.9)
        self.assertEqual(self.sm.get("basic", "volume"), 0.9)

    def test_set_invalid_group(self):
        with self.assertRaises(SettingsManagerError):
            self.sm.set("nope", "x", 1)

    def test_set_group(self):
        r = self.sm.set_group("basic", {"volume": 0.7,
                                        "animation": False})
        self.assertEqual(r["applied"], 2)
        self.assertEqual(self.sm.get("basic", "volume"), 0.7)
        self.assertFalse(self.sm.get("basic", "animation"))

    def test_persistence(self):
        self.sm.set("basic", "volume", 0.6)
        sm2 = SettingsManager(
            path=os.path.join(self._tmp.name, "settings.json"),
        )
        self.assertEqual(sm2.get("basic", "volume"), 0.6)

    def test_changes_recorded(self):
        self.sm.set("basic", "volume", 0.5)
        self.sm.set("ai", "model", "Qwen")
        changes = self.sm.changes()
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0]["group"], "ai")
        self.assertEqual(changes[0]["old"], "auto")
        self.assertEqual(changes[0]["new"], "Qwen")

    def test_dump(self):
        d = self.sm.dump()
        self.assertEqual(set(d.keys()),
                         {"basic", "ai", "memory", "developer"})

    def test_stats(self):
        self.sm.set("basic", "volume", 0.5)
        s = self.sm.stats()
        self.assertEqual(s["change_count"], 1)

    def test_clear(self):
        self.sm.set("basic", "volume", 0.5)
        self.assertEqual(self.sm.clear(), 1)

    def test_load_missing_file(self):
        sm = SettingsManager(
            path=os.path.join(self._tmp.name, "none.json"),
        )
        self.assertEqual(sm.get("basic", "volume"), 0.8)


class TestRuntimeConsole(unittest.TestCase):
    """运行时控制台"""

    def setUp(self):
        self.c = RuntimeConsole()

    def test_initial(self):
        r = self.c.report()
        self.assertEqual(r["system"]["backend"], "Unknown")
        self.assertEqual(r["ai"]["route"], "Local")

    def test_update_system(self):
        r = self.c.update_system(backend="Online", latency_ms=25.3)
        self.assertTrue(r["ok"])
        self.assertEqual(r["system"]["backend"], "Online")
        self.assertEqual(r["system"]["latency_ms"], 25.3)

    def test_update_ai(self):
        r = self.c.update_ai(model="Qwen", route="Local",
                             token_usage=100)
        self.assertEqual(r["ai"]["model"], "Qwen")
        self.assertEqual(r["ai"]["token_usage"], 100)

    def test_update_memory(self):
        r = self.c.update_memory(read=10, write=3, conflict=0)
        self.assertEqual(r["memory"]["read"], 10)
        self.assertEqual(r["memory"]["conflict"], 0)

    def test_update_trace(self):
        r = self.c.update_trace(trace_id="tr_1", task_id="task_1",
                                runtime_id="rt_1")
        self.assertEqual(r["trace"]["runtime_id"], "rt_1")

    def test_report_sections(self):
        r = self.c.report()
        for key in ("system", "ai", "memory", "trace",
                    "generated_at"):
            self.assertIn(key, r)

    def test_stats(self):
        self.c.update_system(backend="Online")
        self.c.update_ai(model="Qwen")
        s = self.c.stats()
        self.assertEqual(s["backend"], "Online")
        self.assertEqual(s["model"], "Qwen")

    def test_disabled(self):
        c = RuntimeConsole(enabled=False)
        r = c.update_system(backend="Online")
        self.assertEqual(r["mode"], "error_frame")

    def test_clear(self):
        self.c.update_system(backend="Online")
        self.c.update_ai(model="Qwen")
        self.c.clear()
        r = self.c.report()
        self.assertEqual(r["system"]["backend"], "Unknown")
        self.assertEqual(r["ai"]["model"], "")


if __name__ == "__main__":
    unittest.main()
