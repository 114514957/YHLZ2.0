"""
YHLZ Embodied AI V6.0 - 身份历史单元测试 (Identity History)

覆盖 (identity_history/):
    - IdentitySnapshot: 快照记录 / 变化提出 / 审批流 / 不可变字段
    - IdentityDiff: 字段级差异 / 噪声字段 / 摘要
    - IdentityAudit: 动作审计
"""
import unittest

from backend.embodied.companion.identity_history import (
    APPROVAL_STATUSES,
    IMMUTABLE_FIELDS,
    DiffError,
    IdentityAudit,
    IdentityAuditError,
    IdentityDiff,
    IdentitySnapshot,
    IdentitySnapshotError,
    NOISE_FIELDS,
)


def make_state(**over):
    state = {
        "fingerprint": "fp_1",
        "base_personality": "铁哥们",
        "mission": "长期陪伴",
        "core_value": "可靠",
        "dimensions": {"warmth": 0.5, "patience": 0.5},
        "trust_level": 0.5,
    }
    state.update(over)
    return state


class TestIdentitySnapshotCapture(unittest.TestCase):
    """身份快照记录"""

    def setUp(self):
        self.snap = IdentitySnapshot()

    def test_capture(self):
        s = self.snap.capture(make_state(), reason="首次")
        self.assertTrue(s["snapshot_id"].startswith("idsnap_"))
        self.assertEqual(s["approval"]["status"], "APPROVED")

    def test_capture_empty(self):
        with self.assertRaises(IdentitySnapshotError):
            self.snap.capture({})

    def test_capture_fingerprint(self):
        s = self.snap.capture(make_state())
        self.assertEqual(len(s["fingerprint"]), 64)

    def test_capture_history(self):
        self.snap.capture(make_state())
        self.snap.capture(make_state(trust_level=0.8))
        self.assertEqual(len(self.snap.history()), 2)

    def test_latest(self):
        self.snap.capture(make_state(trust_level=0.3))
        self.snap.capture(make_state(trust_level=0.9))
        latest = self.snap.latest()
        self.assertEqual(latest["identity_state"]["trust_level"], 0.9)

    def test_latest_empty(self):
        self.assertIsNone(self.snap.latest())

    def test_get(self):
        s = self.snap.capture(make_state())
        got = self.snap.get(s["snapshot_id"])
        self.assertEqual(got["snapshot_id"], s["snapshot_id"])

    def test_get_missing(self):
        self.assertIsNone(self.snap.get("nope"))

    def test_max_history(self):
        snap = IdentitySnapshot(max_history=3)
        for i in range(10):
            snap.capture(make_state(trust_level=i / 10))
        self.assertEqual(len(snap.history()), 3)

    def test_version(self):
        snap = IdentitySnapshot(version="6.1.0")
        s = snap.capture(make_state())
        self.assertEqual(s["version"], "6.1.0")

    def test_empty_version_validation(self):
        with self.assertRaises(IdentitySnapshotError):
            IdentitySnapshot(version="")


class TestIdentityChangeApproval(unittest.TestCase):
    """变化提出与审批"""

    def setUp(self):
        self.snap = IdentitySnapshot()
        self.current = make_state()

    def test_propose_change(self):
        p = self.snap.propose_change(
            self.current, make_state(trust_level=0.8),
            "关系深化",
        )
        self.assertEqual(p["approval"]["status"], "PROPOSED")

    def test_propose_empty_reason(self):
        with self.assertRaises(IdentitySnapshotError):
            self.snap.propose_change(self.current,
                                     make_state(), "  ")

    def test_propose_change_diff(self):
        p = self.snap.propose_change(
            self.current, make_state(trust_level=0.8),
            "关系深化",
        )
        self.assertEqual(p["change_diff"][0]["field"], "trust_level")
        self.assertEqual(p["change_diff"][0]["before"], 0.5)

    def test_propose_no_diff(self):
        p = self.snap.propose_change(
            self.current, make_state(), "无变化",
        )
        self.assertEqual(p["change_diff"], [])

    def test_immutable_mission(self):
        with self.assertRaises(IdentitySnapshotError):
            self.snap.propose_change(
                self.current, make_state(mission="新使命"),
                "改使命",
            )

    def test_immutable_core_value(self):
        with self.assertRaises(IdentitySnapshotError):
            self.snap.propose_change(
                self.current, make_state(core_value="新价值"),
                "改核心价值",
            )

    def test_immutable_base_personality(self):
        with self.assertRaises(IdentitySnapshotError):
            self.snap.propose_change(
                self.current, make_state(base_personality="其他"),
                "改人格",
            )

    def test_mutable_dimensions_allowed(self):
        p = self.snap.propose_change(
            self.current, make_state(
                dimensions={"serious": 0.9},
            ),
            "增加认真维度",
        )
        self.assertEqual(p["approval"]["status"], "PROPOSED")

    def test_approve_change(self):
        p = self.snap.propose_change(
            self.current, make_state(trust_level=0.8), "原因",
        )
        a = self.snap.approve_change(p["snapshot_id"], "user")
        self.assertEqual(a["approval"]["status"], "APPROVED")
        self.assertEqual(a["approval"]["approver"], "user")

    def test_approve_non_proposed(self):
        s = self.snap.capture(make_state())
        with self.assertRaises(IdentitySnapshotError):
            self.snap.approve_change(s["snapshot_id"])

    def test_approve_missing(self):
        with self.assertRaises(IdentitySnapshotError):
            self.snap.approve_change("nope")

    def test_reject_change(self):
        p = self.snap.propose_change(
            self.current, make_state(trust_level=0.8), "原因",
        )
        r = self.snap.reject_change(p["snapshot_id"], "不采纳")
        self.assertEqual(r["approval"]["status"], "REJECTED")
        self.assertEqual(r["approval"]["reason"], "不采纳")

    def test_reject_default_reason(self):
        p = self.snap.propose_change(
            self.current, make_state(), "原因",
        )
        r = self.snap.reject_change(p["snapshot_id"])
        self.assertEqual(r["approval"]["status"], "REJECTED")

    def test_reject_non_proposed(self):
        s = self.snap.capture(make_state())
        with self.assertRaises(IdentitySnapshotError):
            self.snap.reject_change(s["snapshot_id"])

    def test_double_approve_invalid(self):
        p = self.snap.propose_change(
            self.current, make_state(), "原因",
        )
        self.snap.approve_change(p["snapshot_id"])
        with self.assertRaises(IdentitySnapshotError):
            self.snap.approve_change(p["snapshot_id"])

    def test_by_approval_status(self):
        p = self.snap.propose_change(
            self.current, make_state(trust_level=0.8), "原因",
        )
        self.snap.approve_change(p["snapshot_id"])
        self.assertEqual(len(self.snap.by_approval_status(
            "APPROVED")), 1)
        self.assertEqual(len(self.snap.by_approval_status(
            "PROPOSED")), 0)

    def test_by_approval_status_invalid(self):
        with self.assertRaises(IdentitySnapshotError):
            self.snap.by_approval_status("WAT")

    def test_stats(self):
        self.snap.capture(make_state())
        p = self.snap.propose_change(
            self.current, make_state(), "原因",
        )
        self.snap.reject_change(p["snapshot_id"])
        st = self.snap.stats()
        self.assertEqual(st["snapshot_count"], 2)
        self.assertEqual(st["approved_count"], 1)
        self.assertEqual(st["rejected_count"], 1)

    def test_immutable_fields_constant(self):
        for f in ("mission", "core_value", "base_personality"):
            self.assertIn(f, IMMUTABLE_FIELDS)


class TestIdentityDiff(unittest.TestCase):
    """身份差异"""

    def setUp(self):
        self.diff = IdentityDiff()

    def test_no_change(self):
        d = self.diff.compare(make_state(), make_state())
        self.assertFalse(any(x["changed"] for x in d))

    def test_field_change(self):
        d = self.diff.compare(make_state(),
                              make_state(trust_level=0.9))
        changed = [x for x in d if x["changed"]]
        self.assertEqual(changed[0]["field"], "trust_level")
        self.assertEqual(changed[0]["before"], 0.5)

    def test_field_added(self):
        d = self.diff.compare(make_state(),
                              make_state(new_field="v"))
        added = [x for x in d
                 if x["field"] == "new_field" and x["changed"]]
        self.assertEqual(len(added), 1)

    def test_field_removed(self):
        before = make_state(extra="x")
        after = make_state()
        d = self.diff.compare(before, after)
        removed = [x for x in d
                   if x["field"] == "extra" and x["changed"]]
        self.assertEqual(len(removed), 1)

    def test_noise_ignored(self):
        d = self.diff.compare(
            make_state(timestamp=1.0, interaction_count=5),
            make_state(timestamp=2.0, interaction_count=9),
        )
        self.assertFalse(any(x["changed"] for x in d))

    def test_noise_fields_constant(self):
        self.assertIn("timestamp", NOISE_FIELDS)
        self.assertIn("interaction_count", NOISE_FIELDS)

    def test_summarize_no_change(self):
        d = self.diff.compare(make_state(), make_state())
        self.assertIn("无变化", self.diff.summarize(d))

    def test_summarize_changes(self):
        d = self.diff.compare(make_state(),
                              make_state(trust_level=0.9))
        s = self.diff.summarize(d)
        self.assertIn("trust_level", s)
        self.assertIn("→", s)

    def test_changed_fields(self):
        d = self.diff.compare(make_state(),
                              make_state(trust_level=0.9,
                                         dimensions={"serious": 1.0}))
        fields = self.diff.changed_fields(d)
        self.assertIn("trust_level", fields)
        self.assertIn("dimensions", fields)

    def test_invalid_inputs(self):
        with self.assertRaises(DiffError):
            self.diff.compare(None, {})
        with self.assertRaises(DiffError):
            self.diff.compare({}, "str")

    def test_stats(self):
        self.diff.compare(make_state(), make_state(trust_level=0.9))
        st = self.diff.stats()
        self.assertEqual(st["compare_count"], 1)
        self.assertEqual(st["avg_changed"], 1.0)

    def test_clear(self):
        self.diff.compare(make_state(), make_state())
        self.assertEqual(self.diff.clear(), 1)


class TestIdentityAudit(unittest.TestCase):
    """身份审计"""

    def setUp(self):
        self.audit = IdentityAudit()

    def test_record(self):
        e = self.audit.record(action="propose", detail="idsnap_1",
                              ref_id="idsnap_1")
        self.assertTrue(e["audit_id"].startswith("ida_"))

    def test_record_invalid(self):
        with self.assertRaises(IdentityAuditError):
            self.audit.record(action="hack")

    def test_all_actions(self):
        for a in ("capture", "propose", "approve", "reject",
                  "restore", "verify"):
            self.audit.record(action=a)
        self.assertEqual(self.audit.report()["total"], 6)

    def test_report(self):
        self.audit.record(action="capture")
        r = self.audit.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["by_action"]["capture"], 1)

    def test_report_empty(self):
        r = self.audit.report()
        self.assertEqual(r["total"], 0)

    def test_clear(self):
        self.audit.record(action="capture")
        self.assertEqual(self.audit.clear(), 1)


if __name__ == "__main__":
    unittest.main()
