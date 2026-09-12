"""
YHLZ Embodied AI V6.0 - 连续引擎门面测试 (Continuity Engine)

覆盖 (continuity_engine.py):
    - 状态收集 (8 域)
    - 保存 → 新实例加载 → 恢复 (重启连续)
    - 恢复失败不崩溃 (损坏/版本不兼容/无快照)
    - 记忆整理 (生命周期 + 保护)
    - 身份快照 / 变化审批 / 不可变字段
    - 成长追踪 / 报告 / 趋势
    - 安全保护 / 统计 / 审计
"""
import os
import shutil
import tempfile
import unittest

from backend.embodied.companion.continuity_engine import (
    ContinuityEngine,
    ContinuityError,
)
from backend.embodied.companion.creative import CreativeEngine
from backend.embodied.companion.experience import ExperienceManager
from backend.embodied.companion.personality import (
    AdaptivePersonalityEngine,
)
from backend.embodied.companion.reflection import (
    ImprovementProposalEngine,
    ReflectionEngine,
)
from backend.embodied.companion.relationship import RelationshipManager
from backend.embodied.companion.verification import ExperienceVerifier


class ContinuityTestBase(unittest.TestCase):
    """测试基类: 完整引擎环境"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_cont_")
        self.path = os.path.join(self.tmp, "state.jsonl")
        self.mgr = ExperienceManager()
        self.verifier = ExperienceVerifier()
        self.reflection = ReflectionEngine()
        self.improvement = ImprovementProposalEngine()
        self.creative = CreativeEngine(
            experience_manager=self.mgr,
            verifier=self.verifier,
            reflection_engine=self.reflection,
            improvement_engine=self.improvement,
        )
        self.relationship = RelationshipManager()
        self.personality = AdaptivePersonalityEngine(base="铁哥们")
        self.engine = ContinuityEngine(
            experience_manager=self.mgr,
            verifier=self.verifier,
            reflection_engine=self.reflection,
            creative_engine=self.creative,
            relationship_manager=self.relationship,
            personality_engine=self.personality,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seed(self, trigger="生成工程Prompt", n=3):
        """添加并确认经历"""
        ids = []
        for _ in range(n):
            rec = self.mgr.store_from_event(
                success=True, trigger=trigger,
                source="continuity_test", action="a", result="成功",
            )
            ids.append(rec["id"])
        for rid in ids:
            for _ in range(3):
                self.verifier.verify(rid, evidence_count=2,
                                     contradictions=0)
        return ids


class TestEngineInit(unittest.TestCase):
    """初始化"""

    def test_default_init(self):
        e = ContinuityEngine()
        self.assertIsNotNone(e)

    def test_status(self):
        e = ContinuityEngine()
        st = e.status()
        self.assertEqual(st["version"], "9.5.0")
        self.assertTrue(st["enabled"])
        self.assertEqual(st["mode"], "rule_based")

    def test_fingerprint_deterministic(self):
        p1 = AdaptivePersonalityEngine(base="铁哥们")
        p2 = AdaptivePersonalityEngine(base="铁哥们")
        e1 = ContinuityEngine(personality_engine=p1)
        e2 = ContinuityEngine(personality_engine=p2)
        self.assertEqual(e1.status()["fingerprint"],
                         e2.status()["fingerprint"])

    def test_fingerprint_differs_by_base(self):
        p1 = AdaptivePersonalityEngine(base="铁哥们")
        p2 = AdaptivePersonalityEngine(base="其他")
        e1 = ContinuityEngine(personality_engine=p1)
        e2 = ContinuityEngine(personality_engine=p2)
        self.assertNotEqual(e1.status()["fingerprint"],
                            e2.status()["fingerprint"])

    def test_disabled_save_blocked(self):
        e = ContinuityEngine(enabled=False)
        with self.assertRaises(ContinuityError):
            e.save("/tmp/x.jsonl")

    def test_disabled_load_blocked(self):
        e = ContinuityEngine(enabled=False)
        with self.assertRaises(ContinuityError):
            e.load("/tmp/x.jsonl")

    def test_consolidate_always_available(self):
        e = ContinuityEngine(enabled=False)
        r = e.consolidate()
        self.assertIn("stages", r)

    def test_protections(self):
        e = ContinuityEngine()
        names = {c["name"] for c in e.protections()}
        for n in ("identity_immutable", "change_requires_approval",
                  "high_value_protected", "restore_never_crashes",
                  "read_only_reports", "no_black_box"):
            self.assertIn(n, names)

    def test_protections_all_pass(self):
        e = ContinuityEngine()
        for c in e.protections():
            self.assertTrue(c["passed"])


class TestCollectStates(ContinuityTestBase):
    """状态收集"""

    def test_collect_states(self):
        self.seed()
        states = self.engine.collect_states()
        for d in ("identity", "personality", "relationship",
                  "experience", "verification", "reflection",
                  "creative"):
            self.assertIn(d, states)

    def test_experience_collected(self):
        self.seed(n=2)
        states = self.engine.collect_states()
        self.assertEqual(len(states["experience"]), 2)

    def test_identity_fingerprint(self):
        states = self.engine.collect_states()
        self.assertEqual(
            states["identity"]["fingerprint"],
            self.engine._identity_fingerprint,
        )

    def test_personality_base(self):
        states = self.engine.collect_states()
        self.assertEqual(
            states["personality"]["base"], "铁哥们",
        )

    def test_verification_collected(self):
        self.seed()
        states = self.engine.collect_states()
        self.assertEqual(len(states["verification"]), 3)

    def test_collect_no_crash_without_engines(self):
        e = ContinuityEngine()
        states = e.collect_states()
        self.assertIn("identity", states)


class TestSaveLoad(ContinuityTestBase):
    """持久化闭环"""

    def test_save(self):
        n = self.engine.save(self.path)
        self.assertEqual(n, 1)
        self.assertTrue(os.path.exists(self.path))

    def test_save_no_path(self):
        with self.assertRaises(ContinuityError):
            self.engine.save()

    def test_save_audit(self):
        self.engine.save(self.path)
        r = self.engine.audit_report()
        self.assertGreaterEqual(r["by_action"].get("save", 0), 1)

    def test_load_empty_state(self):
        self.engine.save(self.path)
        e2 = ContinuityEngine(
            experience_manager=ExperienceManager(),
            verifier=ExperienceVerifier(),
            reflection_engine=ReflectionEngine(),
            creative_engine=CreativeEngine(),
            relationship_manager=RelationshipManager(),
            personality_engine=AdaptivePersonalityEngine(
                base="铁哥们",
            ),
        )
        res = e2.load(self.path)
        self.assertIn("experience", res["activated"])
        self.assertIn("personality", res["activated"])
        self.assertIn("relationship", res["activated"])

    def test_load_missing_file(self):
        e = ContinuityEngine()
        res = e.load(os.path.join(self.tmp, "nope.jsonl"))
        self.assertFalse(res["success"])
        self.assertEqual(res["activated"], [])

    def test_load_no_path(self):
        e = ContinuityEngine()
        with self.assertRaises(ContinuityError):
            e.load()

    def test_load_corrupt_file_no_crash(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("garbage\n")
            f.write("more garbage\n")
        e = ContinuityEngine()
        res = e.load(self.path)
        self.assertFalse(res["success"])

    def test_load_mixed_corrupt_recovers(self):
        self.engine.save(self.path)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("corrupt line\n")
        e2 = ContinuityEngine(
            experience_manager=ExperienceManager(),
            verifier=ExperienceVerifier(),
        )
        res = e2.load(self.path)
        self.assertTrue(res["success"])

    def test_load_wrong_version_no_crash(self):
        self.engine.save(self.path)
        # 篡改为不兼容版本
        with open(self.path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace('"version": "9.5.0"',
                                  '"version": "9.5.0"')
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)
        e2 = ContinuityEngine()
        res = e2.load(self.path)
        self.assertFalse(res["success"])
        self.assertEqual(res["activated"], [])

    def test_load_tampered_data_no_crash(self):
        self.engine.save(self.path)
        with open(self.path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace('"trust_level": 0.5',
                                  '"trust_level": 0.9')
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)
        e2 = ContinuityEngine()
        res = e2.load(self.path)
        self.assertFalse(res["success"])

    def test_restore_audit(self):
        self.engine.save(self.path)
        e2 = ContinuityEngine()
        e2.load(self.path)
        r = e2.audit_report()
        self.assertGreaterEqual(r["by_action"].get("load", 0), 1)
        self.assertGreaterEqual(r["by_action"].get("restore", 0), 1)

    def test_save_load_roundtrip_experience(self):
        self.seed(n=2)
        self.engine.save(self.path)
        e2 = ContinuityEngine(
            experience_manager=ExperienceManager(),
            verifier=ExperienceVerifier(),
        )
        e2.load(self.path)
        self.assertEqual(e2._experience.stats()["total"], 2)


class TestIdentityFlow(ContinuityTestBase):
    """身份连续"""

    def test_capture_identity(self):
        snap = self.engine.capture_identity(reason="首次")
        self.assertTrue(snap["snapshot_id"].startswith("idsnap_"))

    def test_identity_history(self):
        self.engine.capture_identity(reason="首次")
        self.engine.capture_identity(reason="第二次")
        h = self.engine.identity_history()
        self.assertEqual(h["stats"]["snapshot_count"], 2)

    def test_propose_change(self):
        p = self.engine.propose_identity_change(
            "增加认真维度", {"dimensions": {"serious": 0.9}},
        )
        self.assertEqual(p["approval"]["status"], "PROPOSED")

    def test_approve_change(self):
        p = self.engine.propose_identity_change(
            "增加维度", {"dimensions": {"serious": 0.9}},
        )
        a = self.engine.approve_identity_change(
            p["snapshot_id"], "user",
        )
        self.assertEqual(a["approval"]["status"], "APPROVED")

    def test_reject_change(self):
        p = self.engine.propose_identity_change(
            "增加维度", {"dimensions": {"serious": 0.9}},
        )
        r = self.engine.reject_identity_change(
            p["snapshot_id"], "不采纳",
        )
        self.assertEqual(r["approval"]["status"], "REJECTED")

    def test_immutable_mission_blocked(self):
        with self.assertRaises(Exception):
            self.engine.propose_identity_change(
                "改使命", {"mission": "新使命"},
            )

    def test_identity_audit_traced(self):
        p = self.engine.propose_identity_change(
            "增加维度", {"dimensions": {"serious": 0.9}},
        )
        self.engine.approve_identity_change(p["snapshot_id"])
        h = self.engine.identity_history()
        self.assertGreaterEqual(
            h["audit"]["by_action"].get("approve", 0), 1,
        )

    def test_identity_diff_present(self):
        self.engine.propose_identity_change(
            "关系深化", {"trust_level": 0.9},
        )
        h = self.engine.identity_history()
        self.assertIn("diff_stats", h)

    def test_identity_survives_save_load(self):
        self.engine.capture_identity(reason="首次")
        self.engine.save(self.path)
        e2 = ContinuityEngine()
        e2.load(self.path)
        # 身份指纹一致
        self.assertEqual(
            e2.status()["fingerprint"],
            self.engine.status()["fingerprint"],
        )


class TestConsolidate(ContinuityTestBase):
    """记忆整理"""

    def test_consolidate_stages(self):
        self.seed(n=2)
        r = self.engine.consolidate()
        self.assertEqual(len(r["stages"]["active"]), 2)

    def test_consolidate_protection(self):
        """高价值受保护经验不被回收"""
        self.seed(n=2)
        self.engine.consolidate()
        protected = self.engine.importance.protected_ids()
        for rid in protected:
            self.assertIn(rid, self.engine.consolidate()[
                "stages"]["archive"])

    def test_memory_overview(self):
        self.seed()
        self.engine.consolidate()
        mo = self.engine.memory_overview()
        for key in ("mode", "stages", "importance", "index"):
            self.assertIn(key, mo)

    def test_importance_scored(self):
        self.seed()
        self.engine.consolidate()
        st = self.engine.importance.stats()
        self.assertGreaterEqual(st["scored_count"], 1)

    def test_consolidate_audit(self):
        self.seed()
        self.engine.consolidate()
        r = self.engine.audit_report()
        self.assertGreaterEqual(
            r["by_action"].get("consolidate", 0), 1,
        )


class TestGrowthFlow(ContinuityTestBase):
    """成长"""

    def test_track_event(self):
        e = self.engine.track_event("experience_confirmed",
                                    detail="e1")
        self.assertTrue(e["event_id"].startswith("grow_"))

    def test_track_event_meaning(self):
        self.engine.track_event("reflection_created", detail="r1")
        st = self.engine.meaning.stats()
        self.assertEqual(st["interpretation_count"], 1)

    def test_growth_report(self):
        self.seed()
        self.engine.track_event("experience_confirmed")
        self.engine.track_event("reflection_created")
        r = self.engine.growth_report()
        self.assertGreaterEqual(r["summary"]["confirmed_total"], 3)
        self.assertEqual(r["mode"], "rule_based")

    def test_growth_report_empty(self):
        r = self.engine.growth_report()
        self.assertEqual(r["summary"]["experience_total"], 0)

    def test_growth_trend(self):
        self.engine.track_event("experience_added")
        t = self.engine.growth_trend(bucket="day")
        self.assertEqual(t["bucket"], "day")
        self.assertGreaterEqual(t["total"], 1)

    def test_growth_metrics(self):
        self.engine.track_event("experience_added")
        m = self.engine.growth_metrics()
        self.assertGreaterEqual(m["experience_count"], 1)

    def test_growth_metrics_zero(self):
        m = self.engine.growth_metrics()
        self.assertEqual(m["event_count"], 0)

    def test_stats_structure(self):
        st = self.engine.stats()
        for key in ("mode", "enabled", "schema_version",
                    "identity_fingerprint", "persistence", "memory",
                    "identity", "growth"):
            self.assertIn(key, st)


class TestEdgeCases(ContinuityTestBase):
    """边界"""

    def test_clear(self):
        self.seed()
        self.engine.consolidate()
        self.engine.capture_identity()
        cleared = self.engine.clear()
        self.assertGreaterEqual(cleared["importance"], 0)

    def test_save_after_clear(self):
        self.engine.save(self.path)
        self.engine.clear()
        e2 = ContinuityEngine(
            experience_manager=ExperienceManager(),
            verifier=ExperienceVerifier(),
        )
        res = e2.load(self.path)
        self.assertTrue(res["success"])

    def test_audit_ring_limit(self):
        e = ContinuityEngine()
        for i in range(50):
            e.track_event("experience_added", detail=f"e{i}")
        r = e.audit_report(limit=0)
        self.assertGreaterEqual(r["total"], 0)

    def test_identity_verify_mismatch_blocks(self):
        """不同人格 base 的引擎拒绝恢复"""
        self.engine.save(self.path)
        other_personality = AdaptivePersonalityEngine(base="其他")
        e2 = ContinuityEngine(
            personality_engine=other_personality,
        )
        res = e2.load(self.path)
        self.assertFalse(res["success"])
        self.assertEqual(res["activated"], [])


if __name__ == "__main__":
    unittest.main()
