"""
YHLZ Embodied AI V6.4 - 认知集成补充测试 3 (V6.4 Extra3)

覆盖 (专项补足至 ≥300):
    - Service 边界
    - 网关/反思/反事实交叉
    - 经验对象边界
    - 统计细节
"""
import unittest

from backend.embodied.companion.experience import (
    MultimodalExperience,
    Provenance,
)
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


class TestRuleCross(unittest.TestCase):
    """规则交叉"""

    def test_approval_with_low_reflection(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.1)
        self.assertLess(r["final_score"], 0.6)

    def test_approval_with_high_reflection(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.95)
        self.assertGreaterEqual(r["final_score"], 0.6)

    def test_reflection_score_matches_dimension(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=0.8)
        dim = next(d for d in r["dimensions"]
                   if d["name"] == "reflection")
        self.assertEqual(dim["score"], r["reflection_score"])

    def test_rules_dimension_scores(self):
        rules = ReflectionRules()
        r = rules.evaluate(make_candidate())
        self.assertEqual(len(r["dimensions"]), 5)

    def test_rules_reason_contains_dims(self):
        rules = ReflectionRules()
        r = rules.evaluate(make_candidate())
        self.assertIn("来源", r["reason"])

    def test_rules_threshold_used_by_evaluator(self):
        e = ReflectionEvaluator(
            rules=ReflectionRules(threshold=0.9),
        )
        r = e.evaluate(make_candidate())
        self.assertEqual(r["recommendation"], "reject")


class TestGateCross(unittest.TestCase):
    """网关交叉"""

    def test_gate_approval_dimension_reflection(self):
        g = MemoryGate()
        r = g.process(make_candidate(), store_fn=lambda c: {})
        approval_step = next(s for s in r["steps"]
                             if s["step"] == "approval")
        self.assertTrue(approval_step["ok"])

    def test_gate_with_high_reflection_threshold(self):
        g = MemoryGate()
        g._evaluator = ReflectionEvaluator(
            rules=ReflectionRules(threshold=0.95),
        )
        r = g.process(make_candidate(), store_fn=lambda c: {})
        self.assertEqual(r["status"], "rejected")

    def test_gate_counterfactual_disabled_still_approves(self):
        g = MemoryGate()
        g._counterfactual = CounterfactualCheck(enabled=False)
        r = g.process(make_candidate(),
                      store_fn=lambda c: {})
        self.assertEqual(r["status"], "approved")

    def test_gate_unicode_high_stake(self):
        g = MemoryGate()
        r = g.process(make_candidate(summary="用户要求删除备份"),
                      store_fn=lambda c: {})
        self.assertEqual(r["status"], "rejected")

    def test_gate_stats_steps_consistent(self):
        g = MemoryGate()
        g.process(make_candidate(), store_fn=lambda c: {})
        g.process(make_candidate(summary="支付成功"),
                  store_fn=lambda c: {})
        st = g.stats()
        self.assertEqual(st["approved_count"], 1)
        self.assertEqual(st["rejected_count"], 1)


class TestServiceBoundary(unittest.TestCase):
    """Service 边界"""

    def test_reflection_evaluate_invalid_candidate(self):
        svc = setup_service()
        with self.assertRaises(Exception):
            svc.companion_reflection_evaluate(None)

    def test_counterfactual_any_dict(self):
        svc = setup_service()
        r = svc.companion_counterfactual_check(
            {"summary": "x", "confidence": 0.9},
        )
        self.assertEqual(r["status"], "holds")

    def test_experience_create_text(self):
        svc = setup_service()
        r = svc.companion_experience_create(
            source="text", modalities=["text"],
            meaning="用户文本", confidence=0.8,
        )
        self.assertEqual(r["source"], "text")

    def test_experience_create_audio(self):
        svc = setup_service()
        r = svc.companion_experience_create(
            source="audio", modalities=["audio"],
            meaning="语音", confidence=0.7,
        )
        self.assertEqual(r["modalities"], ["audio"])

    def test_multimodal_event_variants(self):
        svc = setup_service()
        for src in ("vision", "audio", "text"):
            r = svc.companion_multimodal_event_create(
                source=src, meaning=f"{src}事件",
            )
            self.assertEqual(r["meta"]["source"], src)

    def test_perception_stats_empty(self):
        svc = setup_service()
        st = svc.companion_perception_cognitive_stats()
        self.assertEqual(st["perception"]["event_count"], 0)
        self.assertEqual(st["memory_gate"]["candidate_count"], 0)

    def test_gate_after_stats(self):
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
        self.assertGreaterEqual(st["memory_gate"]["approved_count"],
                                1)


class TestProvenanceMore(unittest.TestCase):
    """来源链补充"""

    def test_prov_roundtrip(self):
        p = Provenance.create(**{
            "origin": "vision", "source_event": "pe_x",
            "verification_score": 0.8,
            "reflection_reason": "评估通过",
            "approved_by": "reflection",
        })
        d = p.to_dict()
        p2 = Provenance(
            provenance_id=d["provenance_id"],
            origin=d["origin"], source_event=d["source_event"],
            verification_score=d["verification_score"],
            reflection_reason=d["reflection_reason"],
            approved_by=d["approved_by"],
            timestamp=d["timestamp"],
        )
        ok, reason = p2.validate()
        self.assertTrue(ok)

    def test_prov_reflection_approver(self):
        p = Provenance.create(**{
            "origin": "text", "approved_by": "reflection",
        })
        self.assertEqual(p.approved_by, "reflection")

    def test_prov_user_approver(self):
        p = Provenance.create(**{
            "origin": "text", "approved_by": "user",
        })
        ok, reason = p.validate()
        self.assertTrue(ok)


class TestMultimodalMore(unittest.TestCase):
    """多模态对象补充"""

    def test_mexp_all_sources(self):
        for src in ("vision", "audio", "text", "interaction",
                    "creative", "reflection", "memory_gate"):
            e = MultimodalExperience.create(
                source=src, modalities=["vision" if src in (
                    "vision", "memory_gate") else "text"],
                meaning="m", confidence=0.8,
                provenance={"origin": src},
            )
            ok, reason = e.validate()
            self.assertTrue(ok, src)

    def test_mexp_provenance_required_field(self):
        with self.assertRaises(Exception):
            MultimodalExperience.create(
                source="vision", modalities=["vision"],
                meaning="m", confidence=0.8,
            )

    def test_mexp_multi_modalities_valid(self):
        e = MultimodalExperience.create(
            source="interaction", modalities=[
                "vision", "audio", "text", "interaction",
            ],
            meaning="m", confidence=0.8,
            provenance={"origin": "interaction"},
        )
        self.assertEqual(len(e.modalities), 4)


class TestStatsDetail(unittest.TestCase):
    """统计细节"""

    def test_evaluator_stats_empty(self):
        e = ReflectionEvaluator()
        st = e.stats()
        self.assertEqual(st["evaluated_count"], 0)
        self.assertEqual(st["avg_reflection_score"], 0.0)

    def test_counterfactual_stats_empty(self):
        st = CounterfactualCheck().stats()
        self.assertEqual(st["check_count"], 0)

    def test_gate_stats_empty(self):
        st = MemoryGate().stats()
        self.assertEqual(st["candidate_count"], 0)

    def test_all_stats_modes(self):
        self.assertEqual(
            ReflectionEvaluator().stats()["mode"], "rule_based")
        self.assertEqual(
            CounterfactualCheck().stats()["mode"], "rule_based")
        self.assertEqual(
            MemoryGate().stats()["mode"], "rule_based")
        self.assertEqual(
            ReflectionRules().stats()["mode"], "rule_based")


class TestServiceFull(unittest.TestCase):
    """Service 全流程边界"""

    def setUp(self):
        self.svc = setup_service()

    def test_flow_then_all_apis(self):
        ev = self.svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        self.svc.companion_reflection_evaluate(c)
        self.svc.companion_counterfactual_check(c)
        gate = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(gate["status"], "approved")
        prov = self.svc.companion_experience_provenance(
            gate["stored"]["id"],
        )
        self.assertTrue(prov["traceable"])

    def test_provenance_after_gate_has_reason(self):
        ev = self.svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        gate = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        prov = self.svc.companion_experience_provenance(
            gate["stored"]["id"],
        )
        self.assertEqual(prov["provenance"]["approved_by"],
                         "memory_gate")
        self.assertIn("记忆网关", prov["provenance"][
            "reflection_reason"])

    def test_growth_report_includes_events(self):
        self.svc.companion_multimodal_event_create(
            source="vision", meaning="感知",
        )
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")


class TestFinalEdges(unittest.TestCase):
    """最终边界"""

    def test_version_6_4_0(self):
        self.assertEqual(
            setup_service().companion.status()["version"], "9.5.0",
        )

    def test_handle_compat(self):
        r = setup_service().companion_handle(
            {"text": "扫描环境查看策略建议"},
        )
        self.assertIn("rhythm", r)

    def test_emotion_compat(self):
        svc = setup_service()
        svc.companion_emotion_adjust("success")
        self.assertIn("positivity", svc.companion_emotion())

    def test_persistence_compat(self):
        import os
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="yhlz_e64_")
        path = os.path.join(tmp, "s.jsonl")
        svc = setup_service()
        svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(path)
        self.assertTrue(res["success"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_all_audits_mode(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        svc.companion_reflection_evaluate(c)
        r = svc.companion_perception_cognitive_stats()
        self.assertEqual(r["mode"], "rule_based")

    def test_cognitive_stats_counterfactual(self):
        svc = setup_service()
        c = make_candidate(summary="支付成功")
        svc.companion_counterfactual_check(c)
        r = svc.companion_perception_cognitive_stats()
        self.assertGreaterEqual(r["counterfactual"]["check_count"],
                                1)


if __name__ == "__main__":
    unittest.main()
