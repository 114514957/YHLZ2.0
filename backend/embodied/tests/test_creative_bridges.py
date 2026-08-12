"""
YHLZ Embodied AI V5.9 - 集成桥接单元测试 (Integration Bridges)

覆盖 (integration/):
    - ExperienceBridge: 只 CONFIRMED 经验 / 无验证器保守空 /
      新经验回写 + 验证
    - ReflectionBridge: 报告读取 / 空报告 / 输入转换
    - ApprovalBridge: 审批门槛 / 镜像提交 / 执行资格
"""
import unittest

from backend.embodied.companion.experience import ExperienceManager
from backend.embodied.companion.integration import (
    ApprovalBridge,
    ApprovalBridgeError,
    ExperienceBridge,
    ExperienceBridgeError,
    ReflectionBridge,
    ReflectionBridgeError,
)
from backend.embodied.companion.reflection import (
    ImprovementProposalEngine,
    ReflectionEngine,
)
from backend.embodied.companion.verification import ExperienceVerifier


class TestExperienceBridge(unittest.TestCase):
    """经历桥接"""

    def setUp(self):
        self.mgr = ExperienceManager()
        self.verifier = ExperienceVerifier()
        self.bridge = ExperienceBridge(self.mgr, self.verifier)

    def _add_confirmed(self, trigger="工程经验", n=1):
        """添加并确认经历"""
        ids = []
        for _ in range(n):
            rec = self.mgr.store_from_event(
                success=True, trigger=trigger,
                source="bridge_test", action="a", result="成功",
            )
            ids.append(rec["id"])
        for rid in ids:
            for _ in range(3):
                self.verifier.verify(rid, evidence_count=2,
                                     contradictions=0)
        return ids

    def test_bridge_init(self):
        self.assertIsNotNone(self.bridge)

    def test_confirmed_experiences(self):
        self._add_confirmed()
        exps = self.bridge.confirmed_experiences()
        self.assertEqual(len(exps), 1)

    def test_confirmed_only(self):
        """未验证经历不进入创造"""
        rec = self.mgr.store_from_event(
            success=True, trigger="未验证", result="成功",
        )
        self.bridge.verify_new_experience(rec["id"], evidence_count=0)
        self.verifier.clear()
        exps = self.bridge.confirmed_experiences()
        self.assertEqual(exps, [])

    def test_no_verifier_conservative(self):
        b = ExperienceBridge(self.mgr, None)
        rec = self.mgr.store_from_event(
            success=True, trigger="无验证器", result="成功",
        )
        self.verifier.verify(rec["id"], evidence_count=2)
        for _ in range(2):
            self.verifier.verify(rec["id"], evidence_count=2)
        self.assertEqual(b.confirmed_experiences(), [])

    def test_no_manager(self):
        b = ExperienceBridge(None, self.verifier)
        self.assertEqual(b.confirmed_experiences(), [])

    def test_confirm_two_experiences(self):
        self._add_confirmed(trigger="A")
        self._add_confirmed(trigger="B")
        self.assertEqual(len(self.bridge.confirmed_experiences()), 2)

    def test_confirmed_by_trigger(self):
        self._add_confirmed(trigger="工程经验")
        self._add_confirmed(trigger="生活经验")
        out = self.bridge.confirmed_by_trigger("工程")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["trigger"], "工程经验")

    def test_confirmed_count(self):
        self._add_confirmed(n=3)
        self.assertEqual(self.bridge.confirmed_count(), 3)

    def test_record_new_experience(self):
        rec = self.bridge.record_new_experience(
            trigger="创造:新方案", lesson="成功", result="成功",
        )
        self.assertIn("id", rec)
        self.assertEqual(rec["type"], "engineering")

    def test_record_new_no_manager(self):
        b = ExperienceBridge(None, self.verifier)
        with self.assertRaises(ExperienceBridgeError):
            b.record_new_experience("t", "l")

    def test_verify_new_experience(self):
        rec = self.bridge.record_new_experience("t", "l")
        st = self.bridge.verify_new_experience(rec["id"])
        self.assertEqual(st["status"], "PENDING")

    def test_verify_new_no_verifier(self):
        b = ExperienceBridge(self.mgr, None)
        rec = self.mgr.store_from_event(success=True, trigger="t")
        with self.assertRaises(ExperienceBridgeError):
            b.verify_new_experience(rec["id"])

    def test_stats(self):
        self._add_confirmed(n=2)
        st = self.bridge.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertTrue(st["manager_connected"])
        self.assertTrue(st["verifier_connected"])
        self.assertEqual(st["confirmed_count"], 2)

    def test_new_experience_verification_progress(self):
        """新经验 → 验证 → 最终 CONFIRMED (闭环)"""
        rec = self.bridge.record_new_experience(
            trigger="创造:闭环", lesson="经验", result="成功",
        )
        for _ in range(3):
            self.bridge.verify_new_experience(rec["id"],
                                              evidence_count=2)
        self.assertIn(rec["id"], self.verifier.confirmed_ids())


class TestReflectionBridge(unittest.TestCase):
    """反思桥接"""

    def setUp(self):
        self.engine = ReflectionEngine()
        self.bridge = ReflectionBridge(self.engine)

    def test_no_engine_empty_report(self):
        b = ReflectionBridge(None)
        r = b.latest_report()
        self.assertEqual(r["patterns"], [])

    def test_latest_report(self):
        report = self.engine.reflect([
            {"id": "e1", "type": "failure", "trigger": "失败A",
             "result": "错误", "lesson": "l"},
            {"id": "e2", "type": "failure", "trigger": "失败A",
             "result": "错误", "lesson": "l"},
        ])
        r = self.bridge.latest_report()
        self.assertEqual(r["report_id"], report["report_id"])

    def test_patterns(self):
        self.engine.reflect([
            {"id": f"e{i}", "type": "improvement",
             "trigger": "模式X", "lesson": "l",
             "timestamp": 100 + i * 86400}
            for i in range(5)
        ])
        self.assertGreaterEqual(len(self.bridge.patterns()), 1)

    def test_suggestion(self):
        self.engine.reflect([
            {"id": f"e{i}", "type": "improvement",
             "trigger": "模式Y", "lesson": "l",
             "timestamp": 100 + i * 86400}
            for i in range(5)
        ])
        self.assertTrue(self.bridge.suggestion())

    def test_failure_analyses(self):
        self.engine.reflect([
            {"id": f"e{i}", "type": "failure", "trigger": "失败B",
             "result": "错误", "lesson": "l",
             "timestamp": 100 + i * 86400}
            for i in range(3)
        ])
        self.assertGreaterEqual(
            len(self.bridge.failure_analyses()), 1,
        )

    def test_input_payload(self):
        self.engine.reflect([])
        payload = self.bridge.input_payload()
        for key in ("patterns", "failure_analyses", "suggestion",
                    "risk"):
            self.assertIn(key, payload)

    def test_stats(self):
        st = self.bridge.stats()
        self.assertTrue(st["reflection_connected"])
        self.assertIn("mode", st)

    def test_empty_report_has_fields(self):
        r = self.bridge.empty_report()
        for key in ("patterns", "failure_analyses", "suggestion",
                    "risk"):
            self.assertIn(key, r)

    def test_latest_validated_report(self):
        self.engine.reflect([])
        r = self.bridge.latest_validated_report()
        self.assertIn("report_id", r)

    def test_bridge_does_not_mutate_engine(self):
        self.engine.reflect([
            {"id": "e1", "type": "improvement", "trigger": "T",
             "lesson": "l", "timestamp": 100.0},
        ])
        before = len(self.engine._reports)
        self.bridge.latest_report()
        self.assertEqual(len(self.engine._reports), before)


class TestApprovalBridge(unittest.TestCase):
    """审批桥接"""

    def setUp(self):
        self.engine = ImprovementProposalEngine()
        self.bridge = ApprovalBridge(self.engine)

    def test_requires_approval_true(self):
        self.assertTrue(self.bridge.requires_approval())

    def test_submit_mirror(self):
        mirror = self.bridge.submit({
            "proposal_id": "cp_1",
            "title": "自动化需求",
            "idea": "封装流程",
            "expected_value": "影响 high",
            "risk": "low",
            "opportunity_id": "opp_1",
            "evidence": ["e1"],
        })
        self.assertEqual(mirror["status"], "PENDING_APPROVAL")
        self.assertEqual(mirror["trigger"], "自动化需求")

    def test_submit_no_engine(self):
        b = ApprovalBridge(None)
        self.assertIsNone(b.submit({"proposal_id": "cp_1"}))

    def test_can_execute_approved_only(self):
        self.assertTrue(self.bridge.can_execute("APPROVED"))
        self.assertFalse(self.bridge.can_execute("PENDING"))
        self.assertFalse(self.bridge.can_execute("REJECTED"))
        self.assertFalse(self.bridge.can_execute("EXECUTED"))

    def test_approval_status(self):
        st = self.bridge.approval_status({
            "proposal_id": "cp_1", "status": "PENDING",
        })
        self.assertEqual(st["requires_approval"], True)
        self.assertEqual(st["can_execute"], False)

    def test_approval_status_approved(self):
        st = self.bridge.approval_status({
            "proposal_id": "cp_1", "status": "APPROVED",
        })
        self.assertEqual(st["can_execute"], True)

    def test_stats(self):
        st = self.bridge.stats()
        self.assertTrue(st["approval_connected"])
        self.assertTrue(st["requires_approval"])

    def test_stats_with_mirrors(self):
        self.bridge.submit({
            "proposal_id": "cp_1", "title": "T",
            "idea": "I", "risk": "low",
        })
        st = self.bridge.stats()
        self.assertIn("improvement_by_status", st)

    def test_mirror_approve_flow(self):
        mirror = self.bridge.submit({
            "proposal_id": "cp_1", "title": "T",
            "idea": "I", "risk": "low",
        })
        approved = self.engine.approve(mirror["proposal_id"])
        self.assertEqual(approved["status"], "APPROVED")

    def test_mirror_tracks_proposal_id(self):
        mirror = self.bridge.submit({
            "proposal_id": "cp_x", "title": "标题",
            "idea": "I", "risk": "medium",
        })
        self.assertEqual(mirror["trigger"], "标题")


if __name__ == "__main__":
    unittest.main()
