"""
YHLZ Embodied AI V4.1 - 环境记忆单元测试

覆盖:
    - 记录 (change / action / state / event)
    - 查询 (按类型 / 按 action_id / 上限)
    - 统计 (total / by_type)
    - 最新记录 (latest_change / latest_action)
    - JSONL 持久化 (save / load)
    - 边界 (上限 / 非法参数) 与清空
"""
import os
import tempfile
import unittest

from backend.embodied.world_model import EnvironmentMemory, EnvironmentMemoryError


class TestEnvironmentMemoryRecord(unittest.TestCase):

    def setUp(self):
        self.mem = EnvironmentMemory(max_entries=10)

    def test_record_change(self):
        eid = self.mem.record_change(
            change={"event": "move", "to": [1, 0]}, state_id="s1",
        )
        self.assertTrue(eid.startswith("chg-"))
        entry = self.mem.get(eid)
        self.assertEqual(entry["type"], "change")
        self.assertEqual(entry["state_id"], "s1")

    def test_record_action(self):
        eid = self.mem.record_action(
            feedback={"action_id": "a1", "result": "success"},
            analysis={"success": True},
        )
        entry = self.mem.get(eid)
        self.assertEqual(entry["type"], "action")
        self.assertEqual(entry["action_id"], "a1")
        self.assertTrue(entry["analysis"]["success"])

    def test_record_state(self):
        eid = self.mem.record_state({"state_id": "s9", "objects": []})
        entry = self.mem.get(eid)
        self.assertEqual(entry["type"], "state")
        self.assertEqual(entry["state_id"], "s9")

    def test_record_event(self):
        eid = self.mem.record_event("reset", metadata={"reason": "test"})
        entry = self.mem.get(eid)
        self.assertEqual(entry["type"], "event")
        self.assertEqual(entry["event"], "reset")

    def test_invalid_max_entries(self):
        with self.assertRaises(EnvironmentMemoryError):
            EnvironmentMemory(max_entries=0)

    def test_max_entries_cap(self):
        mem = EnvironmentMemory(max_entries=3)
        for i in range(5):
            mem.record_event(f"e{i}")
        self.assertEqual(mem.count(), 3)
        self.assertIsNone(mem.get("evt-0"))


class TestEnvironmentMemoryQuery(unittest.TestCase):

    def setUp(self):
        self.mem = EnvironmentMemory()
        self.mem.record_change({"event": "move"})
        self.mem.record_action(
            feedback={"action_id": "a1", "result": "success"},
        )
        self.mem.record_action(
            feedback={"action_id": "a2", "result": "failure"},
        )
        self.mem.record_event("reset")

    def test_query_all_latest_first(self):
        entries = self.mem.query()
        self.assertEqual([e["type"] for e in entries], ["event", "action", "action", "change"])

    def test_query_by_type(self):
        entries = self.mem.query(type="action")
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(e["type"] == "action" for e in entries))

    def test_query_by_action_id(self):
        entries = self.mem.query(type="action", action_id="a2")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["feedback"]["action_id"], "a2")

    def test_query_limit(self):
        entries = self.mem.query(limit=2)
        self.assertEqual(len(entries), 2)

    def test_query_no_match(self):
        self.assertEqual(self.mem.query(type="state"), [])

    def test_latest_change(self):
        latest = self.mem.latest_change()
        self.assertEqual(latest["change"], {"event": "move"})

    def test_latest_action(self):
        latest = self.mem.latest_action()
        self.assertEqual(latest["feedback"]["action_id"], "a2")

    def test_stats(self):
        st = self.mem.stats()
        self.assertEqual(st["total"], 4)
        self.assertEqual(st["by_type"]["action"], 2)
        self.assertEqual(st["by_type"]["change"], 1)


class TestEnvironmentMemoryPersistence(unittest.TestCase):

    def test_save_load_roundtrip(self):
        mem = EnvironmentMemory()
        mem.record_change({"event": "move"})
        mem.record_action(feedback={"action_id": "a1"})
        mem.record_event("reset")
        path = os.path.join(tempfile.gettempdir(), "embodied_mem_test.jsonl")
        n = mem.save_to_file(path)
        self.assertEqual(n, 3)

        mem2 = EnvironmentMemory()
        n2 = mem2.load_from_file(path)
        self.assertEqual(n2, 3)
        self.assertEqual(mem2.count(), 3)
        self.assertEqual(mem2.latest_action()["feedback"]["action_id"], "a1")
        if os.path.exists(path):
            os.remove(path)

    def test_clear(self):
        mem = EnvironmentMemory()
        mem.record_event("e1")
        n = mem.clear()
        self.assertEqual(n, 1)
        self.assertEqual(mem.count(), 0)

    def test_max_entries_property(self):
        mem = EnvironmentMemory(max_entries=42)
        self.assertEqual(mem.max_entries, 42)


if __name__ == "__main__":
    unittest.main()
