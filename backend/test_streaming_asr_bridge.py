"""Contract tests for incremental ASR routing and transcript boundaries."""

from __future__ import annotations

import asyncio
import unittest

import numpy as np

from backend.asr_bridge import ASREventKind
from backend.asr_provider_port import ASRStreamUpdate, ASRStreamUpdateKind
from backend.media_adapter import AudioFrame, ProcessedAudioFrame
from backend.session_kernel import AudioRoute, ProviderCapabilities
from backend.streaming_asr_bridge import StreamingASRBridge
from backend.target_chain import TargetVoiceChain


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


def _frame(sequence: int, speech: bool, generation: int = 1) -> ProcessedAudioFrame:
    samples = np.zeros(1600, dtype=np.float32)
    raw = AudioFrame(
        samples=samples,
        sample_rate=16_000,
        channels=1,
        sequence=sequence,
        generation=generation,
        duration_ms=100,
    )
    return ProcessedAudioFrame(raw, samples, speech, False)


class _Reasoner:
    def __init__(self) -> None:
        self.seen = []

    async def generate(self, text, signal):
        self.seen.append(text)
        yield "ok"


class _StreamingProvider:
    def __init__(self, finals) -> None:
        self.finals = list(finals)
        self.started = False
        self.active = {}
        self.opened = []
        self.pushes = []
        self.interrupts = []
        self.stops = []

    def start(self) -> None:
        self.started = True

    def open_stream(self, stream_id, generation, sample_rate, channels, signal) -> None:
        self.opened.append((stream_id, generation, sample_rate, channels))
        self.active[stream_id] = {"generation": generation, "pushed": 0}

    def push_audio(self, stream_id, samples, sample_rate, signal):
        current = self.active[stream_id]
        current["pushed"] += 1
        self.pushes.append((stream_id, sample_rate, int(samples.size)))
        if current["pushed"] == 1:
            return (
                ASRStreamUpdate(
                    stream_id=stream_id,
                    generation=current["generation"],
                    kind=ASRStreamUpdateKind.PARTIAL,
                    text="元亨不应触发",
                    elapsed_ms=15,
                ),
            )
        return ()

    def finish_stream(self, stream_id, signal):
        current = self.active.pop(stream_id)
        text = self.finals.pop(0)
        return ASRStreamUpdate(
            stream_id=stream_id,
            generation=current["generation"],
            kind=ASRStreamUpdateKind.FINAL if text else ASRStreamUpdateKind.EMPTY,
            text=text,
            elapsed_ms=30,
        )

    def interrupt(self, reason="interrupt") -> None:
        self.interrupts.append(reason)
        self.active.clear()

    def wait_stopped(self, timeout_s) -> bool:
        return not self.active

    def stop(self, reason="shutdown") -> None:
        self.stops.append(reason)
        self.active.clear()

    def health(self):
        return {
            "available": self.started,
            "state": "ready" if self.started else "stopped",
            "text": "must redact",
        }


class StreamingASRBridgeTests(unittest.TestCase):
    def test_partial_never_reaches_gate_or_memory_and_final_controls_turns(self) -> None:
        async def scenario() -> None:
            reasoner = _Reasoner()
            provider = _StreamingProvider(["元亨", "继续"])
            events = []
            chain = TargetVoiceChain(reasoner=reasoner)
            chain.start(_capabilities())
            bridge = StreamingASRBridge(asr=provider, chain=chain, on_event=events.append)
            bridge.start()

            await bridge.accept_frame(_frame(1, True))
            await bridge.accept_frame(_frame(2, False))
            await bridge.wait_idle()
            self.assertEqual(reasoner.seen, [])
            self.assertEqual(len(provider.pushes), 2)
            partial = next(event for event in events if event.kind == ASREventKind.PARTIAL.value)
            self.assertEqual(partial.payload["text_length"], len("元亨不应触发"))
            self.assertNotIn("text", partial.payload)
            self.assertTrue(all("元亨不应触发" not in repr(event.payload) for event in events))
            self.assertEqual(bridge.snapshot()["provider"]["text"], "[redacted]")

            await bridge.accept_frame(_frame(3, True))
            await bridge.accept_frame(_frame(4, False))
            await bridge.wait_idle()
            await chain.wait_idle()
            self.assertEqual(reasoner.seen, ["继续"])
            self.assertEqual(bridge.snapshot()["completed"], 2)
            await bridge.close()

        asyncio.run(scenario())

    def test_close_interrupts_live_stream_and_requires_stop_observation(self) -> None:
        async def scenario() -> None:
            provider = _StreamingProvider(["unused"])
            chain = TargetVoiceChain(reasoner=_Reasoner())
            chain.start(_capabilities())
            bridge = StreamingASRBridge(asr=provider, chain=chain, cancel_timeout_s=0.2)
            bridge.start()
            await bridge.accept_frame(_frame(1, True))
            for _ in range(50):
                if provider.active:
                    break
                await asyncio.sleep(0.005)
            self.assertTrue(provider.active)
            await bridge.close("test_shutdown")
            snapshot = bridge.snapshot()
            # The second idempotent interrupt closes the provider-open race:
            # the first may run just before its native stream is materialized.
            self.assertEqual(provider.interrupts[0], "stream_cancel")
            self.assertIn("stream_open_cancelled", provider.interrupts)
            self.assertEqual(provider.stops, ["test_shutdown"])
            self.assertEqual(snapshot["cancel_stop_confirmed"], 1)
            self.assertEqual(snapshot["cancel_stop_timeouts"], 0)
            self.assertTrue(snapshot["closed"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
