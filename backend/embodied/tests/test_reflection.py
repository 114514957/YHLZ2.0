"""
YHLZ Embodied AI V5.8 - 反思层单元测试 (Reflection Layer)

覆盖:
    - PatternDiscovery: 模式发现 (样本/跨度/重复/反例限制)
    - FailureAnalysisEngine: 失败分析 (原因推断/证据/置信度/建议)
    - ImprovementProposalEngine: 改进建议 (Proposal ≠ Action, 审批流)
"""
import time
import unittest

from backend.embodied.companion.reflection import (
    FAILURE_REASONS,
    FailureAnalysisEngine,
    FailureError,
    ImprovementProposalEngine,
    PatternDiscovery,
    PatternError,
    ProposalError,
)


def make_record(trigger="拾取失败", type="failure", lesson="先扫描",
                result="失败", action="pick", ts_offset_days=0):
    return {
        "id": f"exp_{trigger}_{ts_offset_days}",
        "type": type,
        "trigger": trigger,
        "lesson": lesson,
        "result": result,
        "action": action,
        "timestamp": time.time() - ts_offset_days * 86400,
    }


class TestPatternDiscovery(unittest.TestCase):
    """模式发现"""

    def setUp(self):
        self.pd = PatternDiscovery(min_occurrences=3,
                                   min_span_days=1.0)

    def test_single_event_no_pattern(self):
        """单次事件不形成模式"""
        r = self.pd.discover([make_record(ts_offset_days=0)])
        self.assertEqual(r["valid_count"], 0)

    def test_insufficient_occurrences(self):
        """次数不足 → 无效"""
        records = [
            make_record(ts_offset_days=i)
            for i in range(2)  # 2 < 3
        ]
        r = self.pd.discover(records)
        self.assertEqual(r["valid_count"], 0)

    def test_sufficient_occurrences(self):
        """达次数+跨度 → 有效模式"""
        records = [
            make_record(ts_offset_days=i * 2)
            for i in range(3)  # 3 次, 跨度 4 天
        ]
        r = self.pd.discover(records)
        self.assertEqual(r["valid_count"], 1)
        p = r["valid_patterns"][0]
        self.assertEqual(p["occurrences"], 3)
        self.assertGreaterEqual(p["span_days"], 1.0)

    def test_same_time_no_span(self):
        """同时间多次 → 跨度不足 → 无效"""
        records = [
            make_record(ts_offset_days=0)
            for _ in range(3)
        ]
        r = self.pd.discover(records)
        self.assertEqual(r["valid_count"], 0)

    def test_pattern_structure(self):
        """模式结构"""
        records = [make_record(ts_offset_days=i) for i in range(3)]
        r = self.pd.discover(records)
        p = r["patterns"][0]
        for key in ("pattern_id", "key", "type", "trigger",
                    "occurrences", "span_days", "contradictions",
                    "lesson", "valid", "reason"):
            self.assertIn(key, p)

    def test_reason_explainable(self):
        """原因可解释"""
        records = [make_record(ts_offset_days=i) for i in range(2)]
        r = self.pd.discover(records)
        self.assertIn("需 >=", r["patterns"][0]["reason"])

    def test_sort_by_occurrences(self):
        """按次数降序"""
        records = [
            make_record(trigger="高频", ts_offset_days=i)
            for i in range(5)
        ] + [
            make_record(trigger="低频", ts_offset_days=i)
            for i in range(3)
        ]
        r = self.pd.discover(records)
        self.assertGreaterEqual(
            r["patterns"][0]["occurrences"],
            r["patterns"][1]["occurrences"],
        )

    def test_thresholds(self):
        """阈值"""
        th = self.pd.thresholds()
        self.assertEqual(th["min_occurrences"], 3)
        self.assertEqual(th["min_span_days"], 1.0)

    def test_invalid_occurrences(self):
        """min_occurrences <= 0 → 异常"""
        with self.assertRaises(PatternError):
            PatternDiscovery(min_occurrences=0)

    def test_contradictions_invalidate(self):
        """反例使模式无效"""
        pd = PatternDiscovery(min_occurrences=2,
                              min_span_days=0.0,
                              max_contradictions=0)
        records = [
            make_record(result="成功", ts_offset_days=0),
            make_record(result="失败", ts_offset_days=1),
        ]
        r = pd.discover(records)
        self.assertEqual(r["valid_count"], 0)


class TestFailureAnalysis(unittest.TestCase):
    """失败分析"""

    def setUp(self):
        self.engine = FailureAnalysisEngine()

    def test_infer_execution(self):
        """执行原因"""
        self.assertEqual(
            self.engine.infer_reason("位置不匹配"),
            "execution",
        )

    def test_infer_permission(self):
        """权限原因"""
        self.assertEqual(
            self.engine.infer_reason("embodied_enabled=False"),
            "permission",
        )

    def test_infer_environment(self):
        """环境原因"""
        self.assertEqual(
            self.engine.infer_reason("对象不存在"),
            "environment",
        )

    def test_infer_unknown(self):
        """未知原因"""
        self.assertEqual(
            self.engine.infer_reason("随便的错误"),
            "unknown",
        )

    def test_analyze_structure(self):
        """分析结构"""
        r = self.engine.analyze(failure="拾取失败",
                                error="位置不匹配", action="pick")
        for key in ("analysis_id", "failure", "possible_reason",
                    "evidence", "confidence", "correction_proposal",
                    "timestamp", "mode"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")

    def test_analyze_evidence(self):
        """证据收集"""
        r = self.engine.analyze(failure="失败", error="错误X",
                                action="pick")
        self.assertGreaterEqual(len(r["evidence"]), 2)

    def test_analyze_confidence(self):
        """置信度 (有错误+动作 → 0.8)"""
        r = self.engine.analyze(failure="失败", error="错误X",
                                action="pick")
        self.assertEqual(r["confidence"], 0.8)

    def test_analyze_confidence_no_info(self):
        """无信息 → 0.4"""
        r = self.engine.analyze(failure="失败")
        self.assertEqual(r["confidence"], 0.4)

    def test_proposal_by_reason(self):
        """修正建议按原因"""
        r = self.engine.analyze(failure="失败",
                                error="embodied_enabled=False")
        self.assertIn("权限", r["correction_proposal"])

    def test_reasons_whitelist(self):
        """原因白名单"""
        self.assertIn("execution", FAILURE_REASONS)
        self.assertIn("unknown", FAILURE_REASONS)

    def test_stats(self):
        """统计"""
        self.engine.analyze(failure="a", error="位置")
        self.engine.analyze(failure="b", error="对象")
        st = self.engine.stats()
        self.assertEqual(st["total"], 2)
        self.assertEqual(st["by_reason"]["execution"], 1)

    def test_clear(self):
        """清空"""
        self.engine.analyze(failure="a")
        self.assertEqual(self.engine.clear(), 1)
        self.assertEqual(self.engine.stats()["total"], 0)


class TestImprovementProposal(unittest.TestCase):
    """改进建议 (Proposal ≠ Action)"""

    def setUp(self):
        self.engine = ImprovementProposalEngine()

    def test_create(self):
        """创建建议"""
        p = self.engine.create(trigger="频繁失败",
                               suggestion="调整策略",
                               basis="3 次失败经验")
        self.assertEqual(p["status"], "PENDING_APPROVAL")
        self.assertTrue(p["proposal_id"].startswith("prop_"))

    def test_create_structure(self):
        """结构"""
        p = self.engine.create(trigger="t", suggestion="s")
        for key in ("proposal_id", "trigger", "suggestion",
                    "basis", "expected_impact", "risk", "status",
                    "created_at", "approved_at", "reason"):
            self.assertIn(key, p)

    def test_approve(self):
        """批准"""
        p = self.engine.create(trigger="t", suggestion="s")
        a = self.engine.approve(p["proposal_id"])
        self.assertEqual(a["status"], "APPROVED")
        self.assertGreater(a["approved_at"], 0)

    def test_approve_wrong_status(self):
        """重复批准 → 异常"""
        p = self.engine.create(trigger="t", suggestion="s")
        self.engine.approve(p["proposal_id"])
        with self.assertRaises(ProposalError):
            self.engine.approve(p["proposal_id"])

    def test_reject(self):
        """拒绝"""
        p = self.engine.create(trigger="t", suggestion="s")
        r = self.engine.reject(p["proposal_id"], "不适用")
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(r["reason"], "不适用")

    def test_execute_requires_approval(self):
        """未批准不可执行 (Proposal ≠ Action)"""
        p = self.engine.create(trigger="t", suggestion="s")
        with self.assertRaises(ProposalError):
            self.engine.execute(p["proposal_id"])

    def test_execute_after_approval(self):
        """批准后可执行"""
        p = self.engine.create(trigger="t", suggestion="s")
        self.engine.approve(p["proposal_id"])
        e = self.engine.execute(p["proposal_id"])
        self.assertEqual(e["status"], "EXECUTED")

    def test_get(self):
        """查询"""
        p = self.engine.create(trigger="t", suggestion="s")
        got = self.engine.get(p["proposal_id"])
        self.assertEqual(got["suggestion"], "s")
        self.assertIsNone(self.engine.get("nope"))

    def test_by_status(self):
        """按状态"""
        self.engine.create(trigger="a", suggestion="s1")
        p2 = self.engine.create(trigger="b", suggestion="s2")
        self.engine.approve(p2["proposal_id"])
        pending = self.engine.by_status("PENDING_APPROVAL")
        approved = self.engine.by_status("APPROVED")
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(approved), 1)

    def test_stats(self):
        """统计"""
        p = self.engine.create(trigger="t", suggestion="s")
        self.engine.approve(p["proposal_id"])
        st = self.engine.stats()
        self.assertEqual(st["total"], 1)
        self.assertEqual(st["approved"], 1)

    def test_missing_proposal(self):
        """不存在建议 → 异常"""
        with self.assertRaises(ProposalError):
            self.engine.approve("nope")


class TestPatternMore(unittest.TestCase):
    """模式更多场景"""

    def setUp(self):
        self.pd = PatternDiscovery(min_occurrences=2,
                                   min_span_days=0.0)

    def test_two_occurrences_valid(self):
        """2 次即有效 (阈值 2)"""
        records = [make_record(ts_offset_days=i) for i in range(2)]
        r = self.pd.discover(records)
        self.assertEqual(r["valid_count"], 1)

    def test_type_in_key(self):
        """类型参与模式键"""
        r1 = self.pd.discover([make_record(type="failure",
                                           ts_offset_days=i)
                               for i in range(2)])
        r2 = self.pd.discover([make_record(type="improvement",
                                           ts_offset_days=i)
                               for i in range(2)])
        self.assertNotEqual(r1["patterns"][0]["key"],
                            r2["patterns"][0]["key"])

    def test_lesson_from_latest(self):
        """教训取最新"""
        records = [
            make_record(lesson="旧", ts_offset_days=2),
            make_record(lesson="新", ts_offset_days=0),
        ]
        r = self.pd.discover(records)
        self.assertEqual(r["patterns"][0]["lesson"], "新")

    def test_span_calculation(self):
        """跨度计算"""
        records = [
            make_record(ts_offset_days=0),
            make_record(ts_offset_days=2),
        ]
        r = self.pd.discover(records)
        self.assertAlmostEqual(r["patterns"][0]["span_days"], 2.0)


class TestFailureMore(unittest.TestCase):
    """失败分析更多场景"""

    def setUp(self):
        self.engine = FailureAnalysisEngine()

    def test_infer_strategy(self):
        """策略原因"""
        self.assertEqual(
            self.engine.infer_reason("策略选择不当"),
            "strategy",
        )

    def test_infer_boundary(self):
        """边界执行原因"""
        self.assertEqual(
            self.engine.infer_reason("boundary limit"),
            "execution",
        )

    def test_custom_evidence(self):
        """自定义证据"""
        r = self.engine.analyze(failure="f", error="e",
                                evidence=["自定义证据"])
        self.assertIn("自定义证据", r["evidence"])

    def test_proposal_environment(self):
        """环境修正建议"""
        r = self.engine.analyze(failure="f", error="对象不存在")
        self.assertIn("观察环境", r["correction_proposal"])

    def test_confidence_with_action_only(self):
        """仅动作 → 0.6"""
        r = self.engine.analyze(failure="f", action="pick")
        self.assertEqual(r["confidence"], 0.6)


class TestProposalMore(unittest.TestCase):
    """建议更多场景"""

    def setUp(self):
        self.engine = ImprovementProposalEngine(max_proposals=3)

    def test_max_proposals(self):
        """建议上限"""
        self.engine.create(trigger="a", suggestion="s1")
        self.engine.create(trigger="b", suggestion="s2")
        self.engine.create(trigger="c", suggestion="s3")
        with self.assertRaises(ProposalError):
            self.engine.create(trigger="d", suggestion="s4")

    def test_reject_reason_default(self):
        """默认拒绝原因"""
        p = self.engine.create(trigger="t", suggestion="s")
        r = self.engine.reject(p["proposal_id"])
        self.assertEqual(r["reason"], "人工/系统拒绝")

    def test_execute_timestamp(self):
        """执行时间戳"""
        p = self.engine.create(trigger="t", suggestion="s")
        self.engine.approve(p["proposal_id"])
        e = self.engine.execute(p["proposal_id"])
        self.assertGreater(e["executed_at"], 0)

    def test_stats_by_status_complete(self):
        """统计含全状态"""
        p1 = self.engine.create(trigger="t1", suggestion="s1")
        p2 = self.engine.create(trigger="t2", suggestion="s2")
        self.engine.approve(p2["proposal_id"])
        st = self.engine.stats()
        self.assertIn("PENDING_APPROVAL", st["by_status"])
        self.assertIn("APPROVED", st["by_status"])


if __name__ == "__main__":
    unittest.main()
