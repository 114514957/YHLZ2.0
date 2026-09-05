"""Isolation tests for the target voice composition root."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from backend.memory_guard import ReadOnlyMemoryFacade
from backend.streaming_asr_bridge import StreamingASRBridge
from backend.target_composition import (
    TargetCompositionError,
    TargetVoiceComposition,
    TargetVoiceCompositionConfig,
)
from backend.tts_provider_port import TTSProviderCapabilities
from backend.tts_qwen_provider import QwenTTSConfig
from backend.voice_gate import WAKE_WORD


class _Reasoner:
    async def generate(self, text, signal):
        yield "ok"


class _ASR:
    async def transcribe(self, segment, signal):
        return ""

    def start(self):
        return None

    def interrupt(self, reason="interrupt"):
        return None

    async def wait_stopped(self, timeout_s):
        return True

    def stop(self, reason="shutdown"):
        return None

    def health(self):
        return {"available": True, "state": "ready"}


class _StreamingASR:
    def start(self):
        return None

    def open_stream(self, stream_id, generation, sample_rate, channels, signal):
        return None

    def push_audio(self, stream_id, samples, sample_rate, signal):
        return ()

    def finish_stream(self, stream_id, signal):
        return None

    def interrupt(self, reason="interrupt"):
        return None

    def wait_stopped(self, timeout_s):
        return True

    def stop(self, reason="shutdown"):
        return None

    def health(self):
        return {"available": True, "state": "ready"}


class _Source:
    def start(self, callback, device):
        self.callback = callback
        self.device = device

    def stop(self):
        return None

    def health(self):
        return {"ok": True}


class _VAD:
    def detect_speech(self, audio, sample_rate):
        return False


class _Provider:
    def __init__(self, *, idle: bool = True) -> None:
        self.idle = idle
        self.wait_calls = []
        self.shutdown_calls = []

    def describe_capabilities(self):
        return TTSProviderCapabilities(
            provider_id="composition-fake",
            true_audio_stream=True,
            cancel_observable=True,
        )

    async def open(self, request):
        raise AssertionError("composition construction must not open the provider")

    def health(self):
        return {"state": "stopped", "text": "must redact"}

    def metrics(self):
        return {"active": False}

    async def wait_idle_stopped(self, timeout_s):
        self.wait_calls.append(timeout_s)
        return self.idle

    def shutdown(self, reason, *, timeout_s=None):
        self.shutdown_calls.append((reason, timeout_s))


def _config() -> TargetVoiceCompositionConfig:
    return TargetVoiceCompositionConfig(
        qwen=QwenTTSConfig(model_dir=Path("C:/YHLZ-composition-test-model")),
        worker_id="composition-test-worker",
    )


class TargetVoiceCompositionTests(unittest.TestCase):
    def test_constructs_one_isolated_graph_without_opening_provider(self):
        provider = _Provider()
        calls = []

        def factory(config):
            calls.append(config)
            return provider

        composition = TargetVoiceComposition(
            _config(), reasoner=_Reasoner(), provider_factory=factory
        )

        self.assertEqual(calls, [composition.config.qwen])
        self.assertIs(composition.chain.kernel, composition.kernel)
        self.assertIs(composition.chain.tts_provider, provider)
        self.assertIs(composition.chain.memory, composition.memory)
        self.assertEqual(composition.gate.snapshot()["wake_word"], WAKE_WORD)
        self.assertIsNone(composition.runtime)
        self.assertFalse(composition.closed)
        self.assertEqual(provider.wait_calls, [])
        self.assertEqual(provider.shutdown_calls, [])
        health = composition.health()
        self.assertEqual(health["provider"]["state"], "stopped")
        self.assertEqual(health["provider"]["text"], "[redacted]")
        self.assertEqual(health["memory"]["mode"], "read_only")

    def test_create_runtime_is_single_and_uses_explicit_ports(self):
        provider = _Provider()
        composition = TargetVoiceComposition(
            _config(), reasoner=_Reasoner(), provider_factory=lambda config: provider
        )
        source = _Source()
        vad = _VAD()
        asr = _ASR()
        runtime = composition.create_runtime(asr=asr, source=source, vad=vad)

        self.assertIs(composition.runtime, runtime)
        self.assertIs(runtime.media.source, source)
        self.assertIs(runtime.media.vad, vad)
        self.assertIs(runtime.asr.asr, asr)
        self.assertIs(runtime.asr.chain, composition.chain)
        with self.assertRaises(TargetCompositionError) as context:
            composition.create_runtime(asr=asr)
        self.assertEqual(context.exception.code, "VOICE-COMPOSITION-RUNTIME-ALREADY-BOUND")

    def test_create_runtime_selects_streaming_bridge_only_for_complete_stream_port(self):
        provider = _Provider()
        composition = TargetVoiceComposition(
            _config(), reasoner=_Reasoner(), provider_factory=lambda config: provider
        )
        runtime = composition.create_runtime(asr=_StreamingASR(), source=_Source(), vad=_VAD())
        self.assertIsInstance(runtime.asr, StreamingASRBridge)
        self.assertTrue(runtime.asr.snapshot()["ports"]["asr_streaming"])

    def test_shutdown_requires_stop_evidence_before_releasing_provider(self):
        provider = _Provider(idle=True)
        composition = TargetVoiceComposition(
            _config(), reasoner=_Reasoner(), provider_factory=lambda config: provider
        )

        asyncio.run(composition.shutdown("test_close"))

        self.assertTrue(composition.closed)
        self.assertEqual(provider.wait_calls, [composition.config.stop_timeout_s])
        self.assertEqual(
            provider.shutdown_calls,
            [("test_close", composition.config.stop_timeout_s)],
        )

    def test_shutdown_closes_playback_before_waiting_for_provider_idle(self):
        trace = []

        class Playback:
            def close(self):
                trace.append("playback_close")

        class Provider(_Provider):
            async def wait_idle_stopped(self, timeout_s):
                trace.append("provider_wait")
                return await super().wait_idle_stopped(timeout_s)

            def shutdown(self, reason, *, timeout_s=None):
                trace.append("provider_shutdown")
                super().shutdown(reason, timeout_s=timeout_s)

        provider = Provider(idle=True)
        composition = TargetVoiceComposition(
            _config(),
            reasoner=_Reasoner(),
            playback=Playback(),
            provider_factory=lambda config: provider,
        )

        asyncio.run(composition.shutdown("test_close"))

        self.assertEqual(
            trace,
            ["playback_close", "provider_wait", "provider_shutdown"],
        )
        self.assertTrue(composition.closed)

    def test_shutdown_fails_closed_when_stop_evidence_is_missing(self):
        provider = _Provider(idle=False)
        composition = TargetVoiceComposition(
            _config(), reasoner=_Reasoner(), provider_factory=lambda config: provider
        )

        with self.assertRaises(TargetCompositionError) as context:
            asyncio.run(composition.shutdown("test_close"))

        self.assertEqual(context.exception.code, "VOICE-TTS-COMPOSITION-STOP-UNCONFIRMED")
        self.assertFalse(composition.closed)
        self.assertEqual(provider.shutdown_calls, [])

    def test_rejects_unprotected_memory_and_missing_required_ports(self):
        provider = _Provider()
        with self.assertRaises(TargetCompositionError) as memory_context:
            TargetVoiceComposition(
                _config(),
                reasoner=_Reasoner(),
                memory=object(),
                provider_factory=lambda config: provider,
            )
        self.assertEqual(memory_context.exception.code, "MEMORY-WRITE-BLOCKED")

        composition = TargetVoiceComposition(
            _config(), reasoner=_Reasoner(), provider_factory=lambda config: provider
        )
        with self.assertRaises(TargetCompositionError) as asr_context:
            composition.create_runtime(asr=object())
        self.assertEqual(asr_context.exception.code, "VOICE-COMPOSITION-ASR-PORT-INVALID")

        protected = ReadOnlyMemoryFacade()
        with self.assertRaises(PermissionError):
            protected.add("key", "value")


if __name__ == "__main__":
    unittest.main(verbosity=2)
