"""
YHLZ Embodied AI V6.4 - 认知集成补充测试 2 (V6.4 Extra2)

覆盖 (专项补足至 ≥300):
    - Service 组合场景
    - 配置驱动
    - 边界补足
"""
import os
import shutil
import tempfile
import unittest

from backend.embodied.companion.perception import (
    ApprovalRule,
    CounterfactualCheck,
    MemoryGate,
    ReflectionEvaluator,
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


class TestConfigDriven(unittest.TestCase):
    """配置驱动"""

    def test_reflection_threshold_config(self):
        svc = setup_service(reflection_score_threshold=0.8)
        ev = svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        r = svc.companion_reflection_evaluate(c)
        # 评分 ~0.65 < 0.8 → reject 建议
        self.assertEqual(r["recommendation"], "reject")

    def test_counterfactual_disabled_config(self):
        svc = setup_service(counterfactual_enabled=False)
        c = make_candidate(summary="支付成功")
        r = svc.companion_counterfactual_check(c)
        self.assertEqual(r["status"], "neutral")

    def test_nms_config_default(self):
        from backend.embodied.companion.perception import (
            TemplateDetectorAdapter,
        )
        a = TemplateDetectorAdapter()
        self.assertTrue(a._nms_enabled)

    def test_multimodal_experience_enabled_config(self):
        svc = setup_service(multimodal_experience_enabled=False)
        # 配置保留 (对象创建仍可用, 开关语义为上层)
        r = svc.companion_experience_create(
            source="vision", modalities=["vision"],
            meaning="m", confidence=0.9,
        )
        self.assertTrue(r["id"].startswith("mexp_"))


class TestServiceScenarios(unittest.TestCase):
    """Service 组合场景"""

    def setUp(self):
        self.svc = setup_service()

    def test_full_cognitive_flow(self):
        """感知 → 验证 → 反思 → 反事实 → 批准 → 经历 → 成长"""
        ev = self.svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        ref = self.svc.companion_reflection_evaluate(c)
        self.assertEqual(ref["recommendation"], "approve")
        cf = self.svc.companion_counterfactual_check(c)
        self.assertEqual(cf["status"], "holds")
        gate = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(gate["status"], "approved")
        # 成长闭环
        eng = self.svc.companion_continuity_engine
        self.assertGreaterEqual(eng.tracker.stats()["by_type"].get(
            "multimodal_perception", 0), 1)

    def test_high_stake_blocked_chain(self):
        """高风险感知: 反思/反事实拒绝 → 不形成经验"""
        before = self.svc.companion_experience.stats()["total"]
        ev = self.svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "支付成功"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        gate = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(gate["status"], "rejected")
        self.assertEqual(
            self.svc.companion_experience.stats()["total"], before,
        )

    def test_multi_candidates_mixed_results(self):
        for summary in ("重要任务清单A", "支付成功", "随机噪声文本"):
            ev = self.svc.companion_perception_receive(
                source="camera" if "支付" not in summary else "mock",
                content={"kind": "ocr", "text": summary},
                confidence=0.9,
            )
            self.svc.companion_perception_verify(ev["event_id"])
        cands = self.svc.companion_perception_memory_candidates()
        statuses = [
            self.svc.companion_perception_memory_gate(
                c["candidate_id"],
            )["status"]
            for c in cands["candidates"]
        ]
        self.assertIn("approved", statuses)
        self.assertIn("rejected", statuses)

    def test_stats_all_sections(self):
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        st = self.svc.companion_perception_cognitive_stats()
        self.assertGreaterEqual(st["perception"]["event_count"], 1)
        self.assertIn("candidate_count", st["memory_gate"])
        self.assertIn("evaluated_count", st["reflection"])

    def test_growth_report_after_loop(self):
        ev = self.svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        self.svc.companion_perception_memory_gate(c["candidate_id"])
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")


class TestUnitEdges(unittest.TestCase):
    """单元边界"""

    def test_approval_reflection_invalid_type(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score="bad")
        self.assertEqual(r["reflection_score"], 0.5)

    def test_approval_reflection_nan(self):
        r = ApprovalRule().evaluate(make_candidate(),
                                    reflection_score=float("nan"))
        self.assertGreaterEqual(r["reflection_score"], 0.0)

    def test_counterfactual_occurrence_zero(self):
        """无重复证据 + 低置信 → fails"""
        r = CounterfactualCheck().check(make_candidate(
            occurrence_count=0, confidence=0.3,
        ))
        self.assertEqual(r["status"], "fails")

    def test_counterfactual_high_conf_repeat(self):
        r = CounterfactualCheck().check(make_candidate(
            occurrence_count=2, confidence=0.5,
        ))
        self.assertEqual(r["status"], "holds")

    def test_evaluator_unicode(self):
        e = ReflectionEvaluator()
        r = e.evaluate(make_candidate(summary="中文重要任务"))
        self.assertEqual(r["recommendation"], "approve")

    def test_gate_unicode_summary(self):
        g = MemoryGate()
        r = g.process(make_candidate(summary="中文任务清单"),
                      store_fn=lambda c: {})
        self.assertEqual(r["status"], "approved")

    def test_gate_counterfactual_neutral_ok(self):
        g = MemoryGate()
        g._counterfactual = CounterfactualCheck(enabled=False)
        r = g.process(make_candidate(), store_fn=lambda c: {})
        self.assertEqual(r["status"], "approved")

    def test_evaluator_disabled_gate_still_works(self):
        g = MemoryGate()
        g._evaluator = ReflectionEvaluator(enabled=False)
        r = g.process(make_candidate(), store_fn=lambda c: {})
        self.assertEqual(r["status"], "approved")


class TestSnapshotCompat(unittest.TestCase):
    """快照兼容细节"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_c64_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_roundtrip(self):
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
        path = os.path.join(self.tmp, "s.jsonl")
        svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(path)
        self.assertTrue(res["success"])
        self.assertIn("perception_stats", res["activated"])
        # 恢复后经历仍在
        self.assertGreaterEqual(
            svc2.companion_experience.stats()["total"], 1,
        )

    def test_restore_no_side_effects(self):
        """感知统计恢复无副作用 (不修改人格/情绪)"""
        svc = setup_service()
        path = os.path.join(self.tmp, "s.jsonl")
        svc.companion_persistence_save(path)
        em_before = svc.companion_emotion()
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        svc2.companion_persistence_load(path)
        em_after = svc2.companion_emotion()
        self.assertEqual(em_before["positivity"],
                         em_after["positivity"])


class TestMoreEdge(unittest.TestCase):
    """更多边界"""

    def test_version_api(self):
        self.assertEqual(
            setup_service().companion.status()["version"], "9.5.0",
        )

    def test_handle_still_works(self):
        r = setup_service().companion_handle(
            {"text": "扫描环境查看策略建议"},
        )
        self.assertIn("request_id", r)

    def test_expression_still_works(self):
        r = setup_service().companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_creative_still_works(self):
        r = setup_service().companion_creative_run()
        self.assertIn("summary", r)

    def test_multimodal_event_meaning(self):
        svc = setup_service()
        r = svc.companion_multimodal_event_create(
            source="vision", meaning="看到任务清单", impact="参考",
        )
        self.assertEqual(r["detail"], "看到任务清单")
        self.assertEqual(r["meta"]["source"], "vision")
        self.assertEqual(r["meta"]["impact"], "参考")

    def test_perception_stats_reflection_counts(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        svc.companion_reflection_evaluate(c)
        st = svc.companion_perception_cognitive_stats()
        self.assertGreaterEqual(st["reflection"]["evaluated_count"],
                                1)


if __name__ == "__main__":
    unittest.main()
