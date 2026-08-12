"""
YHLZ Embodied AI V5.8 - 反思引擎集成测试 (Reflection Engine)

覆盖 (reflection_engine.py):
    - Reflection Report 结构: observation/evidence/pattern/risk/suggestion/confidence
    - 模式/失败/建议集成
    - 带验证反思 (只 CONFIRMED)
    - 统计: reflection/pattern/proposal/failure counts
    - 审计 (reflection_audit)
"""
import time
import unittest

from backend.embodied.companion.reflection import (
    REFLECTION_AUDIT_ACTIONS,
    ReflectionAudit,
    ReflectionAuditError,
    ReflectionEngine,
)

def make_record(trigger="扫描成功", type="improvement", lesson="路径可复用",
                result="成功", action="scan", rid=None, ts_offset=0):
    return {
        "id": rid or f"exp_{trigger}_{ts_offset}",
        "type": type,
        "trigger": trigger,
        "lesson": lesson,
        "result": result,
        "action": action,
        "timestamp": time.time() - ts_offset * 86400,
    }


class TestReflectionEngine(unittest.TestCase):
    """反思引擎"""

    def setUp(self):
        self.engine = ReflectionEngine()

    def test_empty_reflect(self):
        """空经历反思"""
        r = self.engine.reflect([])
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("report_id", r)
        self.assertTrue(r["report_id"].startswith("ref_"))

    def test_report_structure(self):
        """报告结构"""
        records = [
            make_record(ts_offset=i) for i in range(5)
        ]
        r = self.engine.reflect(records)
        for key in ("report_id", "mode", "observation", "evidence",
                    "pattern", "risk", "suggestion", "confidence",
                    "patterns", "failure_analyses", "proposals",
                    "generated_at"):
            self.assertIn(key, r)

    def test_patterns_detected(self):
        """模式检测"""
        records = [
            make_record(trigger="高频成功", ts_offset=i)
            for i in range(5)
        ]
        r = self.engine.reflect(records)
        self.assertGreaterEqual(len(r["patterns"]), 1)

    def test_failure_analysis(self):
        """失败分析"""
        records = [
            make_record(trigger="拾取失败", type="failure",
                        result="位置不匹配", ts_offset=i)
            for i in range(3)
        ]
        r = self.engine.reflect(records)
        self.assertGreaterEqual(len(r["failure_analyses"]), 3)
        self.assertEqual(r["failure_analyses"][0]["possible_reason"],
                         "execution")

    def test_risk_assessment(self):
        """风险评估"""
        records = [
            make_record(type="failure", ts_offset=i)
            for i in range(6)  # 6 次失败 → high
        ]
        r = self.engine.reflect(records)
        self.assertEqual(r["risk"], "high")

    def test_risk_low(self):
        """低风险"""
        records = [make_record(ts_offset=0)]
        r = self.engine.reflect(records)
        self.assertEqual(r["risk"], "low")

    def test_suggestion_from_pattern(self):
        """模式建议"""
        records = [
            make_record(trigger="高频模式", ts_offset=i)
            for i in range(5)
        ]
        r = self.engine.reflect(records)
        self.assertIn("建议", r["suggestion"])

    def test_confidence_calculated(self):
        """置信度"""
        records = [
            make_record(ts_offset=i) for i in range(10)
        ]
        r = self.engine.reflect(records)
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_evidence_listed(self):
        """证据列表"""
        records = [make_record(ts_offset=i) for i in range(3)]
        r = self.engine.reflect(records)
        self.assertGreaterEqual(len(r["evidence"]), 2)

    def test_proposal_created(self):
        """建议生成 (Proposal ≠ Action)"""
        records = [
            make_record(trigger="模式建议", ts_offset=i)
            for i in range(5)
        ]
        r = self.engine.reflect(records)
        self.assertGreaterEqual(len(r["proposals"]), 1)
        self.assertEqual(r["proposals"][0]["status"],
                         "PENDING_APPROVAL")

    def test_observation(self):
        """观察文本"""
        records = [make_record(ts_offset=0)]
        r = self.engine.reflect(records)
        self.assertIn("观察 1 条经历", r["observation"])


class TestVerifiedReflection(unittest.TestCase):
    """带验证反思"""

    def setUp(self):
        self.engine = ReflectionEngine()

    def test_only_confirmed(self):
        """只反思 CONFIRMED"""
        records = [
            make_record(rid="a", ts_offset=0),
            make_record(rid="b", ts_offset=1),
        ]
        r = self.engine.reflect_with_verification(records, ["a"])
        # 只有 a 参与 → 观察 1 条
        self.assertIn("观察 1 条经历", r["observation"])

    def test_no_confirmed(self):
        """无 CONFIRMED → 空反思"""
        records = [make_record(rid="a", ts_offset=0)]
        r = self.engine.reflect_with_verification(records, [])
        self.assertIn("观察 0 条经历", r["observation"])

    def test_all_confirmed(self):
        """全部 CONFIRMED"""
        records = [
            make_record(rid=f"r{i}", ts_offset=i)
            for i in range(3)
        ]
        r = self.engine.reflect_with_verification(
            records, ["r0", "r1", "r2"],
        )
        self.assertIn("观察 3 条经历", r["observation"])


class TestReflectionStats(unittest.TestCase):
    """反思统计"""

    def setUp(self):
        self.engine = ReflectionEngine()

    def test_stats_empty(self):
        """空统计"""
        st = self.engine.stats()
        self.assertEqual(st["reflection_count"], 0)
        self.assertEqual(st["pattern_count"], 0)

    def test_stats_after_reflect(self):
        """反思后统计"""
        records = [
            make_record(trigger="模式", ts_offset=i)
            for i in range(5)
        ]
        self.engine.reflect(records)
        st = self.engine.stats()
        self.assertEqual(st["reflection_count"], 1)
        self.assertGreaterEqual(st["pattern_count"], 0)
        self.assertIn("proposal_count", st)

    def test_clear(self):
        """清空"""
        self.engine.reflect([make_record(ts_offset=0)])
        self.assertEqual(self.engine.clear(), 1)
        self.assertEqual(self.engine.stats()["reflection_count"], 0)


class TestReflectionAudit(unittest.TestCase):
    """反思审计"""

    def setUp(self):
        self.audit = ReflectionAudit()

    def test_record(self):
        """记录"""
        self.audit.record(action="reflect", detail="报告")
        r = self.audit.report()
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["by_action"]["reflect"], 1)

    def test_actions_whitelist(self):
        """动作白名单"""
        self.assertIn("reflect", REFLECTION_AUDIT_ACTIONS)
        self.assertIn("verify", REFLECTION_AUDIT_ACTIONS)
        self.assertIn("approve", REFLECTION_AUDIT_ACTIONS)

    def test_invalid_action(self):
        """非法动作 → 异常"""
        with self.assertRaises(ReflectionAuditError):
            self.audit.record(action="hack")

    def test_record_structure(self):
        """记录结构"""
        self.audit.record(action="pattern", detail="发现模式")
        r = self.audit.report()
        entry = r["recent"][0]
        for key in ("audit_id", "action", "detail", "ref_id",
                    "timestamp"):
            self.assertIn(key, entry)

    def test_clear(self):
        """清空"""
        self.audit.record(action="reflect")
        self.assertEqual(self.audit.clear(), 1)
        self.assertEqual(self.audit.report()["total"], 0)


class TestReflectionMore(unittest.TestCase):
    """反思更多场景"""

    def setUp(self):
        self.engine = ReflectionEngine()

    def test_report_id_unique(self):
        """报告 ID 唯一"""
        r1 = self.engine.reflect([])
        r2 = self.engine.reflect([])
        self.assertNotEqual(r1["report_id"], r2["report_id"])

    def test_generated_at(self):
        """生成时间"""
        r = self.engine.reflect([])
        self.assertGreater(r["generated_at"], 0)

    def test_pattern_reason(self):
        """模式原因"""
        records = [make_record(ts_offset=i) for i in range(5)]
        r = self.engine.reflect(records)
        self.assertIn("出现", r["patterns"][0]["reason"])

    def test_suggestion_from_failure(self):
        """失败建议 (无模式时)"""
        records = [
            make_record(trigger=f"失败{i}", type="failure",
                        result="位置不匹配", ts_offset=i)
            for i in range(3)
        ]
        r = self.engine.reflect(records)
        self.assertIn("调整策略", r["suggestion"])

    def test_evidence_failure_detail(self):
        """证据含失败详情"""
        records = [
            make_record(type="failure", result="位置不匹配",
                        ts_offset=i)
            for i in range(2)
        ]
        r = self.engine.reflect(records)
        self.assertTrue(any("失败" in e for e in r["evidence"]))

    def test_proposal_pending(self):
        """建议待批准"""
        records = [
            make_record(trigger="p", ts_offset=i)
            for i in range(5)
        ]
        r = self.engine.reflect(records)
        if r["proposals"]:
            self.assertEqual(r["proposals"][0]["status"],
                             "PENDING_APPROVAL")

    def test_stats_failure_count(self):
        """失败分析计数"""
        records = [
            make_record(type="failure", ts_offset=i)
            for i in range(3)
        ]
        self.engine.reflect(records)
        st = self.engine.stats()
        self.assertGreaterEqual(st["failure_analysis_count"], 3)

    def test_audit_actions_full(self):
        """审计动作完整"""
        for action in ("reflect", "pattern", "failure", "proposal",
                       "approve", "reject", "execute", "verify",
                       "contradiction"):
            self.assertIn(action, REFLECTION_AUDIT_ACTIONS)

    def test_reflect_returns_copy(self):
        """报告为副本 (不共享)"""
        r1 = self.engine.reflect([make_record(ts_offset=0)])
        r1["observation"] = "修改"
        r2 = self.engine.reflect([make_record(ts_offset=0)])
        self.assertNotEqual(r1["observation"], r2["observation"])

    def test_pattern_multiple_types(self):
        """多类型模式"""
        records = [
            make_record(type="improvement", trigger="成功",
                        ts_offset=i)
            for i in range(4)
        ] + [
            make_record(type="failure", trigger="失败",
                        ts_offset=i)
            for i in range(4)
        ]
        r = self.engine.reflect(records)
        self.assertGreaterEqual(len(r["patterns"]), 2)

    def test_evidence_count_matches(self):
        """证据与经历关联"""
        records = [make_record(ts_offset=i) for i in range(5)]
        r = self.engine.reflect(records)
        self.assertTrue(any("5 条" in e for e in r["evidence"]))

    def test_risk_medium(self):
        """中风险"""
        records = [
            make_record(type="failure", ts_offset=i)
            for i in range(3)
        ]
        r = self.engine.reflect(records)
        self.assertEqual(r["risk"], "medium")

    def test_confidence_zero_empty(self):
        """空经历置信度低"""
        r = self.engine.reflect([])
        self.assertLessEqual(r["confidence"], 0.2)

    def test_audit_limit(self):
        """审计限制"""
        audit = ReflectionAudit(max_records=10)
        for i in range(12):
            audit.record(action="reflect", detail=str(i))
        r = audit.report()
        self.assertEqual(r["total"], 10)

    def test_audit_invalid_max(self):
        """审计上限校验"""
        with self.assertRaises(ReflectionAuditError):
            ReflectionAudit(max_records=0)

    def test_reflection_stats_after_multiple(self):
        """多次反思统计"""
        self.engine.reflect([make_record(ts_offset=0)])
        self.engine.reflect([make_record(ts_offset=0)])
        st = self.engine.stats()
        self.assertEqual(st["reflection_count"], 2)


if __name__ == "__main__":
    unittest.main()
