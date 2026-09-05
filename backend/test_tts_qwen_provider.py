"""Isolation tests for the Qwen3-TTS target Provider adapter."""

from __future__ import annotations

import asyncio
import time
import unittest
from pathlib import Path

import numpy as np

from backend.tts_provider_port import TTSEventKind, TTSRequest, TTSStreamNormalizer
from backend.tts_qwen_provider import (
    QWEN_PROVIDER_ID,
    QwenTTSAdapterError,
    QwenTTSConfig,
    TailVerifier,
    create_qwen_provider,
    qwen_capabilities,
    _tail_anchor,
)


class _FakeASR:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript

    def start(self) -> None:
        return None

    def open_stream(self, stream_id, generation, sample_rate, channels, signal) -> None:
        return None

    def push_audio(self, stream_id, samples, sample_rate, signal):
        return []

    def finish_stream(self, stream_id, signal):
        class _U:
            text = self.transcript

        return _U()


class _TailAnchorTests(unittest.TestCase):
    def test_anchor_strips_punctuation(self) -> None:
        self.assertEqual(_tail_anchor("进步始于思想，元亨开拓未来。", 2), "未来")
        self.assertEqual(_tail_anchor("元亨，你好", 2), "你好")
        self.assertEqual(_tail_anchor("", 2), "")


class _TailVerifierTests(unittest.TestCase):
    def test_verifier_ok_on_match(self) -> None:
        verifier = TailVerifier(asr_factory=lambda: _FakeASR("进步始于思想 元亨开拓未来"))
        result = verifier.verify("进步始于思想，元亨开拓未来。", b"\x00\x01" * 4800, 24000)
        self.assertTrue(result["checked"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["anchor"], "未来")

    def test_verifier_miss_does_not_raise(self) -> None:
        verifier = TailVerifier(asr_factory=lambda: _FakeASR("进步始于思想 元亨开拓"))
        result = verifier.verify("进步始于思想，元亨开拓未来。", b"\x00\x01" * 4800, 24000)
        self.assertTrue(result["checked"])
        self.assertFalse(result["ok"])

    def test_verifier_skipped_when_disabled(self) -> None:
        from backend.tts_qwen_provider import QwenTTSWorker

        worker = QwenTTSWorker(
            QwenTTSConfig(model_dir=__file__, tail_verify=False), model_factory=lambda c: object()
        )
        self.assertIsNone(worker.verifier)


class _FakeModel:
    def __init__(self, mode: str = "normal", delay_s: float = 0.0) -> None:
        self.mode = mode
        self.delay_s = delay_s
        self.calls: list[dict] = []
        self.closed = False

    def generate_custom_voice_streaming(
        self,
        text: str,
        speaker: str,
        language: str,
        chunk_size: int = 8,
        **kwargs,
    ):
        self.calls.append(
            {
                "text": text,
                "speaker": speaker,
                "language": language,
                "chunk_size": chunk_size,
                "kwargs": dict(kwargs),
            }
        )
        if self.mode == "error":
            raise RuntimeError("synthetic qwen failure")
        if self.mode == "bad_sample_rate":
            yield np.ones(480, dtype=np.float32), 16_000, {}
            return
        count = 100 if self.mode == "slow" else 2
        for index in range(count):
            if self.delay_s:
                time.sleep(self.delay_s)
            # 480 samples make a complete 20 ms frame at the port rate.
            block = np.full(480, 0.1 + index / 1000.0, dtype=np.float32)
            yield block, 24_000, {"step": index, "text": "must redact"}

    def close(self) -> None:
        self.closed = True


def _config() -> QwenTTSConfig:
    # The fake factory means this path need not exist.  The real loader still
    # requires an explicit local directory and never downloads from the net.
    return QwenTTSConfig(
        model_dir=Path("C:/YHLZ-test-model"),
        queue_maxsize=8,
        stop_timeout_s=0.5,
    )


def _request(speech_id: str = "speech-qwen-test", epoch: int = 3) -> TTSRequest:
    return TTSRequest(
        session_id="session-qwen-test",
        turn_id="turn-qwen-test",
        speech_id=speech_id,
        provider_epoch=epoch,
        voice_id="Vivian",
        style={"instruct": "开心地说", "text": "redact"},
    )


async def _collect(session):
    return [event async for event in session.audio_events()]


class QwenProviderAdapterTests(unittest.TestCase):
    def test_capabilities_are_conservative_about_text_and_emotion(self):
        caps = qwen_capabilities()
        self.assertEqual(caps.provider_id, QWEN_PROVIDER_ID)
        self.assertTrue(caps.true_audio_stream)
        self.assertFalse(caps.text_stream)
        # 1.7B-CustomVoice exposes an instruct channel (audition evidence in
        # ledger records 0113/0114); the flag is a candidate declaration, not
        # a runtime guarantee, and c_candidate stays false.
        self.assertTrue(caps.native_emotion)
        self.assertFalse(caps.c_candidate)
        self.assertIn("text_stream", caps.missing_for_candidate())

    def test_normal_generation_uses_port_events_and_preserves_dual_control(self):
        model = _FakeModel()
        provider = create_qwen_provider(_config(), model_factory=lambda config: model)

        async def scenario():
            session = await provider.open(_request())
            await session.push_text("你好")
            await session.push_text("，这里是元亨")
            await session.commit_text()
            events = await _collect(session)
            self.assertEqual(
                [event.kind for event in events],
                ["READY", "PCM_CHUNK", "PCM_CHUNK", "DONE"],
            )
            self.assertEqual(model.calls[0]["text"], "你好，这里是元亨")
            self.assertEqual(model.calls[0]["speaker"], "Vivian")
            self.assertEqual(model.calls[0]["language"], "chinese")
            self.assertEqual(events[1].chunk.sample_rate, 24_000)
            self.assertEqual(events[1].chunk.format, "s16le")
            self.assertEqual(events[1].chunk.sequence, 0)
            self.assertEqual(events[2].chunk.sequence, 1)
            normalizer = TTSStreamNormalizer(_request(), qwen_capabilities())
            normalized = []
            for event in events:
                normalized.extend(normalizer.accept(event))
            self.assertTrue(normalizer.done)
            self.assertEqual(
                [event.kind for event in normalized],
                ["READY", "FIRST_CHUNK", "PCM_CHUNK", "PCM_CHUNK", "DONE"],
            )
            self.assertTrue(await session.wait_stopped(0.2))
            self.assertTrue(await provider.wait_idle_stopped(0.2))
            provider.shutdown(timeout_s=0.2)

        asyncio.run(scenario())
        self.assertTrue(model.closed)

    def test_cancel_emits_stop_evidence_without_done(self):
        model = _FakeModel(mode="slow", delay_s=0.01)
        provider = create_qwen_provider(_config(), model_factory=lambda config: model)

        async def scenario():
            session = await provider.open(_request("speech-cancel"))
            await session.push_text("较长的取消测试")
            await session.commit_text()
            events_task = asyncio.create_task(_collect(session))
            await asyncio.sleep(0.04)
            self.assertTrue(await session.cancel("barge_in"))
            self.assertTrue(await session.wait_stopped(0.5))
            events = await events_task
            kinds = [event.kind for event in events]
            self.assertIn("STOPPED", kinds)
            self.assertNotIn("DONE", kinds)
            self.assertTrue(await provider.wait_idle_stopped(0.5))
            provider.shutdown(timeout_s=0.2)

        asyncio.run(scenario())

    def test_provider_error_is_structured_and_does_not_leak_text(self):
        model = _FakeModel(mode="error")
        provider = create_qwen_provider(_config(), model_factory=lambda config: model)

        async def scenario():
            session = await provider.open(_request("speech-error"))
            await session.push_text("不应进入指标")
            await session.commit_text()
            events = await _collect(session)
            error_events = [event for event in events if event.kind == TTSEventKind.ERROR.value]
            self.assertEqual(len(error_events), 1)
            self.assertEqual(error_events[0].code, "VOICE-TTS-QWEN-GENERATE-FAILED")
            self.assertNotIn("不应进入指标", str(session.metrics()))
            self.assertTrue(await session.wait_stopped(0.2))
            self.assertTrue(await provider.wait_idle_stopped(0.2))
            self.assertEqual(
                provider.health().get("last_error_code"),
                "VOICE-TTS-QWEN-GENERATE-FAILED",
            )
            provider.shutdown(timeout_s=0.2)

        asyncio.run(scenario())

    def test_bad_sample_rate_fails_closed(self):
        model = _FakeModel(mode="bad_sample_rate")
        provider = create_qwen_provider(_config(), model_factory=lambda config: model)

        async def scenario():
            session = await provider.open(_request("speech-rate"))
            await session.push_text("采样率")
            await session.commit_text()
            events = await _collect(session)
            error = next(event for event in events if event.kind == "ERROR")
            self.assertEqual(error.code, "VOICE-TTS-QWEN-SAMPLE-RATE")
            self.assertNotIn("DONE", [event.kind for event in events])
            self.assertTrue(await session.wait_stopped(0.2))
            self.assertTrue(await provider.wait_idle_stopped(0.2))
            provider.shutdown(timeout_s=0.2)

        asyncio.run(scenario())

    def test_empty_commit_has_immediate_stop_evidence(self):
        model = _FakeModel()
        provider = create_qwen_provider(_config(), model_factory=lambda config: model)

        async def scenario():
            session = await provider.open(_request("speech-empty"))
            events_task = asyncio.create_task(_collect(session))
            await asyncio.sleep(0)
            with self.assertRaises(QwenTTSAdapterError) as context:
                await session.commit_text()
            self.assertEqual(context.exception.code, "VOICE-TTS-QWEN-EMPTY-TEXT")
            events = await events_task
            self.assertTrue(await session.wait_stopped(0.2))
            self.assertEqual([event.kind for event in events], ["READY", "ERROR", "STOPPED"])
            self.assertTrue(await provider.wait_idle_stopped(0.2))
            provider.shutdown(timeout_s=0.2)

        asyncio.run(scenario())

    def test_cancel_before_commit_is_not_left_hanging(self):
        model = _FakeModel()
        provider = create_qwen_provider(_config(), model_factory=lambda config: model)

        async def scenario():
            session = await provider.open(_request("speech-pre-cancel"))
            events_task = asyncio.create_task(_collect(session))
            await asyncio.sleep(0)
            await session.cancel("before_commit")
            events = await events_task
            self.assertTrue(await session.wait_stopped(0.2))
            self.assertEqual([event.kind for event in events], ["READY", "STOPPED"])
            self.assertTrue(await provider.wait_idle_stopped(0.2))
            provider.shutdown(timeout_s=0.2)

        asyncio.run(scenario())

    def test_warmup_is_explicit_and_does_not_change_text_stream_claim(self):
        config = QwenTTSConfig(model_dir=Path("C:/YHLZ-test-model"), warmup_text="你好。")
        self.assertTrue(config.to_dict()["warmup_enabled"])
        self.assertFalse(qwen_capabilities().text_stream)


if __name__ == "__main__":
    unittest.main(verbosity=2)
