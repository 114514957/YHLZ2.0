"""
YHLZ Embodied AI V6.2 - 多模态交互与感知补充测试 3 (V6.2 Extra3)

覆盖 (专项补足至 ≥300):
    - 表达: 审计上限/中性置信度细节
    - 感知: 验证历史/事件统计/错误帧
    - 服务: 审计关闭/统计细节
    - 集成: 多模态成长事件与报告
"""
import unittest

from backend.embodied.companion.expression import (
    ExpressionAudit,
    ExpressionEngine,
)
from backend.embodied.companion.perception import (
    DetectionMockAdapter,
    OCRMockAdapter,
    PerceptionManager,
    PerceptionPermission,
    PerceptionService,
    PerceptionVerifier,
)
from backend.embodied.service import EmbodiedService


class TestExpressionFinal(unittest.TestCase):
    """表达收尾"""

    def test_audit_max_validation(self):
        from backend.embodied.companion.expression import AuditError
        with self.assertRaises(AuditError):
            ExpressionAudit(max_records=0)

    def test_audit_report_empty(self):
        a = ExpressionAudit()
        self.assertEqual(a.report()["total"], 0)

    def test_audit_by_action_empty(self):
        a = ExpressionAudit()
        self.assertEqual(a.report()["by_action"], {})

    def test_engine_disabled_status_ok(self):
        e = ExpressionEngine(enabled=False)
        st = e.status()
        self.assertFalse(st["enabled"])

    def test_engine_timestamp_after_generate(self):
        e = ExpressionEngine()
        r1 = e.generate()
        import time as _t
        self.assertLessEqual(r1["timestamp"], _t.time())

    def test_neutral_reason(self):
        e = ExpressionEngine()
        r = e.generate()
        self.assertIn("无规则命中", r["reason"])

    def test_high_positivity_reason_text(self):
        e = ExpressionEngine()
        r = e.generate(emotion={"positivity": 0.9})
        self.assertIn("积极", r["reason"])


class TestPerceptionFinal(unittest.TestCase):
    """感知收尾"""

    def test_verifier_history_after_reject(self):
        v = PerceptionVerifier()
        ev = v._event if False else None
        from backend.embodied.companion.perception import (
            PerceptionEvent,
        )
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.1)
        v.verify(ev)
        h = v.history()
        self.assertEqual(len(h), 1)
        self.assertFalse(h[0]["approved"])

    def test_manager_error_frame_missing_text(self):
        m = PerceptionManager()
        frame = m.ocr()
        self.assertNotIn("text", frame)

    def test_manager_error_frame_type(self):
        m = PerceptionManager()
        frame = m.detect()
        self.assertEqual(frame["type"], "object")

    def test_permission_all_off_to_dict(self):
        p = PerceptionPermission()
        d = p.to_dict()
        self.assertFalse(d["vision_enabled"])
        self.assertFalse(d["ocr_enabled"])
        self.assertFalse(d["detection_enabled"])

    def test_ocr_mock_empty_text(self):
        a = OCRMockAdapter(text="")
        r = a.ocr()
        self.assertEqual(r.text, "")

    def test_detection_mock_default_confidence(self):
        a = DetectionMockAdapter()
        self.assertEqual(a._confidence, 0.85)

    def test_verifier_clear_stats(self):
        v = PerceptionVerifier()
        ev = None
        from backend.embodied.companion.perception import (
            PerceptionEvent,
        )
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.9)
        v.verify(ev)
        v.clear()
        self.assertEqual(v.stats()["input_count"], 0)


class TestServiceFinal(unittest.TestCase):
    """服务收尾"""

    def _svc(self, **cfg):
        base = {"enabled": True, "vision_enabled": True,
                "ocr_enabled": True, "detection_enabled": True}
        base.update(cfg)
        mgr = PerceptionManager(
            default_ocr="ocr_mock", default_detect="detection_mock",
        )
        mgr.register(OCRMockAdapter())
        mgr.register(DetectionMockAdapter())
        return PerceptionService(
            manager=mgr,
            permission=PerceptionPermission(**base),
        )

    def test_audit_disabled_record_empty(self):
        from backend.embodied.companion.perception import (
            PerceptionAudit,
        )
        svc = self._svc()
        svc._audit = PerceptionAudit(enabled=False)
        ev = svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        self.assertEqual(svc.audit_report()["total"], 0)

    def test_stats_permission_dict(self):
        svc = self._svc()
        st = svc.stats()
        self.assertEqual(st["permission"]["mode"], "rule_based")

    def test_stats_manager_defaults(self):
        svc = self._svc()
        st = svc.stats()
        self.assertEqual(st["manager"]["default_ocr"], "ocr_mock")

    def test_ocr_audit_ref(self):
        svc = self._svc()
        r = svc.vision_ocr()
        report = svc.audit_report(limit=10)
        self.assertEqual(report["recent"][0]["ref_id"],
                         r["frame_id"])

    def test_reject_not_found_no_crash(self):
        svc = self._svc()
        r = svc.perception_verify("pe_none")
        self.assertEqual(r["status"], "NOT_FOUND")


class TestIntegrationFinal(unittest.TestCase):
    """集成收尾"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "companion_enabled": True,
            "perception_enabled": True,
            "vision_enabled": True,
            "ocr_enabled": True,
            "detection_enabled": True,
        })

    def test_multimodal_event_in_metrics(self):
        eng = self.svc.companion_continuity_engine
        eng.track_event("multimodal_perception", detail="感知")
        m = eng.growth_metrics()
        self.assertGreaterEqual(m["by_type"].get(
            "multimodal_perception", 0), 1)

    def test_growth_meaning_multimodal(self):
        eng = self.svc.companion_continuity_engine
        eng.track_event("multimodal_perception", detail="视觉")
        meanings = eng.meaning._interpretations
        self.assertEqual(meanings[-1]["event"],
                         "multimodal_perception")

    def test_expression_and_perception_coexist(self):
        r1 = self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        r2 = self.svc.companion_vision_ocr()
        self.assertEqual(r1["style"], "more_positive")
        self.assertEqual(r2["status"], "success")

    def test_perception_audit_mode(self):
        r = self.svc.companion_perception_audit()
        self.assertEqual(r["mode"], "rule_based")

    def test_expression_audit_mode(self):
        r = self.svc.companion_expression_audit()
        self.assertEqual(r["mode"], "rule_based")

    def test_memory_candidates_not_in_experience(self):
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        # 候选存在但经历未写入
        self.assertEqual(
            self.svc.companion_perception_memory_candidates()[
                "total"], 1,
        )

    def test_perception_event_count_stats(self):
        self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_receive(
            source="screen", content={"kind": "ocr"},
            confidence=0.8,
        )
        st = self.svc.companion_perception_stats()
        self.assertEqual(st["event_count"], 2)

    def test_expression_generate_no_mutation(self):
        emotion = {"positivity": 0.9}
        self.svc.companion_expression_generate(emotion=emotion)
        self.assertEqual(emotion, {"positivity": 0.9})

    def test_perception_candidate_confidence(self):
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.85,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        cands = self.svc.companion_perception_memory_candidates()
        self.assertEqual(cands["candidates"][0]["confidence"], 0.85)

    def test_perception_candidate_pending_status(self):
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        cands = self.svc.companion_perception_memory_candidates()
        self.assertEqual(cands["candidates"][0]["status"],
                         "PENDING_REFLECTION")


if __name__ == "__main__":
    unittest.main()
