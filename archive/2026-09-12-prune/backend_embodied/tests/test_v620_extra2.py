"""
YHLZ Embodied AI V6.2 - 多模态交互与感知补充测试 2 (V6.2 Extra2)

覆盖 (专项补足至 ≥300):
    - 表达: 更多规则组合/统计细节/审计边界
    - 感知: schema 边界/适配器信息/权限组合矩阵
    - 服务: 事件类型/候选详情/验证统计
    - 集成: API 全量/兼容细节
"""
import unittest

from backend.embodied.companion.expression import (
    ExpressionContext,
    ExpressionEngine,
    ExpressionRules,
)
from backend.embodied.companion.perception import (
    CameraAdapter,
    DetectionMockAdapter,
    DetectionResult,
    OCRMockAdapter,
    OCRResult,
    PERCEPTION_KINDS,
    PERCEPTION_SOURCES,
    PERCEPTION_TYPES,
    PerceptionEvent,
    PerceptionManager,
    PerceptionPermission,
    PerceptionService,
    PerceptionVerifier,
    VisionMockAdapter,
)
from backend.embodied.service import EmbodiedService


class TestExpressionRulesMore(unittest.TestCase):
    """表达规则补充"""

    def test_friendly_style(self):
        hits = ExpressionRules().match({
            "relationship": {"trust": 0.9},
        })
        self.assertIn("friendly", [h["style"] for h in hits])

    def test_high_trust_tone_warm(self):
        hits = ExpressionRules().match({
            "relationship": {"trust": 0.9},
        })
        self.assertEqual(hits[0]["tone"], "warm")

    def test_rule_reason_contains_rule_name(self):
        hits = ExpressionRules().match({
            "emotion": {"positivity": 0.9},
        })
        self.assertIn("积极", hits[0]["reason"])

    def test_match_order_deterministic(self):
        ctx = {
            "emotion": {"positivity": 0.9, "energy": 0.2,
                        "warmth": 0.9},
            "relationship": {"trust": 0.9},
        }
        r1 = ExpressionRules().match(ctx)
        r2 = ExpressionRules().match(ctx)
        self.assertEqual([h["rule"] for h in r1],
                         [h["rule"] for h in r2])

    def test_threshold_0_never_hit_positivity(self):
        r = ExpressionRules(threshold=1.0)
        hits = r.match({"emotion": {"positivity": 0.99}})
        self.assertNotIn("high_positivity",
                         [h["rule"] for h in hits])

    def test_energy_1_no_hit(self):
        hits = ExpressionRules().match({"emotion": {"energy": 1.0}})
        self.assertNotIn("low_energy", [h["rule"] for h in hits])

    def test_warmth_0_no_hit(self):
        hits = ExpressionRules().match({"emotion": {"warmth": 0.0}})
        self.assertNotIn("high_warmth", [h["rule"] for h in hits])

    def test_rules_snapshot_threshold(self):
        r = ExpressionRules(threshold=0.8).rules()
        self.assertEqual(r["threshold"], 0.8)


class TestExpressionEngineMore(unittest.TestCase):
    """表达引擎补充"""

    def test_generate_with_all_inputs(self):
        e = ExpressionEngine()
        r = e.generate(
            emotion={"positivity": 0.9, "energy": 0.9,
                     "warmth": 0.9},
            relationship={"trust": 0.9},
            task={"result": "ok"},
            conversation={"turns": 10},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_style_distribution_multiple(self):
        e = ExpressionEngine()
        e.generate(emotion={"positivity": 0.9})
        e.generate(emotion={"positivity": 0.9})
        e.generate(emotion={"energy": 0.2})
        st = e.status()
        self.assertEqual(st["style_distribution"][
            "more_positive"], 2)
        self.assertEqual(st["style_distribution"][
            "reduce_intensity"], 1)

    def test_rule_hits_counts(self):
        e = ExpressionEngine()
        e.generate(emotion={"positivity": 0.9})
        e.generate(emotion={"positivity": 0.9, "warmth": 0.9})
        st = e.status()
        self.assertGreaterEqual(st["rule_hits"]["high_positivity"], 2)
        self.assertGreaterEqual(st["rule_hits"]["high_warmth"], 1)

    def test_context_latest_after_generate(self):
        e = ExpressionEngine()
        e.generate(emotion={"positivity": 0.9})
        ctx = e._context.latest()
        self.assertEqual(ctx["emotion"]["positivity"], 0.9)

    def test_audit_ref_id(self):
        e = ExpressionEngine()
        r = e.generate(emotion={"positivity": 0.9})
        report = e.audit_report(limit=10)
        self.assertEqual(report["recent"][0]["ref_id"],
                         r["suggestion_id"])

    def test_multiple_generations_count(self):
        e = ExpressionEngine()
        for _ in range(5):
            e.generate()
        self.assertEqual(e.status()["generate_count"], 5)

    def test_clear_resets_distribution(self):
        e = ExpressionEngine()
        e.generate(emotion={"positivity": 0.9})
        e.clear()
        self.assertEqual(e.status()["style_distribution"], {})


class TestSchemaMore(unittest.TestCase):
    """数据模型补充"""

    def test_types_exact(self):
        self.assertEqual(set(PERCEPTION_TYPES),
                         {"vision", "audio", "text"})

    def test_sources_exact(self):
        self.assertEqual(set(PERCEPTION_SOURCES),
                         {"camera", "screen", "mic", "user_input",
                          "mock"})

    def test_kinds_exact(self):
        self.assertEqual(set(PERCEPTION_KINDS), {"ocr", "object"})

    def test_ocr_result_empty_text(self):
        r = OCRResult(text="")
        self.assertEqual(r.text, "")

    def test_ocr_result_confidence_zero(self):
        r = OCRResult(text="x", confidence=0.0)
        self.assertEqual(r.confidence, 0.0)

    def test_detection_empty_objects(self):
        r = DetectionResult(objects=[], confidence=0.5)
        self.assertEqual(r.objects, [])

    def test_detection_objects_kept(self):
        r = DetectionResult(objects=[{"label": "a"}],
                            confidence=0.5)
        self.assertEqual(r.objects[0]["label"], "a")

    def test_event_to_dict_content(self):
        ev = PerceptionEvent.create(
            source="camera", content={"kind": "ocr", "text": "x"},
            confidence=0.9,
        )
        d = ev.to_dict()
        self.assertEqual(d["content"]["text"], "x")

    def test_event_audio_type(self):
        ev = PerceptionEvent.create(
            source="mic", content={"kind": "text"},
            confidence=0.7, ptype="audio",
        )
        self.assertEqual(ev.type, "audio")

    def test_event_text_type(self):
        ev = PerceptionEvent.create(
            source="user_input", content={"kind": "text"},
            confidence=0.8, ptype="text",
        )
        ok, reason = ev.validate()
        self.assertTrue(ok)


class TestPermissionMatrix(unittest.TestCase):
    """权限组合矩阵"""

    def test_enable_vision_only(self):
        p = PerceptionPermission(enabled=True, vision_enabled=True)
        allowed, _ = p.check("vision")
        self.assertTrue(allowed)
        allowed, _ = p.check("ocr")
        self.assertFalse(allowed)

    def test_enable_ocr_only(self):
        p = PerceptionPermission(enabled=True, ocr_enabled=True)
        allowed, _ = p.check("ocr")
        self.assertTrue(allowed)
        allowed, _ = p.check("detection")
        self.assertFalse(allowed)

    def test_enable_detection_only(self):
        p = PerceptionPermission(enabled=True,
                                 detection_enabled=True)
        allowed, _ = p.check("detection")
        self.assertTrue(allowed)
        allowed, _ = p.check("vision")
        self.assertFalse(allowed)

    def test_master_off_ignores_children(self):
        p = PerceptionPermission(enabled=False, ocr_enabled=True)
        allowed, _ = p.check("ocr")
        self.assertFalse(allowed)

    def test_update_vision(self):
        p = PerceptionPermission()
        p.update(vision_enabled=True)
        allowed, _ = p.check("vision")
        self.assertFalse(allowed)  # 主开关仍关

    def test_update_master_and_child(self):
        p = PerceptionPermission()
        p.update(enabled=True, vision_enabled=True)
        allowed, _ = p.check("vision")
        self.assertTrue(allowed)

    def test_deny_reasons_distinct(self):
        # 子开关关闭时, 各感知类型拒绝原因不同
        p = PerceptionPermission(enabled=True)
        _, r1 = p.check("vision")
        _, r2 = p.check("ocr")
        _, r3 = p.check("detection")
        self.assertNotEqual(r1, r2)
        self.assertNotEqual(r2, r3)


class TestVerifierMore(unittest.TestCase):
    """验证补充"""

    def test_verification_id_prefix(self):
        v = PerceptionVerifier()
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.9)
        ok, reason, result = v.verify(ev)
        self.assertTrue(result["verification_id"].startswith(
            "ver_"))

    def test_rejected_has_no_event_data(self):
        v = PerceptionVerifier()
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.1)
        ok, reason, result = v.verify(ev)
        self.assertIsNone(result["event"])

    def test_approved_keeps_event(self):
        v = PerceptionVerifier()
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.9)
        ok, reason, result = v.verify(ev)
        self.assertEqual(result["event"]["source"], "mock")

    def test_stats_zero(self):
        v = PerceptionVerifier()
        st = v.stats()
        self.assertEqual(st["input_count"], 0)

    def test_stats_min_confidence(self):
        v = PerceptionVerifier(min_confidence=0.7)
        self.assertEqual(v.stats()["min_confidence"], 0.7)

    def test_custom_trusted_sources_all(self):
        v = PerceptionVerifier(trusted_sources=["user_input"])
        ev = PerceptionEvent.create(source="user_input", content={},
                                    confidence=0.9)
        ok, reason, result = v.verify(ev)
        self.assertTrue(ok)


class TestAdaptersMore(unittest.TestCase):
    """适配器补充"""

    def test_adapter_info_structure(self):
        a = OCRMockAdapter()
        info = a.get_info()
        for key in ("name", "source", "available"):
            self.assertIn(key, info)

    def test_vision_mock_get_info(self):
        a = VisionMockAdapter()
        info = a.get_info()
        self.assertEqual(info["name"], "vision_mock")

    def test_detection_mock_get_info(self):
        a = DetectionMockAdapter()
        self.assertEqual(a.source, "mock")

    def test_camera_disconnect_safe(self):
        a = CameraAdapter()
        a.disconnect()  # 不应抛异常

    def test_camera_connect_no_cv2(self):
        a = CameraAdapter()
        # 无 OpenCV 时 connect 返回 False
        if a._cv2 is None:
            self.assertFalse(a.connect())


class TestServiceMore(unittest.TestCase):
    """服务补充"""

    def _svc(self, **cfg):
        base = {"enabled": True, "vision_enabled": True,
                "ocr_enabled": True, "detection_enabled": True}
        base.update(cfg)
        mgr = PerceptionManager(
            default_ocr="ocr_mock", default_detect="detection_mock",
        )
        mgr.register(OCRMockAdapter(text="补充"))
        mgr.register(DetectionMockAdapter())
        return PerceptionService(
            manager=mgr,
            permission=PerceptionPermission(**base),
        )

    def test_ocr_text_from_service(self):
        svc = self._svc()
        r = svc.vision_ocr()
        self.assertEqual(r["text"], "补充")

    def test_detect_frame_structure(self):
        svc = self._svc()
        r = svc.vision_detect()
        for key in ("type", "objects", "confidence", "adapter",
                    "frame_id", "status"):
            self.assertIn(key, r)

    def test_ocr_frame_structure(self):
        svc = self._svc()
        r = svc.vision_ocr()
        for key in ("type", "text", "confidence", "adapter",
                    "frame_id", "status"):
            self.assertIn(key, r)

    def test_receive_screen_source(self):
        svc = self._svc()
        ev = svc.perception_receive(
            source="screen", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.assertEqual(ev["source"], "screen")

    def test_receive_mic_source(self):
        svc = self._svc()
        ev = svc.perception_receive(
            source="mic", content={"kind": "text"},
            confidence=0.7, ptype="audio",
        )
        self.assertEqual(ev["type"], "audio")

    def test_verify_screen_approved(self):
        svc = self._svc()
        ev = svc.perception_receive(
            source="screen", content={"kind": "ocr"},
            confidence=0.9,
        )
        r = svc.perception_verify(ev["event_id"])
        self.assertEqual(r["status"], "APPROVED")

    def test_memory_candidate_summary_truncated(self):
        svc = self._svc()
        ev = svc.perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "长" * 200},
            confidence=0.9,
        )
        svc.perception_verify(ev["event_id"])
        cands = svc.memory_candidates()["candidates"]
        self.assertLessEqual(len(cands[0]["summary"]), 120)

    def test_clear_candidates(self):
        svc = self._svc()
        ev = svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        svc.perception_verify(ev["event_id"])
        cleared = svc.clear()
        self.assertEqual(cleared["candidates"], 1)

    def test_audit_after_clear(self):
        svc = self._svc()
        svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        svc.clear()
        self.assertEqual(svc.audit_report()["total"], 0)


class TestServiceAPIExtra(unittest.TestCase):
    """Service API 补充"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "companion_enabled": True,
            "perception_enabled": True,
            "vision_enabled": True,
            "ocr_enabled": True,
            "detection_enabled": True,
        })

    def test_expression_api_all_params(self):
        r = self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
            relationship={"trust": 0.9},
            task={"result": "ok"},
            conversation={"turns": 3},
        )
        self.assertIn("style", r)

    def test_perception_receive_invalid_api(self):
        r = self.svc.companion_perception_receive(
            source="hacker", content={}, confidence=0.9,
        )
        self.assertEqual(r["status"], "INVALID")

    def test_perception_verify_missing_api(self):
        r = self.svc.companion_perception_verify("pe_none")
        self.assertEqual(r["status"], "NOT_FOUND")

    def test_memory_candidates_api(self):
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        r = self.svc.companion_perception_memory_candidates()
        self.assertEqual(r["total"], 1)

    def test_perception_stats_mode(self):
        st = self.svc.companion_perception_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_expression_status_mode(self):
        st = self.svc.companion_expression_status()
        self.assertEqual(st["mode"], "rule_based")

    def test_emotion_unaffected_by_expression_api(self):
        before = self.svc.companion_emotion()
        self.svc.companion_expression_generate(
            emotion={"positivity": 1.0},
        )
        after = self.svc.companion_emotion()
        self.assertEqual(before["positivity"], after["positivity"])


if __name__ == "__main__":
    unittest.main()
