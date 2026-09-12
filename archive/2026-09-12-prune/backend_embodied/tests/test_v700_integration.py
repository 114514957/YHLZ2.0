"""
YHLZ Embodied AI V7.0 - 具身表达层集成测试 (V7.0 Integration)

覆盖:
    - Service API (companion_presence_*)
    - HIL 联动 (hybrid_execute → presence)
    - Boundary / Continuity / Recovery
    - 身份稳定 / 向后兼容
"""
import unittest

from backend.embodied.service import EmbodiedService


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


class TestPresenceAPI(unittest.TestCase):
    """表达 API"""

    def setUp(self):
        self.svc = setup_service()

    def test_presence_state_api(self):
        r = self.svc.companion_presence_state()
        for key in ("expression", "posture", "intensity",
                    "interaction_mode", "timestamp"):
            self.assertIn(key, r)
        self.assertEqual(r["expression"], "平静")

    def test_presence_update_api(self):
        r = self.svc.companion_presence_update("success")
        self.assertEqual(r["expression"], "高兴")
        self.assertEqual(r["interaction_mode"], "playful")

    def test_presence_update_failure_api(self):
        r = self.svc.companion_presence_update("failure")
        self.assertEqual(r["expression"], "关切")
        self.assertEqual(r["posture"], "聆听")

    def test_presence_interpreter_api(self):
        r = self.svc.companion_presence_interpreter(
            "deep_task",
        )
        self.assertEqual(r["expression"], "思考")
        # 只读: 不改变状态
        state = self.svc.companion_presence_state()
        self.assertEqual(state["expression"], "平静")

    def test_presence_continuity_api(self):
        self.svc.companion_presence_update("success")
        self.svc.companion_presence_update("success")
        c = self.svc.companion_presence_continuity()
        self.assertEqual(c["preferred_mode"], "playful")
        self.assertIn("rhythm_stability", c)

    def test_presence_stats_api(self):
        self.svc.companion_presence_update("idle")
        stats = self.svc.companion_presence_stats()
        self.assertEqual(stats["update_count"], 1)
        self.assertIn("state", stats)
        self.assertIn("memory", stats)

    def test_service_property(self):
        engine = self.svc.companion_presence_engine
        self.assertIsNotNone(engine)
        self.assertTrue(engine.stats()["enabled"])

    def test_config_disabled(self):
        svc = setup_service(companion_presence_enabled=False)
        r = svc.companion_presence_update("success")
        self.assertEqual(r["expression"], "平静")
        self.assertIn("presence_enabled_false", r["reason"])

    def test_config_intensity_step(self):
        svc = setup_service(
            companion_presence_intensity_step=0.5,
        )
        svc.companion_presence_update("success")
        r = svc.companion_presence_update("success")
        self.assertLessEqual(r["intensity"], 0.8)


class TestHybridLinkage(unittest.TestCase):
    """HIL 联动"""

    def setUp(self):
        self.svc = setup_service()

    def test_hybrid_execute_has_presence(self):
        r = self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "设计"},
        )
        self.assertIn("presence", r)
        self.assertEqual(r["presence"]["expression"], "高兴")

    def test_hybrid_deep_task_presence(self):
        r = self.svc.companion_hybrid_execute(
            {"type": "architecture_design"},
            {"prompt": "架构"},
        )
        self.assertEqual(r["presence"]["expression"], "思考")
        self.assertEqual(r["presence"]["posture"], "专注")

    def test_hybrid_local_presence_idle(self):
        r = self.svc.companion_hybrid_execute(
            {"type": "identity_query"}, {"query": "我是谁"},
        )
        self.assertEqual(r["presence"]["expression"], "平静")

    def test_hybrid_link_disabled(self):
        svc = setup_service(
            companion_presence_hybrid_link=False,
        )
        r = svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        self.assertNotIn("presence", r)

    def test_hybrid_link_presence_recorded(self):
        self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        self.assertEqual(
            self.svc.companion_presence_stats()[
                "update_count"], 1)


class TestBoundary(unittest.TestCase):
    """Boundary Test: 表达不改变身份"""

    def setUp(self):
        self.svc = setup_service()

    def test_personality_stable_after_presence(self):
        before = self.svc.companion_personality_engine\
            .personality()
        self.svc.companion_presence_update("failure")
        self.svc.companion_presence_update("success")
        after = self.svc.companion_personality_engine\
            .personality()
        self.assertEqual(before, after)

    def test_emotion_not_modified_by_presence(self):
        before = self.svc.companion_emotion_engine.get_state()
        self.svc.companion_presence_update("failure")
        after = self.svc.companion_emotion_engine.get_state()
        # 表达是只读输入方
        self.assertEqual(before, after)

    def test_identity_guard_no_intercept(self):
        before = self.svc.companion_identity_guard[
            "guard"].stats()["intercept_count"]
        self.svc.companion_presence_update("deep_task")
        after = self.svc.companion_identity_guard[
            "guard"].stats()["intercept_count"]
        self.assertEqual(before, after)

    def test_presence_no_identity_fields(self):
        self.svc.companion_presence_update("success")
        state = self.svc.companion_presence_state()
        for key in ("mission", "core_value",
                    "base_personality", "safety_rules",
                    "permission"):
            self.assertNotIn(key, state)

    def test_presence_no_memory_write(self):
        before = self.svc.companion_experience.stats()[
            "total"]
        self.svc.companion_presence_update("success")
        after = self.svc.companion_experience.stats()[
            "total"]
        self.assertEqual(before, after)


class TestContinuity(unittest.TestCase):
    """Continuity Test: 长期互动表达一致性"""

    def test_long_term_preference(self):
        svc = setup_service()
        for _ in range(10):
            svc.companion_presence_update("success")
        c = svc.companion_presence_continuity(window_days=7)
        self.assertEqual(c["preferred_expression"], "高兴")
        self.assertEqual(c["preferred_mode"], "playful")

    def test_mixed_interactions_stable(self):
        svc = setup_service()
        for i in range(20):
            svc.companion_presence_update(
                "success" if i % 2 == 0 else "failure",
            )
        c = svc.companion_presence_continuity()
        self.assertGreater(c["total"], 0)
        self.assertIn(c["preferred_mode"],
                      ["playful", "supportive"])

    def test_rhythm_stability_range(self):
        svc = setup_service()
        for i in range(10):
            svc.companion_presence_update("idle")
        c = svc.companion_presence_continuity()
        self.assertGreaterEqual(c["rhythm_stability"], 0.0)
        self.assertLessEqual(c["rhythm_stability"], 1.0)


class TestRecovery(unittest.TestCase):
    """Recovery Test: 故障降级"""

    def test_hybrid_cloud_failure_presence_ok(self):
        svc = setup_service(
            companion_hybrid_cloud_enabled=False,
        )
        # 云端停用 → 路由降级本地 → 表达仍输出
        r = svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        self.assertEqual(r["route"], "LOCAL")
        self.assertIn("presence", r)
        self.assertIn("expression", r["presence"])

    def test_presence_after_repeated_failures(self):
        svc = setup_service()
        for _ in range(5):
            r = svc.companion_presence_update("failure")
            self.assertIn("expression", r)
        self.assertEqual(r["expression"], "关切")


class TestCompatibility(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_version_700(self):
        self.assertEqual(
            self.svc.report()["version"], "9.5.0")

    def test_old_hybrid_api(self):
        r = self.svc.companion_hybrid_route(
            {"type": "identity_query"},
        )
        self.assertEqual(r["route"], "LOCAL")

    def test_old_growth_api(self):
        r = self.svc.companion_growth_stats()
        self.assertIn("proposal", r)

    def test_old_emotion_api(self):
        r = self.svc.companion_emotion()
        self.assertIn("positivity", r)

    def test_old_rhythm_api(self):
        r = self.svc.companion_growth_rhythm()
        self.assertIn("enabled", r)

    def test_handle_still_works(self):
        r = self.svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)
        self.assertIn("growth_cycle_check", r)

    def test_companion_status_version(self):
        r = self.svc.companion.status()
        self.assertEqual(r["version"], "9.5.0")

    def test_snapshot_collect_still_works(self):
        states = self.svc.companion._continuity\
            .collect_states()
        self.assertIn("growth_state", states)


class TestFullFlow(unittest.TestCase):
    """端到端具身流程"""

    def test_presence_full_flow(self):
        svc = setup_service()
        # 1. 情绪变化 (HIL 云端任务)
        r = svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "设计方案"},
        )
        self.assertEqual(r["presence"]["expression"], "高兴")
        # 2. 深度任务 → 专注表达
        r = svc.companion_hybrid_execute(
            {"type": "architecture_design"},
            {"prompt": "架构"},
        )
        self.assertEqual(r["presence"]["expression"], "思考")
        # 3. 失败 → 关切
        r = svc.companion_presence_update("failure")
        self.assertEqual(r["expression"], "关切")
        # 4. 连续性
        c = svc.companion_presence_continuity()
        self.assertGreater(c["total"], 0)
        # 5. 身份稳定
        fp = svc.companion._continuity._identity_fingerprint
        self.assertTrue(fp)


if __name__ == "__main__":
    unittest.main()
