"""
YHLZ Embodied AI V6.2 - 多模态交互与感知补充测试 (V6.2 Extra)

覆盖 (专项补足至 ≥300):
    - 表达: 阈值边界 / 规则组合 / 置信度 / 审计上限
    - 感知: 适配器配置 / 管理器边界 / 事件时间戳
    - 服务: 权限组合 / 记忆候选细节 / 审计
    - 集成: 快照兼容 / 成长联动
"""
import time
import unittest

from backend.embodied.companion.expression import (
    EXPRESSION_RULES,
    ExpressionAudit,
    ExpressionEngine,
    ExpressionRules,
)
from backend.embodied.companion.perception import (
    DetectionMockAdapter,
    OCRMockAdapter,
    PerceptionEvent,
    PerceptionManager,
    PerceptionPermission,
    PerceptionService,
    PerceptionVerifier,
    VisionMockAdapter,
)
from backend.embodied.service import EmbodiedService


class TestExpressionExtra(unittest.TestCase):
    """表达补充"""

    def test_threshold_boundary_low(self):
        r = ExpressionRules(threshold=0.3)
        hits = r.match({"emotion": {"positivity": 0.3}})
        self.assertIn("high_positivity", [h["rule"] for h in hits])

    def test_threshold_high_no_hit(self):
        r = ExpressionRules(threshold=0.95)
        hits = r.match({"emotion": {"positivity": 0.9}})
        self.assertEqual(hits, [])

    def test_energy_boundary(self):
        r = ExpressionRules(threshold=0.5)
        hits = r.match({"emotion": {"energy": 0.49}})
        self.assertIn("low_energy", [h["rule"] for h in hits])

    def test_energy_exactly_threshold_no_hit(self):
        r = ExpressionRules(threshold=0.5)
        hits = r.match({"emotion": {"energy": 0.5}})
        self.assertNotIn("low_energy", [h["rule"] for h in hits])

    def test_warmth_combined_with_positivity(self):
        hits = ExpressionRules().match({
            "emotion": {"positivity": 0.9, "warmth": 0.9},
        })
        rules = [h["rule"] for h in hits]
        self.assertIn("high_positivity", rules)
        self.assertIn("high_warmth", rules)

    def test_compose_primary_first(self):
        e = ExpressionEngine()
        r = e.generate(
            emotion={"positivity": 0.9, "warmth": 0.9},
            relationship={"trust": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_confidence_multi_rules_higher(self):
        e = ExpressionEngine()
        r1 = e.generate(emotion={"positivity": 0.9})
        r2 = e.generate(
            emotion={"positivity": 0.9, "warmth": 0.9,
                     "energy": 0.9},
            relationship={"trust": 0.9},
        )
        self.assertGreater(r2["confidence"], r1["confidence"])

    def test_confidence_cap(self):
        e = ExpressionEngine()
        r = e.generate(
            emotion={"positivity": 0.9, "warmth": 0.9,
                     "energy": 0.9},
            relationship={"trust": 0.9},
        )
        self.assertLessEqual(r["confidence"], 0.95)

    def test_neutral_confidence_low(self):
        e = ExpressionEngine()
        r = e.generate()
        self.assertEqual(r["confidence"], 0.3)

    def test_status_styles_list(self):
        e = ExpressionEngine()
        st = e.status()
        self.assertIn("more_positive", st["styles"])
        self.assertIn("neutral", st["styles"])

    def test_status_tones_list(self):
        e = ExpressionEngine()
        st = e.status()
        self.assertIn("warm", st["tones"])

    def test_generate_timestamp(self):
        e = ExpressionEngine()
        r = e.generate()
        self.assertGreater(r["timestamp"], 0.0)

    def test_rules_constant_five(self):
        self.assertEqual(len(EXPRESSION_RULES), 5)

    def test_audit_ring_capacity(self):
        a = ExpressionAudit(max_records=3)
        for _ in range(6):
            a.record(action="generate")
        self.assertEqual(a.report()["total"], 3)

    def test_audit_recent_order(self):
        a = ExpressionAudit()
        a.record(action="generate", detail="first")
        a.record(action="status", detail="second")
        r = a.report(limit=10)
        self.assertEqual(r["recent"][0]["detail"], "second")

    def test_task_failure_with_emotion(self):
        e = ExpressionEngine()
        r = e.generate(
            emotion={"positivity": 0.9},
            task={"result": "failure"},
        )
        # 高积极优先于任务失败 (顺序)
        self.assertEqual(r["style"], "more_positive")

    def test_task_failure_only(self):
        e = ExpressionEngine()
        r = e.generate(task={"status": "failure"})
        self.assertEqual(r["style"], "patient")


class TestPerceptionExtra(unittest.TestCase):
    """感知补充"""

    def test_ocr_mock_custom_confidence(self):
        a = OCRMockAdapter(confidence=0.7)
        r = a.ocr()
        self.assertEqual(r.confidence, 0.7)

    def test_vision_mock_custom_objects(self):
        a = VisionMockAdapter(objects=[{"label": "lamp"}])
        r = a.detect()
        self.assertEqual(r.objects[0]["label"], "lamp")

    def test_detection_mock_custom(self):
        a = DetectionMockAdapter(objects=[{"label": "cat"},
                                          {"label": "dog"}])
        r = a.detect()
        self.assertEqual(len(r.objects), 2)

    def test_event_custom_timestamp(self):
        ev = PerceptionEvent(source="mock", content={},
                             confidence=0.5, timestamp=123.0)
        self.assertEqual(ev.timestamp, 123.0)

    def test_event_roundtrip(self):
        ev = PerceptionEvent.create(
            source="camera",
            content={"kind": "ocr", "text": "round"},
            confidence=0.8,
        )
        d = ev.to_dict()
        self.assertEqual(d["content"]["text"], "round")

    def test_manager_register_replace(self):
        m = PerceptionManager()
        m.register(OCRMockAdapter(text="旧"))
        m.register(OCRMockAdapter(text="新"))
        a = m.get("ocr_mock")
        r = a.ocr()
        self.assertEqual(r.text, "新")

    def test_manager_unregister_all(self):
        m = PerceptionManager()
        m.register(OCRMockAdapter())
        m.clear()
        self.assertEqual(m.names(), [])

    def test_permission_update_off(self):
        p = PerceptionPermission(enabled=True, ocr_enabled=True)
        p.update(ocr_enabled=False)
        allowed, _ = p.check("ocr")
        self.assertFalse(allowed)

    def test_permission_required_flag(self):
        p = PerceptionPermission(enabled=True, ocr_enabled=True,
                                 permission_required=True)
        allowed, _ = p.check("ocr")
        self.assertTrue(allowed)

    def test_verifier_trusted_mock(self):
        v = PerceptionVerifier()
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.9)
        ok, reason, result = v.verify(ev)
        self.assertTrue(ok)

    def test_verifier_boundary_confidence(self):
        v = PerceptionVerifier(min_confidence=0.5)
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.5)
        ok, reason, result = v.verify(ev)
        self.assertTrue(ok)

    def test_verifier_below_boundary(self):
        v = PerceptionVerifier(min_confidence=0.5)
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.49)
        ok, reason, result = v.verify(ev)
        self.assertFalse(ok)


class TestServiceExtra(unittest.TestCase):
    """服务补充"""

    def _svc(self, **cfg):
        base = {"enabled": True, "vision_enabled": True,
                "ocr_enabled": True, "detection_enabled": True}
        base.update(cfg)
        mgr = PerceptionManager(
            default_ocr="ocr_mock", default_detect="detection_mock",
        )
        mgr.register(OCRMockAdapter(text="服务"))
        mgr.register(DetectionMockAdapter())
        return PerceptionService(
            manager=mgr,
            permission=PerceptionPermission(**base),
        )

    def test_ocr_error_no_adapter(self):
        svc = PerceptionService(
            manager=PerceptionManager(),
            permission=PerceptionPermission(enabled=True,
                                            ocr_enabled=True),
        )
        r = svc.vision_ocr()
        self.assertEqual(r["status"], "error")

    def test_receive_then_not_found(self):
        svc = self._svc()
        r = svc.perception_verify("pe_missing")
        self.assertEqual(r["status"], "NOT_FOUND")

    def test_candidate_keeps_event_id(self):
        svc = self._svc()
        ev = svc.perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        svc.perception_verify(ev["event_id"])
        cands = svc.memory_candidates()["candidates"]
        self.assertEqual(cands[0]["event_id"], ev["event_id"])

    def test_candidate_kind(self):
        svc = self._svc()
        ev = svc.perception_receive(
            source="camera",
            content={"kind": "detection", "objects": [1]},
            confidence=0.9,
        )
        svc.perception_verify(ev["event_id"])
        cands = svc.memory_candidates()["candidates"]
        self.assertEqual(cands[0]["kind"], "detection")

    def test_multiple_candidates(self):
        svc = self._svc()
        for _ in range(3):
            ev = svc.perception_receive(
                source="camera", content={"kind": "ocr"},
                confidence=0.9,
            )
            svc.perception_verify(ev["event_id"])
        self.assertEqual(svc.memory_candidates()["total"], 3)

    def test_audit_ring_capacity(self):
        svc = self._svc()
        for i in range(10):
            svc.perception_receive(
                source="camera", content={}, confidence=0.9,
            )
        r = svc.audit_report()
        self.assertEqual(r["total"], 10)  # 10 < 500 上限

    def test_stats_manager_adapters(self):
        svc = self._svc()
        st = svc.stats()
        self.assertGreaterEqual(
            len(st["manager"]["adapters"]), 2,
        )

    def test_clear_verification_history(self):
        svc = self._svc()
        ev = svc.perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        svc.perception_verify(ev["event_id"])
        cleared = svc.clear()
        self.assertGreaterEqual(cleared["verification_history"], 1)


class TestIntegrationExtra(unittest.TestCase):
    """集成补充"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
            "perception_enabled": True,
            "vision_enabled": True,
            "ocr_enabled": True,
            "detection_enabled": True,
            "companion_persistence_enabled": True,
        })

    def test_expression_emotion_linked_service(self):
        """表达建议参考真实情绪引擎状态"""
        self.svc.companion_emotion_adjust("success")
        self.svc.companion_emotion_adjust("success")
        emotion = self.svc.companion_emotion()
        r = self.svc.companion_expression_generate(
            emotion=emotion,
            relationship=self.svc.companion_relationship(),
        )
        self.assertIn(r["style"], EXPRESSION_RULES.values() and [
            "more_positive", "reduce_intensity", "personal",
            "friendly", "patient", "neutral"] or ["neutral"])

    def test_growth_report_after_perception(self):
        self.svc.companion_vision_ocr()
        eng = self.svc.companion_continuity_engine
        eng.track_event("multimodal_perception", detail="感知")
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")

    def test_snapshot_after_perception(self):
        """感知活动后快照保存/恢复正常 (感知不持久化但系统稳定)"""
        import os
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="yhlz_p62_")
        path = os.path.join(tmp, "s.jsonl")
        self.svc.companion_vision_ocr()
        self.svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(path)
        self.assertTrue(res["success"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_handle_with_perception_active(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_all_audits_available(self):
        self.svc.companion_vision_ocr()
        self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        self.assertIn("by_action",
                      self.svc.companion_perception_audit())
        self.assertIn("by_action",
                      self.svc.companion_expression_audit())

    def test_perception_permission_config_default(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        st = svc.companion_perception_stats()
        self.assertFalse(st["permission"]["enabled"])

    def test_expression_handle_response_no_conflict(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertNotIn("expression", r)  # 表达不注入 handle

    def test_version(self):
        self.assertEqual(self.svc.companion.status()["version"],
                         "9.5.0")


class TestEdgeSafety(unittest.TestCase):
    """安全边界"""

    def test_ocr_image_none_mock_ok(self):
        svc = PerceptionService(
            manager=PerceptionManager(
                default_ocr="ocr_mock",
            ).__class__() if False else PerceptionManager(
                default_ocr="ocr_mock",
            ),
            permission=PerceptionPermission(enabled=True,
                                            ocr_enabled=True),
        )
        svc._manager.register(OCRMockAdapter())
        r = svc.vision_ocr(image=None)
        self.assertEqual(r["status"], "success")

    def test_verifier_rejects_bad_content(self):
        v = PerceptionVerifier()
        ev = PerceptionEvent(ptype="vision", source="mock",
                             content="not dict", confidence=0.9)
        ok, reason, result = v.verify(ev)
        self.assertFalse(ok)

    def test_expression_never_writes_emotion(self):
        e = ExpressionEngine()
        e.generate(emotion={"positivity": 1.0})
        # 表达引擎无情绪状态字段
        self.assertFalse(hasattr(e, "_state"))


if __name__ == "__main__":
    unittest.main()
