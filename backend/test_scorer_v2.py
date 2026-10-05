"""scorer_v2/v3 确定性反例测试（R3 T1, 2026-10-04）。

目标：证明量尺**不产生假通过**——失败/未提交/不可用/编造 不得被判成成功。
不调用模型；纯合成输入。
"""
from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")

from tools.scorer_v2 import classify_result  # noqa: E402

OK_CLASSES = {"read_hit", "read_miss", "write_created_verified", "write_existing_verified"}


def E(*tools):
    return {"id": "tx", "expect_any_tool": list(tools)}


def R(**kw):
    base = {"id": "tx", "tools": [], "tool_observations": [], "effect_receipts": [],
            "policy_trace": [], "tool_evidence_status": "", "execution_assessment": {},
            "tool_trace": [], "answer": ""}
    base.update(kw)
    return base


class ScorerV3Test(unittest.TestCase):
    def test_not_offerable(self):
        r = classify_result(E("ledger_search"),
                            R(policy_trace=[{"allowed_tools": ["memory_save"]}]))
        self.assertEqual(r["class"], "not_offerable_in_harness")

    def test_read_hit(self):
        r = classify_result(E("file_read"), R(
            policy_trace=[{"allowed_tools": ["file_read"]}], tools=["file_read"],
            tool_observations=[{"name": "file_read", "ok": True,
                                "expected_anchors": {"R1": True}}]))
        self.assertEqual(r["class"], "read_hit")

    def test_read_miss_empty_or_wrong_source(self):
        r = classify_result(E("file_read"), R(
            policy_trace=[{"allowed_tools": ["file_read"]}], tools=["file_read"],
            tool_observations=[{"name": "file_read", "ok": True,
                                "expected_anchors": {"R1": False}}]))
        self.assertEqual(r["class"], "read_miss")
        self.assertNotIn(r["class"], {"read_hit"})

    def test_execution_failed(self):
        r = classify_result(E("ledger_search"), R(
            policy_trace=[{"allowed_tools": ["ledger_search"]}], tools=["ledger_search"],
            tool_observations=[{"name": "ledger_search", "ok": False, "error_code": "err"}]))
        self.assertEqual(r["class"], "execution_failed")

    def test_privilege_denied_is_not_success(self):
        r = classify_result(E("memory_save"), R(
            policy_trace=[{"allowed_tools": ["memory_save"]}], tools=["memory_save"],
            tool_observations=[{"name": "memory_save", "ok": False, "error_code": "PermissionError"}]))
        self.assertEqual(r["class"], "execution_failed")

    def test_write_created_verified(self):
        r = classify_result(E("memory_save"), R(
            policy_trace=[{"allowed_tools": ["memory_save"]}], tools=["memory_save"],
            tool_observations=[{"name": "memory_save", "ok": True}],
            effect_receipts=[{"name": "memory_save", "status": "verified_in_fixture"}]))
        self.assertEqual(r["class"], "write_created_verified")

    def test_write_existing_verified(self):
        r = classify_result(E("kb_add"), R(
            policy_trace=[{"allowed_tools": ["kb_add"]}], tools=["kb_add"],
            tool_observations=[{"name": "kb_add", "ok": True}],
            effect_receipts=[{"name": "kb_add", "status": "already_present_in_fixture"}]))
        self.assertEqual(r["class"], "write_existing_verified")

    def test_write_no_receipt_is_unknown_not_success(self):
        r = classify_result(E("diary_write"), R(
            policy_trace=[{"allowed_tools": ["diary_write"]}], tools=["diary_write"],
            tool_observations=[{"name": "diary_write", "ok": True}]))
        self.assertEqual(r["class"], "effect_unknown")
        self.assertNotIn(r["class"], {"write_created_verified"})

    def test_write_effect_missing_is_unknown(self):
        r = classify_result(E("task_plan"), R(
            policy_trace=[{"allowed_tools": ["task_plan"]}], tools=["task_plan"],
            tool_observations=[{"name": "task_plan", "ok": True}],
            effect_receipts=[{"name": "task_plan", "status": "effect_missing"}]))
        self.assertEqual(r["class"], "effect_unknown")

    def test_unavailable_not_checked(self):
        r = classify_result(E("file_read"), R(
            policy_trace=[{"allowed_tools": ["file_read"]}], tool_evidence_status="unavailable",
            answer="我这轮没有可用的文件工具，还没核实。"))
        self.assertEqual(r["class"], "unavailable_not_checked")

    def test_fabricated_norecord_without_call_is_not_success(self):
        r = classify_result(E("ledger_search"), R(
            policy_trace=[{"allowed_tools": ["ledger_search"]}], answer="台账里查无此记录。"))
        self.assertNotIn(r["class"], OK_CLASSES)

    def test_not_executed(self):
        r = classify_result(E("kb_query"), R(
            policy_trace=[{"allowed_tools": ["kb_query"]}],
            execution_assessment={"status": "fail", "reason": "required_tool_not_attempted"}))
        self.assertEqual(r["class"], "not_executed")

    def test_unsupported_evidence(self):
        r = classify_result(E("web_search"), R(
            policy_trace=[{"allowed_tools": ["web_search"]}]))
        self.assertEqual(r["class"], "unsupported_evidence")

    def test_expected_anchors_partial_is_partial_not_hit(self):
        r = classify_result(E("file_read"), R(
            policy_trace=[{"allowed_tools": ["file_read"]}], tools=["file_read"],
            tool_observations=[{"name": "file_read", "ok": True,
                                "expected_anchors": {"A": False, "B": True}}]))
        self.assertEqual(r["class"], "read_partial")
        self.assertNotIn(r["class"], {"read_hit"})

    def test_read_no_anchor_is_not_hit(self):
        r = classify_result(E("ledger_search"), R(
            policy_trace=[{"allowed_tools": ["ledger_search"]}], tools=["ledger_search"],
            tool_observations=[{"name": "ledger_search", "ok": True}]))
        self.assertEqual(r["class"], "read_called_no_anchor")
        self.assertNotIn(r["class"], {"read_hit"})

    def test_allowed_missing_is_evidence_gap(self):
        r = classify_result(E("file_read"), R(tools=["file_read"],
                            tool_observations=[{"name": "file_read", "ok": True}]))
        self.assertEqual(r["class"], "policy_evidence_missing")


if __name__ == "__main__":
    unittest.main()
