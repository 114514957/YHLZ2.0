"""
YHLZ Embodied AI V6.3 - 记忆网关单元测试 (Memory Gate)

覆盖 (memory_gate/):
    - 批准规则: 5 维 (来源/重复/价值/身份/风险)
    - 候选校验: 必填字段/值域/长度
    - 网关: 校验 → 反思 → 批准 → 写入 / 拒绝
"""
import unittest

from backend.embodied.companion.perception import (
    ApprovalRule,
    ApprovalRuleError,
    CandidateValidator,
    IDENTITY_KEYWORDS,
    MemoryGate,
    REQUIRED_CANDIDATE_FIELDS,
    RISK_KEYWORDS,
    TRUSTED_SOURCES,
    VALUE_KEYWORDS,
    ValidatorError,
)


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


class TestApprovalRule(unittest.TestCase):
    """批准规则"""

    def setUp(self):
        self.rule = ApprovalRule()

    def test_high_value_approved(self):
        r = self.rule.evaluate(make_candidate())
        self.assertEqual(r["status"], "approved")

    def test_low_value_rejected(self):
        r = self.rule.evaluate(make_candidate(
            source="mock", summary="随机噪声", confidence=0.3,
        ))
        self.assertEqual(r["status"], "rejected")

    def test_result_structure(self):
        r = self.rule.evaluate(make_candidate())
        for key in ("status", "reason", "confidence",
                    "dimensions", "mode"):
            self.assertIn(key, r)

    def test_five_dimensions(self):
        r = self.rule.evaluate(make_candidate())
        names = {d["name"] for d in r["dimensions"]}
        self.assertEqual(names, {"source_trust", "repetition",
                                 "long_term_value",
                                 "identity_impact", "risk"})

    def test_dimension_reasons(self):
        r = self.rule.evaluate(make_candidate())
        for d in r["dimensions"]:
            self.assertTrue(d["reason"])

    def test_risk_blocks_approval(self):
        """高风险直接拒绝"""
        r = self.rule.evaluate(make_candidate(
            summary="执行删除数据库操作",
        ))
        self.assertEqual(r["status"], "rejected")
        self.assertIn("高风险", r["reason"])

    def test_risk_medium_allowed(self):
        """低风险 + 高价值 → 批准"""
        r = self.rule.evaluate(make_candidate(
            summary="用户提到学习计划",
        ))
        self.assertNotIn("高风险", r["reason"])

    def test_source_trust(self):
        d = self.rule._source_trust(make_candidate(source="camera"))
        self.assertEqual(d["score"], 0.9)

    def test_source_unknown_low(self):
        d = self.rule._source_trust(make_candidate(source="weird"))
        self.assertEqual(d["score"], 0.3)

    def test_repetition_single(self):
        d = self.rule._repetition(make_candidate(occurrence_count=1))
        self.assertEqual(d["score"], 0.8)

    def test_repetition_high_low_value(self):
        d = self.rule._repetition(make_candidate(occurrence_count=5))
        self.assertEqual(d["score"], 0.4)

    def test_value_keywords_boost(self):
        d = self.rule._long_term_value(make_candidate(
            summary="重要任务清单目标",
        ))
        self.assertGreater(d["score"], 0.6)

    def test_identity_impact(self):
        d = self.rule._identity_impact(make_candidate(
            summary="身份与人格相关",
        ))
        self.assertGreaterEqual(d["score"], 0.5)

    def test_risk_detected(self):
        d = self.rule._risk(make_candidate(summary="关闭系统"))
        self.assertGreaterEqual(d["score"], 0.5)

    def test_confidence_range(self):
        r = self.rule.evaluate(make_candidate())
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_thresholds(self):
        th = self.rule.thresholds()
        self.assertEqual(th["approve_threshold"], 0.6)
        self.assertEqual(th["reject_threshold"], 0.3)

    def test_threshold_validation(self):
        with self.assertRaises(ApprovalRuleError):
            ApprovalRule(approve_threshold=1.5)

    def test_reject_greater_approve_validation(self):
        with self.assertRaises(ApprovalRuleError):
            ApprovalRule(approve_threshold=0.4,
                         reject_threshold=0.6)

    def test_trusted_sources_constant(self):
        self.assertEqual(TRUSTED_SOURCES["camera"], 0.9)
        self.assertIn("screen", TRUSTED_SOURCES)

    def test_keywords_nonempty(self):
        self.assertTrue(VALUE_KEYWORDS)
        self.assertTrue(IDENTITY_KEYWORDS)
        self.assertTrue(RISK_KEYWORDS)

    def test_mode_rule_based(self):
        r = self.rule.evaluate(make_candidate())
        self.assertEqual(r["mode"], "rule_based")


class TestCandidateValidator(unittest.TestCase):
    """候选校验"""

    def setUp(self):
        self.validator = CandidateValidator()

    def test_valid_candidate(self):
        ok, reason = self.validator.validate(make_candidate())
        self.assertTrue(ok)

    def test_missing_fields(self):
        ok, reason = self.validator.validate({})
        self.assertFalse(ok)
        self.assertIn("为空或非法", reason)

    def test_missing_single_field(self):
        c = make_candidate()
        del c["summary"]
        ok, reason = self.validator.validate(c)
        self.assertFalse(ok)
        self.assertIn("summary", reason)

    def test_bad_source(self):
        ok, reason = self.validator.validate(
            make_candidate(source="hacker"),
        )
        self.assertFalse(ok)
        self.assertIn("来源非法", reason)

    def test_bad_confidence(self):
        ok, reason = self.validator.validate(
            make_candidate(confidence=1.5),
        )
        self.assertFalse(ok)

    def test_summary_too_long(self):
        ok, reason = self.validator.validate(
            make_candidate(summary="x" * 300),
        )
        self.assertFalse(ok)
        self.assertIn("摘要过长", reason)

    def test_none_candidate(self):
        ok, reason = self.validator.validate(None)
        self.assertFalse(ok)

    def test_required_fields_constant(self):
        self.assertIn("candidate_id", REQUIRED_CANDIDATE_FIELDS)
        self.assertIn("summary", REQUIRED_CANDIDATE_FIELDS)

    def test_stats(self):
        self.validator.validate(make_candidate())
        self.validator.validate({})
        st = self.validator.stats()
        self.assertEqual(st["input_count"], 2)
        self.assertEqual(st["passed_count"], 1)
        self.assertEqual(st["rejected_count"], 1)

    def test_clear(self):
        self.validator.validate(make_candidate())
        self.assertEqual(self.validator.clear(), 1)

    def test_max_summary_validation(self):
        with self.assertRaises(ValidatorError):
            CandidateValidator(max_summary_length=0)


class TestMemoryGate(unittest.TestCase):
    """记忆网关"""

    def setUp(self):
        self.gate = MemoryGate()
        self.stored = []

        def store_fn(candidate):
            self.stored.append(candidate)
            return {"id": "exp_1"}

        self.store_fn = store_fn

    def test_high_value_approved_and_stored(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        self.assertEqual(r["status"], "approved")
        self.assertEqual(len(self.stored), 1)

    def test_low_value_rejected(self):
        r = self.gate.process(make_candidate(
            source="mock", summary="随机噪声", confidence=0.3,
        ), store_fn=self.store_fn)
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(self.stored, [])

    def test_steps_recorded(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        steps = [s["step"] for s in r["steps"]]
        self.assertIn("candidate_validator", steps)
        self.assertIn("reflection_evaluation", steps)
        self.assertIn("counterfactual_check", steps)
        self.assertIn("approval", steps)
        self.assertIn("store", steps)

    def test_reflection_fn_called(self):
        calls = []

        def reflect_fn(candidate):
            calls.append(candidate["candidate_id"])
            return "反思通过"

        self.gate.process(make_candidate(),
                          store_fn=self.store_fn,
                          reflect_fn=reflect_fn)
        self.assertEqual(len(calls), 1)

    def test_invalid_candidate_rejected(self):
        r = self.gate.process({}, store_fn=self.store_fn)
        self.assertEqual(r["status"], "rejected")

    def test_approved_no_store_fn(self):
        r = self.gate.process(make_candidate(), store_fn=None)
        self.assertEqual(r["status"], "pending_store")

    def test_store_fn_exception(self):
        def boom(candidate):
            raise RuntimeError("boom")

        r = self.gate.process(make_candidate(), store_fn=boom)
        self.assertEqual(r["status"], "store_failed")

    def test_disabled_gate(self):
        g = MemoryGate(enabled=False)
        r = g.process(make_candidate(), store_fn=self.store_fn)
        self.assertEqual(r["status"], "DISABLED")

    def test_result_structure(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        for key in ("gate_id", "candidate_id", "status", "reason",
                    "confidence", "steps", "mode", "processed_at"):
            self.assertIn(key, r)

    def test_gate_id_prefix(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        self.assertTrue(r["gate_id"].startswith("gate_"))

    def test_high_risk_rejected_no_store(self):
        r = self.gate.process(make_candidate(
            summary="格式化磁盘操作",
        ), store_fn=self.store_fn)
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(self.stored, [])

    def test_stored_candidate_reference(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        self.assertEqual(self.stored[0]["candidate_id"],
                         "mc_1")

    def test_stats(self):
        self.gate.process(make_candidate(),
                          store_fn=self.store_fn)
        self.gate.process(make_candidate(
            source="mock", summary="噪声", confidence=0.2,
        ), store_fn=self.store_fn)
        st = self.gate.stats()
        self.assertEqual(st["candidate_count"], 2)
        self.assertEqual(st["approved_count"], 1)
        self.assertEqual(st["rejected_count"], 1)

    def test_stats_mode(self):
        st = self.gate.stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_history(self):
        self.gate.process(make_candidate(),
                          store_fn=self.store_fn)
        h = self.gate.history()
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["status"], "approved")

    def test_history_limit(self):
        for i in range(4):
            self.gate.process(make_candidate(
                candidate_id=f"mc_{i}",
            ), store_fn=self.store_fn)
        self.assertEqual(len(self.gate.history(limit=2)), 2)

    def test_clear(self):
        self.gate.process(make_candidate(),
                          store_fn=self.store_fn)
        self.assertEqual(self.gate.clear(), 1)


class TestGateIntegration(unittest.TestCase):
    """网关与候选集成"""

    def test_duplicate_low_value_rejected(self):
        """重复内容降价值 → 拒绝"""
        g = MemoryGate()
        r = g.process(make_candidate(
            occurrence_count=4, source="mock",
            summary="重复噪音文本", confidence=0.4,
        ), store_fn=lambda c: {})
        self.assertEqual(r["status"], "rejected")

    def test_medium_value_pending(self):
        """中间价值 → 拒绝 (未达批准阈值, 不写入)"""
        g = MemoryGate()
        r = g.process(make_candidate(
            source="mock", summary="普通观察", confidence=0.5,
        ), store_fn=lambda c: {})
        self.assertNotEqual(r["status"], "approved")

    def test_approved_confidence(self):
        g = MemoryGate()
        r = g.process(make_candidate(),
                      store_fn=lambda c: {})
        self.assertGreaterEqual(r["confidence"], 0.5)


if __name__ == "__main__":
    unittest.main()
