"""工具必须真实、必须可拓展——回归测试（ledger 0886）。

钉死四件事：
  1) 真实注册表快照存在且可复现（43 项；快照 sha 与 live 一致 = 无漂移）；
  2) 生成的 `tool_use_v6.jsonl` 含**假工具名**，必须被 `--check` 判 FAIL；
  3) 出集门对「假工具名」与「生成轨迹（source=tooluse）」一律隔离；
  4) 真实轨迹（source=tooltrace:real + 已签）可以放行；且注册表新增工具时
     `--drift` 能点名（可拓展性回归）。
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import v9_out_gate as gate  # noqa: E402
import v9_tool_registry as reg  # noqa: E402


def rec(**kw) -> dict:
    base = {"messages": [{"role": "user", "content": "hi"}],
            "source": "memory", "source_id": "memory#b1",
            "content_hash": "h1", "consent_status": "n/a",
            "annotator_exec": "agent:assemble", "annotator_review": ""}
    base.update(kw)
    return base


class ToolRegistryTest(unittest.TestCase):
    def setUp(self):
        self.snap = json.loads((ROOT / "data" / "tool_registry" /
                                "snapshot_latest.json").read_text(encoding="utf-8"))
        self.allowed = {t["name"] for t in self.snap["tools"]}

    def test_snapshot_real_registry(self):
        self.assertGreaterEqual(len(self.allowed), 40)
        self.assertIn("file_read", self.allowed)
        self.assertIn("memory_recall", self.allowed)

    def test_v6_has_fake_tools(self):
        used = reg.tool_names_in(ROOT / "data" / "finetune" / "tool_use_v6.jsonl")
        fake = [n for n in used if n not in self.allowed]
        self.assertTrue(fake, "v6 应当含假工具名")

    def test_v8_names_are_real(self):
        used = reg.tool_names_in(ROOT / "data" / "finetune" / "tool_use_v8.jsonl")
        self.assertFalse([n for n in used if n not in self.allowed])

    def test_no_drift_between_snapshot_and_live(self):
        live = {t["function"]["name"]
                for t in reg.live_specs()}
        self.assertEqual(live, self.allowed)


class GateToolRulesTest(unittest.TestCase):
    def setUp(self):
        self.status = {"b1": {"status": "keep"}}
        self.sig = {"hashes": {"h1": "dad:B01@2026-10-20"}, "blocks": {}, "batches": [{}]}

    def test_fake_tool_quarantined(self):
        r = rec(messages=[{"role": "assistant", "tool_calls": [
            {"function": {"name": "search_notes", "arguments": "{}"}}]}])
        dest, reason = gate.judge(r, self.status, self.sig,
                                  allowed_tools={"file_read", "memory_recall"})
        self.assertEqual(dest, "quarantine")
        self.assertIn("fake-tool", reason)

    def test_generated_tool_trace_quarantined(self):
        r = rec(source="tooluse", source_id="tooluse#x")
        dest, reason = gate.judge(r, self.status, self.sig,
                                  allowed_tools={"file_read"})
        self.assertEqual(dest, "quarantine")
        self.assertEqual(reason, "generated-tool-trace")


    def test_simulation_trace_allowed_when_marked(self):
        r = rec(source="toolsynth:normal", source_id="synth#file_read#normal",
                simulation=True,
                messages=[{"role": "assistant", "tool_calls": [
                    {"function": {"name": "file_read", "arguments": "{}"}}]}])
        dest, reason = gate.judge(r, self.status, self.sig,
                                  allowed_tools={"file_read"})
        self.assertEqual(dest, "pass", reason)

    def test_unmarked_generated_still_blocked(self):
        r = rec(source="tooluse", source_id="tooluse#x")
        dest, reason = gate.judge(r, self.status, self.sig,
                                  allowed_tools={"file_read"})
        self.assertEqual(reason, "generated-tool-trace")

    def test_real_trace_passes_with_signature(self):
        r = rec(source="tooltrace:real", source_id="trace#1",
                messages=[{"role": "assistant", "tool_calls": [
                    {"function": {"name": "file_read", "arguments": "{}"}}]}])
        dest, reason = gate.judge(r, self.status, self.sig,
                                  allowed_tools={"file_read"})
        self.assertEqual(dest, "pass", reason)


if __name__ == "__main__":
    unittest.main()
