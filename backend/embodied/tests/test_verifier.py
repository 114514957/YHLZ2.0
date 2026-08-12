"""
YHLZ Embodied AI V5.8 - 经验验证器单元测试 (Experience Verifier)

覆盖 (experience_verifier.py):
    - 状态机: UNKNOWN → PENDING → PROBABLE → CONFIRMED / REJECTED
    - 验证流程: 证据/反例/来源可靠 → 状态转移
    - 阈值: confirm_threshold / reject_threshold
    - 查询: by_status / confirmed_ids / rejected_ids / stats
    - 可回溯: 状态转移历史
    - 参数校验
"""
import unittest

from backend.embodied.companion.verification import (
    VERIFICATION_STATUSES,
    ExperienceVerifier,
    VerifierError,
)


class TestVerifierStateMachine(unittest.TestCase):
    """验证状态机"""

    def setUp(self):
        self.verifier = ExperienceVerifier(
            confirm_threshold=2, reject_threshold=2,
        )

    def test_initial_unknown(self):
        """首次验证 → PENDING (有证据)"""
        v = self.verifier.verify("exp_1", evidence_count=1,
                                 contradictions=0)
        self.assertEqual(v["status"], "PENDING")

    def test_second_verification_probable(self):
        """第二次验证 → PROBABLE"""
        self.verifier.verify("exp_1", evidence_count=1)
        v = self.verifier.verify("exp_1", evidence_count=1)
        self.assertEqual(v["status"], "PROBABLE")

    def test_confirm_threshold(self):
        """达确认阈值 → CONFIRMED"""
        self.verifier.verify("exp_1", evidence_count=1)
        self.verifier.verify("exp_1", evidence_count=1)
        v = self.verifier.verify("exp_1", evidence_count=1)
        self.assertEqual(v["status"], "CONFIRMED")

    def test_reject_threshold(self):
        """达拒绝阈值 → REJECTED"""
        self.verifier.verify("exp_1", contradictions=1)
        v = self.verifier.verify("exp_1", contradictions=1)
        self.assertEqual(v["status"], "REJECTED")

    def test_unreliable_source(self):
        """不可靠来源 → 反例处理"""
        self.verifier.verify("exp_1", source_reliable=False)
        v = self.verifier.verify("exp_1", source_reliable=False)
        self.assertEqual(v["status"], "REJECTED")

    def test_confirmed_can_reject(self):
        """CONFIRMED 遇反例 → 可降级 REJECTED"""
        self.verifier.verify("exp_1", evidence_count=1)
        self.verifier.verify("exp_1", evidence_count=1)
        self.verifier.verify("exp_1", evidence_count=1)  # CONFIRMED
        v = self.verifier.verify("exp_1", contradictions=1)
        v = self.verifier.verify("exp_1", contradictions=1)
        self.assertEqual(v["status"], "REJECTED")

    def test_rejected_can_reverify(self):
        """REJECTED 有新证据 → 重新 PENDING"""
        self.verifier.verify("exp_1", contradictions=1)
        self.verifier.verify("exp_1", contradictions=1)  # REJECTED
        v = self.verifier.verify("exp_1", evidence_count=2)
        self.assertIn(v["status"], ("PENDING", "PROBABLE"))

    def test_statuses_whitelist(self):
        """状态白名单"""
        self.assertEqual(set(VERIFICATION_STATUSES),
                         {"UNKNOWN", "PENDING", "PROBABLE",
                          "CONFIRMED", "REJECTED"})


class TestVerifierQuery(unittest.TestCase):
    """验证查询"""

    def setUp(self):
        self.verifier = ExperienceVerifier(
            confirm_threshold=2, reject_threshold=2,
        )
        self.verifier.verify("exp_a", evidence_count=1)
        self.verifier.verify("exp_a", evidence_count=1)
        self.verifier.verify("exp_a", evidence_count=1)  # CONFIRMED
        self.verifier.verify("exp_b", contradictions=1)
        self.verifier.verify("exp_b", contradictions=1)  # REJECTED
        self.verifier.verify("exp_c", evidence_count=1)  # PENDING

    def test_get(self):
        """查询状态"""
        v = self.verifier.get("exp_a")
        self.assertEqual(v["status"], "CONFIRMED")
        self.assertIsNone(self.verifier.get("nope"))

    def test_by_status(self):
        """按状态查询"""
        confirmed = self.verifier.by_status("CONFIRMED")
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["experience_id"], "exp_a")

    def test_by_status_invalid(self):
        """非法状态 → 异常"""
        with self.assertRaises(VerifierError):
            self.verifier.by_status("hack")

    def test_confirmed_ids(self):
        """已确认 ID"""
        self.assertEqual(self.verifier.confirmed_ids(), ["exp_a"])

    def test_rejected_ids(self):
        """已拒绝 ID"""
        self.assertEqual(self.verifier.rejected_ids(), ["exp_b"])

    def test_stats(self):
        """统计"""
        st = self.verifier.stats()
        self.assertEqual(st["total"], 3)
        self.assertEqual(st["confirmed"], 1)
        self.assertEqual(st["rejected"], 1)
        self.assertEqual(st["pending"], 1)
        self.assertEqual(st["mode"], "rule_based")


class TestVerifierHistory(unittest.TestCase):
    """可回溯"""

    def test_history_recorded(self):
        """状态转移历史"""
        self.verifier = ExperienceVerifier(confirm_threshold=2)
        self.verifier.verify("exp_1", evidence_count=1)
        self.verifier.verify("exp_1", evidence_count=1)
        v = self.verifier.get("exp_1")
        self.assertGreaterEqual(len(v["history"]), 2)
        # 历史含 from/to/reason
        entry = v["history"][0]
        for key in ("from", "to", "reason", "timestamp"):
            self.assertIn(key, entry)

    def test_verifications_count(self):
        """验证次数"""
        self.verifier = ExperienceVerifier()
        self.verifier.verify("exp_1")
        self.verifier.verify("exp_1")
        v = self.verifier.get("exp_1")
        self.assertEqual(v["verifications"], 2)

    def test_confirmations_count(self):
        """确认次数"""
        self.verifier = ExperienceVerifier()
        self.verifier.verify("exp_1", evidence_count=1)
        self.verifier.verify("exp_1", evidence_count=1)
        v = self.verifier.get("exp_1")
        self.assertEqual(v["confirmations"], 2)


class TestVerifierValidation(unittest.TestCase):
    """参数校验"""

    def test_invalid_confirm_threshold(self):
        """confirm_threshold <= 0 → 异常"""
        with self.assertRaises(VerifierError):
            ExperienceVerifier(confirm_threshold=0)

    def test_invalid_reject_threshold(self):
        """reject_threshold <= 0 → 异常"""
        with self.assertRaises(VerifierError):
            ExperienceVerifier(reject_threshold=0)

    def test_clear(self):
        """清空"""
        verifier = ExperienceVerifier()
        verifier.verify("exp_1")
        self.assertEqual(verifier.clear(), 1)
        self.assertEqual(verifier.stats()["total"], 0)

    def test_thresholds_exposed(self):
        """阈值暴露"""
        verifier = ExperienceVerifier(confirm_threshold=3,
                                      reject_threshold=1)
        st = verifier.stats()
        self.assertEqual(st["confirm_threshold"], 3)
        self.assertEqual(st["reject_threshold"], 1)


class TestVerifierMore(unittest.TestCase):
    """验证更多场景"""

    def setUp(self):
        self.verifier = ExperienceVerifier(confirm_threshold=2,
                                           reject_threshold=2)

    def test_multiple_experiences_independent(self):
        """多经验独立状态"""
        self.verifier.verify("a", evidence_count=1)
        self.verifier.verify("b", contradictions=1)
        st = self.verifier.stats()
        self.assertEqual(st["total"], 2)

    def test_evidence_accumulates_status(self):
        """证据累积 → 状态推进"""
        statuses = []
        for _ in range(4):
            v = self.verifier.verify("e", evidence_count=1)
            statuses.append(v["status"])
        self.assertEqual(statuses[0], "PENDING")
        self.assertEqual(statuses[1], "PROBABLE")
        self.assertEqual(statuses[2], "CONFIRMED")

    def test_rejections_accumulate(self):
        """拒绝累积"""
        v1 = self.verifier.verify("r", contradictions=1)
        v2 = self.verifier.verify("r", contradictions=1)
        self.assertEqual(v1["rejections"], 1)
        self.assertEqual(v2["rejections"], 2)

    def test_get_missing_none(self):
        """不存在 → None"""
        self.assertIsNone(self.verifier.get("zzz"))

    def test_history_timestamps(self):
        """历史时间戳"""
        self.verifier.verify("h", evidence_count=1)
        v = self.verifier.get("h")
        self.assertGreater(v["history"][0]["timestamp"], 0)

    def test_verification_state_fields(self):
        """状态字段"""
        self.verifier.verify("f", evidence_count=1)
        v = self.verifier.get("f")
        for key in ("experience_id", "status", "verifications",
                    "confirmations", "rejections", "last_change",
                    "history"):
            self.assertIn(key, v)

    def test_stats_by_status_all(self):
        """统计全部状态"""
        self.verifier.verify("a", evidence_count=1)  # PENDING
        self.verifier.verify("b", contradictions=1)
        self.verifier.verify("b", contradictions=1)  # REJECTED
        st = self.verifier.stats()
        self.assertIn("PENDING", st["by_status"])
        self.assertIn("REJECTED", st["by_status"])


if __name__ == "__main__":
    unittest.main()
