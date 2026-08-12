"""
YHLZ Embodied AI V6.3 - 具身感知补充测试 (V6.3 Extra)

覆盖 (专项补足):
    - 模板检测: 更多边界 (无模板/错误模式/阈值边界)
    - 批准规则: 维度细节/组合
    - 网关: 历史/统计/回调
    - 管道: 路由表/帧边界
"""
import unittest

from backend.embodied.companion.perception import (
    AgentPipelineAdapter,
    ApprovalRule,
    CandidateValidator,
    MemoryGate,
    PerceptionFrame,
    PerceptionRouter,
    TemplateDetectorAdapter,
    TesseractOCRAdapter,
)

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


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


class TestTemplateMore(unittest.TestCase):
    """模板检测补充"""

    def test_threshold_validation(self):
        a = TemplateDetectorAdapter()
        self.assertEqual(a._threshold, 0.7)

    def test_available_no_cv2(self):
        a = TemplateDetectorAdapter(templates={"x": "d"})
        if a._cv2 is None:
            self.assertFalse(a.is_available())
        else:
            self.assertTrue(a.is_available())

    def test_info_templates_list(self):
        a = TemplateDetectorAdapter(templates={"a": 1, "b": 2})
        info = a.get_info()
        self.assertEqual(set(info["templates"]), {"a", "b"})

    def test_info_threshold(self):
        a = TemplateDetectorAdapter(match_threshold=0.8)
        self.assertEqual(a.get_info()["match_threshold"], 0.8)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_confidence_one_exact(self):
        """精确匹配 → confidence ≈ 1.0"""
        scene = np.zeros((100, 100), dtype=np.uint8)
        cv2.rectangle(scene, (10, 10), (59, 59), 255, -1)
        tpl = scene[10:60, 10:60].copy()
        a = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.9,
        )
        r = a.detect(scene)
        self.assertAlmostEqual(r.objects[0]["confidence"], 1.0,
                               delta=0.01)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_bbox_correct(self):
        scene = np.zeros((100, 100), dtype=np.uint8)
        cv2.rectangle(scene, (10, 10), (59, 59), 255, -1)
        tpl = scene[10:60, 10:60].copy()
        a = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.9,
        )
        r = a.detect(scene)
        bbox = r.objects[0]["bbox"]
        self.assertEqual(bbox[0], 10)
        self.assertEqual(bbox[1], 10)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_empty_template_skip(self):
        scene = np.zeros((50, 50), dtype=np.uint8)
        a = TemplateDetectorAdapter(templates={})
        self.assertFalse(a.is_available())


class TestApprovalMore(unittest.TestCase):
    """批准规则补充"""

    def test_source_trust_table(self):
        r = ApprovalRule()
        for src, score in [("camera", 0.9), ("screen", 0.8),
                           ("mock", 0.5)]:
            d = r._source_trust(make_candidate(source=src))
            self.assertEqual(d["score"], score, src)

    def test_repetition_two(self):
        d = ApprovalRule()._repetition(
            make_candidate(occurrence_count=2),
        )
        self.assertEqual(d["score"], 0.6)

    def test_repetition_zero_default(self):
        d = ApprovalRule()._repetition(
            make_candidate(occurrence_count=0),
        )
        self.assertEqual(d["score"], 0.8)

    def test_value_high_confidence(self):
        d = ApprovalRule()._long_term_value(
            make_candidate(confidence=1.0,
                           summary="任务"),
        )
        self.assertGreaterEqual(d["score"], 0.7)

    def test_value_low_confidence(self):
        d = ApprovalRule()._long_term_value(
            make_candidate(confidence=0.0, summary="x"),
        )
        self.assertEqual(d["score"], 0.4)

    def test_identity_no_keyword(self):
        d = ApprovalRule()._identity_impact(
            make_candidate(summary="普通内容"),
        )
        self.assertEqual(d["score"], 0.5)

    def test_risk_no_keyword(self):
        d = ApprovalRule()._risk(make_candidate(summary="安全内容"))
        self.assertEqual(d["score"], 0.2)

    def test_risk_blocks_even_high_value(self):
        """高风险即使高价值也拒绝"""
        r = ApprovalRule().evaluate(make_candidate(
            summary="重要任务: 删除数据库备份",
        ))
        self.assertEqual(r["status"], "rejected")

    def test_approved_reason_text(self):
        r = ApprovalRule().evaluate(make_candidate())
        self.assertIn("批准阈值", r["reason"])

    def test_rejected_reason_text(self):
        r = ApprovalRule().evaluate(make_candidate(
            source="mock", summary="x", confidence=0.2,
        ))
        self.assertIn("未达批准阈值", r["reason"])

    def test_unknown_source_low_trust(self):
        r = ApprovalRule().evaluate(make_candidate(source="weird"))
        d = next(x for x in r["dimensions"]
                 if x["name"] == "source_trust")
        self.assertEqual(d["score"], 0.3)


class TestValidatorMore(unittest.TestCase):
    """候选校验补充"""

    def test_missing_each_field(self):
        v = CandidateValidator()
        for field in ("candidate_id", "source", "kind", "summary",
                      "confidence"):
            c = make_candidate()
            del c[field]
            ok, reason = v.validate(c)
            self.assertFalse(ok, field)
            self.assertIn(field, reason)

    def test_all_sources_valid(self):
        v = CandidateValidator()
        for src in ("vision", "camera", "screen", "mock",
                    "tesseract", "template"):
            ok, reason = v.validate(make_candidate(source=src))
            self.assertTrue(ok, src)

    def test_confidence_boundary(self):
        v = CandidateValidator()
        ok, _ = v.validate(make_candidate(confidence=0.0))
        self.assertTrue(ok)
        ok, _ = v.validate(make_candidate(confidence=1.0))
        self.assertTrue(ok)

    def test_negative_confidence(self):
        v = CandidateValidator()
        ok, reason = v.validate(make_candidate(confidence=-0.1))
        self.assertFalse(ok)

    def test_summary_boundary_length(self):
        v = CandidateValidator(max_summary_length=10)
        ok, _ = v.validate(make_candidate(summary="1234567890"))
        self.assertTrue(ok)
        ok, _ = v.validate(make_candidate(summary="12345678901"))
        self.assertFalse(ok)

    def test_stats_zero(self):
        v = CandidateValidator()
        st = v.stats()
        self.assertEqual(st["input_count"], 0)


class TestGateMore(unittest.TestCase):
    """网关补充"""

    def setUp(self):
        self.gate = MemoryGate()
        self.stored = []

        def store_fn(c):
            self.stored.append(c)
            return {"id": "exp_1"}

        self.store_fn = store_fn

    def test_gate_id_unique(self):
        r1 = self.gate.process(make_candidate(),
                               store_fn=self.store_fn)
        r2 = self.gate.process(make_candidate(
            candidate_id="mc_2"),
            store_fn=self.store_fn)
        self.assertNotEqual(r1["gate_id"], r2["gate_id"])

    def test_reflection_reason_in_steps(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn,
                              reflect_fn=lambda c: [])
        step = next(s for s in r["steps"]
                    if s["step"] == "reflection_evaluation")
        self.assertIn("反思评分", step["reason"])

    def test_reflection_exception_ok(self):
        def boom(c):
            raise RuntimeError("x")

        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn,
                              reflect_fn=boom)
        self.assertEqual(r["status"], "approved")  # 反思异常不阻塞

    def test_stats_by_status(self):
        self.gate.process(make_candidate(), store_fn=self.store_fn)
        self.gate.process(make_candidate(
            source="mock", summary="x", confidence=0.2,
        ), store_fn=self.store_fn)
        st = self.gate.stats()
        self.assertIn("approved", st["by_status"])
        self.assertIn("rejected", st["by_status"])

    def test_stats_thresholds(self):
        st = self.gate.stats()
        self.assertEqual(st["thresholds"]["approve_threshold"], 0.6)

    def test_history_reverse_order(self):
        self.gate.process(make_candidate(candidate_id="mc_a"),
                          store_fn=self.store_fn)
        self.gate.process(make_candidate(candidate_id="mc_b"),
                          store_fn=self.store_fn)
        h = self.gate.history()
        self.assertEqual(h[0]["candidate_id"], "mc_b")

    def test_clear_resets_stats(self):
        self.gate.process(make_candidate(), store_fn=self.store_fn)
        self.gate.clear()
        self.assertEqual(self.gate.stats()["candidate_count"], 0)

    def test_processed_at(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        self.assertGreater(r["processed_at"], 0.0)


class TestPipelineMore(unittest.TestCase):
    """管道补充"""

    def test_frame_audio_route(self):
        r = PerceptionRouter().route(PerceptionFrame.create(
            content={"kind": "audio"}, ftype="audio",
            verified=True,
        ))
        self.assertEqual(r["target"], "audio_agent")

    def test_frame_unknown_kind_default(self):
        r = PerceptionRouter().route(PerceptionFrame.create(
            content={"kind": "weird"}, verified=True,
        ))
        self.assertEqual(r["target"], "perception_agent")

    def test_route_table_vision(self):
        self.assertIn("vision", PerceptionRouter().stats()[
            "route_table"])

    def test_route_reason_contains_target(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        r = PerceptionRouter().route(f)
        self.assertIn("perception_agent", r["reason"])

    def test_pipeline_ingest_timestamp(self):
        a = AgentPipelineAdapter()
        f = PerceptionFrame.create(content={}, verified=True)
        r = a.ingest(f)
        self.assertGreater(r["agent_input"]["observed_at"], 0.0)

    def test_pipeline_stats_router(self):
        a = AgentPipelineAdapter()
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        a.ingest(f)
        st = a.stats()
        self.assertEqual(st["router"]["route_count"], 1)

    def test_frame_to_dict_roundtrip(self):
        f = PerceptionFrame.create(
            content={"kind": "ocr", "text": "hi"},
            meaning="m", verified=True,
        )
        d = f.to_dict()
        self.assertEqual(d["content"]["text"], "hi")
        self.assertEqual(d["meaning"], "m")

    def test_frame_meaning_long(self):
        f = PerceptionFrame.create(content={}, meaning="长" * 500)
        self.assertEqual(len(f.meaning), 500)


class TestTesseractMore(unittest.TestCase):
    """Tesseract 补充"""

    def test_available_state_consistent(self):
        """is_available 与内部 _available 一致"""
        a = TesseractOCRAdapter()
        self.assertEqual(a.is_available(), a._available)

    def test_source_attr(self):
        a = TesseractOCRAdapter()
        self.assertEqual(a.source, "tesseract")

    def test_get_info_name(self):
        a = TesseractOCRAdapter()
        self.assertEqual(a.get_info()["name"], "tesseract_ocr")

    def test_detect_returns_empty(self):
        a = TesseractOCRAdapter()
        r = a.detect(image="dummy")
        self.assertEqual(r.objects, [])


if __name__ == "__main__":
    unittest.main()
