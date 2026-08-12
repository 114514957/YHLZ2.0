"""
YHLZ Embodied AI V6.3 - 感知管道单元测试 (Perception Pipeline)

覆盖 (pipeline/):
    - 感知帧: 结构/校验/序列化
    - 路由: 类型 → 目标 / 行动安全 (未验证禁止)
    - 管道适配器: 注入/统计/拦截
"""
import unittest

from backend.embodied.companion.perception import (
    ACTION_SENSITIVE,
    AgentPipelineAdapter,
    FRAME_TYPES,
    FrameError,
    PerceptionFrame,
    PerceptionRouter,
    ROUTE_TABLE,
)


class TestPerceptionFrame(unittest.TestCase):
    """感知帧"""

    def test_create(self):
        f = PerceptionFrame.create(
            content={"kind": "ocr", "text": "任务清单"},
            meaning="屏幕显示任务清单", verified=True,
        )
        self.assertTrue(f.frame_id.startswith("pf_"))
        self.assertEqual(f.type, "vision")
        self.assertTrue(f.verified)

    def test_to_dict(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   meaning="m", verified=True)
        d = f.to_dict()
        for key in ("type", "content", "verified", "meaning",
                    "timestamp"):
            self.assertIn(key, d)
        self.assertTrue(d["verified"])

    def test_validate_ok(self):
        f = PerceptionFrame.create(content={})
        ok, reason = f.validate()
        self.assertTrue(ok)

    def test_validate_bad_type(self):
        f = PerceptionFrame(ftype="bogus", content={})
        ok, reason = f.validate()
        self.assertFalse(ok)
        self.assertIn("类型", reason)

    def test_create_invalid_raises(self):
        with self.assertRaises(FrameError):
            PerceptionFrame.create(content={}, ftype="bogus")

    def test_frame_types(self):
        self.assertIn("vision", FRAME_TYPES)
        self.assertIn("audio", FRAME_TYPES)
        self.assertIn("text", FRAME_TYPES)

    def test_unverified_default(self):
        f = PerceptionFrame.create(content={})
        self.assertFalse(f.verified)

    def test_meaning_empty_default(self):
        f = PerceptionFrame.create(content={})
        self.assertEqual(f.meaning, "")

    def test_timestamp_set(self):
        f = PerceptionFrame.create(content={})
        self.assertGreater(f.timestamp, 0.0)

    def test_audio_frame(self):
        f = PerceptionFrame.create(content={"kind": "text"},
                                   ftype="audio")
        self.assertEqual(f.type, "audio")


class TestPerceptionRouter(unittest.TestCase):
    """感知路由"""

    def setUp(self):
        self.router = PerceptionRouter()

    def test_route_ocr_to_perception(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        r = self.router.route(f)
        self.assertEqual(r["target"], "perception_agent")

    def test_route_text_to_reasoning(self):
        f = PerceptionFrame.create(content={"kind": "text"},
                                   ftype="text", verified=True)
        r = self.router.route(f)
        self.assertEqual(r["target"], "reasoning_agent")

    def test_verified_action_allowed(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        r = self.router.route(f)
        self.assertTrue(r["action_allowed"])

    def test_unverified_action_blocked(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=False)
        r = self.router.route(f)
        self.assertFalse(r["action_allowed"])
        self.assertIn("未验证", r["reason"])

    def test_sensitive_kind_blocked(self):
        """object 类型行动敏感 → 需额外确认"""
        f = PerceptionFrame.create(content={"kind": "object"},
                                   verified=True)
        r = self.router.route(f)
        self.assertFalse(r["action_allowed"])
        self.assertIn("敏感", r["reason"])

    def test_route_structure(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        r = self.router.route(f)
        for key in ("route_id", "frame_id", "target",
                    "action_allowed", "reason", "mode"):
            self.assertIn(key, r)

    def test_route_id_prefix(self):
        f = PerceptionFrame.create(content={}, verified=True)
        r = self.router.route(f)
        self.assertTrue(r["route_id"].startswith("rt_"))

    def test_invalid_frame_routed_invalid(self):
        f = PerceptionFrame(ftype="bogus", content={})
        r = self.router.route(f)
        self.assertEqual(r["target"], "invalid")
        self.assertFalse(r["action_allowed"])

    def test_route_table(self):
        self.assertEqual(ROUTE_TABLE["vision"],
                         "perception_agent")
        self.assertEqual(ROUTE_TABLE["text"], "reasoning_agent")

    def test_action_sensitive(self):
        self.assertIn("object", ACTION_SENSITIVE)

    def test_stats(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        self.router.route(f)
        st = self.router.stats()
        self.assertEqual(st["route_count"], 1)
        self.assertEqual(st["by_target"]["perception_agent"], 1)

    def test_stats_mode(self):
        st = self.router.stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_clear(self):
        f = PerceptionFrame.create(content={}, verified=True)
        self.router.route(f)
        self.assertEqual(self.router.clear(), 1)


class TestPipelineAdapter(unittest.TestCase):
    """管道适配器"""

    def setUp(self):
        self.adapter = AgentPipelineAdapter()

    def test_ingest(self):
        f = PerceptionFrame.create(
            content={"kind": "ocr", "text": "任务清单"},
            meaning="任务清单", verified=True,
        )
        r = self.adapter.ingest(f)
        self.assertEqual(r["mode"], "rule_based")
        self.assertTrue(r["ingest_id"].startswith("ing_"))

    def test_ingest_agent_input(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        r = self.adapter.ingest(f)
        ai = r["agent_input"]
        self.assertIn("perception_frame", ai)
        self.assertIn("route_target", ai)
        self.assertIn("observed_at", ai)

    def test_ingest_verified_no_block(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        r = self.adapter.ingest(f)
        self.assertFalse(r["action_blocked"])

    def test_ingest_unverified_blocked(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=False)
        r = self.adapter.ingest(f)
        self.assertTrue(r["action_blocked"])

    def test_ingest_sensitive_blocked(self):
        f = PerceptionFrame.create(content={"kind": "object"},
                                   verified=True)
        r = self.adapter.ingest(f)
        self.assertTrue(r["action_blocked"])

    def test_disabled_adapter(self):
        a = AgentPipelineAdapter(enabled=False)
        f = PerceptionFrame.create(content={}, verified=True)
        r = a.ingest(f)
        self.assertTrue(r["action_blocked"])
        self.assertIn("停用", r["reason"])

    def test_stats(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        self.adapter.ingest(f)
        f2 = PerceptionFrame.create(content={"kind": "ocr"},
                                    verified=False)
        self.adapter.ingest(f2)
        st = self.adapter.stats()
        self.assertEqual(st["frame_count"], 2)
        self.assertEqual(st["verified_count"], 1)
        self.assertEqual(st["action_blocked_count"], 1)

    def test_stats_mode(self):
        st = self.adapter.stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_clear(self):
        f = PerceptionFrame.create(content={}, verified=True)
        self.adapter.ingest(f)
        self.assertEqual(self.adapter.clear(), 1)

    def test_ingest_keeps_frame(self):
        f = PerceptionFrame.create(content={"kind": "ocr"},
                                   verified=True)
        r = self.adapter.ingest(f)
        self.assertEqual(r["frame"]["content"]["kind"], "ocr")


class TestPipelineSecurity(unittest.TestCase):
    """管道安全"""

    def test_no_action_instruction(self):
        """agent_input 只含观察, 无行动指令"""
        a = AgentPipelineAdapter()
        f = PerceptionFrame.create(content={"kind": "object"},
                                   verified=True)
        r = a.ingest(f)
        ai = r["agent_input"]
        self.assertNotIn("action", ai)
        self.assertNotIn("execute", ai)

    def test_unverified_never_action(self):
        a = AgentPipelineAdapter()
        for kind in ("ocr", "object", "text"):
            f = PerceptionFrame.create(content={"kind": kind},
                                       verified=False)
            r = a.ingest(f)
            self.assertTrue(r["action_blocked"], kind)

    def test_frame_does_not_modify_agent(self):
        """管道注入不修改 Agent 核心"""
        from backend.embodied.service import EmbodiedService
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        before = svc.companion_personality()
        svc.companion_perception_frame(
            content={"kind": "ocr"}, meaning="x", verified=True,
        )
        after = svc.companion_personality()
        self.assertEqual(before["base"], after["base"])


if __name__ == "__main__":
    unittest.main()
