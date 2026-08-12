"""
YHLZ Embodied AI V6.4 - 感知-记忆认知集成测试 (V6.4 Integration)

覆盖:
    - Service API (reflection/counterfactual/experience/multimodal/stats)
    - 感知-成长闭环 (批准 → multimodal 事件 + 情绪经 meaning)
    - 快照 perception_stats 域
    - 向后兼容 (V6.3 及以前)
"""
import os
import shutil
import tempfile
import unittest

from backend.embodied.service import EmbodiedService


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
        "perception_enabled": True,
        "vision_enabled": True,
        "ocr_enabled": True,
        "detection_enabled": True,
        "companion_persistence_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


def make_verified_candidate(svc, summary="用户屏幕显示重要任务清单",
                            source="camera", confidence=0.9):
    ev = svc.companion_perception_receive(
        source=source,
        content={"kind": "ocr", "text": summary},
        confidence=confidence,
    )
    svc.companion_perception_verify(ev["event_id"])
    return svc.companion_perception_memory_candidates()[
        "candidates"][-1]


class TestReflectionAPI(unittest.TestCase):
    """反思 API"""

    def setUp(self):
        self.svc = setup_service()
        self.c = make_verified_candidate(self.svc)

    def test_reflection_evaluate_api(self):
        r = self.svc.companion_reflection_evaluate(self.c)
        for key in ("reflection_score", "pattern",
                    "contradiction", "value_hint", "reason",
                    "recommendation"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")

    def test_reflection_approve_recommendation(self):
        r = self.svc.companion_reflection_evaluate(self.c)
        self.assertEqual(r["recommendation"], "approve")

    def test_counterfactual_api(self):
        r = self.svc.companion_counterfactual_check(self.c)
        self.assertEqual(r["status"], "holds")

    def test_counterfactual_fail_payment(self):
        c = make_verified_candidate(self.svc, summary="支付成功")
        r = self.svc.companion_counterfactual_check(c)
        self.assertEqual(r["status"], "fails")

    def test_reflection_disabled_config(self):
        svc = setup_service(reflection_enabled=False)
        c = make_verified_candidate(svc)
        r = svc.companion_reflection_evaluate(c)
        self.assertEqual(r["recommendation"], "neutral")


class TestExperienceAPI(unittest.TestCase):
    """经验 API"""

    def setUp(self):
        self.svc = setup_service()

    def test_experience_create_api(self):
        r = self.svc.companion_experience_create(
            source="vision", modalities=["vision"],
            meaning="任务清单", confidence=0.9, impact="任务参考",
        )
        self.assertTrue(r["id"].startswith("mexp_"))
        self.assertEqual(r["provenance"]["origin"], "vision")

    def test_experience_create_invalid(self):
        with self.assertRaises(Exception):
            self.svc.companion_experience_create(
                source="vision", modalities=[], meaning="m",
            )

    def test_experience_provenance_gate(self):
        """网关批准的经历可追溯"""
        c = make_verified_candidate(self.svc)
        gate = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(gate["status"], "approved")
        prov = self.svc.companion_experience_provenance(
            gate["stored"]["id"],
        )
        self.assertTrue(prov["traceable"])
        self.assertEqual(prov["provenance"]["approved_by"],
                         "memory_gate")

    def test_experience_provenance_not_found(self):
        r = self.svc.companion_experience_provenance("exp_none")
        self.assertEqual(r["status"], "NOT_FOUND")

    def test_multimodal_event_api(self):
        r = self.svc.companion_multimodal_event_create(
            source="vision", meaning="感知事件", impact="参考",
        )
        self.assertIn("event_id", r)
        self.assertEqual(r["type"], "multimodal_perception")

    def test_multimodal_event_tracked(self):
        self.svc.companion_multimodal_event_create(
            source="vision", meaning="感知事件",
        )
        eng = self.svc.companion_continuity_engine
        st = eng.tracker.stats()
        self.assertGreaterEqual(st["by_type"].get(
            "multimodal_perception", 0), 1)


class TestGrowthEmotionLoop(unittest.TestCase):
    """感知-成长闭环"""

    def setUp(self):
        self.svc = setup_service()

    def test_approved_triggers_multimodal_event(self):
        before = self.svc.companion_continuity_engine.tracker.stats()[
            "by_type"].get("multimodal_perception", 0)
        c = make_verified_candidate(self.svc)
        self.svc.companion_perception_memory_gate(c["candidate_id"])
        after = self.svc.companion_continuity_engine.tracker.stats()[
            "by_type"].get("multimodal_perception", 0)
        self.assertGreater(after, before)

    def test_approved_updates_emotion(self):
        em_before = self.svc.companion_emotion()
        c = make_verified_candidate(self.svc)
        self.svc.companion_perception_memory_gate(c["candidate_id"])
        em_after = self.svc.companion_emotion()
        # 经 Meaning (任务关键词) → 温和积极
        self.assertGreaterEqual(em_after["positivity"],
                                em_before["positivity"])

    def test_rejected_no_emotion_change(self):
        em_before = self.svc.companion_emotion()
        ev = self.svc.companion_perception_receive(
            source="mock", content={"kind": "ocr", "text": "噪声"},
            confidence=0.6,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "rejected")
        em_after = self.svc.companion_emotion()
        self.assertEqual(em_before["positivity"],
                         em_after["positivity"])

    def test_emotion_not_direct_perception(self):
        """感知事件本身不改情绪 (只经批准后 meaning)"""
        em_before = self.svc.companion_emotion()
        make_verified_candidate(self.svc)  # 只验证不批准
        em_after = self.svc.companion_emotion()
        self.assertEqual(em_before, em_after)

    def test_perception_stats_api(self):
        make_verified_candidate(self.svc)
        st = self.svc.companion_perception_cognitive_stats()
        self.assertIn("perception", st)
        self.assertIn("memory_gate", st)
        self.assertIn("reflection", st)
        self.assertIn("counterfactual", st)


class TestSnapshotPerceptionStats(unittest.TestCase):
    """快照 perception_stats 域"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v640_")
        self.path = os.path.join(self.tmp, "s.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_snapshot_domain_included(self):
        from backend.embodied.companion.persistence import (
            SNAPSHOT_DOMAINS,
        )
        self.assertIn("perception_stats", SNAPSHOT_DOMAINS)

    def test_save_load_perception_stats(self):
        svc = setup_service()
        make_verified_candidate(svc)
        svc.companion_perception_memory_gate(
            make_verified_candidate(svc)["candidate_id"],
        )
        svc.companion_persistence_save(self.path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(self.path)
        self.assertIn("perception_stats", res["activated"])

    def test_old_snapshot_compat(self):
        """旧快照无 perception_stats → 兼容"""
        svc = setup_service()
        svc.companion_persistence_save(self.path)
        import json
        from backend.embodied.companion.persistence import (
            CompanionSnapshot,
        )
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
        state = data["data"]["state"]
        if "perception_stats" in state:
            del state["perception_stats"]
        snap = CompanionSnapshot()
        rebuilt = snap.build(state)
        rebuilt["snapshot_id"] = data["data"]["snapshot_id"]
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "schema_version": "6.3.0", "type": "snapshot",
                "timestamp": 1.0, "data": rebuilt,
            }, ensure_ascii=False) + "\n")
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(self.path)
        self.assertTrue(res["success"])
        self.assertNotIn("perception_stats", res["activated"])


class TestBackwardCompat(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_v63_memory_gate_api(self):
        c = make_verified_candidate(self.svc)
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertIn(r["status"], ("approved", "rejected"))

    def test_v63_pipeline_api(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        self.assertEqual(r["mode"], "rule_based")

    def test_v62_expression_api(self):
        r = self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_v611_emotion_api(self):
        self.svc.companion_emotion_adjust("success")
        self.assertIn("positivity", self.svc.companion_emotion())

    def test_v60_persistence_api(self):
        svc = setup_service()
        tmp = tempfile.mkdtemp(prefix="yhlz_bc64_")
        path = os.path.join(tmp, "s.jsonl")
        svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(path)
        self.assertTrue(res["success"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_v59_creative_api(self):
        r = self.svc.companion_creative_run()
        self.assertIn("summary", r)

    def test_v50_handle_api(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_version_6_4_0(self):
        self.assertEqual(self.svc.companion.status()["version"],
                         "9.5.0")

    def test_growth_report_works(self):
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")


class TestSecurityV640(unittest.TestCase):
    """V6.4 安全"""

    def setUp(self):
        self.svc = setup_service()

    def test_reflection_not_decision_maker(self):
        """反思评估不写入经历 (Advisor 非 Authority)"""
        before = self.svc.companion_experience.stats()["total"]
        c = make_verified_candidate(self.svc)
        self.svc.companion_reflection_evaluate(c)
        after = self.svc.companion_experience.stats()["total"]
        self.assertEqual(before, after)

    def test_counterfactual_not_decision_maker(self):
        before = self.svc.companion_experience.stats()["total"]
        c = make_verified_candidate(self.svc, summary="支付成功")
        self.svc.companion_counterfactual_check(c)
        after = self.svc.companion_experience.stats()["total"]
        self.assertEqual(before, after)

    def test_personality_stable(self):
        p_before = self.svc.companion_personality()
        c = make_verified_candidate(self.svc)
        self.svc.companion_perception_memory_gate(c["candidate_id"])
        self.svc.companion_reflection_evaluate(c)
        p_after = self.svc.companion_personality()
        self.assertEqual(p_before["base"], p_after["base"])

    def test_provenance_required_for_trace(self):
        """非感知经历 provenance 为空 → 不可追溯提示"""
        rec = self.svc.companion_experience.store_from_event(
            success=True, trigger="普通经历",
        )
        prov = self.svc.companion_experience_provenance(rec["id"])
        self.assertFalse(prov["traceable"])


if __name__ == "__main__":
    unittest.main()
