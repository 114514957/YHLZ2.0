"""④ 出集门（v9_out_gate.py）的回归测试（ledger 0839）。

钉死老爹 2026-10-18 的四条裁定：
  G1 利贞分池（只做元亨）｜G2 pending 不出集｜G3 双签（执行与审核分离，可批次盖章）
  ｜G4 候选稿（status != keep）不出集；且**门不过就出空集**，不许放行。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import v9_out_gate as gate  # noqa: E402


def _rec(**kw) -> dict:
    base = {"messages": [{"role": "user", "content": "hi"}],
            "source": "scene:对话-1｜日常", "source_id": "scene#对话-1｜日常",
            "content_hash": "abc123", "consent_status": "n/a",
            "annotator_exec": "agent:finetune_assemble", "annotator_review": ""}
    base.update(kw)
    return base


class GateJudgeTest(unittest.TestCase):
    def setUp(self):
        self.status = {"对话-1": {"status": "keep"}, "对话-2": {"status": "candidate"}}

    def test_lizhen_goes_to_pool(self):
        dest, reason = gate.judge(_rec(source="lizhen:对话-1", source_id="lizhen#对话-1"),
                                  self.status, {"hashes": {}, "blocks": {}, "batches": []})
        self.assertEqual((dest, reason), ("lizhen_pool", "lizhen-pool"))

    def test_pending_quarantined(self):
        dest, reason = gate.judge(_rec(consent_status="pending"), self.status,
                                  {"hashes": {}, "blocks": {}, "batches": []})
        self.assertEqual((dest, reason), ("quarantine", "consent-pending"))

    def test_no_double_sign_quarantined(self):
        dest, reason = gate.judge(_rec(), self.status,
                                  {"hashes": {}, "blocks": {}, "batches": []})
        self.assertEqual((dest, reason), ("quarantine", "no-double-sign"))

    def test_batch_signature_stamps_review(self):
        sig = {"hashes": {"abc123": "dad:B01@2026-10-18"}, "blocks": {}, "batches": [{}]}
        rec = _rec()
        dest, reason = gate.judge(rec, self.status, sig)
        self.assertEqual((dest, reason), ("pass", "ok"))
        self.assertEqual(rec["annotator_review"], "dad:B01@2026-10-18")

    def test_candidate_block_quarantined(self):
        sig = {"hashes": {"abc123": "dad:B01@2026-10-18"}, "blocks": {}, "batches": [{}]}
        rec = _rec(source="scene:对话-2｜故事", source_id="scene#对话-2｜故事")
        dest, reason = gate.judge(rec, self.status, sig)
        self.assertEqual(dest, "quarantine")
        self.assertIn("material-status=candidate", reason)

    def test_unknown_block_treated_as_not_keep(self):
        sig = {"hashes": {"abc123": "dad:B01@2026-10-18"}, "blocks": {}, "batches": [{}]}
        rec = _rec(source_id="scene#不存在｜x")
        dest, reason = gate.judge(rec, self.status, sig)
        self.assertEqual(dest, "quarantine")
        self.assertIn("unknown", reason)


class GateCliTest(unittest.TestCase):
    def test_cli_writes_pools_and_report(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "s_tmp_train.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in [
                _rec(content_hash="h1"),
                _rec(source="lizhen:对话-1", source_id="lizhen#对话-1"),
                _rec(consent_status="pending"),
            ]) + "\n", encoding="utf-8")
        (tmp / "s_tmp_val.jsonl").write_text(
            json.dumps(_rec(), ensure_ascii=False) + "\n", encoding="utf-8")
        out = tmp / "v9"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "v9_out_gate.py"),
             "--in", str(tmp / "s_tmp_train.jsonl"), "--in", str(tmp / "s_tmp_val.jsonl"),
             "--out-prefix", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        report = json.loads((tmp / "v9_gate_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["totals"]["lizhen-pool"], 1)
        self.assertEqual(report["totals"]["consent-pending"], 1)
        self.assertGreaterEqual(report["totals"]["no-double-sign"], 2)
        # 门不过 → 不放行
        self.assertFalse(report["ready_to_train"])
        self.assertTrue((tmp / "v9_lizhen_pool.jsonl").exists())
        self.assertTrue((tmp / "v9_quarantine.jsonl").exists())
        self.assertFalse((tmp / "v9_train.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
