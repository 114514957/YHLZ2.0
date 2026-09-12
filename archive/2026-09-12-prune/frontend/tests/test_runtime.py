"""
YHLZ 前端 Runtime 层测试 (Runtime State/Event/Trace)

覆盖:
    - 状态机 (idle→initializing→online/thinking/learning/waiting/error)
    - 连接状态
    - 事件总线 (订阅/发布/历史/统计)
    - 追踪 (runtime_id/task_id/trace)
    - 停用错误帧
"""
import unittest

from frontend.runtime import (
    RUNTIME_EVENTS,
    RuntimeEvent,
    RuntimeEventBus,
    RuntimeEventError,
    RuntimeState,
    RuntimeStateError,
    TraceManager,
    TraceManagerError,
)


class TestRuntimeState(unittest.TestCase):
    """运行时状态"""

    def test_initial(self):
        rs = RuntimeState()
        snap = rs.snapshot()
        self.assertEqual(snap["state"], "idle")
        self.assertEqual(snap["connection"], "disconnected")
        self.assertFalse(snap["online"])

    def test_set_online(self):
        rs = RuntimeState()
        r = rs.set_state("online")
        self.assertTrue(r["ok"])
        self.assertEqual(r["to"], "online")
        self.assertTrue(rs.snapshot()["online"])

    def test_all_states(self):
        rs = RuntimeState()
        for state in ("initializing", "online", "thinking",
                      "learning", "waiting", "error"):
            r = rs.set_state(state)
            self.assertTrue(r["ok"])
            self.assertEqual(rs.snapshot()["state"], state)

    def test_invalid_state(self):
        rs = RuntimeState()
        with self.assertRaises(RuntimeStateError):
            rs.set_state("nope")

    def test_connection(self):
        rs = RuntimeState()
        r = rs.set_connection("connected")
        self.assertTrue(r["ok"])
        self.assertEqual(rs.snapshot()["connection"], "connected")

    def test_invalid_connection(self):
        rs = RuntimeState()
        with self.assertRaises(RuntimeStateError):
            rs.set_connection("bad")

    def test_on_change_listener(self):
        rs = RuntimeState()
        got = []
        rs.on_change(lambda snap: got.append(snap["state"]))
        rs.set_state("online")
        self.assertEqual(got, ["online"])

    def test_listener_error_isolated(self):
        rs = RuntimeState()
        def bad(_):
            raise RuntimeError("listener fail")
        rs.on_change(bad)
        # 监听者异常不阻断
        r = rs.set_state("online")
        self.assertTrue(r["ok"])

    def test_reset(self):
        rs = RuntimeState()
        rs.set_state("online")
        rs.set_connection("connected")
        rs.reset()
        snap = rs.snapshot()
        self.assertEqual(snap["state"], "idle")
        self.assertEqual(snap["connection"], "disconnected")

    def test_stats(self):
        rs = RuntimeState()
        rs.set_state("thinking")
        self.assertEqual(rs.stats()["state"], "thinking")

    def test_disabled(self):
        rs = RuntimeState(enabled=False)
        r = rs.set_state("online")
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_clear(self):
        rs = RuntimeState()
        rs.on_change(lambda snap: None)
        self.assertEqual(rs.clear(), 1)


class TestRuntimeEvent(unittest.TestCase):
    """事件对象"""

    def test_event_create(self):
        e = RuntimeEvent("SYSTEM_READY", "启动完成", {"steps": 9})
        self.assertEqual(e.event_type, "SYSTEM_READY")
        self.assertEqual(e.detail, "启动完成")
        self.assertEqual(e.data["steps"], 9)

    def test_event_invalid_type(self):
        with self.assertRaises(RuntimeEventError):
            RuntimeEvent("BAD_EVENT")

    def test_event_to_dict(self):
        e = RuntimeEvent("TASK_START")
        d = e.to_dict()
        for key in ("event_id", "event_type", "detail",
                    "data", "timestamp"):
            self.assertIn(key, d)

    def test_events_enum(self):
        self.assertEqual(RUNTIME_EVENTS, [
            "SYSTEM_READY", "MEMORY_SYNC", "MODEL_SWITCH",
            "TASK_START", "TASK_END", "ERROR",
        ])


class TestRuntimeEventBus(unittest.TestCase):
    """事件总线"""

    def setUp(self):
        self.bus = RuntimeEventBus()

    def test_subscribe_publish(self):
        got = []
        self.bus.subscribe("SYSTEM_READY",
                           lambda e: got.append(e.event_type))
        self.bus.publish(RuntimeEvent("SYSTEM_READY"))
        self.assertEqual(got, ["SYSTEM_READY"])

    def test_publish_delivers_count(self):
        got = []
        self.bus.subscribe("ERROR", lambda e: got.append(1))
        self.bus.subscribe("ERROR", lambda e: got.append(2))
        n = self.bus.publish(RuntimeEvent("ERROR", "x"))
        self.assertEqual(n, 2)

    def test_history(self):
        self.bus.publish(RuntimeEvent("SYSTEM_READY"))
        self.bus.publish(RuntimeEvent("TASK_START"))
        h = self.bus.history()
        self.assertEqual(len(h), 2)
        self.assertEqual(h[0]["event_type"], "TASK_START")

    def test_history_filter(self):
        self.bus.publish(RuntimeEvent("SYSTEM_READY"))
        self.bus.publish(RuntimeEvent("TASK_START"))
        h = self.bus.history(event_type="SYSTEM_READY")
        self.assertEqual(len(h), 1)

    def test_history_limit(self):
        for i in range(10):
            self.bus.publish(RuntimeEvent("TASK_START"))
        self.assertEqual(len(self.bus.history(limit=3)), 3)

    def test_subscriber_error_isolated(self):
        def bad(_):
            raise RuntimeError("boom")
        self.bus.subscribe("ERROR", bad)
        n = self.bus.publish(RuntimeEvent("ERROR", "x"))
        self.assertEqual(n, 0)  # 异常被隔离, 不送达

    def test_unsubscribe(self):
        def h(_):
            pass
        self.bus.subscribe("ERROR", h)
        ok = self.bus.unsubscribe("ERROR", h)
        self.assertTrue(ok)
        n = self.bus.publish(RuntimeEvent("ERROR"))
        self.assertEqual(n, 0)

    def test_stats(self):
        self.bus.publish(RuntimeEvent("SYSTEM_READY"))
        self.bus.publish(RuntimeEvent("SYSTEM_READY"))
        s = self.bus.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_type"]["SYSTEM_READY"], 2)

    def test_subscribe_invalid_type(self):
        with self.assertRaises(RuntimeEventError):
            self.bus.subscribe("BAD", lambda e: None)

    def test_subscribe_non_callable(self):
        with self.assertRaises(RuntimeEventError):
            self.bus.subscribe("ERROR", "not-callable")

    def test_max_history(self):
        bus = RuntimeEventBus(max_history=5)
        for i in range(10):
            bus.publish(RuntimeEvent("TASK_START"))
        self.assertEqual(bus.stats()["total"], 5)

    def test_clear(self):
        self.bus.publish(RuntimeEvent("SYSTEM_READY"))
        self.assertEqual(self.bus.clear(), 1)
        self.assertEqual(self.bus.stats()["total"], 0)

    def test_invalid_max(self):
        with self.assertRaises(RuntimeEventError):
            RuntimeEventBus(max_history=0)


class TestTraceManager(unittest.TestCase):
    """追踪"""

    def setUp(self):
        self.tm = TraceManager()

    def test_runtime_id(self):
        self.assertTrue(self.tm.runtime_id.startswith("rt_"))

    def test_runtime_id_stable(self):
        self.assertEqual(self.tm.runtime_id, self.tm.runtime_id)

    def test_begin_task(self):
        tid = self.tm.begin_task("startup")
        self.assertTrue(tid.startswith("task_"))

    def test_trace(self):
        tid = self.tm.begin_task("startup")
        entry = self.tm.trace(tid, "SYSTEM_READY", "完成")
        self.assertTrue(entry["trace_id"].startswith("tr_"))
        self.assertEqual(entry["task_id"], tid)
        self.assertEqual(entry["runtime_id"], self.tm.runtime_id)

    def test_history(self):
        tid = self.tm.begin_task("startup")
        self.tm.trace(tid, "SYSTEM_READY")
        self.tm.trace(tid, "TASK_START")
        h = self.tm.history()
        self.assertEqual(len(h), 2)

    def test_history_by_task(self):
        t1 = self.tm.begin_task("a")
        t2 = self.tm.begin_task("b")
        self.tm.trace(t1, "SYSTEM_READY")
        self.tm.trace(t2, "SYSTEM_READY")
        self.assertEqual(len(self.tm.history(task_id=t1)), 1)

    def test_stats(self):
        tid = self.tm.begin_task("startup")
        self.tm.trace(tid, "SYSTEM_READY")
        s = self.tm.stats()
        self.assertEqual(s["total_records"], 1)
        self.assertEqual(s["active_tasks"], 1)

    def test_clear(self):
        tid = self.tm.begin_task("a")
        self.tm.trace(tid, "SYSTEM_READY")
        self.assertEqual(self.tm.clear(), 1)
        self.assertEqual(self.tm.stats()["total_records"], 0)

    def test_invalid_max(self):
        with self.assertRaises(TraceManagerError):
            TraceManager(max_records=0)


if __name__ == "__main__":
    unittest.main()
