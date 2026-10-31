"""Injected daemon-style factory, safe tool rounds and turn cancellation."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.target_orchestrator import build_openai_compatible_llm_turn


class FactoryStreamBindingTest(unittest.IsolatedAsyncioTestCase):
    async def test_new_turn_does_not_uncancel_old_generation(self):
        from backend import turn_control
        old = turn_control.clear("generation-test")
        turn_control.request("generation-test")
        self.assertTrue(turn_control.cancelled("generation-test", old))
        new = turn_control.clear("generation-test")
        self.assertTrue(turn_control.cancelled("generation-test", old))
        self.assertFalse(turn_control.cancelled("generation-test", new))

    async def test_clone_keeps_original_unmodified_and_delta_before_return(self):
        got = []
        original = build_openai_compatible_llm_turn(base_url="http://local", model="test")
        bound = original.with_stream(on_delta=got.append)
        async def stream(**options):
            await options["on_event"]({"kind": "delta", "stage": "content", "delta": "你好"})
            self.assertEqual(got, ["你好"])
            return {"content": "你好", "tool_calls": []}
        with patch("backend.llm_stream.stream_openai_compatible", stream):
            await bound([], [])
        self.assertIsNot(original, bound)

    async def test_tool_round_content_is_not_spoken(self):
        got = []
        turn = build_openai_compatible_llm_turn(on_delta=got.append, defer_tool_content=True)
        async def stream(**options):
            await options["on_event"]({"kind": "delta", "stage": "content", "delta": "我先查工具"})
            self.assertEqual(got, [])
            return {"content": "我先查工具", "tool_calls": [{"id": "c1"}]}
        with patch("backend.llm_stream.stream_openai_compatible", stream):
            await turn([], [{"type": "function"}])
        self.assertEqual(got, [])

    async def test_tool_offered_but_no_call_is_deferred_until_classified(self):
        got = []
        turn = build_openai_compatible_llm_turn(on_delta=got.append, defer_tool_content=True)
        async def stream(**options):
            await options["on_event"]({"kind": "delta", "stage": "content", "delta": "最终回答"})
            self.assertEqual(got, [])
            return {"content": "最终回答", "tool_calls": []}
        with patch("backend.llm_stream.stream_openai_compatible", stream):
            await turn([], [{"type": "function"}])
        self.assertEqual(got, ["最终回答"])

    async def test_cancel_drops_late_delta_and_deferred_flush(self):
        stop = [False]
        got = []
        turn = build_openai_compatible_llm_turn(on_delta=got.append,
            should_stop=lambda: stop[0], defer_tool_content=True)
        async def stream(**options):
            await options["on_event"]({"kind": "delta", "stage": "content", "delta": "未播"})
            stop[0] = True
            await options["on_event"]({"kind": "delta", "stage": "content", "delta": "迟到"})
            return {"content": "未播迟到", "tool_calls": []}
        with patch("backend.llm_stream.stream_openai_compatible", stream):
            await turn([], [{"type": "function"}])
        self.assertEqual(got, [])

    async def test_stream_failure_after_spoken_content_cannot_duplicate_fallback(self):
        calls = []
        got = []
        turn = build_openai_compatible_llm_turn(on_delta=got.append,
            base_url="http://primary", fallback_base_url="http://fallback")
        async def stream(**options):
            calls.append(options["base_url"])
            await options["on_event"]({"kind": "delta", "stage": "content", "delta": "已播"})
            raise RuntimeError("network break")
        with patch("backend.llm_stream.stream_openai_compatible", stream):
            with self.assertRaises(RuntimeError):
                await turn([], [])
        self.assertEqual(calls, ["http://primary"])
        self.assertEqual(got, ["已播"])

    async def test_audio_injected_factory_rebinds_local_stream_in_session(self):
        from backend.target_entry import ConversationSession
        from backend.target_kw_index import KeywordIndex
        from backend.target_memory import TargetMemoryService
        from backend.target_scheduler_tools import setup_scheduler_capabilities
        with tempfile.TemporaryDirectory() as tmp:
            kw = KeywordIndex(Path(tmp) / "kw.db")
            mem = TargetMemoryService(db_path=Path(tmp) / "mem.db", kw_index=kw)
            original = build_openai_compatible_llm_turn()
            session = ConversationSession(memory=mem, registry=setup_scheduler_capabilities(),
                                           llm_turn=original, channel="stream_test")
            session.render_system = lambda: "test"
            session._transcribe_audio_turn = AsyncMock()
            got = []
            async def stream(**options):
                self.assertEqual(options["model"], "gemma-4-e4b")
                self.assertEqual(options["base_url"], "http://127.0.0.1:8081/v1/chat/completions")
                self.assertEqual(options["max_tokens"], 220)
                await options["on_event"]({"kind": "delta", "stage": "content", "delta": "你好呀"})
                self.assertEqual(got, ["你好呀"])
                return {"content": "你好呀", "tool_calls": []}
            async def run(**kwargs):
                self.assertIsNot(kwargs["llm_turn"], original)
                await kwargs["llm_turn"]([], [])
                return SimpleNamespace(answer="你好呀", tool_uses=[], iterations=1)
            session.orchestrator.run = run
            with patch("backend.llm_stream.stream_openai_compatible", stream):
                info = await session.run_turn("", audio=["fake.wav"], on_delta=got.append)
            self.assertEqual(info["answer"], "你好呀")
            self.assertIs(session.llm_turn, original)
            await asyncio.gather(*session._summary_tasks, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
