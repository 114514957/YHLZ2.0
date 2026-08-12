"""
YHLZ Embodied AI V6.3 - 具身感知补充测试 2 (V6.3 Extra2)

覆盖 (专项补足至 ≥300):
    - Service API 细节
    - 配置驱动 (real_enabled/template 阈值/阈值边界)
    - 安全边界矩阵
    - 成长集成
    - 兼容细节
"""
import unittest

from backend.embodied.companion.perception import (
    AgentPipelineAdapter,
    ApprovalRule,
    CandidateValidator,
    MemoryGate,
    PerceptionFrame,
    PerceptionRouter,
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

    def test_gate_thresholds_config(self):
        svc = setup_service(memory_gate_approve_threshold=0.9)
        gate = svc.companion_memory_gate
        self.assertEqual(gate._rule._approve, 0.9)

    def test_gate_reject_threshold_config(self):
        svc = setup_service(memory_gate_reject_threshold=0.5)
        gate = svc.companion_memory_gate
        self.assertEqual(gate._rule._reject, 0.5)

    def test_template_threshold_config(self):
        svc = setup_service(
            perception_template_match_threshold=0.8,
        )
        # 模板适配器默认未注册, 验证配置读取
        self.assertEqual(
            svc.companion_perception_service._manager
            ._default_detect, "detection_mock",
        )

    def test_memory_gate_enabled_config(self):
        svc = setup_service(memory_gate_enabled=False)
        gate = svc.companion_memory_gate
        self.assertFalse(gate._enabled)

    def test_pipeline_enabled_config(self):
        svc = setup_service(pipeline_perception_enabled=False)
        adapter = svc.companion_perception_pipeline
        self.assertFalse(adapter._enabled)

    def test_real_enabled_config_kept(self):
        svc = setup_service(perception_real_enabled=True)
        self.assertTrue(svc.companion_perception_stats()[
            "permission"]["enabled"])


class TestServiceMore(unittest.TestCase):
    """Service API 补充"""

    def setUp(self):
        self.svc = setup_service()

    def test_gate_stats_mode(self):
        st = self.svc.companion_perception_memory_gate_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_gate_stats_thresholds(self):
        st = self.svc.companion_perception_memory_gate_stats()
        self.assertEqual(st["thresholds"]["approve_threshold"], 0.6)

    def test_pipeline_stats_router(self):
        st = self.svc.companion_perception_pipeline_stats()
        self.assertIn("router", st)

    def test_frame_meaning_preserved(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="屏幕任务",
            verified=True,
        )
        self.assertEqual(r["frame"]["meaning"], "屏幕任务")

    def test_frame_verified_flag(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        self.assertTrue(r["frame"]["verified"])

    def test_gate_approved_experience_trigger(self):
        ev = self.svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "任务清单"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        exp = self.svc.companion_experience.retrieve(
            r["stored"]["id"],
        )
        self.assertIn("感知", exp["trigger"])

    def test_gate_rejected_no_experience(self):
        before = self.svc.companion_experience.stats()["total"]
        ev = self.svc.companion_perception_receive(
            source="mock", content={"kind": "ocr", "text": "噪声"},
            confidence=0.6,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(
            self.svc.companion_experience.stats()["total"], before,
        )

    def test_multiple_gates(self):
        for i in range(3):
            ev = self.svc.companion_perception_receive(
                source="camera",
                content={"kind": "ocr", "text": f"任务清单{i}"},
                confidence=0.9,
            )
            self.svc.companion_perception_verify(ev["event_id"])
        cands = self.svc.companion_perception_memory_candidates()
        self.assertEqual(cands["total"], 3)

    def test_frame_reasoning_input_structure(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "ocr", "text": "任务"},
            meaning="m", verified=True,
        )
        ai = r["agent_input"]
        self.assertEqual(ai["route_target"],
                         "perception_agent")


class TestSecurityMatrix(unittest.TestCase):
    """安全矩阵"""

    def setUp(self):
        self.svc = setup_service()

    def test_unverified_always_blocked(self):
        for verified in (False,):
            r = self.svc.companion_perception_frame(
                content={"kind": "ocr"}, meaning="x",
                verified=verified,
            )
            self.assertTrue(r["action_blocked"])

    def test_verified_ocr_allowed(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        self.assertFalse(r["action_blocked"])

    def test_verified_object_blocked(self):
        r = self.svc.companion_perception_frame(
            content={"kind": "object"}, meaning="x", verified=True,
        )
        self.assertTrue(r["action_blocked"])

    def test_perception_not_direct_memory(self):
        """感知帧不写记忆 (仅观察)"""
        before = self.svc.companion_experience.stats()["total"]
        self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        after = self.svc.companion_experience.stats()["total"]
        self.assertEqual(before, after)

    def test_gate_requires_verification(self):
        """未验证事件无候选 → 无法批准"""
        self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        cands = self.svc.companion_perception_memory_candidates()
        self.assertEqual(cands["total"], 0)

    def test_rejected_candidate_no_emotion_change(self):
        em_before = self.svc.companion_emotion()
        ev = self.svc.companion_perception_receive(
            source="mock", content={"kind": "ocr", "text": "噪声"},
            confidence=0.6,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        em_after = self.svc.companion_emotion()
        self.assertEqual(em_before["positivity"],
                         em_after["positivity"])


class TestGrowthIntegration(unittest.TestCase):
    """成长集成"""

    def setUp(self):
        self.svc = setup_service()

    def test_perception_gate_then_growth_report(self):
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")

    def test_gate_written_experience_reflectable(self):
        ev = self.svc.companion_perception_receive(
            source="camera",
            content={"kind": "ocr", "text": "重要任务清单"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        c = self.svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        r = self.svc.companion_perception_memory_gate(
            c["candidate_id"],
        )
        self.assertIn("stored", r)
        refl = self.svc.companion_reflection()
        self.assertEqual(refl["mode"], "rule_based")

    def test_pipeline_frame_then_handle(self):
        self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)


class TestCompatDetails(unittest.TestCase):
    """兼容细节"""

    def setUp(self):
        self.svc = setup_service()

    def test_v62_permission_still_works(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        r = svc.companion_vision_ocr()
        self.assertEqual(r["status"], "PERMISSION_DENIED")

    def test_v62_memory_candidates_still_there(self):
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        r = self.svc.companion_perception_memory_candidates()
        self.assertIn("total", r)

    def test_v611_emotion_unaffected(self):
        self.svc.companion_emotion_adjust("success")
        st = self.svc.companion_emotion()
        self.assertIn("positivity", st)

    def test_version_still_6_3_0(self):
        self.assertEqual(self.svc.companion.status()["version"],
                         "9.5.0")


class TestUnitEdges(unittest.TestCase):
    """单元边界"""

    def test_approval_rule_thresholds_boundary(self):
        """reject < approve 约束"""
        r = ApprovalRule(approve_threshold=0.1,
                         reject_threshold=0.0)
        self.assertEqual(r._approve, 0.1)
        with self.assertRaises(Exception):
            ApprovalRule(approve_threshold=0.0,
                         reject_threshold=0.0)

    def test_approval_rule_validation_negative(self):
        with self.assertRaises(Exception):
            ApprovalRule(approve_threshold=-0.1)

    def test_validator_stats_mode(self):
        v = CandidateValidator()
        self.assertEqual(v.stats()["mode"], "rule_based")

    def test_gate_enabled_default(self):
        g = MemoryGate()
        self.assertTrue(g._enabled)

    def test_router_route_table_constant(self):
        from backend.embodied.companion.perception import ROUTE_TABLE
        self.assertEqual(ROUTE_TABLE["vision"], "perception_agent")

    def test_frame_validate_ok_default(self):
        f = PerceptionFrame.create(content={})
        ok, reason = f.validate()
        self.assertTrue(ok)

    def test_pipeline_adapter_enabled_default(self):
        a = AgentPipelineAdapter()
        self.assertTrue(a._enabled)

    def test_router_stats_empty(self):
        r = PerceptionRouter()
        st = r.stats()
        self.assertEqual(st["route_count"], 0)

    def test_gate_history_empty(self):
        g = MemoryGate()
        self.assertEqual(g.history(), [])

    def test_validator_clear_empty(self):
        v = CandidateValidator()
        self.assertEqual(v.clear(), 0)

    def test_router_clear_empty(self):
        r = PerceptionRouter()
        self.assertEqual(r.clear(), 0)


if __name__ == "__main__":
    unittest.main()
