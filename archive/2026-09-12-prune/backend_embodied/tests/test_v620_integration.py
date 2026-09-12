"""
YHLZ Embodied AI V6.2 - 多模态交互与感知集成测试 (V6.2 Integration)

覆盖:
    - Service API (expression/perception)
    - 完整流程: 感知 → 验证 → 候选 → 成长事件
    - 权限默认关闭
    - 表达隔离
    - 向后兼容 (V6.1.1 及以前)
"""
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


class TestExpressionAPI(unittest.TestCase):
    """表达 API"""

    def setUp(self):
        self.svc = setup_service()

    def test_expression_generate_api(self):
        r = self.svc.companion_expression_generate(
            emotion={"positivity": 0.9, "energy": 0.8,
                     "warmth": 0.9},
        )
        for key in ("style", "tone", "reason", "confidence",
                    "mode"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")

    def test_expression_generate_empty(self):
        r = self.svc.companion_expression_generate()
        self.assertEqual(r["style"], "neutral")

    def test_expression_status_api(self):
        self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        st = self.svc.companion_expression_status()
        self.assertIn("style_distribution", st)
        self.assertIn("rule_hits", st)

    def test_expression_audit_api(self):
        self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        r = self.svc.companion_expression_audit()
        self.assertGreaterEqual(r["by_action"].get("generate", 0), 1)

    def test_expression_disabled_config(self):
        svc = setup_service(companion_expression_enabled=False)
        with self.assertRaises(Exception):
            svc.companion_expression_generate(
                emotion={"positivity": 0.9},
            )

    def test_expression_threshold_config(self):
        svc = setup_service(companion_expression_threshold=0.5)
        r = svc.companion_expression_generate(
            emotion={"positivity": 0.6},
        )
        self.assertEqual(r["style"], "more_positive")


class TestPerceptionAPI(unittest.TestCase):
    """感知 API"""

    def setUp(self):
        self.svc = setup_service()

    def test_vision_ocr_api(self):
        r = self.svc.companion_vision_ocr()
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["type"], "ocr")

    def test_vision_detect_api(self):
        r = self.svc.companion_vision_detect()
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["type"], "object")

    def test_permission_default_denied(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        r = svc.companion_vision_ocr()
        self.assertEqual(r["status"], "PERMISSION_DENIED")

    def test_permission_denied_detect(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        r = svc.companion_vision_detect()
        self.assertEqual(r["status"], "PERMISSION_DENIED")

    def test_permission_partial(self):
        svc = setup_service(detection_enabled=False)
        r_ocr = svc.companion_vision_ocr()
        r_det = svc.companion_vision_detect()
        self.assertEqual(r_ocr["status"], "success")
        self.assertEqual(r_det["status"], "PERMISSION_DENIED")


class TestPerceptionFlowAPI(unittest.TestCase):
    """感知完整流程 API"""

    def setUp(self):
        self.svc = setup_service()

    def test_receive_verify_candidate(self):
        ev = self.svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "任务清单"},
            confidence=0.9,
        )
        r = self.svc.companion_perception_verify(ev["event_id"])
        self.assertEqual(r["status"], "APPROVED")
        cands = self.svc.companion_perception_memory_candidates()
        self.assertEqual(cands["total"], 1)

    def test_low_confidence_rejected(self):
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.1,
        )
        r = self.svc.companion_perception_verify(ev["event_id"])
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(
            self.svc.companion_perception_memory_candidates()[
                "total"], 0,
        )

    def test_perception_audit_api(self):
        self.svc.companion_vision_ocr()
        r = self.svc.companion_perception_audit()
        self.assertGreaterEqual(r["by_action"].get("ocr", 0), 1)

    def test_perception_stats_api(self):
        self.svc.companion_vision_ocr()
        st = self.svc.companion_perception_stats()
        self.assertIn("verification", st)
        self.assertIn("permission", st)

    def test_audit_disabled_config(self):
        svc = setup_service(perception_audit_enabled=False)
        svc.companion_vision_ocr()
        r = svc.companion_perception_audit()
        self.assertEqual(r["total"], 0)


class TestGrowthIntegration(unittest.TestCase):
    """成长集成"""

    def setUp(self):
        self.svc = setup_service()

    def test_multimodal_event_type_exists(self):
        from backend.embodied.companion.growth import (
            GROWTH_EVENT_TYPES,
        )
        self.assertIn("multimodal_perception",
                      GROWTH_EVENT_TYPES)

    def test_multimodal_event_trackable(self):
        eng = self.svc.companion_continuity_engine
        eng.track_event("multimodal_perception",
                        detail="视觉感知验证通过",
                        meta={"source": "vision"})
        st = eng.tracker.stats()
        self.assertGreaterEqual(st["by_type"].get(
            "multimodal_perception", 0), 1)

    def test_multimodal_meaning(self):
        eng = self.svc.companion_continuity_engine
        eng.track_event("multimodal_perception",
                        detail="感知事件")
        m = eng.meaning.stats()
        self.assertGreaterEqual(m["by_event"].get(
            "multimodal_perception", 0), 1)

    def test_perception_growth_report_works(self):
        self.svc.companion_vision_ocr()
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")


class TestIsolation(unittest.TestCase):
    """安全隔离"""

    def setUp(self):
        self.svc = setup_service()

    def test_expression_not_change_personality(self):
        p_before = self.svc.companion_personality()
        self.svc.companion_expression_generate(
            emotion={"positivity": 1.0, "energy": 1.0,
                     "warmth": 1.0},
        )
        p_after = self.svc.companion_personality()
        self.assertEqual(p_before["base"], p_after["base"])
        self.assertEqual(p_before["dimensions"],
                         p_after["dimensions"])

    def test_perception_not_change_personality(self):
        p_before = self.svc.companion_personality()
        self.svc.companion_vision_ocr()
        ev = self.svc.companion_perception_receive(
            source="camera", content={}, confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        p_after = self.svc.companion_personality()
        self.assertEqual(p_before["base"], p_after["base"])

    def test_perception_not_direct_memory(self):
        """感知不直接写入经历存储"""
        before = self.svc.companion_experience.stats()["total"]
        self.svc.companion_vision_ocr()
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        after = self.svc.companion_experience.stats()["total"]
        self.assertEqual(before, after)

    def test_expression_not_change_emotion(self):
        em_before = self.svc.companion_emotion()
        self.svc.companion_expression_generate(
            emotion={"positivity": 1.0},
        )
        em_after = self.svc.companion_emotion()
        self.assertEqual(em_before["positivity"],
                         em_after["positivity"])


class TestBackwardCompat(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_v611_emotion_api(self):
        self.svc.companion_emotion_adjust("success")
        self.assertIn("positivity", self.svc.companion_emotion())

    def test_v611_rhythm_api(self):
        r = self.svc.companion_growth_rhythm()
        self.assertIn("capture_count", r)

    def test_v60_persistence_api(self):
        import os
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="yhlz_bc62_")
        path = os.path.join(tmp, "s.jsonl")
        self.svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(path)
        self.assertTrue(res["success"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_v59_creative_api(self):
        r = self.svc.companion_creative_run()
        self.assertIn("summary", r)

    def test_v58_reflection_api(self):
        r = self.svc.companion_reflection()
        self.assertEqual(r["mode"], "rule_based")

    def test_v55_personality_api(self):
        p = self.svc.companion_personality()
        self.assertIn("base", p)

    def test_v50_handle_api(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_version_6_2_0(self):
        self.assertEqual(self.svc.companion.status()["version"],
                         "9.5.0")

    def test_handle_still_has_rhythm(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("rhythm", r)


if __name__ == "__main__":
    unittest.main()
