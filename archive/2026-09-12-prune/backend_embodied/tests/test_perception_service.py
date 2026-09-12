"""
YHLZ Embodied AI V6.2 - 感知验证与服务单元测试 (Verification & Service)

覆盖 (perception/verification.py, service.py):
    - 验证网关: Schema → Source → Confidence → Approved
    - 低可信输入拒绝 (不能进入 Memory)
    - 服务: 权限短路 / OCR / 检测 / 事件接收 / 验证 / 记忆候选
    - 审计: 所有自动行为可追踪
"""
import unittest

from backend.embodied.companion.perception import (
    DetectionMockAdapter,
    OCRMockAdapter,
    PerceptionAudit,
    PerceptionManager,
    PerceptionPermission,
    PerceptionService,
    PerceptionVerifier,
    VerificationError,
    VisionMockAdapter,
)


def make_service(**kwargs):
    """构造感知服务 (Mock 适配器, 默认全开)"""
    cfg = {
        "enabled": True, "vision_enabled": True,
        "ocr_enabled": True, "detection_enabled": True,
    }
    cfg.update(kwargs)
    mgr = PerceptionManager(
        default_ocr="ocr_mock", default_detect="detection_mock",
    )
    mgr.register(OCRMockAdapter(text="服务OCR文本"))
    mgr.register(DetectionMockAdapter())
    mgr.register(VisionMockAdapter())
    return PerceptionService(
        manager=mgr,
        permission=PerceptionPermission(**cfg),
        verifier=PerceptionVerifier(min_confidence=0.5),
    )


class TestVerifier(unittest.TestCase):
    """验证网关"""

    def setUp(self):
        self.verifier = PerceptionVerifier(min_confidence=0.5)

    def _event(self, source="camera", confidence=0.9):
        from backend.embodied.companion.perception import (
            PerceptionEvent,
        )
        return PerceptionEvent.create(
            source=source,
            content={"kind": "ocr", "text": "t"},
            confidence=confidence,
        )

    def test_verify_ok(self):
        ok, reason, result = self.verifier.verify(self._event())
        self.assertTrue(ok)
        self.assertTrue(result["approved"])

    def test_verify_steps(self):
        ok, reason, result = self.verifier.verify(self._event())
        steps = [s["step"] for s in result["steps"]]
        self.assertIn("schema_check", steps)
        self.assertIn("source_check", steps)
        self.assertIn("confidence_check", steps)
        self.assertIn("approved", steps)

    def test_low_confidence_rejected(self):
        ok, reason, result = self.verifier.verify(
            self._event(confidence=0.1),
        )
        self.assertFalse(ok)
        self.assertIn("低可信", reason)

    def test_untrusted_source_rejected(self):
        # user_input 合法但不在默认可信来源 (camera/screen/mock)
        ok, reason, result = self.verifier.verify(
            self._event(source="user_input"),
        )
        self.assertFalse(ok)
        self.assertIn("来源", reason)

    def test_invalid_event_rejected(self):
        from backend.embodied.companion.perception import (
            PerceptionEvent,
        )
        ev = PerceptionEvent(ptype="bogus", source="mock",
                             content={}, confidence=0.9)
        ok, reason, result = self.verifier.verify(ev)
        self.assertFalse(ok)

    def test_result_structure(self):
        ok, reason, result = self.verifier.verify(self._event())
        for key in ("verification_id", "approved", "steps",
                    "event", "mode"):
            self.assertIn(key, result)

    def test_stats(self):
        self.verifier.verify(self._event())
        self.verifier.verify(self._event(confidence=0.1))
        st = self.verifier.stats()
        self.assertEqual(st["input_count"], 2)
        self.assertEqual(st["approved_count"], 1)
        self.assertEqual(st["rejected_count"], 1)

    def test_stats_mode(self):
        self.verifier.verify(self._event())
        self.assertEqual(self.verifier.stats()["mode"],
                         "rule_based")

    def test_history(self):
        self.verifier.verify(self._event())
        h = self.verifier.history()
        self.assertEqual(len(h), 1)

    def test_history_limit(self):
        for i in range(5):
            self.verifier.verify(self._event())
        self.assertEqual(len(self.verifier.history(limit=2)), 2)

    def test_clear(self):
        self.verifier.verify(self._event())
        self.assertEqual(self.verifier.clear(), 1)

    def test_min_confidence_validation(self):
        with self.assertRaises(VerificationError):
            PerceptionVerifier(min_confidence=1.5)

    def test_trusted_source_custom(self):
        v = PerceptionVerifier(trusted_sources=["camera"])
        from backend.embodied.companion.perception import (
            PerceptionEvent,
        )
        ev = PerceptionEvent.create(source="screen", content={},
                                    confidence=0.9)
        ok, reason, result = v.verify(ev)
        self.assertFalse(ok)


class TestServicePermission(unittest.TestCase):
    """服务权限"""

    def test_default_denied(self):
        svc = make_service(enabled=False, vision_enabled=False,
                           ocr_enabled=False,
                           detection_enabled=False)
        r = svc.vision_ocr()
        self.assertEqual(r["status"], "PERMISSION_DENIED")

    def test_denied_reason(self):
        svc = make_service(enabled=False)
        r = svc.vision_ocr()
        self.assertIn("默认拒绝", r["reason"])

    def test_denied_detect(self):
        svc = make_service(enabled=True, detection_enabled=False)
        r = svc.vision_detect()
        self.assertEqual(r["status"], "PERMISSION_DENIED")

    def test_denied_no_adapter_call(self):
        svc = make_service(enabled=False)
        r = svc.vision_ocr()
        self.assertNotIn("frame_id", r)

    def test_permission_audited(self):
        svc = make_service(enabled=False)
        svc.vision_ocr()
        report = svc.audit_report()
        self.assertGreaterEqual(
            report["by_action"].get("permission", 0), 1,
        )


class TestServiceVision(unittest.TestCase):
    """服务视觉"""

    def test_ocr_success(self):
        svc = make_service()
        r = svc.vision_ocr()
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["text"], "服务OCR文本")

    def test_ocr_audited(self):
        svc = make_service()
        svc.vision_ocr()
        report = svc.audit_report()
        self.assertGreaterEqual(report["by_action"].get("ocr", 0), 1)

    def test_detect_success(self):
        svc = make_service()
        r = svc.vision_detect()
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["type"], "object")

    def test_detect_audited(self):
        svc = make_service()
        svc.vision_detect()
        report = svc.audit_report()
        self.assertGreaterEqual(
            report["by_action"].get("detect", 0), 1,
        )


class TestServiceEvent(unittest.TestCase):
    """感知事件"""

    def setUp(self):
        self.svc = make_service()

    def test_receive(self):
        ev = self.svc.perception_receive(
            source="camera", content={"kind": "ocr", "text": "hi"},
            confidence=0.9,
        )
        self.assertIn("event_id", ev)
        self.assertEqual(ev["source"], "camera")

    def test_receive_invalid(self):
        r = self.svc.perception_receive(
            source="hacker", content={}, confidence=0.9,
        )
        self.assertEqual(r["status"], "INVALID")

    def test_receive_audited(self):
        self.svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        report = self.svc.audit_report()
        self.assertGreaterEqual(
            report["by_action"].get("receive", 0), 1,
        )

    def test_verify_approved(self):
        ev = self.svc.perception_receive(
            source="camera", content={"kind": "ocr", "text": "hi"},
            confidence=0.9,
        )
        r = self.svc.perception_verify(ev["event_id"])
        self.assertEqual(r["status"], "APPROVED")
        self.assertTrue(r["approved"])

    def test_verify_creates_memory_candidate(self):
        ev = self.svc.perception_receive(
            source="camera", content={"kind": "ocr", "text": "hi"},
            confidence=0.9,
        )
        self.svc.perception_verify(ev["event_id"])
        cands = self.svc.memory_candidates()
        self.assertEqual(cands["total"], 1)
        self.assertEqual(cands["candidates"][0]["source"], "camera")

    def test_candidate_not_direct_memory(self):
        """感知不直接进入经历存储 (仅候选)"""
        ev = self.svc.perception_receive(
            source="camera", content={"kind": "ocr", "text": "hi"},
            confidence=0.9,
        )
        self.svc.perception_verify(ev["event_id"])
        cands = self.svc.memory_candidates()
        self.assertEqual(cands["candidates"][0]["status"],
                         "PENDING_REFLECTION")

    def test_verify_low_conf_rejected_no_candidate(self):
        ev = self.svc.perception_receive(
            source="camera", content={"kind": "ocr", "text": "x"},
            confidence=0.1,
        )
        r = self.svc.perception_verify(ev["event_id"])
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(self.svc.memory_candidates()["total"], 0)

    def test_verify_not_found(self):
        r = self.svc.perception_verify("pe_nonexist")
        self.assertEqual(r["status"], "NOT_FOUND")

    def test_verify_audited(self):
        ev = self.svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        self.svc.perception_verify(ev["event_id"])
        report = self.svc.audit_report()
        self.assertGreaterEqual(report["by_action"].get(
            "verify", 0), 1)
        self.assertGreaterEqual(report["by_action"].get(
            "approve", 0), 1)

    def test_reject_audited(self):
        ev = self.svc.perception_receive(
            source="camera", content={}, confidence=0.1,
        )
        self.svc.perception_verify(ev["event_id"])
        report = self.svc.audit_report()
        self.assertGreaterEqual(report["by_action"].get(
            "reject", 0), 1)

    def test_promote_candidate(self):
        ev = self.svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        self.svc.perception_verify(ev["event_id"])
        cands = self.svc.memory_candidates()["candidates"]
        r = self.svc.promote_candidate(cands[0]["candidate_id"])
        self.assertEqual(r["status"], "PROMOTED")

    def test_promote_missing(self):
        r = self.svc.promote_candidate("mc_none")
        self.assertEqual(r["status"], "NOT_FOUND")


class TestServiceStats(unittest.TestCase):
    """服务统计"""

    def setUp(self):
        self.svc = make_service()

    def test_stats_structure(self):
        st = self.svc.stats()
        for key in ("mode", "event_count", "memory_candidate_count",
                    "verification", "permission", "manager"):
            self.assertIn(key, st)

    def test_stats_counts(self):
        self.svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        st = self.svc.stats()
        self.assertEqual(st["event_count"], 1)

    def test_audit_report(self):
        r = self.svc.audit_report()
        self.assertEqual(r["mode"], "rule_based")

    def test_audit_disabled(self):
        svc = make_service()
        svc._audit = PerceptionAudit(enabled=False)
        svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        self.assertEqual(svc.audit_report()["total"], 0)

    def test_clear(self):
        self.svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        cleared = self.svc.clear()
        self.assertEqual(cleared["events"], 1)
        self.assertEqual(self.svc.stats()["event_count"], 0)


class TestServiceIntegration(unittest.TestCase):
    """端到端流程"""

    def test_full_pipeline(self):
        """接收 → 验证 → 候选 → (反思后) 记忆"""
        svc = make_service()
        ev = svc.perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "屏幕上显示任务清单"},
            confidence=0.9,
        )
        r = svc.perception_verify(ev["event_id"])
        self.assertEqual(r["status"], "APPROVED")
        cands = svc.memory_candidates()
        self.assertEqual(cands["candidates"][0]["summary"],
                         "屏幕上显示任务清单")

    def test_rejected_never_memory(self):
        svc = make_service()
        ev = svc.perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.2,
        )
        svc.perception_verify(ev["event_id"])
        self.assertEqual(svc.memory_candidates()["total"], 0)

    def test_audit_full_trace(self):
        svc = make_service()
        svc.vision_ocr()
        ev = svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        svc.perception_verify(ev["event_id"])
        report = svc.audit_report()
        for action in ("ocr", "receive", "verify", "approve",
                       "memory"):
            self.assertGreaterEqual(
                report["by_action"].get(action, 0), 1, action,
            )


if __name__ == "__main__":
    unittest.main()
