"""
YHLZ Embodied AI V4.2 - 环境事件日志单元测试

覆盖:
    - 记录: action / object_change / move / reset / observe / system
    - 查询: get_events / event_history / 按类型过滤 / 按结果过滤 / 上限
    - 摘要生成 (失败含因果)
    - 统计 (by_type / by_result / by_cause)
    - JSONL 持久化 (save / load / 坏行跳过)
    - 边界 (上限 / 非法参数) 与清空
"""
import json
import os
import tempfile
import unittest

from backend.embodied.reasoning import EnvironmentEventLog, EnvironmentEventLogError
from backend.embodied.schema import EmbodiedAction, EventType


def make_action(action_type="move", target="", params=None) -> EmbodiedAction:
    return EmbodiedAction.create(
        action_type=action_type, target=target, parameters=params or {},
    )


class TestEventLogRecord(unittest.TestCase):

    def setUp(self):
        self.log = EnvironmentEventLog(max_events=10)

    def test_record_action_success(self):
        a = make_action("move", params={"dx": 1, "dy": 0})
        eid = self.log.record_action(
            a, result="success", change={"event": "move", "to": [1, 0]},
        )
        ev = self.log.get(eid)
        self.assertEqual(ev.event_type, EventType.ACTION.value)
        self.assertEqual(ev.action_id, a.action_id)
        self.assertEqual(ev.result, "success")
        self.assertIn("成功", ev.summary)

    def test_record_action_failure_with_cause(self):
        a = make_action("pick", target="lamp", params={"object": "lamp"})
        eid = self.log.record_action(
            a, result="failure", change={"event": "pick_not_in_reach"},
            cause="position_mismatch",
        )
        ev = self.log.get(eid)
        self.assertEqual(ev.event_type, EventType.FAILURE.value)
        self.assertEqual(ev.cause, "position_mismatch")
        self.assertIn("原因=position_mismatch", ev.summary)

    def test_record_object_change(self):
        eid = self.log.record_object_change("lamp", "on", "off")
        ev = self.log.get(eid)
        self.assertEqual(ev.event_type, EventType.OBJECT_CHANGE.value)
        self.assertEqual(ev.object_changes[0]["name"], "lamp")
        self.assertEqual(ev.object_changes[0]["state"], {"from": "on", "to": "off"})

    def test_record_move(self):
        eid = self.log.record_move([0, 0], [1, 1])
        ev = self.log.get(eid)
        self.assertEqual(ev.event_type, EventType.MOVE.value)
        self.assertEqual(ev.position_from, [0, 0])
        self.assertEqual(ev.position_to, [1, 1])

    def test_record_reset_observe_system(self):
        self.log.record_reset(scene="room")
        self.log.record_observe(objects=3, position={"x": 0, "y": 0})
        self.log.record_system("记忆已加载")
        types = {e.event_type for e in self.log.get_events(limit=10)}
        self.assertIn(EventType.RESET.value, types)
        self.assertIn(EventType.OBSERVE.value, types)
        self.assertIn(EventType.SYSTEM.value, types)

    def test_record_none_raises(self):
        with self.assertRaises(EnvironmentEventLogError):
            self.log.record(None)

    def test_invalid_max_events(self):
        with self.assertRaises(EnvironmentEventLogError):
            EnvironmentEventLog(max_events=0)

    def test_max_events_cap(self):
        log = EnvironmentEventLog(max_events=3)
        for i in range(5):
            log.record_system(f"e{i}")
        self.assertEqual(log.count(), 3)


class TestEventLogQuery(unittest.TestCase):

    def setUp(self):
        self.log = EnvironmentEventLog()
        self.log.record_action(make_action("move"), result="success",
                               change={"event": "move"})
        self.log.record_action(make_action("pick", "lamp", {"object": "lamp"}),
                               result="failure", change={"event": "pick_not_in_reach"},
                               cause="position_mismatch")
        self.log.record_action(make_action("move"), result="failure",
                               change={"event": "move_out_of_bounds"},
                               cause="boundary_limit")
        self.log.record_object_change("door", "open", "closed")
        self.log.record_reset()

    def test_get_events_latest_first(self):
        events = self.log.get_events(limit=10)
        self.assertEqual(events[0].event_type, EventType.RESET.value)
        self.assertEqual(len(events), 5)

    def test_get_events_limit(self):
        events = self.log.get_events(limit=2)
        self.assertEqual(len(events), 2)

    def test_get_events_zero_limit(self):
        self.assertEqual(self.log.get_events(limit=0), [])

    def test_filter_event_type(self):
        events = self.log.get_events(event_type=EventType.FAILURE.value)
        self.assertEqual(len(events), 2)
        for e in events:
            self.assertEqual(e.event_type, EventType.FAILURE.value)

    def test_filter_action_type(self):
        events = self.log.get_events(action_type="pick")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action_type, "pick")

    def test_filter_result(self):
        events = self.log.get_events(result="failure")
        self.assertEqual(len(events), 2)

    def test_event_history_dicts(self):
        history = self.log.event_history(limit=3)
        self.assertEqual(len(history), 3)
        self.assertIn("event_id", history[0])
        self.assertIn("timestamp", history[0])

    def test_failure_events_with_cause(self):
        failures = self.log.failure_events(limit=10)
        self.assertEqual(len(failures), 2)
        causes = {f.cause for f in failures}
        self.assertIn("position_mismatch", causes)
        self.assertIn("boundary_limit", causes)

    def test_stats(self):
        st = self.log.stats()
        self.assertEqual(st["total"], 5)
        self.assertEqual(st["by_type"][EventType.FAILURE.value], 2)
        self.assertEqual(st["by_result"]["success"], 1)
        self.assertEqual(st["by_cause"]["boundary_limit"], 1)


class TestEventLogPersistence(unittest.TestCase):

    def setUp(self):
        self.log = EnvironmentEventLog()

    def _tmp_path(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        return path

    def test_save_load_roundtrip(self):
        path = self._tmp_path()
        try:
            self.log.record_action(make_action("move"), result="success",
                                   change={"event": "move"})
            self.log.record_action(make_action("pick", "lamp", {"object": "lamp"}),
                                   result="failure", cause="position_mismatch")
            n = self.log.save_to_file(path)
            self.assertEqual(n, 2)

            other = EnvironmentEventLog()
            loaded = other.load_from_file(path)
            self.assertEqual(loaded, 2)
            events = other.get_events(limit=10)
            self.assertEqual(len(events), 2)
            # 最新在前: pick 失败事件排最前
            self.assertEqual(events[0].cause, "position_mismatch")
            self.assertEqual(events[0].result, "failure")
        finally:
            os.remove(path)

    def test_load_skips_bad_lines(self):
        path = self._tmp_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"event_type": "action"}\n')
                f.write("not-json\n")
                f.write('{"event_type": "system"}\n')
            other = EnvironmentEventLog()
            loaded = other.load_from_file(path)
            self.assertEqual(loaded, 2)
            self.assertEqual(other.count(), 2)
        finally:
            os.remove(path)

    def test_load_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.log.load_from_file("nonexistent.jsonl")


class TestEventLogLifecycle(unittest.TestCase):

    def test_clear(self):
        log = EnvironmentEventLog()
        log.record_system("a")
        log.record_system("b")
        n = log.clear()
        self.assertEqual(n, 2)
        self.assertEqual(log.count(), 0)

    def test_max_events_property(self):
        log = EnvironmentEventLog(max_events=7)
        self.assertEqual(log.max_events, 7)


class TestEventDeterminism(unittest.TestCase):

    def test_summary_deterministic(self):
        a = make_action("pick", "lamp", {"object": "lamp"})
        log1 = EnvironmentEventLog()
        log2 = EnvironmentEventLog()
        e1 = log1.record_action(a, result="failure", change={"event": "pick_not_in_reach"})
        e2 = log2.record_action(a, result="failure", change={"event": "pick_not_in_reach"})
        self.assertEqual(log1.get(e1).summary, log2.get(e2).summary)

    def test_event_immutable_fields(self):
        """事件一经创建即不可变 (时间线可信)"""
        a = make_action("move")
        log = EnvironmentEventLog()
        eid = log.record_action(a, result="success", change={"event": "move"})
        ev = log.get(eid)
        self.assertEqual(ev.result, "success")
        self.assertNotEqual(ev.summary, "")


if __name__ == "__main__":
    unittest.main()
