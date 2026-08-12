"""
YHLZ Embodied AI V5.9 - 创造审计单元测试 (Creative Audit)

覆盖 (creative_audit.py):
    - 10 动作白名单
    - 记录 / 报告 / 按动作查询
    - 上限环形覆盖 / 异常
"""
import unittest

from backend.embodied.companion.creative import (
    CREATIVE_AUDIT_ACTIONS,
    CreativeAudit,
    CreativeAuditError,
)


class TestAuditInit(unittest.TestCase):
    """初始化与白名单"""

    def test_default_init(self):
        a = CreativeAudit()
        self.assertIsNotNone(a)

    def test_max_records_validation(self):
        with self.assertRaises(CreativeAuditError):
            CreativeAudit(max_records=0)

    def test_actions_whitelist(self):
        for action in ("detect", "evaluate", "reason", "propose",
                       "simulate", "approve", "reject", "execute",
                       "result", "persist"):
            self.assertIn(action, CREATIVE_AUDIT_ACTIONS)

    def test_actions_count(self):
        self.assertEqual(len(CREATIVE_AUDIT_ACTIONS), 10)


class TestRecord(unittest.TestCase):
    """记录"""

    def setUp(self):
        self.audit = CreativeAudit()

    def test_record(self):
        e = self.audit.record(action="detect", detail="机会 opp_1",
                              ref_id="opp_1")
        self.assertTrue(e["audit_id"].startswith("cr_"))
        self.assertEqual(e["action"], "detect")

    def test_record_invalid_action(self):
        with self.assertRaises(CreativeAuditError):
            self.audit.record(action="hack")

    def test_record_empty_detail(self):
        e = self.audit.record(action="evaluate")
        self.assertEqual(e["detail"], "")

    def test_record_all_actions(self):
        for action in CREATIVE_AUDIT_ACTIONS:
            self.audit.record(action=action, detail="d")
        self.assertEqual(self.audit.report()["total"], 10)

    def test_record_timestamp(self):
        e = self.audit.record(action="detect")
        self.assertGreater(e["timestamp"], 0.0)


class TestReport(unittest.TestCase):
    """报告"""

    def setUp(self):
        self.audit = CreativeAudit()

    def test_report_structure(self):
        self.audit.record(action="detect")
        r = self.audit.report()
        for key in ("mode", "total", "by_action", "recent"):
            self.assertIn(key, r)

    def test_report_mode(self):
        self.assertEqual(self.audit.report()["mode"], "rule_based")

    def test_report_empty(self):
        r = self.audit.report()
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["by_action"], {})

    def test_report_by_action(self):
        self.audit.record(action="detect")
        self.audit.record(action="detect")
        self.audit.record(action="propose")
        r = self.audit.report()
        self.assertEqual(r["by_action"]["detect"], 2)
        self.assertEqual(r["by_action"]["propose"], 1)

    def test_report_recent_order(self):
        self.audit.record(action="detect", detail="first")
        self.audit.record(action="propose", detail="second")
        r = self.audit.report(limit=10)
        self.assertEqual(r["recent"][0]["detail"], "second")

    def test_report_limit(self):
        for i in range(5):
            self.audit.record(action="detect", detail=f"d{i}")
        r = self.audit.report(limit=2)
        self.assertEqual(len(r["recent"]), 2)

    def test_report_limit_zero(self):
        for i in range(5):
            self.audit.record(action="detect")
        r = self.audit.report(limit=0)
        self.assertEqual(len(r["recent"]), 5)


class TestByAction(unittest.TestCase):
    """按动作查询"""

    def setUp(self):
        self.audit = CreativeAudit()

    def test_by_action(self):
        self.audit.record(action="simulate", ref_id="cp_1")
        self.audit.record(action="simulate", ref_id="cp_2")
        self.audit.record(action="approve", ref_id="cp_1")
        results = self.audit.by_action("simulate")
        self.assertEqual(len(results), 2)

    def test_by_action_invalid(self):
        with self.assertRaises(CreativeAuditError):
            self.audit.by_action("unknown")

    def test_by_action_empty(self):
        self.assertEqual(self.audit.by_action("persist"), [])


class TestLimitAndClear(unittest.TestCase):
    """上限与清空"""

    def test_ring_capacity(self):
        a = CreativeAudit(max_records=5)
        for i in range(10):
            a.record(action="detect", detail=f"d{i}")
        self.assertEqual(a.report()["total"], 5)
        self.assertEqual(a.report()["recent"][0]["detail"], "d9")

    def test_clear_count(self):
        a = CreativeAudit()
        a.record(action="detect")
        a.record(action="propose")
        self.assertEqual(a.clear(), 2)

    def test_clear_empty(self):
        a = CreativeAudit()
        self.assertEqual(a.clear(), 0)

    def test_clear_resets_report(self):
        a = CreativeAudit()
        a.record(action="detect")
        a.clear()
        self.assertEqual(a.report()["total"], 0)


if __name__ == "__main__":
    unittest.main()
