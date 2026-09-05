"""Isolated end-to-end tests for the target voice-chain coordinator."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest

from backend.session_kernel import AudioRoute, EventKind, KernelState, ProviderCapabilities
from backend.target_chain import AudioChunk, CancellationSignal, PipelineError, TargetVoiceChain
from backend.tts_provider_port import (
    PCM_FRAME_SAMPLES,
    PCMChunk,
    TTSEventKind,
    TTSProviderCapabilities,
    TTSProviderEvent,
)


def _capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        continuous_capture=True,
        concurrent_input_output=True,
        audio_route=AudioRoute.HEADSET.value,
        audio_route_verified=True,
        vad_verified=True,
        wake_word_verified=True,
        echo_isolation_verified=True,
        asr_tts_concurrent=True,
        cancel_asr=True,
        cancel_generation=True,
        cancel_tts=True,
        cancel_playback=True,
        playback_verified=True,
        resource_budget_verified=True,
    )


class FakeReasoner:
    def __init__(self, chunks=("答", "案"), started=None, release=None):
        self.chunks = tuple(chunks)
        self.started = started
        self.release = release
        self.seen = []

    async def generate(self, text, signal):
        self.seen.append(text)
        if self.started:
            self.started.set()
        if self.release:
            await self.release.wait()
        for chunk in self.chunks:
            if signal.is_cancelled():
                return
            await asyncio.sleep(0)
            yield chunk


class FakeSpeech:
    def __init__(self, chunks=(b"pcm-1", b"pcm-2")):
        self.chunks = tuple(chunks)
        self.seen = []

    async def synthesize(self, text, signal):
        self.seen.append(text)
        for index, payload in enumerate(self.chunks):
            if signal.is_cancelled():
                return
            await asyncio.sleep(0)
            yield AudioChunk(payload, 24000)


class FakePlayback:
    def __init__(self):
        self.played = []

    async def play(self, chunk, lease, signal):
        if signal.is_cancelled():
            return
        self.played.append((chunk.samples, lease.turn_id))


class SyncReasoner:
    def __init__(self, started=None):
        self.started = started
        self.seen = []

    def generate(self, text, signal):
        self.seen.append(text)
        if self.started:
            self.started.set()
        # A synchronous local provider must not monopolize the event loop.
        time.sleep(0.01)
        if signal.is_cancelled():
            return iter(())
        return iter(("同步回答",))


class SyncSpeech:
    def synthesize(self, text, signal):
        time.sleep(0.01)
        return [(b"sync-audio", 24000)]


class TupleSpeech:
    def synthesize(self, text, signal):
        return (b"tuple-audio", 24000)


class InvalidSpeech:
    async def synthesize(self, text, signal):
        return (b"bad-audio", 0)


class SyncPlayback:
    def __init__(self):
        self.played = []

    def play(self, chunk, lease, signal):
        time.sleep(0.01)
        if not signal.is_cancelled():
            self.played.append((chunk.samples, lease.turn_id))


class InterruptiblePlayback:
    def __init__(self):
        self.started = asyncio.Event()
        self.interrupts = 0

    async def play(self, chunk, lease, signal):
        self.started.set()
        await asyncio.Future()

    def interrupt(self):
        self.interrupts += 1


class ConfirmingPlayback:
    def __init__(self, *, confirms_stop: bool, fails_stop_check: bool = False) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.confirms_stop = confirms_stop
        self.fails_stop_check = fails_stop_check
        self.interrupts = 0
        self.waits = 0

    async def play(self, chunk, lease, signal):
        self.started.set()
        await asyncio.Future()

    def interrupt(self):
        self.interrupts += 1
        if self.confirms_stop:
            self.stopped.set()

    async def wait_stopped(self, timeout_s):
        self.waits += 1
        if self.fails_stop_check:
            raise OSError("playback state unavailable")
        try:
            await asyncio.wait_for(self.stopped.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return False
        return True


class FinishingPlayback:
    """Playback fake whose physical drain is explicitly controlled by a test."""

    def __init__(self) -> None:
        self.played = []
        self.finish_started = asyncio.Event()
        self.release = asyncio.Event()
        self.queue_depth = 0
        self.active_turn_id = None

    async def play(self, chunk, lease, signal):
        self.played.append((chunk.samples, lease.turn_id))
        self.queue_depth = 1
        self.active_turn_id = lease.turn_id
        return True

    async def finish(self, lease, signal):
        self.finish_started.set()
        await self.release.wait()
        self.queue_depth = 0
        self.active_turn_id = None
        return True

    def health(self):
        return {
            "queue_depth": self.queue_depth,
            "queue_duration_ms": self.queue_depth * 20,
            "active_turn_id": self.active_turn_id,
            "playing": self.queue_depth > 0,
        }


class StopObservedPlayback:
    """Cancellation fake that exposes the queue-to-silence transition."""

    def __init__(self) -> None:
        self.played = asyncio.Event()
        self.stopped = asyncio.Event()
        self.queue_depth = 0
        self.active_turn_id = None
        self.interrupts = 0

    async def play(self, chunk, lease, signal):
        self.queue_depth = 1
        self.active_turn_id = lease.turn_id
        self.played.set()
        return True

    def interrupt(self, reason="interrupted"):
        self.interrupts += 1
        self.queue_depth = 0
        self.active_turn_id = None
        self.stopped.set()

    async def wait_stopped(self, timeout_s):
        try:
            await asyncio.wait_for(self.stopped.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return False
        return True

    def health(self):
        return {
            "queue_depth": self.queue_depth,
            "queue_duration_ms": self.queue_depth * 20,
            "active_turn_id": self.active_turn_id,
            "playing": self.queue_depth > 0,
        }


class ConfirmingSpeech:
    def __init__(self, *, confirms_stop: bool, fails_stop_check: bool = False) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.confirms_stop = confirms_stop
        self.fails_stop_check = fails_stop_check
        self.interrupts = 0
        self.waits = 0

    async def synthesize(self, text, signal):
        self.started.set()
        await asyncio.Future()
        if False:
            yield AudioChunk(b"unused", 24_000)

    def interrupt(self):
        self.interrupts += 1
        if self.confirms_stop:
            self.stopped.set()

    async def wait_stopped(self, timeout_s):
        self.waits += 1
        if self.fails_stop_check:
            raise OSError("speech state unavailable")
        try:
            await asyncio.wait_for(self.stopped.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return False
        return True


class DualStreamSession:
    """In-memory text/audio session used to exercise the new provider port."""

    def __init__(self, request, *, block_after_audio: bool = False):
        self.request = request
        self.text = []
        self.committed = asyncio.Event()
        self.stopped = asyncio.Event()
        self.cancelled = 0
        self.cancel_reasons = []
        self.block_after_audio = block_after_audio
        self.ready = asyncio.Event()

    async def push_text(self, delta):
        self.text.append(delta)

    async def commit_text(self):
        self.committed.set()

    async def audio_events(self):
        yield TTSProviderEvent(
            TTSEventKind.READY,
            self.request.speech_id,
            self.request.provider_epoch,
        )
        await self.committed.wait()
        yield TTSProviderEvent(
            TTSEventKind.PCM_CHUNK,
            self.request.speech_id,
            self.request.provider_epoch,
            chunk=PCMChunk(
                b"\x01\x00" * PCM_FRAME_SAMPLES,
                0,
            ),
        )
        if self.block_after_audio:
            await asyncio.Future()
        yield TTSProviderEvent(
            TTSEventKind.DONE,
            self.request.speech_id,
            self.request.provider_epoch,
        )

    def cancel(self, reason="cancelled"):
        self.cancelled += 1
        self.cancel_reasons.append(reason)
        self.stopped.set()

    async def wait_stopped(self, timeout_s):
        try:
            await asyncio.wait_for(self.stopped.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return False
        return True

    def health(self):
        return {"state": "ready" if not self.stopped.is_set() else "stopped"}

    def metrics(self):
        return {"queue_depth": 0, "text_deltas": len(self.text)}


class DualStreamProvider:
    def __init__(self, *, block_after_audio: bool = False):
        self.sessions = []
        self.block_after_audio = block_after_audio

    def describe_capabilities(self):
        return TTSProviderCapabilities(
            provider_id="fake-dual-stream",
            true_audio_stream=True,
            text_stream=True,
            cancel_observable=True,
            worker_isolated=True,
            worker_persistent=True,
        )

    def open(self, request):
        session = DualStreamSession(request, block_after_audio=self.block_after_audio)
        self.sessions.append(session)
        return session

    def health(self):
        return {"state": "ready", "sessions": len(self.sessions)}

    def metrics(self):
        return {"sessions": len(self.sessions)}


class PlaybackTrackingProvider(DualStreamProvider):
    def __init__(self, *, block_after_audio: bool = False) -> None:
        super().__init__(block_after_audio=block_after_audio)
        self.playback_states = []

    def set_playback_state(self, *, active, queue_depth=0, queue_duration_ms=0):
        self.playback_states.append(
            {
                "active": bool(active),
                "queue_depth": int(queue_depth),
                "queue_duration_ms": int(queue_duration_ms),
            }
        )


class ImmediateErrorSession(DualStreamSession):
    async def audio_events(self):
        yield TTSProviderEvent(
            TTSEventKind.READY,
            self.request.speech_id,
            self.request.provider_epoch,
        )
        await asyncio.sleep(0.02)
        yield TTSProviderEvent(
            TTSEventKind.ERROR,
            self.request.speech_id,
            self.request.provider_epoch,
            code="VOICE-TTS-FAKE-ERROR",
            detail="fake provider failed",
        )


class ImmediateErrorProvider(DualStreamProvider):
    def open(self, request):
        session = ImmediateErrorSession(request)
        self.sessions.append(session)
        return session


class UnconfirmedErrorProvider(ImmediateErrorProvider):
    def open(self, request):
        session = ImmediateErrorSession(request)

        async def never_stopped(timeout_s):
            await asyncio.sleep(0)
            return False

        session.wait_stopped = never_stopped
        self.sessions.append(session)
        return session


class CommitRaceSession(DualStreamSession):
    def __init__(self, request):
        super().__init__(request)
        self.commit_started = asyncio.Event()

    async def commit_text(self):
        self.commit_started.set()
        await asyncio.sleep(0.05)
        self.committed.set()

    async def audio_events(self):
        await self.commit_started.wait()
        # This event intentionally arrives while commit_text is still
        # awaiting; the chain must reject it as premature.
        yield TTSProviderEvent(
            TTSEventKind.DONE,
            self.request.speech_id,
            self.request.provider_epoch,
        )


class CommitRaceProvider(DualStreamProvider):
    def open(self, request):
        session = CommitRaceSession(request)
        self.sessions.append(session)
        return session


class BlockingReasoner:
    def __init__(self):
        self.started = asyncio.Event()

    async def generate(self, text, signal):
        self.started.set()
        await asyncio.Future()
        if False:
            yield "unreachable"


class RaisingReasoner:
    async def generate(self, text, signal):
        raise RuntimeError("reasoner failure")
        if False:
            yield "unreachable"


class UnconfirmedDualStreamProvider(DualStreamProvider):
    def open(self, request):
        session = DualStreamSession(request, block_after_audio=True)

        async def never_stopped(timeout_s):
            await asyncio.sleep(0)
            return False

        session.wait_stopped = never_stopped
        self.sessions.append(session)
        return session


class CountingCapabilityProvider(DualStreamProvider):
    def __init__(self):
        super().__init__()
        self.capability_calls = 0

    def describe_capabilities(self):
        self.capability_calls += 1
        return super().describe_capabilities()


class SyncDualStreamSession:
    def __init__(self, request):
        self.request = request
        self.text = []
        self.committed = threading.Event()
        self.stopped = threading.Event()
        self.cancelled = 0

    def push_text(self, delta):
        self.text.append(delta)

    def commit_text(self):
        self.committed.set()

    def audio_events(self):
        yield TTSProviderEvent(TTSEventKind.READY, self.request.speech_id, self.request.provider_epoch)
        self.committed.wait(1.0)
        yield TTSProviderEvent(
            TTSEventKind.PCM_CHUNK,
            self.request.speech_id,
            self.request.provider_epoch,
            chunk=PCMChunk(b"\x02\x00" * PCM_FRAME_SAMPLES, 0),
        )
        yield TTSProviderEvent(TTSEventKind.DONE, self.request.speech_id, self.request.provider_epoch)

    def cancel(self, reason="cancelled"):
        self.cancelled += 1
        self.stopped.set()

    def wait_stopped(self, timeout_s):
        return self.stopped.wait(timeout_s)

    def health(self):
        return {"state": "ready"}

    def metrics(self):
        return {"queue_depth": 0}


class SyncDualStreamProvider(DualStreamProvider):
    def open(self, request):
        session = SyncDualStreamSession(request)
        self.sessions.append(session)
        return session


class TargetVoiceChainTests(unittest.TestCase):
    def test_cancellation_signal_invokes_registered_side_effect_once(self):
        signal = CancellationSignal()
        calls = []
        signal.add_cancel_callback(lambda: calls.append("stop"))
        signal.cancel()
        signal.cancel()
        self.assertEqual(calls, ["stop"])

    def test_async_cancellation_hook_failure_is_consumed(self):
        async def scenario():
            signal = CancellationSignal()

            async def failing_hook():
                raise RuntimeError("hook failed")

            signal.add_cancel_callback(failing_hook)
            signal.cancel()
            await asyncio.sleep(0)
            # The hook failure must not escape as an unhandled task warning or
            # prevent the cooperative cancellation flag from being set.
            self.assertTrue(signal.is_cancelled())

        asyncio.run(scenario())

    def test_zero_budget_still_attempts_one_bounded_terminal_observation(self):
        async def scenario():
            signal = CancellationSignal()
            signal.mark_done()
            observations = []

            async def observer(timeout_s):
                observations.append(timeout_s)
                return False

            signal.add_terminal_waiter(observer)
            result = await asyncio.wait_for(signal.wait_terminal(0.0), timeout=0.05)
            self.assertFalse(result)
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0], 0.0)

        asyncio.run(scenario())

    def test_zero_budget_hanging_terminal_observation_is_bounded(self):
        async def scenario():
            signal = CancellationSignal()
            signal.mark_done()
            started = asyncio.Event()

            async def observer(timeout_s):
                started.set()
                await asyncio.Future()

            signal.add_terminal_waiter(observer)
            result = await asyncio.wait_for(signal.wait_terminal(0.0), timeout=0.05)
            self.assertFalse(result)
            self.assertTrue(started.is_set())

        asyncio.run(scenario())

    def test_zero_budget_sync_terminal_observation_is_bounded(self):
        async def scenario():
            signal = CancellationSignal()
            signal.mark_done()
            entered = threading.Event()
            release = threading.Event()

            def observer(timeout_s):
                entered.set()
                release.wait(1.0)
                return True

            signal.add_terminal_waiter(observer)
            result = await asyncio.wait_for(signal.wait_terminal(0.0), timeout=0.05)
            self.assertFalse(result)
            self.assertTrue(entered.is_set())
            release.set()
            await asyncio.sleep(0.01)

        asyncio.run(scenario())

    def test_idle_requires_wake_word_and_active_state_does_not(self):
        async def scenario():
            reasoner = FakeReasoner()
            chain = TargetVoiceChain(reasoner=reasoner)
            chain.start(_capabilities())

            ignored = await chain.submit_transcript("你好")
            self.assertIsNone(ignored.lease)
            self.assertEqual(reasoner.seen, [])

            activated = await chain.submit_transcript("元亨")
            self.assertIsNone(activated.lease)
            accepted = await chain.submit_transcript("继续")
            self.assertIsNotNone(accepted.lease)
            outcome = await accepted.task
            self.assertEqual(outcome.status, "completed")
            self.assertEqual(reasoner.seen, ["继续"])

        asyncio.run(scenario())

    def test_text_to_tts_to_playback_has_ordered_events_and_no_memory_commit(self):
        async def scenario():
            reasoner = FakeReasoner(("一", "句"))
            speech = FakeSpeech()
            playback = FakePlayback()
            chain = TargetVoiceChain(reasoner=reasoner, speech=speech, playback=playback)
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("测试链路")
            outcome = await submission.task

            self.assertEqual(outcome.status, "completed")
            self.assertFalse(outcome.committed)
            self.assertEqual(speech.seen, ["一句"])
            self.assertEqual(len(playback.played), 2)
            kinds = [event["kind"] for event in chain.kernel.recent_events()]
            self.assertLess(kinds.index(EventKind.TOKEN.value), kinds.index(EventKind.AUDIO_START.value))
            self.assertLess(kinds.index(EventKind.AUDIO_START.value), kinds.index(EventKind.AUDIO_DONE.value))
            self.assertLess(kinds.index(EventKind.AUDIO_DONE.value), kinds.index(EventKind.COMPLETE.value))
            self.assertEqual(chain.snapshot()["state"], KernelState.READY.value)

        asyncio.run(scenario())

    def test_interrupt_during_generation_invalidates_old_turn_and_suppresses_audio_done(self):
        async def scenario():
            started = asyncio.Event()
            release = asyncio.Event()
            reasoner = FakeReasoner(("不会输出",), started=started, release=release)
            speech = FakeSpeech()
            playback = FakePlayback()
            chain = TargetVoiceChain(reasoner=reasoner, speech=speech, playback=playback)
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("请中断")
            await started.wait()

            result = await chain.interrupt("barge_in", timeout_s=0.01)
            self.assertTrue(result.requested)
            outcome = await submission.task
            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(playback.played, [])
            self.assertFalse(any(
                event["kind"] == EventKind.AUDIO_DONE.value
                for event in chain.kernel.recent_events()
            ))
            self.assertEqual(chain.snapshot()["active_turn_id"], None)
            self.assertEqual(chain.snapshot()["state"], KernelState.READY.value)

        asyncio.run(scenario())

    def test_new_input_supersedes_previous_turn_without_stale_tokens(self):
        async def scenario():
            first_started = asyncio.Event()
            first_release = asyncio.Event()
            first_reasoner = FakeReasoner(("旧",), started=first_started, release=first_release)
            second_reasoner = FakeReasoner(("新",))

            # Use one adapter whose output changes after the first call.
            class SwitchingReasoner:
                def __init__(self):
                    self.calls = 0

                async def generate(self, text, signal):
                    self.calls += 1
                    if self.calls == 1:
                        first_started.set()
                        await first_release.wait()
                        if signal.is_cancelled():
                            return
                        yield "旧"
                    else:
                        yield "新"

            chain = TargetVoiceChain(reasoner=SwitchingReasoner())
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            first = await chain.submit_transcript("第一句")
            await first_started.wait()
            second = await chain.submit_transcript("第二句")
            first_outcome = await first.task
            second_outcome = await second.task

            self.assertEqual(first_outcome.status, "interrupted")
            self.assertEqual(second_outcome.status, "completed")
            token_events = [
                event
                for event in chain.kernel.recent_events()
                if event["kind"] == EventKind.TOKEN.value
            ]
            self.assertEqual(len(token_events), 1)
            self.assertEqual(token_events[0]["turn_id"], second.lease.turn_id)
            self.assertEqual(token_events[0]["payload"]["text"], "[redacted]")
            self.assertEqual(chain.snapshot()["owned_tasks"], 0)

        asyncio.run(scenario())

    def test_sync_provider_ports_run_off_event_loop_and_complete_normally(self):
        async def scenario():
            reasoner = SyncReasoner()
            speech = SyncSpeech()
            playback = SyncPlayback()
            chain = TargetVoiceChain(reasoner=reasoner, speech=speech, playback=playback)
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("同步路径")
            outcome = await submission.task

            self.assertEqual(outcome.status, "completed")
            self.assertEqual(reasoner.seen, ["同步路径"])
            self.assertEqual(len(playback.played), 1)

        asyncio.run(scenario())

    def test_single_block_tts_tuple_is_not_split_into_two_chunks(self):
        async def scenario():
            playback = SyncPlayback()
            chain = TargetVoiceChain(
                reasoner=SyncReasoner(),
                speech=TupleSpeech(),
                playback=playback,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("整段合成")
            outcome = await submission.task
            self.assertEqual(outcome.status, "completed")
            self.assertEqual(len(playback.played), 1)

        asyncio.run(scenario())

    def test_tts_provider_port_runs_text_and_audio_as_dual_stream(self):
        async def scenario():
            provider = DualStreamProvider()
            playback = SyncPlayback()
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答", "案")),
                tts_provider=provider,
                playback=playback,
                tts_voice_id="voice-reselected",
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("双流测试")
            outcome = await submission.task

            self.assertEqual(outcome.status, "completed")
            self.assertEqual(provider.sessions[0].text, ["答", "案"])
            self.assertTrue(provider.sessions[0].committed.is_set())
            self.assertEqual(len(playback.played), 1)
            self.assertEqual(len(playback.played[0][0]), 960)
            events = chain.kernel.recent_events()
            self.assertTrue(
                any(
                    event["kind"] == EventKind.TASK.value
                    and event["payload"].get("event_kind") == "FIRST_CHUNK"
                    for event in events
                )
            )
            tts_text_events = [
                event
                for event in events
                if event["kind"] == EventKind.TASK.value
                and event["payload"].get("event_kind") == "TTS_TEXT"
            ]
            self.assertEqual(len(tts_text_events), 3)
            self.assertTrue(any(event["payload"].get("final") for event in tts_text_events))
            self.assertTrue(any(event["kind"] == EventKind.AUDIO_DONE.value for event in events))
            snapshot = chain.snapshot()
            self.assertEqual(snapshot["ports"]["tts_voice_id"], "voice-reselected")
            self.assertEqual(snapshot["ports"]["tts_sessions"], 0)
            self.assertIsNotNone(snapshot["ports"]["tts_provider_metrics"])

        asyncio.run(scenario())

    def test_playback_finish_precedes_normal_audio_done(self):
        async def scenario():
            provider = PlaybackTrackingProvider()
            playback = FinishingPlayback()
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                tts_provider=provider,
                playback=playback,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("物理排空")

            await asyncio.wait_for(playback.finish_started.wait(), timeout=0.5)
            self.assertFalse(submission.task.done())
            self.assertFalse(
                any(
                    event["kind"] == EventKind.AUDIO_DONE.value
                    for event in chain.kernel.recent_events()
                )
            )
            self.assertTrue(provider.playback_states[-1]["active"])

            playback.release.set()
            outcome = await asyncio.wait_for(submission.task, timeout=0.5)
            self.assertEqual(outcome.status, "completed")
            self.assertTrue(
                any(
                    event["kind"] == EventKind.AUDIO_DONE.value
                    for event in chain.kernel.recent_events()
                )
            )
            self.assertFalse(provider.playback_states[-1]["active"])
            self.assertTrue(chain.snapshot()["ports"]["playback_finish_observable"])

        asyncio.run(scenario())

    def test_cancel_keeps_tts_playback_gate_busy_until_stop_is_observed(self):
        async def scenario():
            provider = PlaybackTrackingProvider(block_after_audio=True)
            playback = StopObservedPlayback()
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                tts_provider=provider,
                playback=playback,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("尾帧停止")
            await asyncio.wait_for(playback.played.wait(), timeout=0.5)

            result = await chain.interrupt("barge_in", timeout_s=0.5)
            outcome = await asyncio.wait_for(submission.task, timeout=0.5)

            self.assertEqual(outcome.status, "interrupted")
            self.assertFalse(result.timed_out_tasks)
            self.assertEqual(playback.interrupts, 1)
            self.assertTrue(
                any(
                    state["active"] and state["queue_depth"] == 0
                    for state in provider.playback_states
                )
            )
            self.assertFalse(provider.playback_states[-1]["active"])

        asyncio.run(scenario())

    def test_sync_tts_provider_session_is_adapted_without_blocking_loop(self):
        async def scenario():
            provider = SyncDualStreamProvider()
            playback = SyncPlayback()
            chain = TargetVoiceChain(
                reasoner=SyncReasoner(),
                tts_provider=provider,
                playback=playback,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("同步双流")
            outcome = await submission.task
            self.assertEqual(outcome.status, "completed")
            self.assertEqual(provider.sessions[0].text, ["同步回答"])
            self.assertEqual(len(playback.played), 1)

        asyncio.run(scenario())

    def test_tts_provider_cancel_is_registered_before_session_opens(self):
        async def scenario():
            provider = DualStreamProvider(block_after_audio=True)
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                tts_provider=provider,
                playback=SyncPlayback(),
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("取消双流")
            # Let the provider open and reach its committed audio stream.
            while not provider.sessions:
                await asyncio.sleep(0)
            await provider.sessions[0].committed.wait()
            result = await chain.interrupt("barge_in", timeout_s=0.5)
            outcome = await submission.task

            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(provider.sessions[0].cancelled, 1)
            self.assertFalse(result.timed_out_tasks)
            self.assertEqual(chain.snapshot()["ports"]["tts_controls_pending"], 0)
            self.assertFalse(
                any(event["kind"] == EventKind.AUDIO_DONE.value for event in chain.kernel.recent_events())
            )

        asyncio.run(scenario())

    def test_tts_audio_failure_interrupts_stalled_reasoner_and_preserves_error_code(self):
        async def scenario():
            provider = ImmediateErrorProvider()
            reasoner = BlockingReasoner()
            chain = TargetVoiceChain(reasoner=reasoner, tts_provider=provider)
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("音频先失败")
            await reasoner.started.wait()

            outcome = await asyncio.wait_for(submission.task, timeout=0.5)

            self.assertEqual(outcome.status, "failed")
            self.assertEqual(outcome.error_code, "VOICE-TTS-FAKE-ERROR")
            self.assertEqual(provider.sessions[0].cancelled, 1)
            self.assertEqual(provider.sessions[0].cancel_reasons, ["tts_provider_error"])
            self.assertEqual(chain.snapshot()["active_turn_id"], None)
            self.assertEqual(chain.snapshot()["state"], KernelState.READY.value)
            self.assertTrue(
                any(
                    event["kind"] == EventKind.ERROR.value
                    and event["payload"].get("code") == "VOICE-TTS-FAKE-ERROR"
                    for event in chain.kernel.recent_events()
                )
            )

        asyncio.run(scenario())

    def test_tts_failure_with_unconfirmed_stop_blocks_follow_up(self):
        async def scenario():
            provider = UnconfirmedErrorProvider()
            chain = TargetVoiceChain(reasoner=BlockingReasoner(), tts_provider=provider)
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("失败且未停止")

            outcome = await asyncio.wait_for(submission.task, timeout=0.5)
            self.assertEqual(outcome.status, "failed")
            self.assertTrue(chain.snapshot()["ports"]["tts_cleanup_blocked"])
            with self.assertRaises(PipelineError):
                await chain.submit_transcript("不应重叠")

        asyncio.run(scenario())

    def test_done_during_commit_is_rejected_until_commit_returns(self):
        async def scenario():
            provider = CommitRaceProvider()
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                tts_provider=provider,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("提交竞态")

            outcome = await asyncio.wait_for(submission.task, timeout=0.5)
            self.assertEqual(outcome.status, "failed")
            self.assertEqual(outcome.error_code, "VOICE-TTS-DONE-BEFORE-COMMIT")

        asyncio.run(scenario())

    def test_reasoner_failure_cancels_provider_session_once(self):
        async def scenario():
            provider = DualStreamProvider()
            chain = TargetVoiceChain(reasoner=RaisingReasoner(), tts_provider=provider)
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("推理失败")

            outcome = await asyncio.wait_for(submission.task, timeout=0.5)
            self.assertEqual(outcome.status, "failed")
            self.assertEqual(outcome.error_code, "PIPELINE_ERROR")
            self.assertEqual(provider.sessions[0].cancelled, 1)
            self.assertEqual(chain.snapshot()["ports"]["tts_controls_pending"], 0)

        asyncio.run(scenario())

    def test_tts_provider_done_before_commit_fails_closed(self):
        async def scenario():
            class PrematureSession(DualStreamSession):
                async def audio_events(self):
                    yield TTSProviderEvent(
                        TTSEventKind.DONE,
                        self.request.speech_id,
                        self.request.provider_epoch,
                    )

            class PrematureProvider(DualStreamProvider):
                def open(self, request):
                    session = PrematureSession(request)
                    self.sessions.append(session)
                    return session

            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                tts_provider=PrematureProvider(),
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("过早完成")
            outcome = await submission.task
            self.assertEqual(outcome.status, "failed")
            self.assertEqual(outcome.error_code, "VOICE-TTS-DONE-BEFORE-COMMIT")

        asyncio.run(scenario())

    def test_unconfirmed_provider_stop_blocks_follow_up_input_until_cleanup(self):
        async def scenario():
            provider = UnconfirmedDualStreamProvider()
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                tts_provider=provider,
                playback=SyncPlayback(),
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("需要阻塞")
            while not provider.sessions:
                await asyncio.sleep(0)
            await provider.sessions[0].committed.wait()
            result = await chain.interrupt("barge_in", timeout_s=0.05)
            await submission.task
            self.assertTrue(result.timed_out_tasks)
            self.assertTrue(chain.snapshot()["ports"]["tts_cleanup_blocked"])
            with self.assertRaises(PipelineError):
                await chain.submit_transcript("不应重叠")

        asyncio.run(scenario())

    def test_tts_capabilities_are_bound_for_one_provider_epoch(self):
        async def scenario():
            provider = CountingCapabilityProvider()
            chain = TargetVoiceChain(reasoner=FakeReasoner(("答",)), tts_provider=provider)
            chain.start(_capabilities())
            first = chain.snapshot()
            second = chain.snapshot()
            self.assertEqual(provider.capability_calls, 1)
            self.assertEqual(
                first["ports"]["tts_provider_capabilities"],
                second["ports"]["tts_provider_capabilities"],
            )
            chain.set_tts_voice("another-voice")
            self.assertEqual(provider.capability_calls, 1)

        asyncio.run(scenario())

    def test_invalid_audio_metadata_fails_the_turn_closedly(self):
        async def scenario():
            chain = TargetVoiceChain(reasoner=SyncReasoner(), speech=InvalidSpeech())
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("无效音频")
            outcome = await submission.task
            self.assertEqual(outcome.status, "failed")
            self.assertEqual(outcome.error_code, "PIPELINE_ERROR")
            self.assertEqual(chain.snapshot()["active_turn_id"], None)
            self.assertEqual(chain.snapshot()["state"], KernelState.READY.value)

        asyncio.run(scenario())

    def test_playback_interrupt_hook_runs_before_cancelled_turn_finishes(self):
        async def scenario():
            playback = InterruptiblePlayback()
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                speech=FakeSpeech((b"audio",)),
                playback=playback,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("播放中断")
            await playback.started.wait()

            result = await chain.interrupt("barge_in", timeout_s=0.5)
            self.assertTrue(result.requested)
            outcome = await submission.task
            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(playback.interrupts, 1)
            self.assertFalse(any(
                event["kind"] == EventKind.AUDIO_DONE.value
                for event in chain.kernel.recent_events()
            ))

        asyncio.run(scenario())

    def test_confirmed_playback_stop_is_included_in_cancel_completion(self):
        async def scenario():
            playback = ConfirmingPlayback(confirms_stop=True)
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                speech=FakeSpeech((b"audio",)),
                playback=playback,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("确认停止")
            await playback.started.wait()

            result = await chain.interrupt("barge_in", timeout_s=0.5)
            outcome = await submission.task
            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(playback.interrupts, 1)
            self.assertEqual(playback.waits, 1)
            self.assertFalse(result.timed_out_tasks)
            self.assertTrue(result.completed_tasks)
            ports = chain.snapshot()["ports"]
            self.assertTrue(ports["playback_cancel_supported"])
            self.assertTrue(ports["playback_stop_observable"])

        asyncio.run(scenario())

    def test_unconfirmed_playback_stop_is_a_kernel_cancel_timeout(self):
        async def scenario():
            playback = ConfirmingPlayback(confirms_stop=False)
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                speech=FakeSpeech((b"audio",)),
                playback=playback,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("无法确认停止")
            await playback.started.wait()

            result = await chain.interrupt("barge_in", timeout_s=0.02)
            outcome = await submission.task
            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(playback.interrupts, 1)
            self.assertEqual(playback.waits, 1)
            self.assertEqual(len(result.timed_out_tasks), 1)
            errors = [
                event
                for event in chain.kernel.recent_events()
                if event["kind"] == EventKind.ERROR.value
                and event["payload"].get("code") == "VOICE-CANCEL-TIMEOUT"
            ]
            self.assertTrue(errors)

        asyncio.run(scenario())

    def test_confirmed_tts_stop_is_included_in_cancel_completion(self):
        async def scenario():
            speech = ConfirmingSpeech(confirms_stop=True)
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                speech=speech,
                playback=FakePlayback(),
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("停止合成")
            await speech.started.wait()

            result = await chain.interrupt("barge_in", timeout_s=0.2)
            outcome = await submission.task
            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(speech.interrupts, 1)
            self.assertEqual(speech.waits, 1)
            self.assertFalse(result.timed_out_tasks)
            self.assertFalse(
                any(
                    event["kind"] == EventKind.AUDIO_DONE.value
                    for event in chain.kernel.recent_events()
                )
            )
            ports = chain.snapshot()["ports"]
            self.assertTrue(ports["speech_cancel_supported"])
            self.assertTrue(ports["speech_stop_observable"])

        asyncio.run(scenario())

    def test_unconfirmed_tts_stop_is_a_kernel_cancel_timeout(self):
        async def scenario():
            speech = ConfirmingSpeech(confirms_stop=False)
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                speech=speech,
                playback=FakePlayback(),
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("无法确认合成停止")
            await speech.started.wait()

            result = await chain.interrupt("barge_in", timeout_s=0.05)
            outcome = await submission.task
            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(speech.interrupts, 1)
            self.assertEqual(speech.waits, 1)
            self.assertEqual(len(result.timed_out_tasks), 1)
            self.assertTrue(
                any(
                    event["kind"] == EventKind.ERROR.value
                    and event["payload"].get("code") == "VOICE-CANCEL-TIMEOUT"
                    for event in chain.kernel.recent_events()
                )
            )

        asyncio.run(scenario())

    def test_playback_stop_check_failure_is_a_kernel_cancel_failure(self):
        async def scenario():
            playback = ConfirmingPlayback(
                confirms_stop=False,
                fails_stop_check=True,
            )
            chain = TargetVoiceChain(
                reasoner=FakeReasoner(("答",)),
                speech=FakeSpeech((b"audio",)),
                playback=playback,
            )
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("停止状态异常")
            await playback.started.wait()

            result = await chain.interrupt("barge_in", timeout_s=0.2)
            outcome = await submission.task
            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(len(result.failed_tasks), 1)
            errors = [
                event
                for event in chain.kernel.recent_events()
                if event["kind"] == EventKind.ERROR.value
                and event["payload"].get("code") == "VOICE-CANCEL-FAILED"
            ]
            self.assertTrue(errors)

        asyncio.run(scenario())

    def test_blocking_sync_reasoner_can_be_interrupted(self):
        async def scenario():
            started = threading.Event()

            class BlockingSyncReasoner:
                def generate(self, text, signal):
                    started.set()
                    while not signal.is_cancelled():
                        time.sleep(0.005)
                    return iter(())

            chain = TargetVoiceChain(reasoner=BlockingSyncReasoner())
            chain.start(_capabilities())
            await chain.submit_transcript("元亨")
            submission = await chain.submit_transcript("请停止")
            await asyncio.to_thread(started.wait, 1.0)

            result = await chain.interrupt("barge_in", timeout_s=0.5)
            self.assertTrue(result.requested)
            outcome = await submission.task
            self.assertEqual(outcome.status, "interrupted")
            self.assertIsNone(chain.snapshot()["active_turn_id"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
