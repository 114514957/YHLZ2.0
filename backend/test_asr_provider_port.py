"""Tests for the target ASR port and fail-closed no-model behavior."""

from __future__ import annotations

import asyncio
import unittest

from backend.asr_bridge import ASRBridge, ASREventKind
from backend.asr_provider_port import (
    ASRProviderError,
    ASRProviderState,
    UnavailableASRProvider,
    is_asr_provider_port,
)
from backend.media_adapter import AudioFrame, ProcessedAudioFrame
from backend.session_kernel import AudioRoute, ProviderCapabilities
from backend.speech_segment import SpeechSegmentAssembler
from backend.target_chain import TargetVoiceChain


class _Reasoner:
    async def generate(self, text, signal):
        yield "not reached"


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


def _frame(sequence: int, speech: bool) -> ProcessedAudioFrame:
    raw = AudioFrame(
        samples=b"frame",
        sample_rate=16_000,
        channels=1,
        sequence=sequence,
        generation=1,
        duration_ms=100,
    )
    return ProcessedAudioFrame(raw, raw.samples, speech, False)


class ASRProviderPortTests(unittest.TestCase):
    def test_unavailable_provider_is_a_complete_observable_port(self):
        async def scenario() -> None:
            provider = UnavailableASRProvider()
            self.assertTrue(is_asr_provider_port(provider))
            provider.start()
            self.assertEqual(provider.state, ASRProviderState.UNAVAILABLE)
            self.assertTrue(await provider.wait_stopped(0))
            provider.interrupt("test")
            self.assertEqual(provider.health()["metrics"]["interrupts"], 1)
            provider.stop()
            self.assertEqual(provider.state, ASRProviderState.STOPPED)

        asyncio.run(scenario())

    def test_no_model_surfaces_its_stable_error_code_through_asr_bridge(self):
        async def scenario() -> None:
            provider = UnavailableASRProvider()
            events = []
            chain = TargetVoiceChain(reasoner=_Reasoner())
            chain.start(_capabilities())
            bridge = ASRBridge(
                asr=provider,
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                on_event=events.append,
            )
            await bridge.accept_frame(_frame(1, True))
            task = await bridge.accept_frame(_frame(2, False))
            result = await task
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error_code, "ASR-MODEL-UNAVAILABLE")
            self.assertTrue(any(
                event.kind == ASREventKind.ERROR.value
                and event.payload.get("code") == "ASR-MODEL-UNAVAILABLE"
                for event in events
            ))
            self.assertFalse(bridge.snapshot()["provider"]["available"])
            await bridge.close()

        asyncio.run(scenario())

    def test_unavailable_provider_never_returns_mock_text(self):
        provider = UnavailableASRProvider()
        with self.assertRaises(ASRProviderError) as result:
            provider.transcribe(None, type("Signal", (), {"is_cancelled": lambda self: False})())
        self.assertEqual(result.exception.code, "ASR-MODEL-UNAVAILABLE")
        self.assertEqual(provider.health()["metrics"]["requests"], 1)

    def test_port_check_rejects_transcribe_only_legacy_shape(self):
        class LegacyASR:
            def transcribe(self, segment, signal):
                return ""

        self.assertFalse(is_asr_provider_port(LegacyASR()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
