"""Turn Orchestrator tests (ADR-007 core loop, fake LLM driven)."""

import os
import unittest

from backend.target_capability_registry import Capability, CapabilityRegistry
from backend.target_orchestrator import TurnOrchestrator
from backend.target_scheduler_tools import setup_scheduler_capabilities

# 2026-11-05（台账 1097）：与 test_target_capability_registry 同口径——
# see_now/screen_text 由 YHLZ_SEE_NOW 控制，钉成生产值以免环境差异造成假红。
os.environ.setdefault("YHLZ_SEE_NOW", "1")


def _ok(params: dict) -> str:
    return "tool-result:" + str(params.get("q", ""))


def _fake_llm_with_tools(registry_tools: list[dict]):
    calls = {"n": 0}

    async def llm_turn(messages, tools):
        calls["n"] += 1
        if calls["n"] == 1 and tools:
            return {
                "content": "我来查一下",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": tools[0]["function"]["name"],
                            "arguments": '{"q": "麦克风"}',
                        },
                    }
                ],
            }
        return {"content": "查到结果了", "tool_calls": []}

    return llm_turn


class TestTurnOrchestrator(unittest.TestCase):
    def setUp(self):
        self.reg = CapabilityRegistry()
        self.reg.register_policy("allow", lambda: True)
        self.reg.register_capability(
            Capability(name="demo.search", handler=_ok, input=("q",),
                       requires=("allow",))
        )

    def test_tool_round_then_answer(self):
        orch = TurnOrchestrator(self.reg)
        result = None
        import asyncio

        async def go():
            nonlocal result
            result = await orch.run(
                "查一下",
                "你是测试助手",
                _fake_llm_with_tools(orch._export_tools()),
            )

        asyncio.run(go())
        self.assertEqual(result.answer, "查到结果了")
        self.assertEqual(len(result.tool_uses), 1)
        self.assertTrue(result.tool_uses[0].ok)
        self.assertEqual(result.tool_uses[0].output, "tool-result:麦克风")
        self.assertEqual(result.iterations, 2)

    def test_audio_content_parts(self):
        import asyncio
        import tempfile
        from pathlib import Path

        captured = {}

        async def llm_turn(messages, tools):
            captured["messages"] = messages
            return {"content": "听到了", "tool_calls": []}

        wav = Path(tempfile.mkdtemp()) / "in.wav"
        wav.write_bytes(b"RIFF0000WAVEfake")

        asyncio.run(TurnOrchestrator(self.reg).run(
            "", "sys", llm_turn, audio=[str(wav)]))
        user = captured["messages"][-1]
        self.assertEqual(user["role"], "user")
        self.assertIsInstance(user["content"], list)
        parts = user["content"]
        self.assertEqual(parts[-1]["type"], "input_audio")
        self.assertEqual(parts[-1]["input_audio"]["format"], "wav")
        self.assertTrue(parts[-1]["input_audio"]["data"])

    def test_audio_missing_file_keeps_text_head(self):
        import asyncio

        captured = {}

        async def llm_turn(messages, tools):
            captured["messages"] = messages
            return {"content": "ok", "tool_calls": []}

        asyncio.run(TurnOrchestrator(self.reg).run(
            "", "sys", llm_turn, audio=["Z:/nope-missing.wav"]))
        user = captured["messages"][-1]
        self.assertEqual(user["content"], "（语音消息，听完直接回应）")

    def test_policy_denied_tool_reported_failure(self):
        reg = CapabilityRegistry()
        reg.register_policy("deny", lambda: False)
        reg.register_capability(
            Capability(name="demo.search", handler=_ok, input=("q",),
                       requires=("deny",))
        )
        orch = TurnOrchestrator(reg)
        import asyncio

        async def llm(messages, tools):
            if tools:
                return {
                    "content": "",
                    "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "demo_search",
                                      "arguments": '{"q": "x"}'}}
                    ],
                }
            return {"content": "无法执行", "tool_calls": []}

        async def go():
            nonlocal orch
            return await orch.run("q", "s", llm)

        result = asyncio.run(go())
        self.assertFalse(result.tool_uses[0].ok)
        self.assertIn("deny", result.tool_uses[0].error)
        self.assertEqual(result.answer, "无法执行")

    def test_max_rounds_bounded_no_loop(self):
        import asyncio

        async def endless_llm(messages, tools):
            if tools:
                return {
                    "content": "",
                    "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "demo_search",
                                      "arguments": '{"q": "x"}'}}
                    ],
                }
            return {"content": "done", "tool_calls": []}

        orch = TurnOrchestrator(self.reg, max_tool_rounds=1)

        async def go():
            return await orch.run("q", "s", endless_llm)

        result = asyncio.run(go())
        self.assertLessEqual(result.iterations, 2)
        self.assertTrue(result.answer)

    def test_scheduler_capabilities_export_shape(self):
        reg = setup_scheduler_capabilities()
        orch = TurnOrchestrator(reg)
        tools = orch._export_tools()
        names = {t["function"]["name"] for t in tools}
        # 2026-10-20 更新到现状：
        #  · 今日删掉 3 个真依赖 NapCat/QCE 的 qq_* 工具（bootstrap/runbatch/shutdown）；
        #  · qq_export / qq_status / qq_process / qq_digest / qq_summarize 五个改为恒暴露
        #    （export 双路走 Lite 历史库；其余只读本地文件与知识库）；
        #  · member_profile 早已注册导出，旧名单漏了它。
        self.assertEqual(
            names,
            {             "ledger_search", "ledger_get", "ledger_list", "ledger_add", "ledger_update", "ledger_delete",
             "memory_recall", "memory_save", "system_time", "runtime_status",
             "diary_write", "diary_list", "diary_delete",
             "file_list", "file_read", "file_download", "file_share",
             "task_plan", "web_fetch", "web_search",
             "kb_add", "kb_query", "memory_audit", "memory_profile", "memory_causal", "memory_why",
             "member_profile", "report_qq_weekly",
             "qq_export", "qq_status", "qq_process", "qq_digest", "qq_summarize",
             "schedule_plan", "skill_add", "skill_feedback", "skill_search",
             "see_now", "screen_text",
             "song_list", "song_play", "song_send",
             "bili_find", "bili_watch", "bili_status", "bili_notes",
             "bili_read"},
        )


class TestLocalFallback(unittest.TestCase):
    def test_compact_fits_local_context(self):
        from backend.target_orchestrator import (
            _FALLBACK_TOOL_NAMES, _compact_for_local,
        )
        msgs = [{"role": "system", "content": "人设" * 3000}]
        msgs += [{"role": "user" if i % 2 == 0 else "assistant",
                  "content": "历史" * 500} for i in range(12)]
        out = _compact_for_local(msgs)
        self.assertEqual(len(out), 7)  # system + last 6
        self.assertLessEqual(len(out[0]["content"]), 3000)
        self.assertIn("bili_status", _FALLBACK_TOOL_NAMES)
        self.assertIn("bili_find", _FALLBACK_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
