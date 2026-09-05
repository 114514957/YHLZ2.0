"""Isolation tests for the persistent TTS worker lifecycle boundary."""

from __future__ import annotations

import asyncio
import threading
import unittest

from backend.tts_provider_port import (
    PCM_FRAME_SAMPLES,
    PCMChunk,
    TTSEventKind,
    TTSProviderCapabilities,
    TTSProviderEvent,
    TTSRequest,
)
from backend.target_chain import TargetVoiceChain
from backend.tts_provider_worker import (
    PersistentTTSProvider,
    StrictIdleGate,
    WorkerLifecycleError,
    WorkerLifecycleState,
)


def _caps() -> TTSProviderCapabilities:
    return TTSProviderCapabilities(
        provider_id="fake-worker-provider",
        true_audio_stream=True,
        text_stream=True,
        cancel_observable=True,
        worker_isolated=True,
        worker_persistent=True,
    )


def _request(epoch: int = 0, speech_id: str = "speech-1") -> TTSRequest:
    return TTSRequest(
        session_id="session-1",
        turn_id="turn-1",
        speech_id=speech_id,
        provider_epoch=epoch,
        voice_id="voice-a",
    )


class _Session:
    def __init__(self, request: TTSRequest, worker: "_Worker") -> None:
        self.request = request
        self.worker = worker
        self.text = []
        self.stopped = threading.Event()
        self.cancel_reasons = []

    async def push_text(self, delta: str) -> None:
        self.text.append(delta)

    async def commit_text(self) -> None:
        return None

    async def audio_events(self):
        yield TTSProviderEvent(TTSEventKind.READY, self.request.speech_id, self.request.provider_epoch)
        yield TTSProviderEvent(
            TTSEventKind.PCM_CHUNK,
            self.request.speech_id,
            self.request.provider_epoch,
            chunk=PCMChunk(b"\x01\x00" * PCM_FRAME_SAMPLES, 0),
        )
        yield TTSProviderEvent(TTSEventKind.DONE, self.request.speech_id, self.request.provider_epoch)

    async def cancel(self, reason: str = "cancelled") -> None:
        self.cancel_reasons.append(reason)
        self.stopped.set()

    async def wait_stopped(self, timeout_s: float) -> bool:
        return self.stopped.wait(timeout_s)

    def health(self):
        return {"state": "stopped" if self.stopped.is_set() else "ready"}

    def metrics(self):
        return {"queue_depth": 0, "text_count": len(self.text), "text": "must redact"}


class _Worker:
    def __init__(self, serial: int, *, stop_confirms: bool = True) -> None:
        self.serial = serial
        self.alive = False
        self.stop_confirms = stop_confirms
        self.sessions = []
        self.stop_reasons = []

    def start(self) -> None:
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def describe_capabilities(self):
        return _caps()

    def open(self, request: TTSRequest):
        session = _Session(request, self)
        self.sessions.append(session)
        return session

    def shutdown(self, reason: str = "shutdown") -> None:
        self.stop_reasons.append(reason)
        self.alive = False

    def wait_stopped(self, timeout_s: float) -> bool:
        return self.alive is False and self.stop_confirms

    def health(self):
        return {"state": "ready" if self.alive else "stopped", "serial": self.serial}

    def metrics(self):
        return {"worker_serial": self.serial, "text": "must redact"}


class _StubbornWorker(_Worker):
    def __init__(self, serial: int) -> None:
        super().__init__(serial, stop_confirms=False)
        self.terminated = False

    def shutdown(self, reason: str = "shutdown") -> None:
        self.stop_reasons.append(reason)
        # Simulate a third-party provider that ignores graceful stop.

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False

    def wait_stopped(self, timeout_s: float) -> bool:
        return self.terminated and not self.alive


class StrictIdleGateTests(unittest.TestCase):
    def test_gate_explains_each_blocker_and_accepts_after_stop(self):
        gate = StrictIdleGate()
        gate.set_worker_alive(True)
        gate.begin_turn("turn")
        gate.begin_session("speech")
        gate.begin_text()
        gate.set_playback(active=True, queue_depth=2, queue_duration_ms=40)
        snapshot = gate.snapshot()
        self.assertFalse(snapshot.strict_idle)
        self.assertEqual(
            set(snapshot.reasons),
            {"active_turn", "active_session", "pending_text", "playback_not_empty"},
        )

        gate.end_text()
        gate.set_playback(active=False)
        gate.end_turn("turn")
        gate.mark_session_done("speech")
        self.assertFalse(gate.is_strict_idle())
        gate.mark_session_stopped("speech")
        self.assertTrue(gate.is_strict_idle())


class PersistentWorkerTests(unittest.TestCase):
    def test_open_reservation_blocks_recycle_until_session_is_published(self):
        created = []
        factory_ready = threading.Event()

        class BlockingOpenWorker(_Worker):
            def __init__(self, serial):
                super().__init__(serial)
                self.open_entered = threading.Event()
                self.release_open = threading.Event()

            def open(self, request):
                self.open_entered.set()
                self.release_open.wait(0.5)
                return super().open(request)

        def factory():
            worker = BlockingOpenWorker(len(created) + 1)
            created.append(worker)
            factory_ready.set()
            return worker

        provider = PersistentTTSProvider(factory, capabilities=_caps(), worker_isolated=True)

        async def scenario():
            opening = asyncio.create_task(provider.open(_request()))
            self.assertTrue(
                await asyncio.wait_for(
                    asyncio.to_thread(factory_ready.wait, 0.5),
                    timeout=1.0,
                )
            )
            self.assertTrue(
                await asyncio.wait_for(
                    asyncio.to_thread(created[0].open_entered.wait, 0.5),
                    timeout=1.0,
                )
            )
            snapshot = provider.strict_idle_snapshot()
            self.assertFalse(snapshot.strict_idle)
            self.assertEqual(snapshot.pending_open_ops, 1)
            self.assertIn("pending_open", snapshot.reasons)
            with self.assertRaises(WorkerLifecycleError) as blocked:
                provider.recycle(timeout_s=0.01)
            self.assertEqual(blocked.exception.code, "VOICE-TTS-WORKER-NOT-IDLE")

            created[0].release_open.set()
            session = await opening
            await session.cancel("cleanup")
            self.assertTrue(await session.wait_stopped(0.1))

        asyncio.run(scenario())

    def test_concurrent_open_rejects_second_request_while_first_is_opening(self):
        created = []
        factory_ready = threading.Event()

        class BlockingOpenWorker(_Worker):
            def __init__(self, serial):
                super().__init__(serial)
                self.open_entered = threading.Event()
                self.release_open = threading.Event()

            def open(self, request):
                self.open_entered.set()
                self.release_open.wait(0.5)
                return super().open(request)

        def factory():
            worker = BlockingOpenWorker(len(created) + 1)
            created.append(worker)
            factory_ready.set()
            return worker

        provider = PersistentTTSProvider(factory, capabilities=_caps(), worker_isolated=True)

        async def scenario():
            first_open = asyncio.create_task(provider.open(_request(speech_id="speech-first")))
            self.assertTrue(
                await asyncio.wait_for(
                    asyncio.to_thread(factory_ready.wait, 0.5),
                    timeout=1.0,
                )
            )
            self.assertTrue(
                await asyncio.wait_for(
                    asyncio.to_thread(created[0].open_entered.wait, 0.5),
                    timeout=1.0,
                )
            )
            with self.assertRaises(WorkerLifecycleError) as blocked:
                await provider.open(_request(speech_id="speech-second"))
            self.assertEqual(blocked.exception.code, "VOICE-TTS-WORKER-BUSY")

            created[0].release_open.set()
            session = await first_open
            self.assertEqual(len(created[0].sessions), 1)
            await session.cancel("cleanup")
            self.assertTrue(await session.wait_stopped(0.1))

        asyncio.run(scenario())

    def test_synchronous_worker_open_does_not_block_the_event_loop(self):
        class SlowOpenWorker(_Worker):
            def __init__(self):
                super().__init__(1)
                self.release_open = threading.Event()

            def open(self, request):
                self.release_open.wait(0.5)
                return super().open(request)

        worker = SlowOpenWorker()
        provider = PersistentTTSProvider(
            lambda: worker,
            capabilities=_caps(),
            worker_isolated=True,
        )

        async def scenario():
            callback_ran = asyncio.Event()
            loop = asyncio.get_running_loop()

            def release_from_loop():
                callback_ran.set()
                worker.release_open.set()

            loop.call_later(0.02, release_from_loop)
            session = await provider.open(_request())
            self.assertTrue(
                callback_ran.is_set(),
                "the loop callback must run while synchronous worker.open waits",
            )
            await session.cancel("cleanup")
            self.assertTrue(await session.wait_stopped(0.1))

        asyncio.run(scenario())

    def test_factory_is_lazy_and_worker_is_reused_until_recycle(self):
        created = []

        def factory():
            worker = _Worker(len(created) + 1)
            created.append(worker)
            return worker

        provider = PersistentTTSProvider(
            factory,
            capabilities=_caps(),
            worker_isolated=True,
            worker_persistent=True,
        )
        self.assertEqual(created, [])
        self.assertTrue(provider.describe_capabilities().c_candidate)

        async def scenario():
            first = await provider.open(_request())
            await first.push_text("a")
            await first.commit_text()
            events = [event async for event in first.audio_events()]
            self.assertEqual([event.kind for event in events], ["READY", "PCM_CHUNK", "DONE"])
            self.assertEqual(len(created), 1)
            self.assertTrue(provider.strict_idle_snapshot().reusable_idle)
            self.assertFalse(provider.strict_idle_snapshot().strict_idle)
            with self.assertRaises(WorkerLifecycleError) as blocked:
                provider.recycle(timeout_s=0.01)
            self.assertEqual(blocked.exception.code, "VOICE-TTS-WORKER-NOT-IDLE")

            self.assertEqual(provider.pending_stop_sessions(), ("speech-1",))
            await first.cancel("test-stop")
            self.assertTrue(await provider.wait_idle_stopped(0.1))
            self.assertTrue(provider.strict_idle_snapshot().strict_idle)
            provider.recycle(timeout_s=0.1)
            self.assertEqual(len(created), 2)
            self.assertEqual(provider.metrics()["worker_generation"], 2)

            second = await provider.open(_request(speech_id="speech-2"))
            self.assertEqual(len(created[1].sessions), 1)
            with self.assertRaises(WorkerLifecycleError) as stale:
                await first.push_text("late")
            self.assertEqual(stale.exception.code, "VOICE-TTS-WORKER-SESSION-STALE")
            await second.cancel("done")
            self.assertTrue(await second.wait_stopped(0.1))

        asyncio.run(scenario())

    def test_pending_text_and_playback_block_recycle(self):
        created = []

        class BlockingSession(_Session):
            def __init__(self, request, worker):
                super().__init__(request, worker)
                self.entered = asyncio.Event()
                self.release = asyncio.Event()

            async def push_text(self, delta):
                self.entered.set()
                await self.release.wait()
                self.text.append(delta)

        class BlockingWorker(_Worker):
            def open(self, request):
                session = BlockingSession(request, self)
                self.sessions.append(session)
                return session

        def factory():
            worker = BlockingWorker(len(created) + 1)
            created.append(worker)
            return worker

        provider = PersistentTTSProvider(factory, capabilities=_caps(), worker_isolated=True)

        async def scenario():
            session = await provider.open(_request())
            push_task = asyncio.create_task(session.push_text("pending"))
            await session.inner.entered.wait()
            self.assertIn("pending_text", provider.strict_idle_snapshot().reasons)
            with self.assertRaises(WorkerLifecycleError):
                provider.recycle(timeout_s=0.01)
            provider.set_playback_state(active=True, queue_depth=1, queue_duration_ms=20)
            self.assertIn("playback_not_empty", provider.strict_idle_snapshot().reasons)
            session.inner.release.set()
            await push_task
            provider.set_playback_state(active=False)
            await session.cancel("cleanup")
            self.assertTrue(await session.wait_stopped(0.1))
            provider.recycle(timeout_s=0.1)

        asyncio.run(scenario())

    def test_dead_worker_is_stop_evidence_but_not_reusable(self):
        worker = _Worker(1)
        provider = PersistentTTSProvider(
            lambda: worker,
            capabilities=_caps(),
            worker_isolated=True,
        )

        async def scenario():
            session = await provider.open(_request())
            worker.alive = False
            health = provider.health()
            self.assertEqual(health["state"], WorkerLifecycleState.FAILED.value)
            self.assertFalse(health["reusable_idle"])
            self.assertTrue(health["strict_idle"])
            # A dead worker can be rebuilt only through the explicit recycle
            # boundary; old session calls are stale after the crash.
            provider.recycle(timeout_s=0.1)
            self.assertEqual(provider.metrics()["worker_generation"], 2)
            with self.assertRaises(WorkerLifecycleError):
                await session.push_text("old")

        asyncio.run(scenario())

    def test_worker_crash_clears_finished_session_registry_before_recycle(self):
        created = []

        def factory():
            worker = _Worker(len(created) + 1)
            created.append(worker)
            return worker

        provider = PersistentTTSProvider(factory, capabilities=_caps(), worker_isolated=True)

        async def scenario():
            first = await provider.open(_request())
            await first.push_text("first")
            await first.commit_text()
            events = [event async for event in first.audio_events()]
            self.assertEqual(events[-1].kind, TTSEventKind.DONE.value)
            self.assertEqual(provider.pending_stop_sessions(), ("speech-1",))

            created[0].alive = False
            self.assertEqual(provider.health()["state"], WorkerLifecycleState.FAILED.value)
            self.assertEqual(provider.pending_stop_sessions(), ())
            self.assertEqual(provider.metrics()["finished_sessions"], [])
            self.assertTrue(provider.strict_idle_snapshot().strict_idle)

            provider.recycle(timeout_s=0.1)
            self.assertEqual(len(created), 2)
            self.assertEqual(provider.metrics()["worker_generation"], 2)

        asyncio.run(scenario())

    def test_late_old_generation_stop_callback_cannot_release_new_session(self):
        created = []

        def factory():
            worker = _Worker(len(created) + 1)
            created.append(worker)
            return worker

        provider = PersistentTTSProvider(factory, capabilities=_caps(), worker_isolated=True)

        async def scenario():
            first = await provider.open(_request())
            await first.push_text("first")
            await first.commit_text()
            _ = [event async for event in first.audio_events()]
            await first.cancel("first-stop")
            self.assertTrue(await first.wait_stopped(0.1))
            provider.recycle(timeout_s=0.1)

            second = await provider.open(_request())
            self.assertEqual(second.generation, 2)
            provider._session_stopped(first)
            self.assertEqual(provider.metrics()["active_sessions"], ["speech-1"])
            self.assertFalse(provider.strict_idle_snapshot().reusable_idle)

            await second.cancel("second-stop")
            self.assertTrue(await second.wait_stopped(0.1))

        asyncio.run(scenario())

    def test_failed_graceful_stop_requires_explicit_force_recovery(self):
        created = []

        def factory():
            worker = _StubbornWorker(len(created) + 1)
            created.append(worker)
            return worker

        provider = PersistentTTSProvider(factory, capabilities=_caps(), worker_isolated=True)
        provider.start()
        with self.assertRaises(WorkerLifecycleError) as failed:
            provider.recycle(timeout_s=0.01)
        self.assertEqual(failed.exception.code, "VOICE-TTS-WORKER-STOP-TIMEOUT")
        self.assertEqual(len(created), 1)
        self.assertFalse(provider.strict_idle_snapshot().strict_idle)
        self.assertFalse(provider.strict_idle_snapshot().reusable_idle)
        self.assertFalse(provider.health()["reusable_idle"])

        async def blocked_open():
            with self.assertRaises(WorkerLifecycleError) as blocked:
                await provider.open(_request())
            self.assertEqual(blocked.exception.code, "VOICE-TTS-WORKER-RECOVERY-REQUIRED")

        asyncio.run(blocked_open())

        provider.force_recycle(timeout_s=0.01)
        self.assertTrue(created[0].terminated)
        self.assertEqual(len(created), 2)
        self.assertEqual(provider.metrics()["worker_generation"], 2)

    def test_metrics_redact_provider_text(self):
        worker = _Worker(1)
        provider = PersistentTTSProvider(worker, capabilities=_caps(), worker_isolated=True)
        provider.start()
        metrics = provider.metrics()
        self.assertEqual(metrics["provider"]["text"], "[redacted]")
        self.assertEqual(provider.health()["state"], "ready")

    def test_target_chain_honors_strict_worker_switch_guard(self):
        worker = _Worker(1)
        provider = PersistentTTSProvider(worker, capabilities=_caps(), worker_isolated=True)
        chain = TargetVoiceChain(reasoner=object(), tts_provider=provider)
        provider.start()
        provider.set_playback_state(active=True, queue_depth=1, queue_duration_ms=20)
        with self.assertRaises(WorkerLifecycleError) as blocked:
            chain.set_tts_provider(None)
        self.assertEqual(blocked.exception.code, "VOICE-TTS-WORKER-NOT-IDLE")
        provider.set_playback_state(active=False)
        chain.set_tts_provider(None)
        self.assertIsNone(chain.tts_provider)


if __name__ == "__main__":
    unittest.main()
