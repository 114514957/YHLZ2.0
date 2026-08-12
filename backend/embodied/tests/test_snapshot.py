"""
YHLZ Embodied AI V6.0 - 快照与恢复单元测试 (Snapshot & Restore)

覆盖 (persistence/snapshot.py, persistence/restore.py):
    - 快照结构: Version / State / Checksum
    - checksum 校验 (篡改检测)
    - 恢复流程: Load → Checksum → Schema → Identity → Memory → Activate
    - 恢复失败不崩溃 (跳过 + 记录)
    - 版本不兼容降级
    - 身份指纹校验
"""
import unittest

from backend.embodied.companion.persistence import (
    RESTORE_STEPS,
    SNAPSHOT_DOMAINS,
    CompanionSnapshot,
    RestoreManager,
    RestoreError,
    SnapshotError,
)


def full_states():
    """构造全量状态"""
    return {
        "identity": {"fingerprint": "fp1", "base": "铁哥们"},
        "personality": {"base": "铁哥们", "dimensions": {"warmth": 0.5}},
        "relationship": {"trust_level": 0.8},
        "experience": [{"id": "e1", "trigger": "t"}],
        "verification": [{"experience_id": "e1", "status": "CONFIRMED"}],
        "reflection": [{"report_id": "r1"}],
        "creative": {"summary": {"proposal_count": 1},
                     "memory": [{"proposal_id": "cp_1"}]},
        "creative_memory": [{"proposal_id": "cp_1"}],
    }


class TestSnapshotBuild(unittest.TestCase):
    """快照构建"""

    def setUp(self):
        self.snap = CompanionSnapshot()

    def test_build_structure(self):
        s = self.snap.build(full_states())
        for key in ("snapshot_id", "version", "created_at",
                    "checksum", "state"):
            self.assertIn(key, s)

    def test_build_id_prefix(self):
        s = self.snap.build(full_states())
        self.assertTrue(s["snapshot_id"].startswith("snap_"))

    def test_build_version(self):
        s = self.snap.build(full_states())
        self.assertEqual(s["version"], "9.5.0")

    def test_build_state_kept(self):
        s = self.snap.build(full_states())
        self.assertEqual(len(s["state"]), 8)

    def test_build_checksum_hex(self):
        s = self.snap.build(full_states())
        self.assertEqual(len(s["checksum"]), 64)

    def test_build_empty_states(self):
        with self.assertRaises(SnapshotError):
            self.snap.build({})

    def test_build_none_states(self):
        with self.assertRaises(SnapshotError):
            self.snap.build({"identity": None})

    def test_build_deterministic_checksum(self):
        s1 = self.snap.build(full_states())
        s2 = self.snap.build(full_states())
        self.assertEqual(s1["checksum"], s2["checksum"])

    def test_build_changed_state_changes_checksum(self):
        s1 = self.snap.build(full_states())
        st = full_states()
        st["relationship"] = {"trust_level": 0.9}
        s2 = self.snap.build(st)
        self.assertNotEqual(s1["checksum"], s2["checksum"])

    def test_build_ignores_absent_domains(self):
        s = self.snap.build({"identity": {"fp": "x"}})
        self.assertEqual(s["state"], {"identity": {"fp": "x"}})

    def test_custom_version(self):
        snap = CompanionSnapshot(version="7.1.0")
        s = snap.build(full_states())
        self.assertEqual(s["version"], "7.1.0")

    def test_empty_version_validation(self):
        with self.assertRaises(SnapshotError):
            CompanionSnapshot(version="")


class TestSnapshotVerify(unittest.TestCase):
    """快照校验"""

    def setUp(self):
        self.snap = CompanionSnapshot()

    def test_verify_ok(self):
        s = self.snap.build(full_states())
        ok, reason = self.snap.verify(s)
        self.assertTrue(ok)
        self.assertIn("完整", reason)

    def test_verify_none(self):
        ok, reason = self.snap.verify(None)
        self.assertFalse(ok)

    def test_verify_missing_field(self):
        s = self.snap.build(full_states())
        del s["checksum"]
        ok, reason = self.snap.verify(s)
        self.assertFalse(ok)
        self.assertIn("缺字段", reason)

    def test_verify_tampered_state(self):
        s = self.snap.build(full_states())
        s["state"]["relationship"] = {"trust_level": 1.0}
        ok, reason = self.snap.verify(s)
        self.assertFalse(ok)
        self.assertIn("checksum", reason)

    def test_verify_empty_state(self):
        ok, reason = self.snap.verify({
            "snapshot_id": "snap_1", "version": "9.5.0",
            "created_at": 1.0, "checksum": "x", "state": {},
        })
        self.assertFalse(ok)

    def test_verify_require_domains_ok(self):
        s = self.snap.build(full_states())
        ok, reason = self.snap.verify(s, require_domains=["identity"])
        self.assertTrue(ok)

    def test_verify_require_domains_missing(self):
        s = self.snap.build({"identity": {"fp": "x"}})
        ok, reason = self.snap.verify(
            s, require_domains=["personality"],
        )
        self.assertFalse(ok)
        self.assertIn("缺失必需域", reason)

    def test_domains(self):
        s = self.snap.build(full_states())
        self.assertIn("identity", self.snap.domains(s))
        self.assertIn("experience", self.snap.domains(s))

    def test_stats(self):
        st = self.snap.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertEqual(len(st["domains"]), 12)


class TestRestoreFlow(unittest.TestCase):
    """恢复流程"""

    def setUp(self):
        self.snap = CompanionSnapshot()
        self.restore = RestoreManager(snapshot=self.snap)
        self.applied = []

        def applier(data):
            self.applied.append(data)
            return True

        self.appliers = {
            "personality": applier,
            "relationship": applier,
            "experience": applier,
        }

    def test_restore_ok(self):
        s = self.snap.build(full_states())
        r = self.restore.restore(s, self.appliers)
        self.assertTrue(r["success"])
        self.assertIn("personality", r["activated"])
        self.assertIn("relationship", r["activated"])
        self.assertIn("experience", r["activated"])

    def test_restore_steps(self):
        s = self.snap.build(full_states())
        r = self.restore.restore(s, self.appliers)
        steps = [x["step"] for x in r["steps"]]
        self.assertIn("load", steps)
        self.assertIn("checksum_verify", steps)
        self.assertIn("schema_verify", steps)
        self.assertIn("identity_verify", steps)
        self.assertIn("memory_verify:experience", steps)
        self.assertIn("activate:experience", steps)

    def test_restore_mode(self):
        s = self.snap.build(full_states())
        r = self.restore.restore(s, self.appliers)
        self.assertEqual(r["mode"], "rule_based")

    def test_restore_none_snapshot(self):
        r = self.restore.restore(None, self.appliers)
        self.assertFalse(r["success"])
        self.assertEqual(r["activated"], [])

    def test_restore_tampered_fails(self):
        s = self.snap.build(full_states())
        s["state"]["relationship"] = {"trust_level": 0.0}
        r = self.restore.restore(s, self.appliers)
        self.assertFalse(r["success"])
        self.assertEqual(r["activated"], [])

    def test_restore_no_appliers_skip(self):
        s = self.snap.build(full_states())
        r = self.restore.restore(s, None)
        self.assertFalse(r["success"])
        self.assertEqual(r["activated"], [])

    def test_restore_partial_appliers(self):
        s = self.snap.build(full_states())
        r = self.restore.restore(s, {"experience": lambda d: True})
        self.assertEqual(r["activated"], ["experience"])
        self.assertTrue(r["success"])

    def test_restore_applier_false_skips(self):
        s = self.snap.build(full_states())
        r = self.restore.restore(s, {
            "personality": lambda d: False,
            "relationship": lambda d: True,
        })
        self.assertIn("relationship", r["activated"])
        self.assertIn("personality", r["skipped"])

    def test_restore_applier_exception_skips(self):
        s = self.snap.build(full_states())

        def boom(data):
            raise RuntimeError("boom")

        r = self.restore.restore(s, {
            "personality": boom,
            "relationship": lambda d: True,
        })
        self.assertIn("relationship", r["activated"])
        self.assertIn("personality", r["skipped"])

    def test_restore_result_keys(self):
        s = self.snap.build(full_states())
        r = self.restore.restore(s, self.appliers)
        for key in ("restore_id", "steps", "activated", "skipped",
                    "success", "mode", "restored_at"):
            self.assertIn(key, r)

    def test_restore_id_prefix(self):
        s = self.snap.build(full_states())
        r = self.restore.restore(s, self.appliers)
        self.assertTrue(r["restore_id"].startswith("rest_"))


class TestSchemaVerify(unittest.TestCase):
    """版本兼容"""

    def setUp(self):
        self.snap = CompanionSnapshot()
        self.restore = RestoreManager(snapshot=self.snap)

    def test_same_major_ok(self):
        s = self.snap.build(full_states())
        ok, reason = self.restore._schema_verify(s)
        self.assertTrue(ok)

    def test_minor_different_ok(self):
        s = self.snap.build(full_states())
        s["version"] = "9.1.0"
        ok, reason = self.restore._schema_verify(s)
        self.assertTrue(ok)

    def test_major_different_deny(self):
        s = self.snap.build(full_states())
        s["version"] = "10.0.0"
        ok, reason = self.restore._schema_verify(s)
        self.assertFalse(ok)
        self.assertIn("不兼容", reason)

    def test_empty_version_deny(self):
        s = self.snap.build(full_states())
        s["version"] = ""
        ok, reason = self.restore._schema_verify(s)
        self.assertFalse(ok)

    def test_major_deny_restore_skips(self):
        s = self.snap.build(full_states())
        s["version"] = "10.0.0"
        r = self.restore.restore(s, {"experience": lambda d: True})
        self.assertFalse(r["success"])
        self.assertEqual(r["activated"], [])


class TestIdentityVerify(unittest.TestCase):
    """身份指纹校验"""

    def test_no_fingerprint_configured_pass(self):
        snap = CompanionSnapshot()
        restore = RestoreManager(snapshot=snap)
        s = snap.build({"identity": {"fingerprint": "anything"}})
        ok, reason = restore._identity_verify(s)
        self.assertTrue(ok)

    def test_match_pass(self):
        snap = CompanionSnapshot()
        restore = RestoreManager(snapshot=snap,
                                 identity_fingerprint="fp_x")
        s = snap.build({"identity": {"fingerprint": "fp_x"}})
        ok, reason = restore._identity_verify(s)
        self.assertTrue(ok)

    def test_mismatch_fail(self):
        snap = CompanionSnapshot()
        restore = RestoreManager(snapshot=snap,
                                 identity_fingerprint="fp_x")
        s = snap.build({"identity": {"fingerprint": "fp_other"}})
        ok, reason = restore._identity_verify(s)
        self.assertFalse(ok)
        self.assertIn("不匹配", reason)

    def test_no_identity_domain_pass(self):
        restore = RestoreManager(snapshot=CompanionSnapshot())
        s = CompanionSnapshot().build({"experience": []})
        ok, reason = restore._identity_verify(s)
        self.assertTrue(ok)

    def test_mismatch_blocks_restore(self):
        snap = CompanionSnapshot()
        restore = RestoreManager(snapshot=snap,
                                 identity_fingerprint="fp_x")
        s = snap.build({"identity": {"fingerprint": "fp_y"},
                        "experience": [{"id": "e1"}]})
        r = restore.restore(s, {"experience": lambda d: True})
        self.assertFalse(r["success"])
        self.assertEqual(r["activated"], [])


class TestMemoryVerify(unittest.TestCase):
    """记忆校验"""

    def test_list_ok(self):
        ok, reason = RestoreManager._memory_verify("experience",
                                                   [{"id": "e1"}])
        self.assertTrue(ok)

    def test_dict_ok(self):
        ok, reason = RestoreManager._memory_verify("personality",
                                                   {"base": "x"})
        self.assertTrue(ok)

    def test_none_fail(self):
        ok, reason = RestoreManager._memory_verify("identity", None)
        self.assertFalse(ok)

    def test_bad_type_fail(self):
        ok, reason = RestoreManager._memory_verify("identity", 123)
        self.assertFalse(ok)

    def test_huge_list_fail(self):
        ok, reason = RestoreManager._memory_verify(
            "experience", [{}] * 100001,
        )
        self.assertFalse(ok)


class TestRestoreMisc(unittest.TestCase):
    """其余"""

    def test_restore_steps_constant(self):
        for step in ("load", "checksum_verify", "schema_verify",
                     "identity_verify", "memory_verify", "activate"):
            self.assertTrue(any(step in s for s in RESTORE_STEPS))

    def test_snapshot_domains_constant(self):
        for d in ("identity", "personality", "relationship",
                  "experience", "verification", "reflection",
                  "creative", "creative_memory"):
            self.assertIn(d, SNAPSHOT_DOMAINS)

    def test_stats(self):
        st = self._m().stats()
        self.assertEqual(st["mode"], "rule_based")

    def _m(self):
        return RestoreManager(snapshot=CompanionSnapshot())


if __name__ == "__main__":
    unittest.main()
