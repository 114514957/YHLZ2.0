"""
YHLZ Embodied AI V6.0 - 持久化审计单元测试 (Persistence Audit)

覆盖 (persistence/persistence_audit.py):
    - 10 动作白名单 / 记录 / 报告 / 上限 / 清空
"""
import unittest

from backend.embodied.companion.persistence import (
    PERSISTENCE_AUDIT_ACTIONS,
    PersistenceAudit,
    PersistenceAuditError,
)


class TestPersistenceAudit(unittest.TestCase):
    """持久化审计"""

    def test_actions_whitelist(self):
        for a in ("save", "load", "restore", "activate", "skip",
                  "error", "verify", "consolidate", "archive",
                  "recycle"):
            self.assertIn(a, PERSISTENCE_AUDIT_ACTIONS)

    def test_actions_count(self):
        self.assertEqual(len(PERSISTENCE_AUDIT_ACTIONS), 10)

    def test_record(self):
        a = PersistenceAudit()
        e = a.record(action="save", detail="snap_1", ref_id="snap_1")
        self.assertTrue(e["audit_id"].startswith("pa_"))

    def test_record_invalid(self):
        a = PersistenceAudit()
        with self.assertRaises(PersistenceAuditError):
            a.record(action="hack")

    def test_report(self):
        a = PersistenceAudit()
        a.record(action="save")
        a.record(action="load")
        r = a.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["by_action"]["save"], 1)

    def test_report_empty(self):
        a = PersistenceAudit()
        self.assertEqual(a.report()["total"], 0)

    def test_report_limit(self):
        a = PersistenceAudit()
        for i in range(5):
            a.record(action="verify")
        self.assertEqual(len(a.report(limit=2)["recent"]), 2)

    def test_by_action(self):
        a = PersistenceAudit()
        a.record(action="skip")
        a.record(action="skip")
        self.assertEqual(len(a.by_action("skip")), 2)

    def test_by_action_invalid(self):
        a = PersistenceAudit()
        with self.assertRaises(PersistenceAuditError):
            a.by_action("bad")

    def test_ring_capacity(self):
        a = PersistenceAudit(max_records=3)
        for i in range(6):
            a.record(action="verify")
        self.assertEqual(a.report()["total"], 3)

    def test_max_records_validation(self):
        with self.assertRaises(PersistenceAuditError):
            PersistenceAudit(max_records=0)

    def test_clear(self):
        a = PersistenceAudit()
        a.record(action="save")
        self.assertEqual(a.clear(), 1)
        self.assertEqual(a.report()["total"], 0)


if __name__ == "__main__":
    unittest.main()
