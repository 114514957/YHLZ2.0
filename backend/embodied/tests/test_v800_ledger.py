"""
YHLZ Embodied AI V8.0 - 治理总账与演化建议单元测试 (Ledger & Evolution)

覆盖:
    - ConstitutionLedger: 记录/报告/回放
    - EvolutionProposal: 演化建议/审批
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionLedger,
    EvolutionProposal,
)
from backend.embodied.companion.constitution.audit.constitution_ledger import (
    LedgerError,
)
from backend.embodied.companion.constitution.proposal.evolution_proposal import (
    PROPOSAL_STATUS,
    EvolutionProposalError,
)


class TestConstitutionLedger(unittest.TestCase):
    """治理总账"""

    def setUp(self):
        self.ledger = ConstitutionLedger()

    def test_record_structure(self):
        entry = self.ledger.record(
            module="growth", action="review",
            decision="approve", rule="growth_policy",
            reason="通过",
        )
        for key in ("ledger_id", "time", "module", "action",
                    "decision", "rule", "reason"):
            self.assertIn(key, entry)
        self.assertTrue(entry["ledger_id"].startswith("cl_"))

    def test_record_count(self):
        self.ledger.record(module="a", action="x",
                           decision="ok")
        self.ledger.record(module="b", action="y",
                           decision="block")
        self.assertEqual(self.ledger.stats()[
            "record_count"], 2)

    def test_report_by_module(self):
        self.ledger.record(module="growth", action="x",
                           decision="ok")
        self.ledger.record(module="growth", action="y",
                           decision="ok")
        self.ledger.record(module="hybrid", action="z",
                           decision="block")
        report = self.ledger.report()
        self.assertEqual(report["by_module"]["growth"], 2)
        self.assertEqual(report["by_module"]["hybrid"], 1)

    def test_report_by_decision(self):
        self.ledger.record(module="a", action="x",
                           decision="approve")
        self.ledger.record(module="a", action="y",
                           decision="block")
        report = self.ledger.report()
        self.assertEqual(report["by_decision"]["approve"], 1)
        self.assertEqual(report["by_decision"]["block"], 1)

    def test_report_recent_order(self):
        self.ledger.record(module="first", action="x",
                           decision="ok")
        self.ledger.record(module="second", action="y",
                           decision="ok")
        report = self.ledger.report()
        self.assertEqual(report["recent"][0]["module"],
                         "second")

    def test_report_limit(self):
        for i in range(10):
            self.ledger.record(module=f"m{i}", action="x",
                               decision="ok")
        report = self.ledger.report(limit=3)
        self.assertEqual(len(report["recent"]), 3)

    def test_replay(self):
        self.ledger.record(module="growth", action="review",
                           decision="approve",
                           rule="growth_policy")
        replay = self.ledger.replay()
        self.assertEqual(replay["replay_count"], 1)
        seq = replay["sequence"][0]
        self.assertEqual(seq["module"], "growth")
        self.assertEqual(seq["rule"], "growth_policy")

    def test_max_records_cap(self):
        ledger = ConstitutionLedger(max_records=5)
        for i in range(20):
            ledger.record(module=f"m{i}", action="x",
                          decision="ok")
        self.assertEqual(ledger.stats()["record_count"], 5)

    def test_invalid_max_records(self):
        with self.assertRaises(LedgerError):
            ConstitutionLedger(max_records=0)

    def test_disabled(self):
        ledger = ConstitutionLedger(enabled=False)
        entry = ledger.record(module="a", action="x",
                              decision="ok")
        self.assertEqual(entry, {})
        self.assertEqual(ledger.stats()["record_count"], 0)

    def test_clear(self):
        self.ledger.record(module="a", action="x",
                           decision="ok")
        n = self.ledger.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.ledger.stats()[
            "record_count"], 0)

    def test_mode(self):
        self.assertEqual(self.ledger.stats()["mode"],
                         "rule_based")


class TestEvolutionProposal(unittest.TestCase):
    """演化建议"""

    def setUp(self):
        self.proposal = EvolutionProposal()

    def test_propose_structure(self):
        p = self.proposal.propose("修改原则X", "理由", "user")
        for key in ("proposal_id", "change", "reason",
                    "operator", "status", "created_at",
                    "auto_applied"):
            self.assertIn(key, p)
        self.assertTrue(p["proposal_id"].startswith("ep_"))
        self.assertEqual(p["status"], "pending_review")
        self.assertFalse(p["auto_applied"])

    def test_pending_list(self):
        self.proposal.propose("修改A")
        self.proposal.propose("修改B")
        pending = self.proposal.pending()
        self.assertEqual(pending["pending_count"], 2)

    def test_decide_approve_mark_only(self):
        p = self.proposal.propose("修改A")
        r = self.proposal.decide(p["proposal_id"], "approve",
                                 "user_x")
        self.assertEqual(r["decision"], "approve")
        self.assertFalse(r["auto_applied"])
        self.assertIn("人工", r["reason"])

    def test_decide_reject(self):
        p = self.proposal.propose("修改A")
        r = self.proposal.decide(p["proposal_id"], "reject")
        self.assertEqual(r["decision"], "reject")

    def test_decide_updates_status(self):
        p = self.proposal.propose("修改A")
        self.proposal.decide(p["proposal_id"], "approve")
        stats = self.proposal.stats()
        self.assertEqual(stats["by_status"]["approved"], 1)

    def test_decide_missing(self):
        with self.assertRaises(EvolutionProposalError):
            self.proposal.decide("ep_missing", "approve")

    def test_decide_invalid(self):
        p = self.proposal.propose("修改A")
        with self.assertRaises(EvolutionProposalError):
            self.proposal.decide(p["proposal_id"], "maybe")

    def test_decided_not_pending(self):
        p = self.proposal.propose("修改A")
        self.proposal.decide(p["proposal_id"], "approve")
        pending = self.proposal.pending()
        self.assertEqual(pending["pending_count"], 0)

    def test_reviewer_recorded(self):
        p = self.proposal.propose("修改A")
        self.proposal.decide(p["proposal_id"], "approve",
                             "human_admin")
        stats = self.proposal.stats()
        self.assertEqual(stats["by_status"]["approved"], 1)

    def test_proposal_status_constant(self):
        self.assertEqual(PROPOSAL_STATUS,
                         ["pending_review", "approved",
                          "rejected"])

    def test_max_records(self):
        proposal = EvolutionProposal(max_records=3)
        for i in range(10):
            proposal.propose(f"修改{i}")
        self.assertEqual(proposal.stats()[
            "proposal_count"], 3)

    def test_disabled(self):
        proposal = EvolutionProposal(enabled=False)
        r = proposal.propose("修改A")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.proposal.propose("修改A")
        n = self.proposal.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.proposal.stats()[
            "proposal_count"], 0)


if __name__ == "__main__":
    unittest.main()
