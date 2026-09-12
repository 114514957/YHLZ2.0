"""
YHLZ Embodied AI V5.9 - 方案记忆单元测试 (Proposal Memory)

覆盖 (proposal_memory.py):
    - 保存 / 查询 / 按状态查询
    - 生命周期状态机: PENDING → APPROVED/REJECTED → EXECUTED →
      COMPLETED/FAILED
    - 非法转移拒绝 / 未批准禁止执行
    - 结果记录 → 经验关联 (闭环)
    - JSONL 持久化 (save_to_file / load_from_file)
    - 统计 / 清空 / 异常
"""
import os
import tempfile
import unittest

from backend.embodied.companion.creative import (
    PROPOSAL_STATUSES,
    PROPOSAL_TRANSITIONS,
    MemoryError,
    ProposalMemory,
)


def make_proposal(pid="cp_1", status="PENDING"):
    """构造方案 dict"""
    return {
        "proposal_id": pid,
        "title": "自动化重复需求",
        "problem": "重复需求问题",
        "idea": "封装为自动化流程",
        "reasoning": "当前: 手动 → 理想: 自动",
        "expected_value": "影响 high",
        "risk": "low",
        "confidence": 0.8,
        "source_type": "repetition",
        "path_type": "automation",
        "evidence": ["exp_1", "exp_2"],
        "opportunity_id": "opp_1",
        "status": status,
        "simulation": None,
        "created_at": 1000.0,
    }


class TestMemoryInit(unittest.TestCase):
    """初始化与参数校验"""

    def test_default_init(self):
        m = ProposalMemory()
        self.assertIsNotNone(m)

    def test_max_records_validation(self):
        with self.assertRaises(MemoryError):
            ProposalMemory(max_records=0)

    def test_max_records_negative(self):
        with self.assertRaises(MemoryError):
            ProposalMemory(max_records=-1)

    def test_statuses_whitelist(self):
        self.assertEqual(
            set(PROPOSAL_STATUSES),
            {"PENDING", "APPROVED", "REJECTED", "EXECUTED",
             "COMPLETED", "FAILED"},
        )

    def test_transitions_pending(self):
        self.assertEqual(PROPOSAL_TRANSITIONS["PENDING"],
                         ["APPROVED", "REJECTED"])

    def test_transitions_approved(self):
        self.assertEqual(PROPOSAL_TRANSITIONS["APPROVED"],
                         ["EXECUTED", "REJECTED"])

    def test_transitions_executed(self):
        self.assertEqual(PROPOSAL_TRANSITIONS["EXECUTED"],
                         ["COMPLETED", "FAILED"])

    def test_transitions_terminal(self):
        self.assertEqual(PROPOSAL_TRANSITIONS["COMPLETED"], [])
        self.assertEqual(PROPOSAL_TRANSITIONS["FAILED"], [])


class TestSaveAndGet(unittest.TestCase):
    """保存与查询"""

    def setUp(self):
        self.memory = ProposalMemory()

    def test_save(self):
        rec = self.memory.save(make_proposal())
        self.assertEqual(rec["status"], "PENDING")

    def test_save_missing_id(self):
        with self.assertRaises(MemoryError):
            self.memory.save({"title": "无ID"})

    def test_get(self):
        self.memory.save(make_proposal())
        rec = self.memory.get("cp_1")
        self.assertEqual(rec["title"], "自动化重复需求")

    def test_get_missing(self):
        self.assertIsNone(self.memory.get("cp_none"))

    def test_save_initializes_lifecycle(self):
        rec = self.memory.save(make_proposal())
        self.assertGreaterEqual(len(rec["lifecycle"]), 1)
        self.assertEqual(rec["lifecycle"][0]["event"], "saved")

    def test_save_keeps_proposal_fields(self):
        self.memory.save(make_proposal())
        rec = self.memory.get("cp_1")
        self.assertEqual(rec["opportunity_id"], "opp_1")
        self.assertEqual(len(rec["evidence"]), 2)

    def test_max_records(self):
        m = ProposalMemory(max_records=1)
        m.save(make_proposal(pid="cp_1"))
        with self.assertRaises(MemoryError):
            m.save(make_proposal(pid="cp_2"))

    def test_update_proposal(self):
        self.memory.save(make_proposal())
        m = self.memory.update_proposal("cp_1", {"simulation": {"r": 1}})
        self.assertEqual(m["simulation"], {"r": 1})

    def test_update_missing(self):
        self.assertIsNone(
            self.memory.update_proposal("cp_none", {"a": 1}),
        )

    def test_save_returns_copy(self):
        rec = self.memory.save(make_proposal())
        rec["title"] = "已修改"
        stored = self.memory.get("cp_1")
        self.assertEqual(stored["title"], "自动化重复需求")


class TestLifecycle(unittest.TestCase):
    """生命周期状态机"""

    def setUp(self):
        self.memory = ProposalMemory()
        self.memory.save(make_proposal())

    def test_approve(self):
        rec = self.memory.approve("cp_1", approver="user")
        self.assertEqual(rec["status"], "APPROVED")
        self.assertEqual(rec["approver"], "user")

    def test_approve_sets_approved_at(self):
        rec = self.memory.approve("cp_1")
        self.assertGreater(rec["approved_at"], 0.0)

    def test_reject_from_pending(self):
        rec = self.memory.reject("cp_1", reason="不需要")
        self.assertEqual(rec["status"], "REJECTED")
        self.assertEqual(rec["reason"], "不需要")

    def test_reject_default_reason(self):
        rec = self.memory.reject("cp_1")
        self.assertTrue(rec["reason"])

    def test_execute_requires_approved(self):
        with self.assertRaises(MemoryError):
            self.memory.execute("cp_1")

    def test_execute_after_approve(self):
        self.memory.approve("cp_1")
        rec = self.memory.execute("cp_1")
        self.assertEqual(rec["status"], "EXECUTED")
        self.assertGreater(rec["executed_at"], 0.0)

    def test_execute_missing(self):
        with self.assertRaises(MemoryError):
            self.memory.execute("cp_none")

    def test_approve_missing(self):
        with self.assertRaises(MemoryError):
            self.memory.approve("cp_none")

    def test_reject_missing(self):
        with self.assertRaises(MemoryError):
            self.memory.reject("cp_none")

    def test_double_approve_invalid(self):
        self.memory.approve("cp_1")
        with self.assertRaises(MemoryError):
            self.memory.approve("cp_1")

    def test_reject_after_execute_invalid(self):
        self.memory.approve("cp_1")
        self.memory.execute("cp_1")
        with self.assertRaises(MemoryError):
            self.memory.reject("cp_1")

    def test_reject_approved_allowed(self):
        self.memory.approve("cp_1")
        rec = self.memory.reject("cp_1", "撤回")
        self.assertEqual(rec["status"], "REJECTED")

    def test_lifecycle_events(self):
        self.memory.approve("cp_1")
        self.memory.execute("cp_1")
        events = self.memory.lifecycle("cp_1")
        event_to = [e["to"] for e in events]
        self.assertIn("APPROVED", event_to)
        self.assertIn("EXECUTED", event_to)

    def test_lifecycle_missing(self):
        with self.assertRaises(MemoryError):
            self.memory.lifecycle("cp_none")

    def test_by_status(self):
        rec = self.memory.approve("cp_1")
        ps = self.memory.by_status("APPROVED")
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["proposal_id"], "cp_1")

    def test_by_status_invalid(self):
        with self.assertRaises(MemoryError):
            self.memory.by_status("INVALID")

    def test_by_status_empty(self):
        self.assertEqual(self.memory.by_status("COMPLETED"), [])


class TestRecordResult(unittest.TestCase):
    """结果记录 → 新经验"""

    def setUp(self):
        self.memory = ProposalMemory()
        self.memory.save(make_proposal())
        self.memory.approve("cp_1")
        self.memory.execute("cp_1")

    def test_record_success(self):
        rec = self.memory.record_result(
            "cp_1", True, result="成功", experience_id="exp_new",
        )
        self.assertEqual(rec["status"], "COMPLETED")
        self.assertEqual(rec["experience_id"], "exp_new")
        self.assertTrue(rec["success"])

    def test_record_failure(self):
        rec = self.memory.record_result(
            "cp_1", False, result="失败",
        )
        self.assertEqual(rec["status"], "FAILED")
        self.assertFalse(rec["success"])

    def test_record_result_requires_executed(self):
        m = ProposalMemory()
        m.save(make_proposal(pid="cp_2"))
        with self.assertRaises(MemoryError):
            m.record_result("cp_2", True)

    def test_record_result_missing(self):
        with self.assertRaises(MemoryError):
            self.memory.record_result("cp_none", True)

    def test_record_stores_result_text(self):
        self.memory.record_result("cp_1", True, result="一次通过")
        rec = self.memory.get("cp_1")
        self.assertEqual(rec["result"], "一次通过")

    def test_record_sets_timestamp(self):
        rec = self.memory.record_result("cp_1", True)
        self.assertGreater(rec["result_recorded_at"], 0.0)

    def test_record_after_complete_invalid(self):
        self.memory.record_result("cp_1", True)
        with self.assertRaises(MemoryError):
            self.memory.record_result("cp_1", True)

    def test_full_lifecycle_chain(self):
        m = ProposalMemory()
        m.save(make_proposal())
        m.approve("cp_1")
        m.execute("cp_1")
        m.record_result("cp_1", True, experience_id="exp_9")
        events = [e["event"] for e in m.lifecycle("cp_1")]
        self.assertEqual(events,
                         ["saved", "approved", "executed", "completed"])

    def test_failed_terminal(self):
        self.memory.record_result("cp_1", False)
        with self.assertRaises(MemoryError):
            self.memory.execute("cp_1")


class TestStats(unittest.TestCase):
    """统计"""

    def test_stats_empty(self):
        m = ProposalMemory()
        st = m.stats()
        self.assertEqual(st["total"], 0)
        self.assertEqual(st["by_status"], {})

    def test_stats_by_status(self):
        m = ProposalMemory()
        m.save(make_proposal(pid="cp_1"))
        m.save(make_proposal(pid="cp_2"))
        m.approve("cp_1")
        st = m.stats()
        self.assertEqual(st["total"], 2)
        self.assertEqual(st["by_status"]["APPROVED"], 1)
        self.assertEqual(st["by_status"]["PENDING"], 1)

    def test_stats_approved_count(self):
        m = ProposalMemory()
        m.save(make_proposal())
        m.approve("cp_1")
        self.assertEqual(m.stats()["approved"], 1)

    def test_stats_mode(self):
        m = ProposalMemory()
        self.assertEqual(m.stats()["mode"], "rule_based")

    def test_stats_completed_failed(self):
        m = ProposalMemory()
        m.save(make_proposal(pid="a"))
        m.approve("a")
        m.execute("a")
        m.record_result("a", True)
        m.save(make_proposal(pid="b"))
        m.approve("b")
        m.execute("b")
        m.record_result("b", False)
        st = m.stats()
        self.assertEqual(st["completed"], 1)
        self.assertEqual(st["failed"], 1)


class TestPersistence(unittest.TestCase):
    """JSONL 持久化"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_mem_")
        self.path = os.path.join(self.tmp, "proposals.jsonl")

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)
        os.rmdir(self.tmp)

    def test_save_to_file(self):
        m = ProposalMemory()
        m.save(make_proposal())
        n = m.save_to_file(self.path)
        self.assertEqual(n, 1)
        self.assertTrue(os.path.exists(self.path))

    def test_save_no_path(self):
        m = ProposalMemory()
        m.save(make_proposal())
        with self.assertRaises(MemoryError):
            m.save_to_file()

    def test_load_from_file(self):
        m = ProposalMemory()
        m.save(make_proposal(pid="cp_1"))
        m.save(make_proposal(pid="cp_2"))
        m.save_to_file(self.path)
        m2 = ProposalMemory()
        n = m2.load_from_file(self.path)
        self.assertEqual(n, 2)
        self.assertEqual(m2.get("cp_1")["status"], "PENDING")

    def test_load_missing_file(self):
        m = ProposalMemory()
        with self.assertRaises(MemoryError):
            m.load_from_file(self.path)

    def test_load_no_path(self):
        m = ProposalMemory()
        with self.assertRaises(MemoryError):
            m.load_from_file()

    def test_roundtrip_lifecycle(self):
        m = ProposalMemory()
        m.save(make_proposal())
        m.approve("cp_1")
        m.execute("cp_1")
        m.record_result("cp_1", True, experience_id="exp_x")
        m.save_to_file(self.path)
        m2 = ProposalMemory()
        m2.load_from_file(self.path)
        rec = m2.get("cp_1")
        self.assertEqual(rec["status"], "COMPLETED")
        self.assertEqual(rec["experience_id"], "exp_x")

    def test_load_ignores_invalid_lines(self):
        m = ProposalMemory()
        m.save(make_proposal())
        m.save_to_file(self.path)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("not json\n")
        m2 = ProposalMemory()
        n = m2.load_from_file(self.path)
        self.assertEqual(n, 1)

    def test_empty_file_load(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("")
        m = ProposalMemory()
        self.assertEqual(m.load_from_file(self.path), 0)

    def test_persist_path_from_init(self):
        m = ProposalMemory(persist_path=self.path)
        m.save(make_proposal())
        self.assertEqual(m.save_to_file(), 1)
        self.assertTrue(os.path.exists(self.path))

    def test_clear_after_load(self):
        m = ProposalMemory()
        m.save(make_proposal())
        m.save_to_file(self.path)
        m2 = ProposalMemory()
        m2.load_from_file(self.path)
        self.assertEqual(m2.clear(), 1)


class TestClear(unittest.TestCase):
    """清空"""

    def test_clear_count(self):
        m = ProposalMemory()
        m.save(make_proposal(pid="a"))
        m.save(make_proposal(pid="b"))
        self.assertEqual(m.clear(), 2)

    def test_clear_empty(self):
        m = ProposalMemory()
        self.assertEqual(m.clear(), 0)

    def test_clear_removes(self):
        m = ProposalMemory()
        m.save(make_proposal())
        m.clear()
        self.assertIsNone(m.get("cp_1"))


class TestEdgeCases(unittest.TestCase):
    """边界情况"""

    def test_save_keeps_existing_lifecycle(self):
        m = ProposalMemory()
        prop = make_proposal()
        prop["lifecycle"] = [{"event": "custom", "to": "PENDING",
                              "reason": "r", "timestamp": 1.0}]
        rec = m.save(prop)
        self.assertEqual(rec["lifecycle"][0]["event"], "custom")

    def test_save_approved_proposal_keeps_status(self):
        m = ProposalMemory()
        m.save(make_proposal())
        m.approve("cp_1")
        st = m.stats()
        self.assertEqual(st["by_status"]["APPROVED"], 1)

    def test_execute_on_approved_only(self):
        m = ProposalMemory()
        m.save(make_proposal(pid="a"))
        m.save(make_proposal(pid="b"))
        m.approve("a")
        m.execute("a")
        self.assertEqual(m.get("b").get("executed_at", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
