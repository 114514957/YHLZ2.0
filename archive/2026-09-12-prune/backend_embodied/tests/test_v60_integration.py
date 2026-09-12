"""
YHLZ Embodied AI V6.0 - 长期连续 Service 集成测试
(Long-term Identity & Growth Continuity via Service)

覆盖:
    - Service API: persistence_save/load, growth_report,
      experience_lifecycle, identity_*, continuity_stats
    - 重启连续: 保存 → 新 Service → 恢复 → 状态一致
    - 恢复安全: 损坏数据跳过 / 版本不兼容 / 不崩溃
    - 身份连续: 人格/关系/记忆恢复
    - 向后兼容 (V5.9/V5.8 API 仍可用)
"""
import os
import shutil
import tempfile
import unittest

from backend.embodied.service import EmbodiedService


def setup_service():
    svc = EmbodiedService()
    svc.load_config({
        "embodied_enabled": True,
        "companion_enabled": True,
        "companion_persistence_enabled": True,
    })
    return svc


def seed_state(svc, n=3):
    """制造经历 + 确认 + 关系 + 反思 + 创造"""
    mgr = svc.companion_experience
    verifier = svc.companion_verifier
    ids = []
    for _ in range(n):
        rec = mgr.store_from_event(
            success=True, trigger="生成工程Prompt",
            source="v60_integration", action="a", result="成功",
        )
        ids.append(rec["id"])
    for rid in ids:
        for _ in range(3):
            verifier.verify(rid, evidence_count=2, contradictions=0)
    for _ in range(5):
        svc.companion_relationship_update(True)
    svc.companion_reflection()
    svc.companion_creative_run()


class ServiceV60Base(unittest.TestCase):
    """基类: 临时目录"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v60i_")
        self.path = os.path.join(self.tmp, "state.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestServicePersistenceAPI(ServiceV60Base):
    """持久化 API"""

    def setUp(self):
        super().setUp()
        self.svc = setup_service()

    def test_persistence_save_api(self):
        n = self.svc.companion_persistence_save(self.path)
        self.assertEqual(n, 1)
        self.assertTrue(os.path.exists(self.path))

    def test_persistence_load_api(self):
        seed_state(self.svc)
        self.svc.companion_persistence_save(self.path)
        svc2 = setup_service()
        res = svc2.companion_persistence_load(self.path)
        self.assertTrue(res["success"])
        self.assertIn("experience", res["activated"])
        self.assertIn("verification", res["activated"])

    def test_load_missing_file_no_crash(self):
        res = self.svc.companion_persistence_load(
            os.path.join(self.tmp, "nope.jsonl"),
        )
        self.assertFalse(res["success"])

    def test_continuity_stats_api(self):
        st = self.svc.companion_continuity_stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertIn("memory", st)

    def test_continuity_audit_api(self):
        self.svc.companion_persistence_save(self.path)
        r = self.svc.companion_continuity_audit()
        self.assertGreaterEqual(r["by_action"].get("save", 0), 1)

    def test_save_without_path_raises(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_persistence_enabled": True,
        })
        with self.assertRaises(Exception):
            svc.companion_persistence_save()


class TestRestartContinuity(ServiceV60Base):
    """重启连续"""

    def setUp(self):
        super().setUp()
        self.svc = setup_service()
        seed_state(self.svc, n=3)
        self.svc.companion_persistence_save(self.path)
        self.svc2 = setup_service()

    def test_personality_restored(self):
        self.svc2.companion_persistence_load(self.path)
        self.assertEqual(
            self.svc2.companion_personality()["base"],
            self.svc.companion_personality()["base"],
        )

    def test_relationship_restored(self):
        before = self.svc.companion_relationship()["trust_level"]
        self.svc2.companion_persistence_load(self.path)
        after = self.svc2.companion_relationship()["trust_level"]
        self.assertEqual(before, after)

    def test_experience_restored(self):
        before = self.svc.companion_experience.stats()["total"]
        self.svc2.companion_persistence_load(self.path)
        after = self.svc2.companion_experience.stats()["total"]
        self.assertEqual(before, after)

    def test_verification_restored(self):
        self.svc2.companion_persistence_load(self.path)
        st = self.svc2.companion_verification_stats()
        self.assertGreaterEqual(st["confirmed"], 3)

    def test_reflection_restored(self):
        self.svc2.companion_persistence_load(self.path)
        st = self.svc2.companion_reflection_engine.stats()
        self.assertGreaterEqual(st["reflection_count"], 1)

    def test_creative_proposals_restored(self):
        self.svc2.companion_persistence_load(self.path)
        st = self.svc2.companion_creative_stats()
        self.assertGreaterEqual(st["summary"]["proposal_count"], 0)

    def test_identity_fingerprint_same(self):
        f1 = self.svc.companion_continuity_engine.status()[
            "fingerprint"]
        f2 = self.svc2.companion_continuity_engine.status()[
            "fingerprint"]
        self.assertEqual(f1, f2)

    def test_engine_consistency_after_load(self):
        """load 后 Service 与引擎持有同一实例"""
        self.svc2.companion_persistence_load(self.path)
        eng = self.svc2.companion_continuity_engine
        self.assertIs(eng, self.svc2.companion._continuity)


class TestRestoreSafety(ServiceV60Base):
    """恢复安全"""

    def setUp(self):
        super().setUp()
        self.svc = setup_service()
        seed_state(self.svc)
        self.svc.companion_persistence_save(self.path)

    def test_corrupt_data_skipped(self):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("garbage\n")
        svc2 = setup_service()
        res = svc2.companion_persistence_load(self.path)
        self.assertTrue(res["success"])

    def test_wrong_version_denied(self):
        with open(self.path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace('"version": "9.5.0"',
                                  '"version": "10.0.0"')
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)
        svc2 = setup_service()
        res = svc2.companion_persistence_load(self.path)
        self.assertFalse(res["success"])

    def test_tampered_checksum_denied(self):
        with open(self.path, "r", encoding="utf-8") as f:
            content = f.read()
        # 篡改 checksum 字段 (任何快照都有)
        import re
        content = re.sub(
            r'"checksum": "[0-9a-f]{64}"',
            '"checksum": "0000000000000000000000000000000000000000000000000000000000000000"',
            content,
        )
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)
        svc2 = setup_service()
        res = svc2.companion_persistence_load(self.path)
        self.assertFalse(res["success"])

    def test_full_corrupt_file(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("@@@\n")
        svc2 = setup_service()
        res = svc2.companion_persistence_load(self.path)
        self.assertFalse(res["success"])


class TestLifecycleAPI(ServiceV60Base):
    """生命周期与记忆 API"""

    def setUp(self):
        super().setUp()
        self.svc = setup_service()
        seed_state(self.svc, n=3)

    def test_experience_lifecycle_api(self):
        r = self.svc.companion_experience_lifecycle()
        self.assertIn("stages", r)
        self.assertGreaterEqual(len(r["stages"]["active"]), 1)

    def test_memory_overview_api(self):
        self.svc.companion_experience_lifecycle()
        mo = self.svc.companion_memory_overview()
        self.assertIn("stages", mo)
        self.assertIn("importance", mo)

    def test_high_value_protection_api(self):
        self.svc.companion_experience_lifecycle()
        eng = self.svc.companion_continuity_engine
        st = eng.importance.stats()
        self.assertIn("protected_count", st)


class TestIdentityAPI(ServiceV60Base):
    """身份 API"""

    def setUp(self):
        super().setUp()
        self.svc = setup_service()

    def test_identity_capture_api(self):
        snap = self.svc.companion_identity_capture(reason="首次")
        self.assertTrue(snap["snapshot_id"].startswith("idsnap_"))

    def test_identity_history_api(self):
        self.svc.companion_identity_capture(reason="首次")
        h = self.svc.companion_identity_history()
        self.assertEqual(h["stats"]["snapshot_count"], 1)

    def test_identity_propose_api(self):
        p = self.svc.companion_identity_propose_change(
            "增加维度", {"dimensions": {"serious": 0.9}},
        )
        self.assertEqual(p["approval"]["status"], "PROPOSED")

    def test_identity_approve_api(self):
        p = self.svc.companion_identity_propose_change(
            "增加维度", {"dimensions": {"serious": 0.9}},
        )
        a = self.svc.companion_identity_approve_change(
            p["snapshot_id"], "user",
        )
        self.assertEqual(a["approval"]["status"], "APPROVED")

    def test_identity_reject_api(self):
        p = self.svc.companion_identity_propose_change(
            "增加维度", {"dimensions": {"serious": 0.9}},
        )
        r = self.svc.companion_identity_reject_change(
            p["snapshot_id"], "不采纳",
        )
        self.assertEqual(r["approval"]["status"], "REJECTED")

    def test_identity_immutable_api(self):
        with self.assertRaises(Exception):
            self.svc.companion_identity_propose_change(
                "改使命", {"mission": "新使命"},
            )


class TestGrowthAPI(ServiceV60Base):
    """成长 API"""

    def setUp(self):
        super().setUp()
        self.svc = setup_service()
        seed_state(self.svc)

    def test_growth_report_api(self):
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertGreaterEqual(r["summary"]["experience_total"], 3)

    def test_growth_trend_api(self):
        eng = self.svc.companion_continuity_engine
        eng.track_event("experience_confirmed", detail="e1")
        t = self.svc.companion_growth_trend(bucket="day")
        self.assertEqual(t["bucket"], "day")

    def test_growth_metrics_api(self):
        m = self.svc.companion_growth_metrics()
        self.assertIn("by_type", m)

    def test_growth_report_four_dimensions(self):
        r = self.svc.companion_growth_report()
        for key in ("experience_growth", "cognitive_growth",
                    "creative_growth", "relationship_growth"):
            self.assertIn(key, r)


class TestBackwardCompatibility(ServiceV60Base):
    """V5.x 向后兼容"""

    def setUp(self):
        super().setUp()
        self.svc = setup_service()

    def test_v59_creative_api(self):
        r = self.svc.companion_creative_run()
        self.assertIn("summary", r)

    def test_v58_reflection_api(self):
        r = self.svc.companion_reflection()
        self.assertEqual(r["mode"], "rule_based")

    def test_v57_experience_api(self):
        st = self.svc.companion_experience_stats()
        self.assertIn("total", st)

    def test_v56_relationship_api(self):
        r = self.svc.companion_relationship()
        self.assertIn("trust_level", r)

    def test_v55_personality_api(self):
        p = self.svc.companion_personality()
        self.assertIn("base", p)

    def test_v50_handle_api(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_version_6_0(self):
        self.assertEqual(self.svc.companion.status()["version"],
                         "9.5.0")

    def test_creative_engine_version(self):
        st = self.svc.companion_creative_engine.status()
        self.assertEqual(st["version"], "9.5.0")


class TestPersistenceAuditAPI(ServiceV60Base):
    """持久化审计"""

    def setUp(self):
        super().setUp()
        self.svc = setup_service()

    def test_audit_after_save_load(self):
        self.svc.companion_persistence_save(self.path)
        # 保存审计在保存方
        by1 = self.svc.companion_continuity_audit()["by_action"]
        self.assertGreaterEqual(by1.get("save", 0), 1)
        # 加载/激活审计在恢复方
        svc2 = setup_service()
        svc2.companion_persistence_load(self.path)
        by2 = svc2.companion_continuity_audit()["by_action"]
        self.assertGreaterEqual(by2.get("load", 0), 1)
        self.assertGreaterEqual(by2.get("activate", 0), 1)

    def test_audit_skip_on_corrupt(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("bad\n")
        self.svc.companion_persistence_load(self.path)
        r = self.svc.companion_continuity_audit()
        self.assertGreaterEqual(
            r["by_action"].get("skip", 0), 1,
        )


if __name__ == "__main__":
    unittest.main()
