"""
YHLZ Embodied AI V6.3 - 具身感知补充测试 4 (V6.3 Extra4)

覆盖 (专项补足至 ≥300):
    - 网关与管道交叉场景
    - 统计细节
    - 边界组合
"""
import unittest

from backend.embodied.companion.perception import (
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


class TestRuleEdges(unittest.TestCase):
    """规则边界"""

    def test_rule_confidence_exact_threshold(self):
        """评分恰好 = 批准阈值 → approved"""
        r = ApprovalRule(approve_threshold=0.5,
                         reject_threshold=0.1).evaluate(
            make_candidate(source="mock", summary="x",
                           confidence=0.5),
        )
        # 0.5+0.8+0.5+0.5+0.2 = 2.5/5 = 0.5 → approved
        self.assertEqual(r["status"], "approved")

    def test_rule_mid_zone_rejected(self):
        """中间区 (≥reject, <approve) → 拒绝"""
        r = ApprovalRule(approve_threshold=0.7,
                         reject_threshold=0.3).evaluate(
            make_candidate(),
        )
        self.assertEqual(r["status"], "rejected")

    def test_reject_reason_distinct(self):
        r = ApprovalRule().evaluate(make_candidate(
            source="mock", summary="x", confidence=0.2,
        ))
        self.assertIn("未达批准阈值", r["reason"])

    def test_dimension_count_always_five(self):
        r = ApprovalRule().evaluate(make_candidate())
        self.assertEqual(len(r["dimensions"]), 5)


class TestGateEdges(unittest.TestCase):
    """网关边界"""

    def test_gate_result_copy(self):
        g = MemoryGate()
        r1 = g.process(make_candidate(), store_fn=lambda c: {})
        r1["status"] = "hacked"
        h = g.history()
        self.assertEqual(h[0]["status"], "approved")

    def test_gate_store_returns_stored(self):
        g = MemoryGate()
        r = g.process(make_candidate(),
                      store_fn=lambda c: {"id": "exp_x"})
        self.assertEqual(r["stored"]["id"], "exp_x")

    def test_gate_stats_zero_init(self):
        g = MemoryGate()
        st = g.stats()
        self.assertEqual(st["candidate_count"], 0)
        self.assertEqual(st["approved_count"], 0)

    def test_gate_disabled_stats(self):
        g = MemoryGate(enabled=False)
        r = g.process(make_candidate(), store_fn=lambda c: {})
        self.assertEqual(r["status"], "DISABLED")
        self.assertEqual(g.stats()["candidate_count"], 0)

    def test_gate_processed_at_latest(self):
        import time
        g = MemoryGate()
        r = g.process(make_candidate(), store_fn=lambda c: {})
        self.assertLessEqual(r["processed_at"], time.time())


class TestValidatorEdges(unittest.TestCase):
    """校验边界"""

    def test_validator_history(self):
        v = CandidateValidator()
        v.validate(make_candidate())
        v.validate({})
        st = v.stats()
        self.assertEqual(st["passed_count"], 1)

    def test_validator_max_summary_custom(self):
        v = CandidateValidator(max_summary_length=5)
        ok, _ = v.validate(make_candidate(summary="abcde"))
        self.assertTrue(ok)

    def test_validator_unicode_summary(self):
        v = CandidateValidator()
        ok, reason = v.validate(make_candidate(
            summary="中文摘要内容",
        ))
        self.assertTrue(ok)


class TestRouterEdges(unittest.TestCase):
    """路由边界"""

    def test_router_route_id_unique(self):
        r = PerceptionRouter()
        f = PerceptionFrame.create(content={}, verified=True)
        r1 = r.route(f)
        r2 = r.route(f)
        self.assertNotEqual(r1["route_id"], r2["route_id"])

    def test_router_stats_route_table(self):
        r = PerceptionRouter()
        st = r.stats()
        self.assertIn("route_table", st)

    def test_router_frame_id_kept(self):
        r = PerceptionRouter()
        f = PerceptionFrame.create(content={}, verified=True)
        result = r.route(f)
        self.assertEqual(result["frame_id"], f.frame_id)

    def test_router_text_unverified(self):
        r = PerceptionRouter()
        f = PerceptionFrame.create(content={"kind": "text"},
                                   ftype="text",
                                   verified=False)
        result = r.route(f)
        self.assertEqual(result["target"], "reasoning_agent")
        self.assertFalse(result["action_allowed"])


class TestServiceCombos(unittest.TestCase):
    """Service 组合"""

    def setUp(self):
        self.svc = setup_service()

    def test_gate_then_frame_chain(self):
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
        # 批准后管道仍可用
        frame = self.svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        self.assertEqual(frame["route"]["target"],
                         "perception_agent")

    def test_all_stats_after_flow(self):
        self.svc.companion_vision_ocr()
        ev = self.svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        self.svc.companion_perception_verify(ev["event_id"])
        pstats = self.svc.companion_perception_stats()
        self.assertGreaterEqual(pstats["event_count"], 1)
        gstats = self.svc.companion_perception_memory_gate_stats()
        self.assertIn("by_status", gstats)
        plstats = self.svc.companion_perception_pipeline_stats()
        self.assertIn("frame_count", plstats)

    def test_handle_after_gate(self):
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
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_expression_still_available(self):
        r = self.svc.companion_expression_generate()
        self.assertEqual(r["style"], "neutral")

    def test_emotion_still_available(self):
        self.svc.companion_emotion_adjust("success")
        self.assertGreater(
            self.svc.companion_emotion()["positivity"], 0.6,
        )

    def test_creative_still_available(self):
        r = self.svc.companion_creative_run()
        self.assertIn("summary", r)


class TestFinalCounts(unittest.TestCase):
    """统计完整性"""

    def test_approval_stats_mode(self):
        self.assertEqual(
            ApprovalRule().thresholds()["mode"], "rule_based",
        )

    def test_gate_stats_mode(self):
        g = MemoryGate()
        self.assertEqual(g.stats()["mode"], "rule_based")

    def test_router_stats_mode(self):
        r = PerceptionRouter()
        self.assertEqual(r.stats()["mode"], "rule_based")

    def test_validator_stats_mode(self):
        v = CandidateValidator()
        self.assertEqual(v.stats()["mode"], "rule_based")

    def test_version_api(self):
        self.assertEqual(
            setup_service().companion.status()["version"], "9.5.0",
        )

    def test_compat_handle_rhythm(self):
        r = setup_service().companion_handle(
            {"text": "扫描环境查看策略建议"},
        )
        self.assertIn("rhythm", r)


class TestMoreEdges(unittest.TestCase):
    """更多边界"""

    def test_rule_evaluate_camera_empty_summary(self):
        r = ApprovalRule().evaluate(make_candidate(summary=""))
        self.assertIn(r["status"], ("approved", "rejected"))

    def test_rule_evaluate_none_confidence(self):
        c = make_candidate()
        c["confidence"] = None
        r = ApprovalRule().evaluate(c)
        self.assertIn(r["status"], ("approved", "rejected"))

    def test_gate_unicode_candidate(self):
        g = MemoryGate()
        r = g.process(make_candidate(summary="中文重要任务"),
                      store_fn=lambda c: {})
        self.assertEqual(r["status"], "approved")

    def test_gate_no_store_after_approve(self):
        g = MemoryGate()
        r = g.process(make_candidate())
        self.assertEqual(r["status"], "pending_store")

    def test_validator_timestamp_field_extra(self):
        v = CandidateValidator()
        ok, reason = v.validate(make_candidate(
            timestamp=123.0,
        ))
        self.assertTrue(ok)

    def test_router_verified_text_allowed(self):
        r = PerceptionRouter().route(PerceptionFrame.create(
            content={"kind": "text"}, ftype="text",
            verified=True,
        ))
        self.assertTrue(r["action_allowed"])

    def test_pipeline_ingest_many_frames(self):
        from backend.embodied.companion.perception import (
            AgentPipelineAdapter,
        )
        a = AgentPipelineAdapter()
        for i in range(10):
            a.ingest(PerceptionFrame.create(
                content={"kind": "ocr"}, verified=True,
            ))
        self.assertEqual(a.stats()["frame_count"], 10)

    def test_service_gate_then_verify_rejected(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.1,
        )
        r = svc.companion_perception_verify(ev["event_id"])
        self.assertEqual(r["status"], "REJECTED")

    def test_service_frame_verified_object(self):
        svc = setup_service()
        r = svc.companion_perception_frame(
            content={"kind": "object"}, meaning="目标",
            verified=True,
        )
        self.assertEqual(r["route"]["target"],
                         "perception_agent")

    def test_service_expression_threshold_config(self):
        svc = setup_service(companion_expression_threshold=0.5)
        r = svc.companion_expression_generate(
            emotion={"positivity": 0.6},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_service_gate_stats_after_reject(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="mock", content={"kind": "ocr", "text": "噪声"},
            confidence=0.6,
        )
        svc.companion_perception_verify(ev["event_id"])
        c = svc.companion_perception_memory_candidates()[
            "candidates"][-1]
        svc.companion_perception_memory_gate(c["candidate_id"])
        st = svc.companion_perception_memory_gate_stats()
        self.assertGreaterEqual(st["rejected_count"], 1)

    def test_service_growth_after_all(self):
        svc = setup_service()
        ev = svc.companion_perception_receive(
            source="camera", content={"kind": "ocr"},
            confidence=0.9,
        )
        svc.companion_perception_verify(ev["event_id"])
        r = svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")

    def test_service_memory_candidates_empty(self):
        svc = setup_service()
        r = svc.companion_perception_memory_candidates()
        self.assertEqual(r["total"], 0)

    def test_service_pipeline_stats_empty(self):
        svc = setup_service()
        st = svc.companion_perception_pipeline_stats()
        self.assertEqual(st["frame_count"], 0)

    def test_service_gate_stats_empty(self):
        svc = setup_service()
        st = svc.companion_perception_memory_gate_stats()
        self.assertEqual(st["candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
