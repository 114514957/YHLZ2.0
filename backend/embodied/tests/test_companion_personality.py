"""
YHLZ Embodied AI V5.5 - 自适应人格引擎单元测试 (Adaptive Personality)

覆盖 (personality_rules.py + personality.py):
    - 人格维度: warmth/patience/humor/serious (0.0~1.0)
    - 默认人格: 铁哥们 + 基础维度
    - 规则调整: 成功/失败/连续失败/轻松交流/严肃任务
    - 维度边界: [0.0, 1.0] 截断
    - 核心人格稳定: base 不可修改
    - 人格审计: 每次调整记录 (context/before/after/result/timestamp)
    - 互动统计: 只存数字 (interaction/success/failure/success_rate)
    - 单例: get_personality_service / reset_personality_service
    - 参数校验: step <= 0 / 非法情境
"""
import unittest

from backend.embodied.companion import (
    BASE_DIMENSIONS,
    PERSONALITY_CONTEXTS,
    PERSONALITY_DIMENSIONS,
    PERSONALITY_RULES,
    AdaptivePersonalityEngine,
    PersonalityError,
    PersonalityRuleError,
    apply_adjustment,
    get_personality_service,
    reset_personality_service,
    rule_for,
)


class TestPersonalityRules(unittest.TestCase):
    """人格规则系统"""

    def test_dimensions_whitelist(self):
        """维度白名单"""
        self.assertEqual(set(PERSONALITY_DIMENSIONS),
                         {"warmth", "patience", "humor", "serious"})

    def test_contexts_whitelist(self):
        """情境白名单"""
        self.assertEqual(set(PERSONALITY_CONTEXTS),
                         {"success", "failure", "consecutive_fail",
                          "casual_chat", "serious_task"})

    def test_rules_nonempty(self):
        """全部情境有规则"""
        for ctx in PERSONALITY_CONTEXTS:
            self.assertTrue(PERSONALITY_RULES[ctx], ctx)

    def test_rule_for_success(self):
        """成功规则"""
        rule = rule_for("success")
        self.assertGreater(rule["warmth"], 0)
        self.assertGreater(rule["humor"], 0)

    def test_rule_for_consecutive_fail(self):
        """连续失败规则"""
        rule = rule_for("consecutive_fail")
        self.assertGreater(rule["patience"], 0)
        self.assertLess(rule["humor"], 0)

    def test_rule_for_invalid_raises(self):
        """非法情境 → PersonalityRuleError"""
        with self.assertRaises(PersonalityRuleError):
            rule_for("zzz")

    def test_apply_adjustment_success(self):
        """成功调整: 热情提升"""
        dims = dict(BASE_DIMENSIONS)
        updated = apply_adjustment(dims, "success", step=0.1)
        self.assertEqual(updated["warmth"], 0.9)
        self.assertEqual(updated["humor"], 0.65)

    def test_apply_adjustment_no_mutate(self):
        """调整不修改原对象"""
        dims = dict(BASE_DIMENSIONS)
        apply_adjustment(dims, "success", step=0.1)
        self.assertEqual(dims, BASE_DIMENSIONS)

    def test_apply_adjustment_upper_bound(self):
        """上限 1.0 截断"""
        dims = {"warmth": 0.95, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        updated = apply_adjustment(dims, "success", step=0.1)
        self.assertLessEqual(updated["warmth"], 1.0)

    def test_apply_adjustment_lower_bound(self):
        """下限 0.0 截断"""
        dims = {"warmth": 0.8, "patience": 0.7,
                "humor": 0.05, "serious": 0.4}
        updated = apply_adjustment(dims, "consecutive_fail", step=0.1)
        self.assertGreaterEqual(updated["humor"], 0.0)

    def test_apply_adjustment_invalid_step(self):
        """step <= 0 → PersonalityRuleError"""
        with self.assertRaises(PersonalityRuleError):
            apply_adjustment(BASE_DIMENSIONS, "success", step=0)

    def test_base_dimensions(self):
        """基础维度"""
        self.assertEqual(BASE_DIMENSIONS["warmth"], 0.8)
        self.assertEqual(BASE_DIMENSIONS["patience"], 0.7)
        self.assertEqual(BASE_DIMENSIONS["humor"], 0.6)
        self.assertEqual(BASE_DIMENSIONS["serious"], 0.4)


class TestPersonalityState(unittest.TestCase):
    """人格状态"""

    def setUp(self):
        self.engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)

    def test_default_state(self):
        """默认人格"""
        p = self.engine.personality()
        self.assertEqual(p["base"], "铁哥们")
        self.assertEqual(p["dimensions"]["warmth"], 0.8)
        self.assertEqual(p["interactions"], 0)
        self.assertEqual(p["success_rate"], 0.0)

    def test_state_structure(self):
        """状态结构完整"""
        p = self.engine.personality()
        for key in ("base", "dimensions", "interactions",
                    "success_rate", "last_adjust"):
            self.assertIn(key, p)

    def test_dimensions_range(self):
        """维度范围 [0,1]"""
        p = self.engine.personality()
        self.assertTrue(all(0.0 <= v <= 1.0
                            for v in p["dimensions"].values()))

    def test_base_immutable(self):
        """核心人格不可修改"""
        self.engine.adjust("success")
        self.engine.adjust("failure")
        p = self.engine.personality()
        self.assertEqual(p["base"], "铁哥们")

    def test_custom_base(self):
        """自定义基础人格"""
        engine = AdaptivePersonalityEngine(base="知心朋友")
        self.assertEqual(engine.personality()["base"], "知心朋友")


class TestAdjust(unittest.TestCase):
    """人格调整"""

    def setUp(self):
        self.engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)

    def test_adjust_success(self):
        """成功调整"""
        r = self.engine.adjust("success")
        self.assertTrue(r["applied"])
        self.assertEqual(r["result"], "applied")
        self.assertIn("warmth", r["dimensions"])

    def test_adjust_increases_warmth(self):
        """成功 → 热情提升"""
        before = self.engine.personality()["dimensions"]["warmth"]
        self.engine.adjust("success")
        after = self.engine.personality()["dimensions"]["warmth"]
        self.assertGreater(after, before)

    def test_adjust_failure_patience(self):
        """失败 → 耐心提升"""
        before = self.engine.personality()["dimensions"]["patience"]
        self.engine.adjust("failure")
        after = self.engine.personality()["dimensions"]["patience"]
        self.assertGreater(after, before)

    def test_adjust_consecutive_fail(self):
        """连续失败 → 耐心+幽默-"""
        p1 = self.engine.personality()["dimensions"]
        self.engine.adjust("consecutive_fail")
        p2 = self.engine.personality()["dimensions"]
        self.assertGreater(p2["patience"], p1["patience"])
        self.assertLess(p2["humor"], p1["humor"])

    def test_adjust_casual_chat(self):
        """轻松交流 → 幽默提升"""
        before = self.engine.personality()["dimensions"]["humor"]
        self.engine.adjust("casual_chat")
        after = self.engine.personality()["dimensions"]["humor"]
        self.assertGreater(after, before)

    def test_adjust_serious_task(self):
        """严肃任务 → 严肃提升"""
        before = self.engine.personality()["dimensions"]["serious"]
        self.engine.adjust("serious_task")
        after = self.engine.personality()["dimensions"]["serious"]
        self.assertGreater(after, before)

    def test_adjust_invalid_context_raises(self):
        """非法情境 → PersonalityError"""
        with self.assertRaises(PersonalityError):
            self.engine.adjust("zzz")

    def test_adjust_explainable(self):
        """调整可解释"""
        r = self.engine.adjust("success")
        self.assertIn("情境", r["adjustment"])
        self.assertIn("warmth", r["adjustment"])

    def test_adjust_disabled(self):
        """停用不调整"""
        engine = AdaptivePersonalityEngine(enabled=False)
        r = engine.adjust("success")
        self.assertFalse(r["applied"])
        self.assertEqual(r["result"], "disabled")

    def test_adjust_custom_step(self):
        """自定义步长"""
        engine = AdaptivePersonalityEngine(step=0.2)
        before = engine.personality()["dimensions"]["warmth"]
        engine.adjust("success")
        after = engine.personality()["dimensions"]["warmth"]
        self.assertAlmostEqual(after - before, 0.2)

    def test_invalid_step_raises(self):
        """step <= 0 → PersonalityError"""
        with self.assertRaises(PersonalityError):
            AdaptivePersonalityEngine(step=0)


class TestAudit(unittest.TestCase):
    """人格审计"""

    def setUp(self):
        self.engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)

    def test_audit_records(self):
        """调整记录"""
        self.engine.adjust("success")
        self.engine.adjust("failure")
        aud = self.engine.audit()
        self.assertEqual(aud["total"], 2)

    def test_audit_structure(self):
        """审计结构"""
        self.engine.adjust("success")
        aud = self.engine.audit()
        self.assertEqual(aud["mode"], "rule_based")
        entry = aud["recent"][0]
        for key in ("record_id", "context", "before_state",
                    "adjustment", "after_state", "result", "timestamp"):
            self.assertIn(key, entry)

    def test_audit_before_after(self):
        """前后状态记录"""
        self.engine.adjust("success")
        entry = self.engine.audit()["recent"][0]
        self.assertEqual(entry["context"], "success")
        self.assertLess(
            entry["before_state"]["dimensions"]["warmth"],
            entry["after_state"]["dimensions"]["warmth"],
        )

    def test_audit_newest_first(self):
        """最新在前"""
        self.engine.adjust("success")
        self.engine.adjust("failure")
        aud = self.engine.audit()
        self.assertEqual(aud["recent"][0]["context"], "failure")

    def test_audit_limit(self):
        """审计限制"""
        self.engine.adjust("success")
        self.engine.adjust("failure")
        aud = self.engine.audit(limit=1)
        self.assertEqual(len(aud["recent"]), 1)

    def test_audit_empty(self):
        """空审计"""
        aud = self.engine.audit()
        self.assertEqual(aud["total"], 0)


class TestStats(unittest.TestCase):
    """互动统计"""

    def setUp(self):
        self.engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)

    def test_stats_initial(self):
        """初始统计"""
        st = self.engine.stats()
        self.assertEqual(st["interactions"], 0)
        self.assertEqual(st["success_count"], 0)
        self.assertEqual(st["failure_count"], 0)
        self.assertEqual(st["success_rate"], 0.0)

    def test_stats_after_success(self):
        """成功后统计"""
        self.engine.adjust("success")
        st = self.engine.stats()
        self.assertEqual(st["interactions"], 1)
        self.assertEqual(st["success_count"], 1)
        self.assertEqual(st["success_rate"], 1.0)

    def test_stats_after_failure(self):
        """失败后统计"""
        self.engine.adjust("failure")
        st = self.engine.stats()
        self.assertEqual(st["failure_count"], 1)
        self.assertEqual(st["success_rate"], 0.0)

    def test_stats_mixed(self):
        """混合统计"""
        self.engine.adjust("success")
        self.engine.adjust("failure")
        st = self.engine.stats()
        self.assertEqual(st["interactions"], 2)
        self.assertEqual(st["success_rate"], 0.5)

    def test_record_interaction(self):
        """手动记录互动"""
        r = self.engine.record_interaction(success=True)
        self.assertEqual(r["interactions"], 1)
        self.assertEqual(r["success_count"], 1)

    def test_stats_only_numbers(self):
        """统计只含数字 (无聊天内容)"""
        st = self.engine.stats()
        self.assertTrue(all(isinstance(v, (int, float))
                            for v in st.values()))

    def test_reset_preserves_stats(self):
        """重置保留统计"""
        self.engine.adjust("success")
        self.engine.reset()
        st = self.engine.stats()
        self.assertEqual(st["interactions"], 1)
        p = self.engine.personality()
        self.assertEqual(p["dimensions"]["warmth"], 0.8)


class TestSingleton(unittest.TestCase):
    """单例"""

    def test_get_service(self):
        """获取单例"""
        reset_personality_service()
        s1 = get_personality_service()
        s2 = get_personality_service()
        self.assertIs(s1, s2)

    def test_reset_service(self):
        """重置单例"""
        s1 = reset_personality_service()
        s2 = reset_personality_service()
        self.assertIsNot(s1, s2)

    def test_singleton_base(self):
        """单例基础人格"""
        reset_personality_service()
        self.assertEqual(get_personality_service().personality()["base"],
                         "铁哥们")


class TestSecurity(unittest.TestCase):
    """安全约束"""

    def setUp(self):
        self.engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)

    def test_base_never_changes(self):
        """多次调整后 base 不变"""
        for ctx in PERSONALITY_CONTEXTS:
            self.engine.adjust(ctx)
        self.assertEqual(self.engine.personality()["base"], "铁哥们")

    def test_no_memory_field(self):
        """状态无 Memory 字段"""
        p = self.engine.personality()
        self.assertNotIn("memory", p)
        self.assertNotIn("chat", p)

    def test_thresholds(self):
        """阈值暴露"""
        th = self.engine.thresholds()
        self.assertEqual(th["base"], "铁哥们")
        self.assertEqual(th["step"], 0.1)
        self.assertTrue(th["enabled"])


class TestAdjustMore(unittest.TestCase):
    """调整更多场景"""

    def setUp(self):
        self.engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)

    def test_success_humor_half_step(self):
        """成功幽默半步长"""
        before = self.engine.personality()["dimensions"]["humor"]
        self.engine.adjust("success")
        after = self.engine.personality()["dimensions"]["humor"]
        self.assertAlmostEqual(after - before, 0.05)

    def test_consecutive_patience_double(self):
        """连续失败耐心双步长"""
        before = self.engine.personality()["dimensions"]["patience"]
        self.engine.adjust("consecutive_fail")
        after = self.engine.personality()["dimensions"]["patience"]
        self.assertAlmostEqual(after - before, 0.2)

    def test_adjust_returns_dimensions(self):
        """调整返回维度"""
        r = self.engine.adjust("success")
        self.assertIn("dimensions", r)

    def test_adjust_base_present(self):
        """调整返回 base"""
        r = self.engine.adjust("success")
        self.assertEqual(r["base"], "铁哥们")

    def test_adjust_applied_flag(self):
        """applied 标志"""
        r = self.engine.adjust("casual_chat")
        self.assertTrue(r["applied"])

    def test_last_adjust_updated(self):
        """last_adjust 更新"""
        self.engine.adjust("success")
        p = self.engine.personality()
        self.assertIn("情境", p["last_adjust"])

    def test_many_adjustments(self):
        """多次调整累积"""
        for _ in range(10):
            self.engine.adjust("success")
        p = self.engine.personality()
        self.assertEqual(p["dimensions"]["warmth"], 1.0)  # 0.8+10*0.1 截断

    def test_enabled_toggle(self):
        """启用开关"""
        self.engine.set_enabled(False)
        r = self.engine.adjust("success")
        self.assertEqual(r["result"], "disabled")
        self.engine.set_enabled(True)
        r = self.engine.adjust("success")
        self.assertTrue(r["applied"])


class TestInferContext(unittest.TestCase):
    """情境推断"""

    def test_infer_success(self):
        """成功 → success"""
        ctx = AdaptivePersonalityEngine.infer_context(result=True)
        self.assertEqual(ctx, "success")

    def test_infer_failure(self):
        """失败 → failure"""
        ctx = AdaptivePersonalityEngine.infer_context(result=False)
        self.assertEqual(ctx, "failure")

    def test_infer_consecutive_fail(self):
        """连续失败 → consecutive_fail"""
        ctx = AdaptivePersonalityEngine.infer_context(
            result=False, consecutive_failures=2,
        )
        self.assertEqual(ctx, "consecutive_fail")

    def test_infer_casual(self):
        """轻松交流 → casual_chat"""
        ctx = AdaptivePersonalityEngine.infer_context(casual=True)
        self.assertEqual(ctx, "casual_chat")

    def test_infer_serious(self):
        """严肃任务 → serious_task"""
        ctx = AdaptivePersonalityEngine.infer_context(serious=True)
        self.assertEqual(ctx, "serious_task")

    def test_infer_default_casual(self):
        """未知 → casual_chat"""
        ctx = AdaptivePersonalityEngine.infer_context()
        self.assertEqual(ctx, "casual_chat")

    def test_infer_success_beats_casual(self):
        """casual 显式优先 (明确轻松交流情境)"""
        ctx = AdaptivePersonalityEngine.infer_context(
            result=True, casual=True,
        )
        self.assertEqual(ctx, "casual_chat")


class TestAuditMore(unittest.TestCase):
    """审计更多场景"""

    def setUp(self):
        self.engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)

    def test_audit_all_contexts(self):
        """全部情境审计"""
        for ctx in PERSONALITY_CONTEXTS:
            self.engine.adjust(ctx)
        aud = self.engine.audit()
        self.assertEqual(aud["total"], len(PERSONALITY_CONTEXTS))

    def test_audit_record_id(self):
        """记录 ID 前缀"""
        self.engine.adjust("success")
        entry = self.engine.audit()["recent"][0]
        self.assertTrue(entry["record_id"].startswith("pa_"))

    def test_audit_after_state(self):
        """after_state 含维度"""
        self.engine.adjust("success")
        entry = self.engine.audit()["recent"][0]
        self.assertIn("dimensions", entry["after_state"])

    def test_audit_result_applied(self):
        """结果标记 applied"""
        self.engine.adjust("success")
        entry = self.engine.audit()["recent"][0]
        self.assertEqual(entry["result"], "applied")


class TestStatsMore(unittest.TestCase):
    """统计更多场景"""

    def setUp(self):
        self.engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)

    def test_stats_after_serious(self):
        """严肃任务计互动 (不计成功/失败)"""
        self.engine.adjust("serious_task")
        st = self.engine.stats()
        self.assertEqual(st["interactions"], 1)
        self.assertEqual(st["success_count"], 0)
        self.assertEqual(st["failure_count"], 0)

    def test_stats_after_casual(self):
        """轻松交流计互动 (不计成功/失败)"""
        self.engine.adjust("casual_chat")
        st = self.engine.stats()
        self.assertEqual(st["interactions"], 1)
        self.assertEqual(st["success_count"], 0)
        self.assertEqual(st["failure_count"], 0)

    def test_stats_success_rate_round(self):
        """成功率保留 4 位"""
        self.engine.adjust("success")
        self.engine.adjust("failure")
        self.engine.adjust("failure")
        st = self.engine.stats()
        self.assertEqual(st["success_rate"], 0.3333)

    def test_record_interaction_failure(self):
        """手动记录失败"""
        r = self.engine.record_interaction(success=False)
        self.assertEqual(r["failure_count"], 1)

    def test_state_snapshot(self):
        """状态快照"""
        self.engine.adjust("success")
        snap = self.engine.personality()
        self.assertIn("base", snap)
        self.assertIn("dimensions", snap)


if __name__ == "__main__":
    unittest.main()
