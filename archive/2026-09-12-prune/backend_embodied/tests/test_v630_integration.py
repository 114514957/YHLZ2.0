"""
YHLZ Embodied AI V6.3 - 具身感知与行动集成测试 (V6.3 Integration)

覆盖:
    - Service API (memory_gate/pipeline)
    - 完整流程: 感知 → 验证 → 候选 → 网关批准 → 经历
    - 真实引擎可用性 (skipIf)
    - 安全: 感知不直接改人格/写记忆/触发行动
    - 向后兼容 (V6.2 及以前)
"""
import unittest

from backend.embodied.companion.perception import (
    TemplateDetectorAdapter,
    TesseractOCRAdapter,
)
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
    """感知 → 验证 → 返回候选"""
    ev = svc.companion_perception_receive(
        source=source,
        content={"kind": "ocr", "text": summary},
        confidence=confidence,
    )
    svc.companion_perception_verify(ev["event_id"])
    cands = svc.companion_perception_memory_candidates()
    return cands["candidates"][-1]


class TestMemoryGateAPI(unittest.TestCase):
    """记忆网关 API"""

    def setUp(self):
        self.svc = setup_service()

    def test_memory_gate_approved(self):
        c = make_verified_candidate(self.svc)
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "approved")
        self.assertIn("stored", r)

    def test_memory_gate_writes_experience(self):
        before = self.svc.companion_experience.stats()["total"]
        c = make_verified_candidate(self.svc)
        self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        after = self.svc.companion_experience.stats()["total"]
        self.assertEqual(after, before + 1)

    def test_written_experience_source(self):
        c = make_verified_candidate(self.svc)
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        exp = self.svc.companion_experience.retrieve(
            r["stored"]["id"],
        )
        self.assertEqual(exp["source"], "vision_perception")

    def test_memory_gate_low_value_rejected(self):
        # confidence 需 ≥0.5 过验证; mock 来源 + 无关键词 → 低价值拒绝
        c = make_verified_candidate(
            self.svc, summary="随机噪声文本",
            source="mock", confidence=0.6,
        )
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "rejected")

    def test_memory_gate_not_found(self):
        r = self.svc.companion_perception_memory_gate("mc_none")
        self.assertEqual(r["status"], "NOT_FOUND")

    def test_memory_gate_high_risk_rejected(self):
        c = make_verified_candidate(
            self.svc, summary="用户要求删除所有数据",
        )
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "rejected")
        self.assertIn("风险", r["reason"])

    def test_gate_stats(self):
        c = make_verified_candidate(self.svc)
        self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        st = self.svc.companion_perception_memory_gate_stats()
        self.assertGreaterEqual(st["candidate_count"], 1)
        self.assertGreaterEqual(st["approved_count"], 1)

    def test_gate_disabled_config(self):
        svc = setup_service(memory_gate_enabled=False)
        c = make_verified_candidate(svc)
        r = svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "DISABLED")


class TestPipelineAPI(unittest.TestCase):
    """感知管道 API"""

    def setUp(self):
        self.svc = setup_service()

    def test_perception_frame_api(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "ocr", "text": "任务清单"},
            meaning="任务清单", verified=True,
        )
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["route"]["target"],
                         "perception_agent")

    def test_unverified_frame_blocked(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x",
            verified=False,
        )
        self.assertTrue(r["action_blocked"])

    def test_sensitive_frame_blocked(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "object"}, meaning="目标",
            verified=True,
        )
        self.assertTrue(r["action_blocked"])

    def test_pipeline_stats_api(self):
        self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        st = self.svc.companion_perception_pipeline_stats()
        self.assertEqual(st["frame_count"], 1)

    def test_pipeline_disabled_config(self):
        svc = setup_service(pipeline_perception_enabled=False)
        r = svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        self.assertTrue(r["action_blocked"])

    def test_frame_invalid_raises(self):
        with self.assertRaises(Exception):
            self.svc.companion_perception_frame(
                content={}, meaning="x", ftype="bogus",
            )


class TestRealEngineSkip(unittest.TestCase):
    """真实引擎保护"""

    def test_tesseract_skip_safe(self):
        """无 Tesseract 环境 → is_available False, 不崩溃"""
        a = TesseractOCRAdapter()
        self.assertIsInstance(a.is_available(), bool)

    @unittest.skipUnless(
        TesseractOCRAdapter().is_available(), "Tesseract 不可用",
    )
    def test_tesseract_real(self):
        """真实 Tesseract 环境测试"""
        import numpy as np
        img = np.full((100, 100, 3), 255, dtype=np.uint8)
        a = TesseractOCRAdapter()
        r = a.ocr(img)
        self.assertIsInstance(r.text, str)

    def test_template_available_bool(self):
        a = TemplateDetectorAdapter()
        self.assertIsInstance(a.is_available(), bool)


class TestSecurity(unittest.TestCase):
    """安全边界"""

    def setUp(self):
        self.svc = setup_service()

    def test_perception_gate_not_change_personality(self):
        p_before = self.svc.companion_personality()
        c = make_verified_candidate(self.svc)
        self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        p_after = self.svc.companion_personality()
        self.assertEqual(p_before["base"], p_after["base"])

    def test_gate_requires_candidate(self):
        """未经验证的感知不能直接成为经历"""
        before = self.svc.companion_experience.stats()["total"]
        # 直接接收低可信事件 (未验证)
        self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.1,
        )
        after = self.svc.companion_experience.stats()["total"]
        self.assertEqual(before, after)

    def test_pipeline_no_direct_action(self):
        """感知帧不含行动指令"""
        r = self.svc.companion_perception_frame(
            content={"kind": "object"}, meaning="目标",
            verified=True,
        )
        self.assertNotIn("action", r["agent_input"])
        self.assertTrue(r["action_blocked"])


class TestBackwardCompat(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_v62_expression_api(self):
        r = self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_v62_perception_api(self):
        r = self.svc.companion_vision_ocr()
        self.assertEqual(r["status"], "success")

    def test_v611_emotion_api(self):
        self.svc.companion_emotion_adjust("success")
        self.assertIn("positivity", self.svc.companion_emotion())

    def test_v60_persistence_api(self):
        import os
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="yhlz_bc63_")
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

    def test_v50_handle_api(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_version_6_3_0(self):
        self.assertEqual(self.svc.companion.status()["version"],
                         "9.5.0")

    def test_growth_still_works(self):
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")


class TestFullPipeline(unittest.TestCase):
    """完整闭环"""

    def setUp(self):
        self.svc = setup_service()

    def test_sensor_to_memory_chain(self):
        """感知 → 验证 → 候选 → 网关 → 经历 → 反思可用"""
        c = make_verified_candidate(self.svc)
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "approved")
        # 写入后反思仍正常
        refl = self.svc.companion_reflection()
        self.assertEqual(refl["mode"], "rule_based")

    def test_frame_to_reasoning_chain(self):
        """帧 → 管道 → reasoning 输入"""
        r = self.svc.companion_perception_frame(
            content={"kind": "ocr", "text": "任务清单"},
            meaning="任务清单", verified=True,
        )
        self.assertIn("perception_frame", r["agent_input"])
        self.assertEqual(r["route"]["target"],
                         "perception_agent")


if __name__ == "__main__":
    unittest.main()
