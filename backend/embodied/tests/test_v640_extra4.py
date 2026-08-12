"""
YHLZ Embodied AI V6.4 - 认知集成补充测试 4 (V6.4 Extra4)

覆盖 (专项补足至 ≥300):
    - Service 组合边界
    - 单元边界补足
"""
import unittest

from backend.embodied.companion.perception import (
    ApprovalRule,
    CounterfactualCheck,
    MemoryGate,
    ReflectionEvaluator,
    ReflectionRules,
)
from backend.embodied.service import EmbodiedService


def setup_service(**extra):
    cfg = {
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


def make_candidate(**over):
    c = {
        "candidate_id": "mc_1",
        "source": "camera",
        "kind": "ocr",
        "summary": "用户屏幕显示重要任务清单",
        "confidence": 0.9,
        "occurrence_count": 1,
    }
    c.update(over)
    return c


class TestUnitCompletes(unittest.TestCase):
    """单元补足"""

    def test_approval_reflection_dimension_count(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.5)
        self.assertEqual(len(r["dimensions"]), 6)

    def test_approval_no_reflection_dimension_count(self):
        r = ApprovalRule().evaluate(make_candidate())
        self.assertEqual(len(r["dimensions"]), 5)

    def test_approval_final_score_range(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.5)
        self.assertGreaterEqual(r["final_score"], 0.0)
        self.assertLessEqual(r["final_score"], 1.0)

    def test_approval_reflection_reason(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.6)
        dim = next(d for d in r["dimensions"]
                   if d["name"] == "reflection")
        self.assertIn("反思评估评分", dim["reason"])

    def test_rules_credibility_unknown_source(self):
        d = ReflectionRules()._credibility(make_candidate(
            source="alien", confidence=0.5,
        ))
        self.assertEqual(d["score"], 0.4)

    def test_rules_consistency_multi_known(self):
        d = ReflectionRules()._consistency(
            make_candidate(),
            [{"trigger": "环境扫描", "lesson": "l"},
             {"trigger": "拾取物体", "lesson": "l"}],
        )
        self.assertEqual(d["score"], 0.8)

    def test_rules_value_confidence_effect(self):
        r1 = ReflectionRules()._long_term_value(make_candidate(
            summary="重要任务", confidence=1.0,
        ))
        r2 = ReflectionRules()._long_term_value(make_candidate(
            summary="重要任务", confidence=0.0,
        ))
        self.assertGreaterEqual(r1["score"], r2["score"])
        self.assertGreater(r1["score"], r2["score"] + 0.1)

    def test_rules_pattern_short_trigger(self):
        p = ReflectionRules()._find_pattern(
            make_candidate(summary="任务清单"),
            [{"trigger": "任务清", "lesson": "l"}],
        )
        self.assertIn("相似", p)

    def test_evaluator_known_impact(self):
        """已有相似经历 → 一致性矛盾 → 建议拒绝"""
        e = ReflectionEvaluator()
        r = e.evaluate(
            make_candidate(),
            [{"trigger": "用户屏幕显示重要", "lesson": "l"}],
        )
        self.assertEqual(r["recommendation"], "reject")

    def test_evaluator_clean_approve(self):
        e = ReflectionEvaluator()
        r = e.evaluate(
            make_candidate(),
            [{"trigger": "环境扫描", "lesson": "l"}],
        )
        self.assertEqual(r["recommendation"], "approve")

    def test_counterfactual_stake_no_risk_word(self):
        """无风险词 + 低置信 → fails (置信度规则)"""
        r = CounterfactualCheck().check(make_candidate(
            confidence=0.2,
        ))
        self.assertEqual(r["status"], "fails")

    def test_counterfactual_repeat_any_content(self):
        r = CounterfactualCheck().check(make_candidate(
            occurrence_count=3, confidence=0.1,
        ))
        self.assertEqual(r["status"], "holds")

    def test_counterfactual_neutral_disabled(self):
        c = CounterfactualCheck(enabled=False)
        r = c.check(make_candidate(summary="支付成功"))
        self.assertEqual(r["status"], "neutral")

    def test_gate_known_duplicate_rejected(self):
        """已有相同经历 → 拒绝 (防重复记忆)"""
        g = MemoryGate()
        r = g.process(make_candidate(),
                      store_fn=lambda c: {},
                      reflect_fn=lambda c: [
                          {"trigger": "用户屏幕显示重要",
                           "lesson": "l"},
                      ])
        self.assertEqual(r["status"], "rejected")

    def test_gate_no_known_approved(self):
        g = MemoryGate()
        r = g.process(make_candidate(),
                      store_fn=lambda c: {},
                      reflect_fn=lambda c: [
                          {"trigger": "环境扫描", "lesson": "l"},
                      ])
        self.assertEqual(r["status"], "approved")

    def test_gate_reflection_stdout(self):
        """默认 evaluator 正常集成"""
        g = MemoryGate()
        r = g.process(make_candidate(), store_fn=lambda c: {})
        self.assertEqual(r["status"], "approved")


class TestServiceCompletes(unittest.TestCase):
    """Service 补足"""

    def test_cognitive_stats_full_sections(self):
        svc = setup_service()
        st = svc.companion_perception_cognitive_stats()
        for key in ("perception", "memory_gate", "reflection",
                    "counterfactual"):
            self.assertIn(key, st)

    def test_cognitive_stats_after_flow(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        svc.companion_perception_memory_gate(c["candidate_id"])
        st = svc.companion_perception_cognitive_stats()
        self.assertGreaterEqual(st["perception"]["event_count"], 1)
        self.assertGreaterEqual(st["memory_gate"]["approved_count"],
                                1)
        self.assertGreaterEqual(st["reflection"]["evaluated_count"],
                                1)

    def test_reflection_recommendation_reject_blocks_gate(self):
        svc = setup_service(reflection_score_threshold=0.99)
        ev = svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        r = svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "rejected")

    def test_multimodal_event_after_gate(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        svc.companion_perception_memory_gate(c["candidate_id"])
        r = svc.companion_multimodal_event_create(
            source="vision", meaning="闭环后事件",
        )
        self.assertEqual(r["type"], "multimodal_perception")

    def test_provenance_origin_variants(self):
        svc = setup_service()
        for src in ("vision", "audio", "text"):
            r = svc.companion_experience_create(
                source=src, modalities=[src], meaning="m",
                confidence=0.8,
            )
            self.assertEqual(r["provenance"]["origin"], src)

    def test_provenance_gate_chain(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        gate = svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        prov = svc.companion_experience_provenance(
            gate["stored"]["id"],
        )
        p = prov["provenance"]
        self.assertEqual(p["origin"], "vision")
        self.assertEqual(p["approved_by"], "memory_gate")
        self.assertGreaterEqual(p["verification_score"], 0.5)

    def test_handle_still_has_rhythm(self):
        r = setup_service().companion_handle(
            {"text": "扫描环境查看策略建议"},
        )
        self.assertIn("rhythm", r)

    def test_expression_after_cognitive_flow(self):
        svc = setup_service()
        r = svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_emotion_after_cognitive_flow(self):
        svc = setup_service()
        self.svc = svc
        self.svc.companion_emotion_adjust("success")
        self.assertGreater(self.svc.companion_emotion()["positivity"],
                           0.6)

    def test_version(self):
        self.assertEqual(setup_service().companion.status()["version"],
                         "9.5.0")


class TestCompatFinal(unittest.TestCase):
    """兼容收尾"""

    def test_v63_stats_api_intact(self):
        """V6.2/6.3 的 companion_perception_stats 结构不变"""
        svc = setup_service()
        st = svc.companion_perception_stats()
        for key in ("event_count", "verification", "permission",
                    "manager"):
            self.assertIn(key, st)

    def test_v63_gate_api_intact(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        r = svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "approved")

    def test_v63_pipeline_intact(self):
        r = setup_service().companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        self.assertEqual(r["mode"], "rule_based")

    def test_v60_persistence_intact(self):
        import os
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="yhlz_f64_")
        path = os.path.join(tmp, "s.jsonl")
        svc = setup_service()
        svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(path)
        self.assertTrue(res["success"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_v59_creative_intact(self):
        r = setup_service().companion_creative_run()
        self.assertIn("summary", r)

    def test_v58_reflection_intact(self):
        r = setup_service().companion_reflection()
        self.assertEqual(r["mode"], "rule_based")

    def test_v55_personality_intact(self):
        p = setup_service().companion_personality()
        self.assertIn("base", p)


class TestSnapshotFinal(unittest.TestCase):
    """快照收尾"""

    def test_snapshot_domains_eleven(self):
        from backend.embodied.companion.persistence import (
            SNAPSHOT_DOMAINS,
        )
        self.assertIn("perception_stats", SNAPSHOT_DOMAINS)

    def test_restore_keeps_personality(self):
        svc = setup_service()
        import os
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="yhlz_sp64_")
        path = os.path.join(tmp, "s.jsonl")
        svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        svc2.companion_persistence_load(path)
        self.assertEqual(svc2.companion_personality()["base"],
                         "铁哥们")
        shutil.rmtree(tmp, ignore_errors=True)


class TestFinalCounts(unittest.TestCase):
    """最终统计补足"""

    def test_approval_reflection_6dim_mode(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.5)
        self.assertEqual(r["mode"], "rule_based")

    def test_approval_reflection_roundtrip(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.75)
        self.assertEqual(r["reflection_score"], 0.75)

    def test_rules_value_clamp(self):
        d = ReflectionRules()._long_term_value(make_candidate(
            summary="重要目标任务计划清单", confidence=1.0,
        ))
        self.assertLessEqual(d["score"], 1.0)

    def test_rules_value_none_confidence(self):
        d = ReflectionRules()._long_term_value(make_candidate(
            summary="重要任务", confidence=None,
        ))
        self.assertGreaterEqual(d["score"], 0.7)

    def test_counterfactual_check_id(self):
        r = CounterfactualCheck().check(make_candidate())
        self.assertTrue(r["check_id"].startswith("cc_"))

    def test_counterfactual_checked_at(self):
        r = CounterfactualCheck().check(make_candidate())
        self.assertGreater(r["checked_at"], 0.0)

    def test_gate_processed_at(self):
        g = MemoryGate()
        r = g.process(make_candidate(), store_fn=lambda c: {})
        self.assertGreater(r["processed_at"], 0.0)

    def test_evaluator_evaluated_at(self):
        e = ReflectionEvaluator()
        r = e.evaluate(make_candidate())
        self.assertGreater(r["evaluated_at"], 0.0)

    def test_service_cognitive_mode(self):
        st = setup_service().companion_perception_cognitive_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_service_v62_stats_mode(self):
        st = setup_service().companion_perception_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_multimodal_event_meta_impact(self):
        svc = setup_service()
        r = svc.companion_multimodal_event_create(
            source="vision", meaning="m", impact="重要",
        )
        self.assertEqual(r["meta"]["impact"], "重要")

    def test_experience_provenance_timestamp(self):
        svc = setup_service()
        r = svc.companion_experience_create(
            source="vision", modalities=["vision"],
            meaning="m", confidence=0.9,
        )
        self.assertGreater(r["provenance"]["timestamp"], 0.0)

    def test_all_growth_metrics_after_loop(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        svc.companion_perception_memory_gate(c["candidate_id"])
        eng = svc.companion_continuity_engine
        m = eng.growth_metrics()
        self.assertIn("by_type", m)

    def test_identity_fingerprint_stable(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        eng = svc.companion_continuity_engine
        fp = eng.status()["fingerprint"]
        self.assertEqual(len(fp), 16)

    def test_version_final(self):
        self.assertEqual(
            setup_service().companion.status()["version"], "9.5.0",
        )


if __name__ == "__main__":
    unittest.main()
