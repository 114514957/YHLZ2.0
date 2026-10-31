"""Tests for the thin Target workbench adapter."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from backend.target_chain import PipelineSubmission
from backend.target_workbench_adapter import (
    TargetWorkbenchAdapter,
    WorkbenchTurnResult,
)


class _FakeChain:
    def __init__(self, submission):
        self.submission = submission
        self.calls = []
        self.kernel = object()

    async def submit_transcript(self, text, *, source="microphone"):
        self.calls.append((text, source))
        return self.submission

    async def interrupt(self, reason, *, timeout_s):
        self.calls.append(("interrupt", reason, timeout_s))
        return {"ok": True}

    def snapshot(self):
        return {"active_turn_id": None}

    async def shutdown(self):
        self.calls.append(("shutdown",))


class _FakeRuntime:
    def __init__(self, chain):
        self.chain = chain
        self.calls = []
        self.started = False

    def ingest(self, samples, **kwargs):
        self.calls.append(("ingest", samples, kwargs))
        return self.started

    def start(self, device, capabilities):
        self.calls.append(("start", device, capabilities))
        self.started = True
        return "assessment"

    async def run(self):
        self.calls.append(("run",))

    async def stop(self, reason):
        self.calls.append(("stop", reason))
        self.started = False

    def health(self):
        return {"state": "running"}


class TargetWorkbenchAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_default_and_explicit_request_normalization(self):
        self.assertEqual(TargetWorkbenchAdapter.normalize_request({}).pipeline, "legacy")
        request = TargetWorkbenchAdapter.normalize_request(
            {"pipeline": "TARGET", "continuous": "true", "audio_route": "HEADSET"}
        )
        self.assertEqual(request.pipeline, "target")
        self.assertTrue(request.continuous)
        self.assertEqual(request.audio_route, "headset")
        self.assertFalse(TargetWorkbenchAdapter.is_target_request({}))
        self.assertTrue(TargetWorkbenchAdapter.is_target_request({"pipeline": "target"}))

    def test_invalid_policy_is_rejected_or_not_opted_in(self):
        with self.assertRaises(ValueError):
            TargetWorkbenchAdapter.normalize_request({"pipeline": "experimental"})
        with self.assertRaises(ValueError):
            TargetWorkbenchAdapter.normalize_request({"audio_route": "speaker"})
        self.assertFalse(TargetWorkbenchAdapter.is_target_request({"pipeline": "experimental"}))

    async def test_submit_text_uses_existing_chain_and_returns_outcome(self):
        lease = SimpleNamespace(turn_id="turn-1")
        task = asyncio.create_task(
            asyncio.sleep(0, result=SimpleNamespace(
                status="completed", turn_id="turn-1", text="回答", error_code=None
            ))
        )
        chain = _FakeChain(PipelineSubmission(SimpleNamespace(), lease, task))
        events = []
        adapter = TargetWorkbenchAdapter(chain=chain, event_sink=events.append)
        result = await adapter.submit_text("你好", source="workbench")
        self.assertIsInstance(result, WorkbenchTurnResult)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.text, "回答")
        self.assertEqual(chain.calls, [("你好", "workbench")])
        self.assertEqual(events[-1]["event"], "turn_done")
        self.assertNotIn("回答", str(events[-1]))

    async def test_ignored_submission_does_not_create_turn(self):
        chain = _FakeChain(PipelineSubmission(SimpleNamespace(event=SimpleNamespace(value="WAKE_REQUIRED"))))
        adapter = TargetWorkbenchAdapter(chain=chain)
        result = await adapter.submit_text("闲聊")
        self.assertEqual(result.status, "ignored")
        self.assertEqual(result.error_code, "WAKE_REQUIRED")

    async def test_runtime_is_shared_and_lifecycle_delegates(self):
        chain = _FakeChain(PipelineSubmission(SimpleNamespace()))
        runtime = _FakeRuntime(chain)
        adapter = TargetWorkbenchAdapter(chain=chain, runtime=runtime)
        self.assertIs(adapter.chain, runtime.chain)
        self.assertFalse(adapter.ingest(b"audio"))
        runtime_started = await adapter.start("device", "caps")
        self.assertEqual(runtime_started, "assessment")
        self.assertTrue(adapter.ingest(b"audio", sample_rate=16000))
        await adapter.run()
        await adapter.stop("test")
        self.assertIn(("start", "device", "caps"), runtime.calls)
        self.assertEqual(runtime.calls[-1], ("stop", "test"))

    async def test_interrupt_delegates_without_own_state_machine(self):
        chain = _FakeChain(PipelineSubmission(SimpleNamespace()))
        adapter = TargetWorkbenchAdapter(chain=chain)
        await adapter.interrupt("barge_in", timeout_s=1.5)
        self.assertEqual(chain.calls[-1], ("interrupt", "barge_in", 1.5))

    def test_event_sink_redacts_raw_text(self):
        chain = _FakeChain(PipelineSubmission(SimpleNamespace()))
        events = []
        adapter = TargetWorkbenchAdapter(chain=chain, event_sink=events.append)
        adapter._emit("test", {"text": "secret", "audio": b"raw", "status": "ok"})
        self.assertEqual(events[0]["text"], "[redacted]")
        self.assertEqual(events[0]["audio"], "[redacted]")


class AdapterBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_rejects_mismatched_runtime(self):
        chain = _FakeChain(None)
        with self.assertRaises(ValueError):
            TargetWorkbenchAdapter(chain=chain, runtime=_FakeRuntime(_FakeChain(None)))

    def test_rejects_async_sink(self):
        with self.assertRaises(TypeError):
            TargetWorkbenchAdapter(chain=_FakeChain(None), event_sink=AsyncMock())

    async def test_exception_text_is_not_telemetry(self):
        chain = _FakeChain(None)
        chain.submit_transcript = AsyncMock(side_effect=RuntimeError('secret-provider-key'))
        events = []
        result = await TargetWorkbenchAdapter(chain=chain, event_sink=events.append).submit_text('hi')
        self.assertEqual(result.error_code, 'TARGET-ADAPTER-ERROR')
        self.assertNotIn('secret-provider-key', str(events))

    async def test_cancel_waiter_does_not_cancel_chain_task(self):
        release = asyncio.Event()
        async def work():
            await release.wait()
            return SimpleNamespace(status='completed', text='', error_code=None)
        task = asyncio.create_task(work())
        chain = _FakeChain(PipelineSubmission(SimpleNamespace(), SimpleNamespace(turn_id='one'), task))
        waiter = asyncio.create_task(TargetWorkbenchAdapter(chain=chain).submit_text('hi'))
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertFalse(task.cancelled())
        self.assertFalse(task.done())
        release.set()
        await task

    async def test_interrupt_timeout_is_not_reported_as_stopped(self):
        chain = _FakeChain(None)
        chain.interrupt = AsyncMock(return_value=SimpleNamespace(timed_out_tasks=('tts',), failed_tasks=()))
        events = []
        await TargetWorkbenchAdapter(chain=chain, event_sink=events.append).interrupt()
        self.assertEqual(events[-1]['event'], 'interrupt_result')
        self.assertTrue(events[-1]['timed_out'])
        self.assertNotEqual(events[-1]['status'], 'interrupted')

    def test_nested_payload_redaction(self):
        events = []
        adapter = TargetWorkbenchAdapter(chain=_FakeChain(None), event_sink=events.append)
        adapter._emit('test', {'parts': [[{'text': 'secret', 'token': 'secret'}], b'secret', object()]})
        self.assertNotIn('secret', str(events))

if __name__ == "__main__":
    unittest.main()
