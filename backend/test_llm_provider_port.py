"""Unit tests for the LLM Hexagonal port: vLLM adapter + reasoner adapter."""

from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from backend.llm_provider_port import (
    LLMProviderError,
    LLMProviderPort,
    is_llm_provider_port,
    llm_health_snapshot,
)
from backend.llm_reasoner import LLMReasoner, SYSTEM_PROMPT
from backend.llm_vllm_provider import LlmVllmProvider


def _sse_response(chunks: list[str], *, status: int = 200) -> httpx.Response:
    body = b""
    for text in chunks:
        item = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "model": "qwen2.5-3b-awq",
            "choices": [{"index": 0, "delta": {"content": text}}],
        }
        body += b"data: " + json.dumps(item).encode() + b"\n\n"
    body += b"data: [DONE]\n\n"
    return httpx.Response(status, content=body)


class _Signal:
    def __init__(self) -> None:
        self._cancelled = False

    def is_cancelled(self) -> bool:
        return self._cancelled


class LlmVllmProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_yields_deltas_and_metrics(self) -> None:
        transport = httpx.MockTransport(
            lambda request: _sse_response(["你", "好", "元亨"])
        )
        provider = LlmVllmProvider(client=httpx.AsyncClient(transport=transport))
        out = []
        async for delta in provider.stream_chat(
            [{"role": "user", "content": "hi"}], max_tokens=10
        ):
            out.append(delta)
        self.assertEqual("".join(out), "你好元亨")
        info = await provider.health()
        metrics = info["metrics"]
        self.assertGreater(metrics["first_token_ms"], 0)
        self.assertEqual(metrics["tokens"], 3)
        self.assertEqual(provider.state.value, "idle")
        await provider.close()

    async def test_abort_cancels_stream_and_wait_stopped(self) -> None:
        provider = LlmVllmProvider(
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: _sse_response(["a"] * 1000)
                )
            )
        )
        got: list[str] = []
        done = asyncio.Event()

        async def consume():
            try:
                async for delta in provider.stream_chat(
                    [{"role": "user", "content": "hi"}], max_tokens=1000
                ):
                    got.append(delta)
                    if len(got) >= 1:
                        provider.abort("test_interrupt")
                        await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                pass
            finally:
                done.set()

        task = asyncio.create_task(consume())
        await task
        self.assertTrue(done.is_set())
        self.assertTrue(await provider.wait_stopped(1.0))
        await provider.close()

    async def test_http_error_carries_stable_code(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(500, content=b"boom")
        )
        provider = LlmVllmProvider(client=httpx.AsyncClient(transport=transport))
        with self.assertRaises(LLMProviderError) as ctx:
            async for _ in provider.stream_chat(
                [{"role": "user", "content": "hi"}]
            ):
                pass
        self.assertEqual(ctx.exception.code, "LLM-PROVIDER-HTTP-500")
        await provider.close()

    async def test_connect_error_is_fail_closed(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        provider = LlmVllmProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
        with self.assertRaises(LLMProviderError) as ctx:
            async for _ in provider.stream_chat(
                [{"role": "user", "content": "hi"}]
            ):
                pass
        self.assertEqual(ctx.exception.code, "LLM-PROVIDER-CONNECT")
        await provider.close()

    async def test_health_reports_models(self) -> None:
        def health_ok(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"data": [{"id": "qwen2.5-3b-awq"}]},
            )

        provider = LlmVllmProvider(
            client=httpx.AsyncClient(transport=httpx.MockTransport(health_ok))
        )
        info = await provider.health()
        self.assertTrue(info["available"])
        self.assertIn("qwen2.5-3b-awq", info["models"])
        await provider.close()

    def test_port_detection(self) -> None:
        provider = LlmVllmProvider(
            client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: _sse_response([])))
        )
        self.assertTrue(is_llm_provider_port(provider))
        self.assertFalse(is_llm_provider_port(object()))
        snap = llm_health_snapshot(provider)
        self.assertIn("available", snap)
        self.assertNotIn("content", snap)

    async def test_tools_are_passed_through_in_payload(self) -> None:
        captured: dict = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return _sse_response(["ok"])

        provider = LlmVllmProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(capture)))
        tools = [{"type": "function", "function": {"name": "get_time"}}]
        async for _ in provider.stream_chat(
            [{"role": "user", "content": "hi"}], tools=tools, tool_choice="auto"
        ):
            pass
        self.assertEqual(captured["tools"], tools)
        self.assertEqual(captured["tool_choice"], "auto")
        await provider.close()

    async def test_without_tools_payload_stays_compatible(self) -> None:
        captured: dict = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return _sse_response(["ok"])

        provider = LlmVllmProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(capture)))
        async for _ in provider.stream_chat([{"role": "user", "content": "hi"}]):
            pass
        self.assertNotIn("tools", captured)
        self.assertNotIn("tool_choice", captured)
        await provider.close()


class OtherProviderStub:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.aborted = False
        self.stopped = False

    async def stream_chat(
        self,
        messages,
        *,
        signal=None,
        temperature=0.7,
        max_tokens=256,
        tools=None,
        tool_choice=None,
    ):
        self.messages = list(messages)
        for token in ["1", "2", "3"]:
            if signal is not None and signal.is_cancelled():
                return
            yield token

    def abort(self, reason="interrupt") -> None:
        self.aborted = True

    async def wait_stopped(self, timeout_s) -> bool:
        return True

    def stop(self, reason="shutdown") -> None:
        self.stopped = True

    def health(self) -> dict:
        return {"available": True, "state": "idle"}


class LLMReasonerTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_fixed_system_prompt_and_streams(self) -> None:
        stub = OtherProviderStub()
        reasoner = LLMReasoner(stub)
        out = []
        async for chunk in reasoner.generate("元亨，你好", None):
            out.append(chunk)
        self.assertEqual("".join(out), "123")
        self.assertEqual(stub.messages[0]["role"], "system")
        self.assertEqual(stub.messages[0]["content"], SYSTEM_PROMPT)
        self.assertEqual(stub.messages[1]["content"], "元亨，你好")

    async def test_signal_cancel_stops_yielding(self) -> None:
        stub = OtherProviderStub()
        reasoner = LLMReasoner(stub)
        signal = _Signal()
        out = []

        async def half() -> None:
            signal._cancelled = True

        async for chunk in reasoner.generate("x", signal):
            out.append(chunk)
            await half()
        self.assertEqual(len(out), 1)

    async def test_provider_error_is_carried(self) -> None:
        class BrokenStub(OtherProviderStub):
            async def stream_chat(self, messages, **kw):
                raise LLMProviderError("LLM-PROVIDER-CONNECT", "refused")
                yield ""  # pragma: no cover

        reasoner = LLMReasoner(BrokenStub())
        with self.assertRaises(LLMProviderError) as ctx:
            async for _ in reasoner.generate("x", None):
                pass
        self.assertEqual(ctx.exception.code, "LLM-PROVIDER-CONNECT")
        info = await reasoner.health()
        self.assertEqual(info["reasoner_error_code"], "LLM-PROVIDER-CONNECT")

    async def test_reasoner_passes_tools_through(self) -> None:
        class ToolsStub(OtherProviderStub):
            def __init__(self):
                super().__init__()
                self.tools = None
                self.tool_choice = None

            async def stream_chat(self, messages, **kw):
                self.tools = kw.get("tools")
                self.tool_choice = kw.get("tool_choice")
                yield "ok"

        stub = ToolsStub()
        reasoner = LLMReasoner(stub)
        reasoner.tools = [{"type": "function", "function": {"name": "get_time"}}]
        reasoner.tool_choice = "auto"
        out = [chunk async for chunk in reasoner.generate("hi", None)]
        self.assertEqual("".join(out), "ok")
        self.assertEqual(stub.tools, reasoner.tools)
        self.assertEqual(stub.tool_choice, "auto")

    def test_port_requires_conforming_provider(self) -> None:
        with self.assertRaises(ValueError):
            LLMReasoner(object())
        self.assertIsInstance(LlmVllmProvider.health, object)  # smoke attr


if __name__ == "__main__":
    unittest.main()
