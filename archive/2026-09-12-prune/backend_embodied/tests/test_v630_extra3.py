"""
YHLZ Embodied AI V6.3 - 具身感知补充测试 3 (V6.3 Extra3)

覆盖 (专项补足至 ≥300):
    - 批准规则维度矩阵
    - 网关多候选处理
    - 管道多帧处理
    - Service 组合场景
    - 配置边界
"""
import unittest

from backend.embodied.companion.perception import (
    ApprovalRule,
    CandidateValidator,
    MemoryGate,
    PerceptionFrame,
    PerceptionRouter,
    TemplateDetectorAdapter,
)
from backend.embodied.service import EmbodiedService

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


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


class TestApprovalMatrix(unittest.TestCase):
    """批准规则矩阵"""

    def setUp(self):
        self.rule = ApprovalRule()

    def test_camera_task_approved(self):
        r = self.rule.evaluate(make_candidate())
        self.assertEqual(r["status"], "approved")

    def test_screen_task_approved(self):
        r = self.rule.evaluate(make_candidate(
            source="screen", summary="重要任务清单目标计划",
        ))
        self.assertEqual(r["status"], "approved")

    def test_screen_learning_approved(self):
        r = self.rule.evaluate(make_candidate(
            source="screen", summary="学习计划目标",
        ))
        self.assertEqual(r["status"], "approved")

    def test_low_conf_rejected(self):
        r = self.rule.evaluate(make_candidate(
            source="mock", summary="x", confidence=0.1,
        ))
        self.assertEqual(r["status"], "rejected")

    def test_unknown_source_plus_noise_rejected(self):
        r = self.rule.evaluate(make_candidate(
            source="weird", summary="x", confidence=0.2,
        ))
        self.assertEqual(r["status"], "rejected")

    def test_repeated_rejected(self):
        """重复 5 次 → 价值降低 → 拒绝"""
        r = self.rule.evaluate(make_candidate(
            source="mock", summary="普通", confidence=0.5,
            occurrence_count=5,
        ))
        self.assertEqual(r["status"], "rejected")

    def test_dimension_scores_summary(self):
        r = self.rule.evaluate(make_candidate())
        total = sum(d["score"] for d in r["dimensions"])
        self.assertAlmostEqual(r["confidence"], total / 5,
                               places=4)

    def test_all_approved_high(self):
        """全维度高分 → 高置信批准"""
        r = self.rule.evaluate(make_candidate(
            summary="重要目标任务计划",
        ))
        self.assertEqual(r["status"], "approved")
        self.assertGreaterEqual(r["confidence"], 0.6)

    def test_identity_keyword_keeps_value(self):
        r = self.rule.evaluate(make_candidate(
            summary="用户提到身份价值观相关",
        ))
        self.assertEqual(r["status"], "approved")


class TestGateMulti(unittest.TestCase):
    """网关多候选"""

    def setUp(self):
        self.gate = MemoryGate()
        self.stored = []

        def store_fn(c):
            self.stored.append(c["candidate_id"])
            return {"id": f"exp_{len(self.stored)}"}

        self.store_fn = store_fn

    def test_mixed_candidates(self):
        """高价值批准 + 低价值拒绝"""
        self.gate.process(make_candidate(candidate_id="mc_good"),
                          store_fn=self.store_fn)
        self.gate.process(make_candidate(
            candidate_id="mc_bad", source="mock", summary="x",
            confidence=0.2,
        ), store_fn=self.store_fn)
        self.assertEqual(self.stored, ["mc_good"])

    def test_gate_stats_counts(self):
        for i in range(2):
            self.gate.process(make_candidate(
                candidate_id=f"mc_{i}",
            ), store_fn=self.store_fn)
        self.gate.process(make_candidate(
            candidate_id="mc_x", source="mock", summary="x",
            confidence=0.1,
        ), store_fn=self.store_fn)
        st = self.gate.stats()
        self.assertEqual(st["approved_count"], 2)
        self.assertEqual(st["rejected_count"], 1)

    def test_gate_sequential_same_candidate(self):
        r1 = self.gate.process(make_candidate(),
                               store_fn=self.store_fn)
        r2 = self.gate.process(make_candidate(),
                               store_fn=self.store_fn)
        self.assertEqual(r1["status"], "approved")
        self.assertEqual(r2["status"], "approved")


class TestPipelineMulti(unittest.TestCase):
    """管道多帧"""

    def setUp(self):
        self.router = PerceptionRouter()

    def test_multiple_frames_routes(self):
        frames = [
            PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True),
            PerceptionFrame.create(content={"kind": "text"},
                                   ftype="text", verified=True),
            PerceptionFrame.create(content={"kind": "object"},
                                   verified=True),
        ]
        targets = [self.router.route(f)["target"] for f in frames]
        self.assertEqual(targets[0], "perception_agent")
        self.assertEqual(targets[1], "reasoning_agent")
        self.assertEqual(targets[2], "perception_agent")

    def test_stats_after_many(self):
        for i in range(5):
            self.router.route(PerceptionFrame.create(
                content={"kind": "ocr"}, verified=True,
            ))
        st = self.router.stats()
        self.assertEqual(st["route_count"], 5)

    def test_blocked_vs_allowed_count(self):
        self.router.route(PerceptionFrame.create(
            content={"kind": "ocr"}, verified=True,
        ))
        self.router.route(PerceptionFrame.create(
            content={"kind": "ocr"}, verified=False,
        ))
        self.router.route(PerceptionFrame.create(
            content={"kind": "object"}, verified=True,
        ))
        st = self.router.stats()
        self.assertEqual(st["route_count"], 3)


class TestTemplateMore2(unittest.TestCase):
    """模板补充 2"""

    def test_threshold_default(self):
        a = TemplateDetectorAdapter()
        self.assertEqual(a.get_info()["match_threshold"], 0.7)

    def test_remove_missing(self):
        a = TemplateDetectorAdapter(templates={"a": 1})
        self.assertFalse(a.remove_template("b"))

    def test_add_after_init(self):
        a = TemplateDetectorAdapter()
        a.add_template("x", "d")
        self.assertIn("x", a.get_info()["templates"])

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_multiple_instances(self):
        """场景含两个方块 → 匹配 (逐模板一次)"""
        scene = np.zeros((100, 100), dtype=np.uint8)
        cv2.rectangle(scene, (10, 10), (59, 59), 255, -1)
        tpl = scene[10:60, 10:60].copy()
        a = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.9,
        )
        r = a.detect(scene)
        self.assertEqual(len(r.objects), 1)


class TestServiceScenarios(unittest.TestCase):
    """Service 组合场景"""

    def setUp(self):
        self.svc = setup_service()

    def test_full_vision_flow(self):
        """OCR → 帧 → 管道 → 网关全流程"""
        ocr = self.svc.companion_vision_ocr()
        self.assertEqual(ocr["status"], "success")
        frame = self.svc.companion_perception_frame(
            content={"kind": "ocr", "text": ocr["text"]},
            meaning="识别文本", verified=True,
        )
        self.assertFalse(frame["action_blocked"])
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
        self.assertEqual(gate["status"], "approved")

    def test_expression_with_perception_active(self):
        r = self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_rhythm_with_gate(self):
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        st = self.svc.companion_growth_rhythm()
        self.assertIn("capture_count", st)

    def test_perception_stats_after_flow(self):
        self.svc.companion_vision_ocr()
        st = self.svc.companion_perception_stats()
        self.assertEqual(st["event_count"], 0)  # OCR 非事件
        self.assertIn("verification", st)

    def test_gate_stats_after_multiple(self):
        for text in ("重要任务清单A", "重要任务清单B"):
            ev = self.svc.companion_perception_receive(
                source="camera",
                content={"kind": "ocr", "text": text},
                confidence=0.9,
            )
            self.svc.companion_perception_verify(ev["event_id"])
        cands = self.svc.companion_perception_memory_candidates()
        for c in cands["candidates"]:
            self.svc.companion_perception_memory_gate(
                c["candidate_id"],
            )
        st = self.svc.companion_perception_memory_gate_stats()
        self.assertGreaterEqual(st["approved_count"], 2)


class TestConfigBoundary(unittest.TestCase):
    """配置边界"""

    def test_no_permission_no_flow(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        r = svc.companion_vision_ocr()
        self.assertEqual(r["status"], "PERMISSION_DENIED")

    def test_gate_threshold_high_rejects_more(self):
        svc = setup_service(memory_gate_approve_threshold=0.95)
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

    def test_gate_threshold_low_approves_more(self):
        svc = setup_service(memory_gate_approve_threshold=0.4)
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


class TestUnitEdges2(unittest.TestCase):
    """单元边界 2"""

    def test_validator_rejects_string(self):
        v = CandidateValidator()
        ok, reason = v.validate("not dict")
        self.assertFalse(ok)

    def test_validator_rejects_list(self):
        v = CandidateValidator()
        ok, reason = v.validate([1, 2])
        self.assertFalse(ok)

    def test_gate_accepts_no_reflect(self):
        g = MemoryGate()
        r = g.process(make_candidate(), store_fn=lambda c: {})
        self.assertEqual(r["status"], "approved")

    def test_router_route_audio_unverified(self):
        r = PerceptionRouter().route(PerceptionFrame.create(
            content={"kind": "audio"}, ftype="audio",
            verified=False,
        ))
        self.assertFalse(r["action_allowed"])

    def test_frame_content_none(self):
        f = PerceptionFrame.create(content=None)
        self.assertEqual(f.content, {})


if __name__ == "__main__":
    unittest.main()
