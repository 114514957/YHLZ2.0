"""Isolated tests for the VAD-segment to TargetVoiceChain ASR bridge."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest

from backend.asr_bridge import ASRError, ASREventKind, ASRBridge
from backend.media_adapter import AudioFrame, ProcessedAudioFrame
from backend.session_kernel import AudioRoute, ProviderCapabilities
from backend.speech_segment import SpeechSegment, SpeechSegmentAssembler
from backend.target_chain import TargetVoiceChain


def _caps() -> ProviderCapabilities:
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


def _processed(sequence: int, generation: int, speech: bool, text: bytes = b"x"):
    frame = AudioFrame(
        samples=text,
        sample_rate=16_000,
        channels=1,
        sequence=sequence,
        generation=generation,
    )
    return ProcessedAudioFrame(frame=frame, samples=text, speech=speech, aec_applied=False)


class FakeReasoner:
    def __init__(self) -> None:
        self.seen = []

    async def generate(self, text, signal):
        self.seen.append(text)
        yield "ok"


class SequenceASR:
    def __init__(self, values) -> None:
        self.values = list(values)

    async def transcribe(self, segment: SpeechSegment, signal) -> str:
        await asyncio.sleep(0)
        return self.values.pop(0)


class DictASR:
    async def transcribe(self, segment: SpeechSegment, signal):
        return {"text": "元亨字典结果"}


class BlockingASR:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.calls = 0

    def transcribe(self, segment: SpeechSegment, signal) -> str:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            while not signal.is_cancelled():
                time.sleep(0.005)
            return "旧"
        return "元亨新"


class StopObservedASR:
    def __init__(self, *, confirms_stop: bool, fails_stop_check: bool = False) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.confirms_stop = confirms_stop
        self.fails_stop_check = fails_stop_check
        self.calls = 0
        self.interrupts = 0
        self.waits = 0

    async def transcribe(self, segment: SpeechSegment, signal) -> str:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            await asyncio.Future()
        return "元亨新"

    def interrupt(self) -> None:
        self.interrupts += 1
        if self.confirms_stop:
            self.stopped.set()

    async def wait_stopped(self, timeout_s: float) -> bool:
        self.waits += 1
        if self.fails_stop_check:
            raise OSError("asr state unavailable")
        try:
            await asyncio.wait_for(self.stopped.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return False
        return True


class ASRBridgeTests(unittest.TestCase):
    def test_segment_transcript_passes_wake_gate_then_reaches_chain(self) -> None:
        async def scenario() -> None:
            reasoner = FakeReasoner()
            chain = TargetVoiceChain(reasoner=reasoner)
            chain.start(_caps())
            events = []
            bridge = ASRBridge(
                asr=SequenceASR(["元亨", "继续"]),
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                on_event=events.append,
            )
            generation = 1
            self.assertIsNone(await bridge.accept_frame(_processed(1, generation, True)))
            first_task = await bridge.accept_frame(_processed(2, generation, False))
            first_result = await first_task
            self.assertEqual(first_result.status, "completed")
            self.assertIsNone(first_result.submission.lease)

            await bridge.accept_frame(_processed(3, generation, True))
            second_task = await bridge.accept_frame(_processed(4, generation, False))
            second_result = await second_task
            self.assertEqual(second_result.status, "completed")
            await second_result.submission.task
            self.assertEqual(reasoner.seen, ["继续"])
            self.assertTrue(any(event.kind == ASREventKind.COMPLETED.value for event in events))
            self.assertTrue(all("text" not in event.payload for event in events))
            await bridge.close()

        asyncio.run(scenario())

    def test_new_segment_cancels_sync_asr_and_discards_old_transcript(self) -> None:
        async def scenario() -> None:
            reasoner = FakeReasoner()
            chain = TargetVoiceChain(reasoner=reasoner)
            chain.start(_caps())
            asr = BlockingASR()
            bridge = ASRBridge(
                asr=asr,
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                cancel_timeout_s=0.2,
            )
            first = await bridge.accept_frame(_processed(1, 1, True))
            first = await bridge.accept_frame(_processed(2, 1, False))
            await asyncio.to_thread(asr.started.wait, 1.0)
            await bridge.accept_frame(_processed(3, 1, True))
            second = await bridge.accept_frame(_processed(4, 1, False))
            with self.assertRaises(asyncio.CancelledError):
                await first
            second_result = await second
            self.assertEqual(second_result.text, "元亨新")
            self.assertEqual(reasoner.seen, ["新"])
            self.assertGreaterEqual(bridge.snapshot()["stale"], 1)
            self.assertGreaterEqual(bridge.snapshot()["cancelled"], 1)
            await bridge.close()

        asyncio.run(scenario())

    def test_timeout_and_empty_result_are_explicit_failures(self) -> None:
        async def scenario() -> None:
            reasoner = FakeReasoner()
            chain = TargetVoiceChain(reasoner=reasoner)

            class Slow:
                async def transcribe(self, segment, signal):
                    await asyncio.sleep(1)

            bridge = ASRBridge(
                asr=Slow(),
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                timeout_s=0.01,
            )
            await bridge.accept_frame(_processed(1, 1, True))
            task = await bridge.accept_frame(_processed(2, 1, False))
            result = await task
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error_code, "ASR-TIMEOUT")
            self.assertEqual(bridge.snapshot()["timeouts"], 1)
            self.assertEqual(reasoner.seen, [])
            await bridge.close()

        asyncio.run(scenario())

    def test_confirmed_asr_stop_allows_next_segment_without_overlap(self) -> None:
        async def scenario() -> None:
            reasoner = FakeReasoner()
            chain = TargetVoiceChain(reasoner=reasoner)
            chain.start(_caps())
            asr = StopObservedASR(confirms_stop=True)
            bridge = ASRBridge(
                asr=asr,
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                cancel_timeout_s=0.2,
            )
            await bridge.accept_frame(_processed(1, 1, True))
            first = await bridge.accept_frame(_processed(2, 1, False))
            await asr.started.wait()

            await bridge.accept_frame(_processed(3, 1, True))
            second = await bridge.accept_frame(_processed(4, 1, False))
            with self.assertRaises(asyncio.CancelledError):
                await first
            result = await second
            self.assertEqual(result.status, "completed")
            self.assertEqual(reasoner.seen, ["新"])
            snapshot = bridge.snapshot()
            self.assertEqual(snapshot["cancel_stop_confirmed"], 1)
            self.assertEqual(snapshot["cancel_stop_timeouts"], 0)
            self.assertEqual(asr.interrupts, 1)
            self.assertEqual(asr.waits, 1)
            self.assertTrue(snapshot["ports"]["asr_cancel_supported"])
            self.assertTrue(snapshot["ports"]["asr_stop_observable"])
            await bridge.close()

        asyncio.run(scenario())

    def test_unconfirmed_asr_stop_rejects_next_segment_and_records_timeout(self) -> None:
        async def scenario() -> None:
            chain = TargetVoiceChain(reasoner=FakeReasoner())
            chain.start(_caps())
            events = []
            asr = StopObservedASR(confirms_stop=False)
            bridge = ASRBridge(
                asr=asr,
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                cancel_timeout_s=0.01,
                on_event=events.append,
            )
            await bridge.accept_frame(_processed(1, 1, True))
            first = await bridge.accept_frame(_processed(2, 1, False))
            await asr.started.wait()

            await bridge.accept_frame(_processed(3, 1, True))
            with self.assertRaises(ASRError):
                await bridge.accept_frame(_processed(4, 1, False))
            with self.assertRaises(asyncio.CancelledError):
                await first
            snapshot = bridge.snapshot()
            self.assertEqual(snapshot["cancel_stop_timeouts"], 1)
            self.assertEqual(snapshot["last_cancel_stop_status"], "timeout")
            self.assertEqual(asr.interrupts, 1)
            self.assertEqual(asr.waits, 1)
            self.assertTrue(any(
                event.kind == ASREventKind.ERROR.value
                and event.payload.get("code") == "ASR-CANCEL-TIMEOUT"
                for event in events
            ))
            await bridge.close()

        asyncio.run(scenario())

    def test_failed_asr_stop_check_rejects_next_segment_and_records_failure(self) -> None:
        async def scenario() -> None:
            chain = TargetVoiceChain(reasoner=FakeReasoner())
            chain.start(_caps())
            events = []
            asr = StopObservedASR(
                confirms_stop=False,
                fails_stop_check=True,
            )
            bridge = ASRBridge(
                asr=asr,
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                cancel_timeout_s=0.2,
                on_event=events.append,
            )
            await bridge.accept_frame(_processed(1, 1, True))
            first = await bridge.accept_frame(_processed(2, 1, False))
            await asr.started.wait()

            await bridge.accept_frame(_processed(3, 1, True))
            with self.assertRaises(ASRError):
                await bridge.accept_frame(_processed(4, 1, False))
            with self.assertRaises(asyncio.CancelledError):
                await first
            snapshot = bridge.snapshot()
            self.assertEqual(snapshot["cancel_stop_failures"], 1)
            self.assertEqual(snapshot["last_cancel_stop_status"], "failed")
            self.assertTrue(any(
                event.kind == ASREventKind.ERROR.value
                and event.payload.get("code") == "ASR-CANCEL-FAILED"
                for event in events
            ))
            await bridge.close()

        asyncio.run(scenario())

    def test_mapping_result_is_normalized_without_logging_transcript(self) -> None:
        async def scenario() -> None:
            reasoner = FakeReasoner()
            chain = TargetVoiceChain(reasoner=reasoner)
            chain.start(_caps())
            events = []
            bridge = ASRBridge(
                asr=DictASR(),
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                on_event=events.append,
            )
            await bridge.accept_frame(_processed(1, 1, True))
            task = await bridge.accept_frame(_processed(2, 1, False))
            result = await task
            self.assertEqual(result.text, "元亨字典结果")
            self.assertTrue(any(event.kind == ASREventKind.COMPLETED.value for event in events))
            self.assertTrue(all("text" not in event.payload for event in events))
            await bridge.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
