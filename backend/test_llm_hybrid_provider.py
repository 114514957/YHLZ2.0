"""Unit tests for the hybrid LLM provider (API primary + local backup)."""

from __future__ import annotations

import asyncio
import unittest

from backend.llm_hybrid_provider import HybridLLMProvider
from backend.llm_provider_port import LLMProviderError


class StubLLM:
    def __init__(self, name, available=True, fail_streams=0, tokens=("a", "b", "c")):
        self.name = name
        self.available = available
        self.fail_streams = fail_streams
        self.tokens = list(tokens)
        self.stream_calls = 0
        self.aborted = False
        self.stopped = False
        self.passed = None

    async def stream_chat(self, messages, **kw):
        self.stream_calls += 1
        if self.stream_calls <= self.fail_streams:
            raise LLMProviderError("LLM-PROVIDER-CONNECT", self.name)
        for tok in self.tokens:
            yield tok

    def abort(self, reason="interrupt") -> None:
        self.aborted = True

    async def wait_stopped(self, timeout_s) -> bool:
        return True

    def stop(self, reason="shutdown") -> None:
        self.stopped = True

    def health(self) -> dict:
        return {"available": bool(self.available), "name": self.name}


class HybridLLMProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_primary_used_when_healthy(self) -> None:
        primary = StubLLM("api")
        backup = StubLLM("local")
        hybrid = HybridLLMProvider(primary, backup)
        out = [t async for t in hybrid.stream_chat([{"role": "user", "content": "hi"}])]
        self.assertEqual("".join(out), "abc")
        self.assertEqual(primary.stream_calls, 1)
        self.assertEqual(backup.stream_calls, 0)
        self.assertFalse(hybrid.using_backup)

    async def test_fails_over_after_threshold(self) -> None:
        primary = StubLLM("api", fail_streams=5)
        backup = StubLLM("local")
        hybrid = HybridLLMProvider(primary, backup, fail_threshold=2)
        # First failure raises (not yet at threshold).
        with self.assertRaises(LLMProviderError):
            async for _ in hybrid.stream_chat([{"role": "user", "content": "x"}]):
                pass
        # Second failure triggers the switch and the same call continues onto
        # the backup endpoint, which succeeds.
        out = [t async for t in hybrid.stream_chat([{"role": "user", "content": "x"}])]
        self.assertEqual("".join(out), "abc")
        self.assertTrue(hybrid.using_backup)
        self.assertEqual(backup.stream_calls, 1)

    async def test_recovers_primary_after_recheck(self) -> None:
        primary = StubLLM("api", fail_streams=2)
        backup = StubLLM("local")
        hybrid = HybridLLMProvider(primary, backup, fail_threshold=2, recheck_s=0.05)
        with self.assertRaises(LLMProviderError):
            async for _ in hybrid.stream_chat([{"role": "user", "content": "x"}]):
                pass
        async for _ in hybrid.stream_chat([{"role": "user", "content": "x"}]):
            pass
        self.assertTrue(hybrid.using_backup)
        await asyncio.sleep(0.06)
        # Recheck sees a healthy primary and switches back before streaming.
        out = [t async for t in hybrid.stream_chat([{"role": "user", "content": "x"}])]
        self.assertEqual("".join(out), "abc")
        self.assertFalse(hybrid.using_backup)

    async def test_all_down_is_fail_closed(self) -> None:
        primary = StubLLM("api", fail_streams=99)
        backup = StubLLM("local", fail_streams=99)
        hybrid = HybridLLMProvider(primary, backup, fail_threshold=1)
        with self.assertRaises(LLMProviderError) as ctx:
            async for _ in hybrid.stream_chat([{"role": "user", "content": "x"}]):
                pass
        self.assertEqual(ctx.exception.code, "LLM-PROVIDER-ALL-DOWN")

    def test_requires_conforming_endpoints(self) -> None:
        with self.assertRaises(ValueError):
            HybridLLMProvider(object(), StubLLM("b"))

    async def test_abort_and_stop_route_both(self) -> None:
        primary = StubLLM("api")
        backup = StubLLM("local")
        hybrid = HybridLLMProvider(primary, backup)
        hybrid.abort("x")
        hybrid.stop("y")
        self.assertTrue(primary.aborted and backup.aborted)
        self.assertTrue(primary.stopped and backup.stopped)
        self.assertTrue(await hybrid.wait_stopped(1.0))


if __name__ == "__main__":
    unittest.main()
