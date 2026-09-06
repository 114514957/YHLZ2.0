"""Turn Orchestrator tests (ADR-007 core loop, fake LLM driven)."""

import unittest

from backend.target_capability_registry import Capability, CapabilityRegistry
from backend.target_orchestrator import TurnOrchestrator
from backend.target_scheduler_tools import setup_scheduler_capabilities


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
        self.assertEqual(
            names,
            {"ledger_search", "memory_recall", "memory_save", "system_time",
             "diary_write", "diary_list", "diary_delete",
             "file_list", "file_read", "task_plan", "web_fetch", "web_search",
             "kb_add", "kb_query",
             "qq_bootstrap", "qq_digest", "qq_export", "qq_process", "qq_runbatch", "qq_shutdown", "qq_status", "qq_summarize"},
        )


if __name__ == "__main__":
    unittest.main()
