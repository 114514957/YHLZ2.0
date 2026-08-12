"""
YHLZ Embodied AI V6.6 - 自主成长成熟化集成测试 (V6.6 Integration)

覆盖:
    - Service API: reflection_emotion_adjust / growth_cycle_run /
      growth_pending_approvals / growth_cycle_decide /
      growth_trend_analysis
    - 节律联动: handle → 成长闭环检查
    - 安全: 应用需审批 / 人格稳定 / 身份守护
    - 向后兼容 (V6.5 及以前 API)
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


def seed_experiences(svc, success_n=4, fail_n=3):
    mgr = svc.companion_experience
    for _ in range(success_n):
        mgr.store_from_event(
            success=True, trigger="生成工程Prompt",
            source="v660_test", action="a", result="成功",
        )
    for _ in range(fail_n):
        mgr.store_from_event(
            success=False, trigger="拾取物体",
            source="v660_test", action="a", result="位置不匹配",
        )


class TestReflectionEmotionAPI(unittest.TestCase):
    """反思-情绪集成 API"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)

    def test_adjust_api(self):
        r = self.svc.companion_reflection_emotion_adjust()
        for key in ("result_id", "report_id", "meaning",
                    "emotion_analysis", "growth_value",
                    "risk_level", "emotion_context",
                    "adjustment", "mode"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")

    def test_adjust_through_meaning(self):
        r = self.svc.companion_reflection_emotion_adjust()
        self.assertIn("meaning", r)
        self.assertIn("state", r["emotion_analysis"])

    def test_adjust_uses_emotion_engine(self):
        before = self.svc.companion_emotion_engine.get_stats()[
            "update_count"]
        self.svc.companion_reflection_emotion_adjust()
        after = self.svc.companion_emotion_engine.get_stats()[
            "update_count"]
        self.assertGreaterEqual(after, before)

    def test_adjust_personality_stable(self):
        before = self.svc.companion_personality_engine\
            .personality()
        self.svc.companion_reflection_emotion_adjust()
        after = self.svc.companion_personality_engine\
            .personality()
        self.assertEqual(before, after)

    def test_adjust_no_personality_guard_block(self):
        before = self.svc.companion_identity_guard["guard"]\
            .stats()["intercept_count"]
        self.svc.companion_reflection_emotion_adjust()
        after = self.svc.companion_identity_guard["guard"]\
            .stats()["intercept_count"]
        self.assertEqual(before, after)

    def test_adjust_empty_experience(self):
        svc = setup_service()
        r = svc.companion_reflection_emotion_adjust()
        self.assertIn("result_id", r)
        self.assertIn("adjustment", r)


class TestGrowthCycleAPI(unittest.TestCase):
    """成长闭环 API"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)

    def test_cycle_run_api(self):
        r = self.svc.companion_growth_cycle_run(
            trigger="manual",
        )
        self.assertEqual(r["cycle"]["status"], "completed")
        self.assertIn("reflection", r)
        self.assertIn("proposals", r)
        self.assertIn("evaluations", r)

    def test_cycle_pending_api(self):
        self.svc.companion_growth_cycle_run(trigger="manual")
        p = self.svc.companion_growth_pending_approvals()
        self.assertIn("pending_count", p)
        self.assertIn("items", p)
        self.assertGreater(p["pending_count"], 0)

    def test_cycle_decide_approve_not_applied(self):
        self.svc.companion_growth_cycle_run(trigger="manual")
        pid = self.svc.companion_growth_pending_approvals()[
            "items"][0]["pending_id"]
        r = self.svc.companion_growth_cycle_decide(
            pid, "approve", "用户确认",
        )
        self.assertEqual(r["decision"], "approve")
        self.assertFalse(r["applied"])

    def test_cycle_decide_reject(self):
        self.svc.companion_growth_cycle_run(trigger="manual")
        pid = self.svc.companion_growth_pending_approvals()[
            "items"][0]["pending_id"]
        r = self.svc.companion_growth_cycle_decide(
            pid, "reject",
        )
        self.assertEqual(r["decision"], "reject")

    def test_cycle_auto_run_no_trigger(self):
        svc = setup_service()
        r = svc.companion_growth_cycle_run(trigger="auto")
        self.assertIsNone(r["cycle"])

    def test_cycle_audit_recorded(self):
        self.svc.companion_growth_cycle_run(trigger="manual")
        audit = self.svc.companion_growth_audit(limit=0)
        self.assertIn("cycle_completed",
                      audit["by_decision"])

    def test_cycle_auto_apply_never(self):
        cfg = {"embodied_enabled": True, "companion_enabled":
               True, "growth_auto_apply": True}
        svc = EmbodiedService()
        svc.load_config(cfg)
        seed_experiences(svc)
        svc.companion_growth_cycle_run(trigger="manual")
        applier = svc.companion_growth_engine["applier"]\
            .stats()
        self.assertEqual(applier["applied_count"], 0)


class TestTrendAPI(unittest.TestCase):
    """成长趋势 API"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)

    def test_trend_api(self):
        r = self.svc.companion_growth_trend_analysis()
        for key in ("analysis_id", "period", "growth_score",
                    "trend", "analysis"):
            self.assertIn(key, r)
        self.assertEqual(r["period"], "day")

    def test_trend_period_week(self):
        r = self.svc.companion_growth_trend_analysis(
            period="week",
        )
        self.assertEqual(r["period"], "week")

    def test_trend_metrics_from_real_stats(self):
        self.svc.companion_reflection_analyze()
        r = self.svc.companion_growth_trend_analysis()
        metrics = [a["metric"] for a in r["analysis"]]
        self.assertIn("reflection_count", metrics)
        self.assertIn("proposal_count", metrics)
        self.assertIn("approval_rate", metrics)
        self.assertIn("applied_count", metrics)
        self.assertIn("identity_guard_block", metrics)
        self.assertIn("experience_growth", metrics)
        self.assertIn("memory_quality", metrics)

    def test_trend_reflection_count_reflects(self):
        self.svc.companion_reflection_analyze()
        r = self.svc.companion_growth_trend_analysis()
        m = next(a for a in r["analysis"]
                 if a["metric"] == "reflection_count")
        self.assertGreater(m["value"], 0)

    def test_trend_identity_guard_metrics(self):
        r = self.svc.companion_growth_trend_analysis()
        m = next(a for a in r["analysis"]
                 if a["metric"] == "identity_guard_block")
        self.assertGreaterEqual(m["value"], 0)

    def test_trend_score_in_range(self):
        r = self.svc.companion_growth_trend_analysis()
        self.assertGreaterEqual(r["growth_score"], 0.0)
        self.assertLessEqual(r["growth_score"], 1.0)

    def test_trend_mode(self):
        r = self.svc.companion_growth_trend_analysis()
        self.assertEqual(r["mode"], "rule_based")


class TestRhythmLinkage(unittest.TestCase):
    """节律联动 (handle → 成长闭环检查)"""

    def test_handle_includes_cycle_check(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("growth_cycle_check", r)
        self.assertIn("triggered",
                      r["growth_cycle_check"])

    def test_handle_cycle_check_mode(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertEqual(r["growth_cycle_check"]["mode"],
                         "rule_based")

    def test_handle_rhythm_still_works(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("rhythm", r)


class TestSafety(unittest.TestCase):
    """安全保证"""

    def test_growth_auto_apply_default_false(self):
        svc = setup_service()
        applier = svc.companion_growth_engine["applier"]
        self.assertFalse(applier._auto_apply)

    def test_growth_apply_needs_approval(self):
        svc = setup_service()
        r = svc.companion_growth_apply(
            proposal={"id": "gp_x",
                      "type": "skill_improvement",
                      "description": "改进",
                      "risk": "low"},
            evaluation={"approved": False,
                        "reason": "未批准"},
        )
        self.assertEqual(r["status"], "blocked")

    def test_identity_guard_blocks_protected(self):
        svc = setup_service()
        r = svc.companion.growth_apply(
            proposal={"id": "gp_x", "type": "x",
                      "description": "修改使命"},
            changes={"mission": "新使命"},
        )
        self.assertEqual(r["status"], "blocked")

    def test_personality_fingerprint_stable(self):
        svc = setup_service()
        before = svc.companion_personality_engine\
            .personality()["base"]
        svc.companion_reflection_emotion_adjust()
        svc.companion_growth_cycle_run(trigger="manual")
        after = svc.companion_personality_engine\
            .personality()["base"]
        self.assertEqual(before, after)

    def test_emotion_does_not_change_core_value(self):
        svc = setup_service()
        state_before = svc.companion_emotion_engine\
            .get_state()
        svc.companion_reflection_emotion_adjust()
        state_after = svc.companion_emotion_engine\
            .get_state()
        for key in state_before:
            self.assertIn(key, state_after)
        self.assertNotIn("mission", state_after)


class TestCompatibility(unittest.TestCase):
    """向后兼容 (V6.5 及以前)"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)

    def test_version_660(self):
        self.assertEqual(
            self.svc.report()["version"], "9.5.0")

    def test_old_reflection_api(self):
        r = self.svc.companion_reflection_analyze()
        self.assertIn("report_id", r)

    def test_old_growth_generate_api(self):
        r = self.svc.companion_growth_generate()
        self.assertIn("proposals", r)

    def test_old_growth_evaluate_api(self):
        r = self.svc.companion_growth_evaluate(
            {"id": "gp_x", "type": "skill_improvement",
             "description": "改进执行", "risk": "low"},
        )
        self.assertIn("approved", r)

    def test_old_growth_audit_api(self):
        r = self.svc.companion_growth_audit()
        self.assertIn("total", r)

    def test_old_growth_stats_api(self):
        r = self.svc.companion_growth_stats()
        self.assertIn("proposal", r)
        self.assertIn("evaluator", r)
        self.assertIn("applier", r)

    def test_old_growth_trend_api(self):
        r = self.svc.companion_growth_trend(bucket="day")
        self.assertIn("bucket", r)

    def test_old_rhythm_api(self):
        r = self.svc.companion_growth_rhythm()
        self.assertIn("enabled", r)

    def test_old_creative_api(self):
        r = self.svc.companion_creative_stats()
        self.assertIn("mode", r)

    def test_old_emotion_api(self):
        r = self.svc.companion_emotion()
        self.assertIn("positivity", r)

    def test_old_experience_api(self):
        r = self.svc.companion_experience_stats()
        self.assertIn("total", r)

    def test_snapshot_domains_included(self):
        svc = setup_service()
        states = svc.companion._continuity.collect_states()
        self.assertIn("growth_state", states)
        self.assertIn("reflection_state", states)

    def test_companion_status_version(self):
        r = self.svc.companion.status()
        self.assertEqual(r["version"], "9.5.0")


class TestConfigDriven(unittest.TestCase):
    """配置驱动"""

    def test_emotion_integration_disabled(self):
        svc = setup_service(
            companion_reflection_emotion_enabled=False,
        )
        r = svc.companion_reflection_emotion_adjust()
        self.assertFalse(r["adjustment"]["applied"])

    def test_cycle_disabled(self):
        svc = setup_service(
            companion_growth_cycle_enabled=False,
        )
        r = svc.companion_growth_cycle_run(trigger="manual")
        self.assertIsNone(r["cycle"])
        self.assertIn("停用", r["reason"])

    def test_trend_disabled(self):
        svc = setup_service(
            companion_growth_trend_enabled=False,
        )
        r = svc.companion_growth_trend_analysis()
        self.assertEqual(r["analysis"], [])
        self.assertEqual(r["growth_score"], 0.0)

    def test_cycle_days_config(self):
        svc = setup_service(companion_growth_cycle_days=3)
        engine = svc.companion_growth_cycle
        self.assertEqual(
            engine.stats()["thresholds"]["cycle_days"], 3)

    def test_cycle_delta_config(self):
        svc = setup_service(
            companion_growth_cycle_min_experience_delta=9,
        )
        engine = svc.companion_growth_cycle
        self.assertEqual(
            engine.stats()["thresholds"][
                "min_experience_delta"], 9)


class TestStatsAPI(unittest.TestCase):
    """V6.6 统计集成"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)

    def test_emotion_integrator_stats(self):
        self.svc.companion_reflection_emotion_adjust()
        stats = self.svc.companion_reflection_emotion.stats()
        self.assertIn("analysis_count", stats)
        self.assertIn("adjustment_count", stats)

    def test_cycle_stats(self):
        self.svc.companion_growth_cycle_run(trigger="manual")
        stats = self.svc.companion_growth_cycle.stats()
        self.assertEqual(stats["cycle_count"], 1)
        self.assertIn("pending_count", stats)

    def test_trend_analyzer_stats(self):
        self.svc.companion_growth_trend_analysis()
        stats = self.svc.companion_growth_trend_analyzer\
            .stats()
        self.assertEqual(stats["analysis_count"], 1)


class TestFullFlow(unittest.TestCase):
    """端到端闭环"""

    def test_full_maturation_flow(self):
        svc = setup_service()
        seed_experiences(svc)
        # 1. 反思-情绪联动
        emo = svc.companion_reflection_emotion_adjust()
        self.assertIn("adjustment", emo)
        # 2. 成长闭环
        cycle = svc.companion_growth_cycle_run(
            trigger="manual",
        )
        self.assertEqual(cycle["cycle"]["status"],
                         "completed")
        # 3. 待审批
        pending = svc.companion_growth_pending_approvals()
        self.assertGreater(pending["pending_count"], 0)
        # 4. 批准 (仍不自动应用)
        pid = pending["items"][0]["pending_id"]
        decided = svc.companion_growth_cycle_decide(
            pid, "approve",
        )
        self.assertFalse(decided["applied"])
        # 5. 趋势报告
        trend = svc.companion_growth_trend_analysis()
        self.assertGreaterEqual(trend["growth_score"], 0.0)
        # 6. 身份稳定
        fp = svc.companion._continuity._identity_fingerprint
        self.assertTrue(fp)


if __name__ == "__main__":
    unittest.main()
