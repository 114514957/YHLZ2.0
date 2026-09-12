"""
YHLZ Embodied AI V4.4 - 决策审计系统单元测试 (Policy Audit Log)

覆盖:
    - 审计记录: 字段完整性 / 白名单动作校验 / 必填校验
    - 聚合查询: audit_policy_log (应用次数 / 拒绝次数 / 原因 / by_trigger)
    - 独立存储: 不依赖 Agent Memory (无任何 Memory 接口)
    - JSONL 持久化 (save / load / 坏行跳过)
    - 容量限制与清空
"""
import json
import os
import tempfile
import unittest

from backend.embodied.strategy.audit import (
    AUDIT_ACTIONS,
    PolicyAuditError,
    PolicyAuditLog,
)


class TestAuditRecord(unittest.TestCase):

    def setUp(self):
        self.audit = PolicyAuditLog()

    def test_record_fields(self):
        e = self.audit.record(
            trigger="recipe_pick", action="apply", applied=True,
            goal_id="g-1", kind="success", scene="room",
            reason="模板应用到规划",
        )
        self.assertIn("timestamp", e)
        self.assertEqual(e["goal_id"], "g-1")
        self.assertEqual(e["trigger"], "recipe_pick")
        self.assertEqual(e["kind"], "success")
        self.assertEqual(e["action"], "apply")
        self.assertEqual(e["scene"], "room")
        self.assertTrue(e["applied"])
        self.assertEqual(e["reason"], "模板应用到规划")

    def test_record_empty_trigger_raises(self):
        with self.assertRaises(PolicyAuditError):
            self.audit.record(trigger="", action="apply")

    def test_record_invalid_action_raises(self):
        with self.assertRaises(PolicyAuditError):
            self.audit.record(trigger="t", action="hack")

    def test_whitelist_actions(self):
        for action in AUDIT_ACTIONS:
            self.audit.record(trigger="t", action=action)
        self.assertEqual(self.audit.count(), len(AUDIT_ACTIONS))

    def test_record_applied_false(self):
        e = self.audit.record(
            trigger="t", action="reject", applied=False, reason="未采纳",
        )
        self.assertFalse(e["applied"])

    def test_record_default_timestamp(self):
        e = self.audit.record(trigger="t", action="suggest")
        self.assertGreater(e["timestamp"], 0)

    def test_custom_timestamp(self):
        e = self.audit.record(trigger="t", action="suggest", timestamp=123.0)
        self.assertEqual(e["timestamp"], 123.0)

    def test_no_agent_memory_dependency(self):
        """数据独立: 审计模块无 Memory 属性/接口"""
        self.assertFalse(hasattr(self.audit, "memory"))
        self.assertFalse(hasattr(self.audit, "_agent_memory"))


class TestAuditAggregation(unittest.TestCase):

    def setUp(self):
        self.audit = PolicyAuditLog()
        self.audit.record(trigger="recipe_pick", action="apply", applied=True,
                          goal_id="g-1", scene="room", reason="排序最优")
        self.audit.record(trigger="recipe_pick", action="apply", applied=True,
                          goal_id="g-2", scene="warehouse", reason="排序最优")
        self.audit.record(trigger="pick_failure_position", action="reject",
                          applied=False, goal_id="g-3", reason="warning 未采纳")

    def test_applied_rejected_counts(self):
        s = self.audit.audit_policy_log()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["applied_count"], 2)
        self.assertEqual(s["rejected_count"], 1)

    def test_by_action(self):
        s = self.audit.audit_policy_log()
        self.assertEqual(s["by_action"]["apply"], 2)
        self.assertEqual(s["by_action"]["reject"], 1)

    def test_by_trigger(self):
        s = self.audit.audit_policy_log()
        self.assertEqual(s["by_trigger"]["recipe_pick"]["applied"], 2)
        self.assertEqual(s["by_trigger"]["recipe_pick"]["rejected"], 0)
        self.assertEqual(
            s["by_trigger"]["pick_failure_position"]["rejected"], 1
        )

    def test_top_reasons(self):
        s = self.audit.audit_policy_log()
        reasons = {r["reason"]: r["count"] for r in s["top_reasons"]}
        self.assertEqual(reasons["排序最优"], 2)
        self.assertEqual(reasons["warning 未采纳"], 1)

    def test_recent_order_newest_first(self):
        self.audit.record(trigger="t2", action="rank", applied=False)
        s = self.audit.audit_policy_log(limit=10)
        self.assertEqual(s["recent"][0]["trigger"], "t2")

    def test_recent_limit(self):
        s = self.audit.audit_policy_log(limit=2)
        self.assertEqual(len(s["recent"]), 2)

    def test_empty_aggregation(self):
        s = PolicyAuditLog().audit_policy_log()
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["applied_count"], 0)
        self.assertEqual(s["rejected_count"], 0)

    def test_entries_newest_first(self):
        entries = self.audit.entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["goal_id"], "g-3")


class TestAuditPersistence(unittest.TestCase):

    def test_save_load_roundtrip(self):
        audit = PolicyAuditLog()
        audit.record(trigger="t", action="apply", applied=True,
                     goal_id="g-1", reason="r1")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "embodied_policy_audit.jsonl")
            self.assertEqual(audit.save_to_file(path), 1)
            audit2 = PolicyAuditLog()
            self.assertEqual(audit2.load_from_file(path), 1)
            self.assertEqual(audit2.count(), 1)
            s = audit2.audit_policy_log()
            self.assertEqual(s["applied_count"], 1)
            self.assertEqual(s["by_trigger"]["t"]["applied"], 1)

    def test_load_missing_file(self):
        self.assertEqual(PolicyAuditLog().load_from_file("nope.jsonl"), 0)

    def test_load_bad_line_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "trigger": "t", "action": "apply", "applied": True,
                }) + "\n")
                f.write("NOT JSON\n")
            audit = PolicyAuditLog()
            self.assertEqual(audit.load_from_file(path), 1)
            self.assertEqual(audit.count(), 1)

    def test_save_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.jsonl")
            self.assertEqual(PolicyAuditLog().save_to_file(path), 0)


class TestAuditLifecycle(unittest.TestCase):

    def test_max_entries_limit(self):
        audit = PolicyAuditLog(max_entries=5)
        for i in range(10):
            audit.record(trigger=f"t{i}", action="suggest")
        self.assertEqual(audit.count(), 5)
        entries = audit.entries()
        self.assertEqual(entries[0]["trigger"], "t9")

    def test_max_entries_zero_raises(self):
        with self.assertRaises(PolicyAuditError):
            PolicyAuditLog(max_entries=0)

    def test_clear(self):
        audit = PolicyAuditLog()
        audit.record(trigger="t", action="apply")
        self.assertEqual(audit.clear(), 1)
        self.assertEqual(audit.count(), 0)

    def test_max_entries_property(self):
        self.assertEqual(PolicyAuditLog(max_entries=7).max_entries, 7)


if __name__ == "__main__":
    unittest.main()
