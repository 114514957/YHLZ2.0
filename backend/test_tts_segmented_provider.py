"""No-model/no-device proofs for engineering segmented TTS."""
import asyncio
import unittest
from dataclasses import replace

from backend.tts_provider_port import (
    PCMChunk, TTSProviderCapabilities, TTSProviderEvent, TTSProviderPortError,
    TTSRequest, TTSStreamNormalizer,
)
from backend.tts_segmented_provider import SegmentedTTSProvider
from backend.voice_streaming import TextChunkerConfig


def request(speech="logical"):
    return TTSRequest("session", "turn", speech, 3, "xiaoyi")


class FakeSession:
    def __init__(self, owner, req):
        self.owner, self.req = owner, req
        self.text = ""
        self.cancelled = False
        self.done = self.drained = False

    async def push_text(self, text):
        self.text += text

    async def commit_text(self):
        self.owner.commits.append(self.text)

    async def cancel(self, reason):
        self.cancelled = True
        self.owner.release.set()

    async def wait_stopped(self, timeout):
        return self.done and self.drained and self.owner.stop_ok

    def health(self):
        return {}

    def metrics(self):
        return {}

    async def audio_events(self):
        yield TTSProviderEvent("READY", self.req.speech_id, self.req.provider_epoch)
        if self.owner.bad_identity:
            yield TTSProviderEvent("PCM_CHUNK", "stale", 1,
                                   chunk=PCMChunk(b"\x01\x00" * 480, 0))
        if self.owner.fail:
            yield TTSProviderEvent("ERROR", self.req.speech_id, self.req.provider_epoch,
                                   code="VOICE-FAKE-ERROR")
            self.done = self.drained = True
            return
        if not self.cancelled:
            yield TTSProviderEvent("PCM_CHUNK", self.req.speech_id, self.req.provider_epoch,
                                   chunk=PCMChunk(b"\x01\x00" * 600, 0))
            self.owner.first_pcm.set()
        # PCM_END is NOT a reuse boundary. DONE and iterator tail must finish.
        yield TTSProviderEvent("PCM_STREAM_END", self.req.speech_id, self.req.provider_epoch)
        await self.owner.release.wait()
        if not self.cancelled:
            yield TTSProviderEvent("DONE", self.req.speech_id, self.req.provider_epoch)
        self.done = self.drained = True


class FakeProvider:
    def __init__(self, *, gate=False, bad_identity=False, fail=False, stop_ok=True):
        self.sessions = []
        self.commits = []
        self.first_pcm = asyncio.Event()
        self.release = asyncio.Event()
        if not gate:
            self.release.set()
        self.bad_identity, self.fail, self.stop_ok = bad_identity, fail, stop_ok

    def describe_capabilities(self):
        return TTSProviderCapabilities("fake-qwen", true_audio_stream=True,
                                       text_stream=False, worker_persistent=True,
                                       cancel_observable=True)

    async def open(self, req):
        if self.sessions and not self.sessions[-1].drained:
            raise AssertionError("worker reopened before terminal drain")
        session = FakeSession(self, req)
        self.sessions.append(session)
        return session

    def health(self):
        return {"state": "ready"}

    def metrics(self):
        return {"model_loads": 1}


async def collect(session):
    return [event async for event in session.audio_events()]


class SegmentedProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_pcm_before_whole_answer_commit_and_same_worker(self):
        raw = FakeProvider()
        provider = SegmentedTTSProvider(raw)
        session = await provider.open(request())
        seen = []
        first = asyncio.Event()
        async def read():
            async for event in session.audio_events():
                seen.append(event)
                if event.kind == "PCM_CHUNK":
                    first.set()
        reader = asyncio.create_task(read())
        await session.push_text("这是已经可以开始播放的第一句。")
        await asyncio.wait_for(first.wait(), 1)
        self.assertFalse(session._committed)
        await session.push_text("这是还在生成的第二句，继续说下去。")
        await session.commit_text()
        await asyncio.wait_for(reader, 1)
        self.assertTrue(await session.wait_stopped(1))
        self.assertGreaterEqual(len(raw.sessions), 2)
        self.assertEqual("".join(raw.commits), "这是已经可以开始播放的第一句。这是还在生成的第二句，继续说下去。")
        self.assertTrue(all(s.req.voice_id == "xiaoyi" for s in raw.sessions))
        self.assertEqual(sum(e.kind == "DONE" for e in seen), 1)
        self.assertEqual(sum(e.kind == "PCM_STREAM_END" for e in seen), 1)
        pcm = [e for e in seen if e.kind == "PCM_CHUNK"]
        self.assertEqual([e.chunk.sequence for e in pcm], list(range(len(pcm))))
        self.assertTrue(all(len(e.chunk.data) == 960 for e in pcm))
        normalizer = TTSStreamNormalizer(request(), provider.describe_capabilities())
        for e in seen:
            normalizer.accept(e)
        self.assertFalse(provider.describe_capabilities().text_stream)
        self.assertEqual(provider.metrics()["model_loads"], 1)
        self.assertTrue(session.reusable)

    async def test_real_timer_flush_without_another_delta(self):
        raw = FakeProvider()
        config = TextChunkerConfig(no_punctuation_flush_ms=20, hard_flush_ms=40)
        session = await SegmentedTTSProvider(raw, config=config, tick_ms=5).open(request())
        reader = asyncio.create_task(collect(session))
        await session.push_text("甲" * 10)
        await asyncio.wait_for(raw.first_pcm.wait(), 1)
        self.assertFalse(session._committed)
        await session.commit_text()
        await reader

    async def test_wait_for_done_and_terminal_drain_before_next_segment(self):
        raw = FakeProvider(gate=True)
        session = await SegmentedTTSProvider(raw).open(request())
        reader = asyncio.create_task(collect(session))
        await session.push_text("甲" * 100)
        await raw.first_pcm.wait()
        await asyncio.sleep(.02)
        self.assertEqual(len(raw.sessions), 1)
        raw.release.set()
        await session.commit_text()
        await asyncio.wait_for(reader, 1)
        self.assertGreater(len(raw.sessions), 1)

    async def test_cancel_clears_segments_rejects_late_data_and_allows_new_turn(self):
        raw = FakeProvider(gate=True)
        provider = SegmentedTTSProvider(raw)
        session = await provider.open(request())
        reader = asyncio.create_task(collect(session))
        await session.push_text("甲" * 100)
        await raw.first_pcm.wait()
        await session.cancel("barge_in")
        with self.assertRaises(TTSProviderPortError):
            await session.push_text("迟到输出")
        self.assertTrue(await session.wait_stopped(1))
        await reader
        self.assertEqual(len(raw.sessions), 1)
        self.assertFalse(any(e.kind == "DONE" for e in reader.result()))
        next_session = await provider.open(request("new"))
        next_reader = asyncio.create_task(collect(next_session))
        await next_session.commit_text()
        await next_reader

    async def test_busy_and_identity_rejection(self):
        raw = FakeProvider(bad_identity=True)
        provider = SegmentedTTSProvider(raw)
        session = await provider.open(request())
        with self.assertRaises(TTSProviderPortError):
            await provider.open(request("early"))
        reader = asyncio.create_task(collect(session))
        await session.push_text("甲" * 20)
        await session.commit_text()
        seen = await reader
        self.assertEqual(session.metrics()["stale_event_count"], 1)
        self.assertTrue(all(e.speech_id == "logical" for e in seen))

    async def test_unconfirmed_stop_prevents_reopen(self):
        raw = FakeProvider(stop_ok=False)
        provider = SegmentedTTSProvider(raw)
        session = await provider.open(request())
        reader = asyncio.create_task(collect(session))
        await session.push_text("甲" * 20)
        await session.commit_text()
        seen = await reader
        self.assertTrue(any(e.kind == "ERROR" for e in seen))
        self.assertFalse(await session.wait_stopped(1))
        with self.assertRaises(TTSProviderPortError):
            await provider.open(request("new"))

    async def test_bounded_pcm_backpressure_remains_cancellable(self):
        raw = FakeProvider()
        session = await SegmentedTTSProvider(raw, pcm_frame_capacity=1).open(request())
        await session.push_text("甲" * 100)
        await asyncio.sleep(.02)
        self.assertLessEqual(session._audio.qsize(), 1)
        await session.cancel()
        self.assertTrue(await session.wait_stopped(1))
        await collect(session)

    async def test_markers_do_not_reach_child_and_empty_commit_ends(self):
        raw = FakeProvider()
        provider = SegmentedTTSProvider(raw)
        session = await provider.open(request())
        reader = asyncio.create_task(collect(session))
        await session.push_text("<think>秘密")
        await session.commit_text()
        seen = await reader
        self.assertEqual(raw.commits, [])
        self.assertTrue(any(e.kind == "DONE" for e in seen))

    async def test_child_error_propagates_and_new_push_is_rejected(self):
        raw = FakeProvider(fail=True)
        provider = SegmentedTTSProvider(raw)
        session = await provider.open(request())
        reader = asyncio.create_task(collect(session))
        await session.push_text("甲" * 20)
        seen = await asyncio.wait_for(reader, 1)
        self.assertTrue(any(e.code == "VOICE-FAKE-ERROR" for e in seen))
        self.assertFalse(any(e.kind == "DONE" for e in seen))
        with self.assertRaises(TTSProviderPortError):
            await session.push_text("后续")
        self.assertTrue(await session.wait_stopped(1))

    async def test_existing_target_chain_plays_before_last_llm_delta(self):
        from pathlib import Path
        from backend.target_composition import TargetVoiceComposition, TargetVoiceCompositionConfig
        from backend.tts_qwen_provider import QwenTTSConfig
        from backend.session_kernel import ProviderCapabilities
        raw = FakeProvider()
        played = asyncio.Event()
        order = []
        class Playback:
            async def play(self, chunk, lease, signal):
                order.append("pcm")
                played.set()
                return True
            async def finish(self, lease, signal):
                return True
        class Reasoner:
            async def generate(self, text, signal):
                yield "这是能先开始播放的第一句话。"
                await asyncio.wait_for(played.wait(), 1)
                order.append("last_delta")
                yield "这是后面才生成的第二句话。"
        composition = TargetVoiceComposition(
            TargetVoiceCompositionConfig(qwen=QwenTTSConfig(model_dir=Path("C:/fake")),
                                         segmented_tts_enabled=True),
            reasoner=Reasoner(), playback=Playback(), provider_factory=lambda config: raw)
        composition.chain.start(ProviderCapabilities(continuous_capture=True))
        submission = await composition.chain.submit_transcript("元亨，测试一下", source="test")
        self.assertIsNotNone(submission.task)
        outcome = await asyncio.wait_for(submission.task, 2)
        self.assertEqual(outcome.status, "completed")
        self.assertLess(order.index("pcm"), order.index("last_delta"))
        self.assertGreaterEqual(len(raw.sessions), 2)
        await composition.chain.shutdown()

    async def test_actual_qwen_adapter_with_fake_model_reuses_one_worker(self):
        from pathlib import Path
        from backend.test_tts_qwen_provider import _FakeModel
        from backend.tts_qwen_provider import QwenTTSConfig, create_qwen_provider
        from unittest.mock import patch
        with patch("backend.tts_qwen_provider._gpu_snapshot", return_value={"cuda_available": False}), \
             patch("backend.tts_qwen_provider.QwenTTSWorker._release_model", lambda model: model.close()):
            model = _FakeModel()
            loads = []
            def factory(config):
                loads.append(config)
                return model
            raw = create_qwen_provider(QwenTTSConfig(model_dir=Path("C:/fake"), tail_verify=False),
                                       model_factory=factory)
            provider = SegmentedTTSProvider(raw)
            session = await provider.open(replace(request(), voice_id="Vivian"))
            reader = asyncio.create_task(collect(session))
            try:
                await session.push_text("甲" * 100)
                await session.commit_text()
                seen = await asyncio.wait_for(reader, 10)
                self.assertFalse(any(e.kind == "ERROR" for e in seen))
                self.assertGreaterEqual(len(model.calls), 2)
                self.assertEqual(len(loads), 1)
                self.assertTrue(await session.wait_stopped(1))
            finally:
                if not session._runner.done():
                    await session.cancel()
                    await session.wait_stopped(1)
                await asyncio.to_thread(raw.shutdown, "test_complete")


if __name__ == "__main__":
    unittest.main()
