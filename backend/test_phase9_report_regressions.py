"""Phase9 report review: device-free behavioral regressions, not hardware proof."""
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from backend.test_tts_pcm_stream_end import _make_request, _make_caps
from backend.tts_provider_port import PCMChunk, TTSProviderEvent, TTSStreamNormalizer, TTSProviderPortError
from backend.tts_qwen_process import QwenProcessWorker
from backend.tts_qwen_provider import QwenTTSConfig
from backend.playback_aec import PlaybackReferenceBuffer, NLMSAECAdapter


def event(kind, seq=0, samples=None):
    return TTSProviderEvent(kind=kind, speech_id="sp1", provider_epoch=0,
                           sequence=seq, chunk=None if samples is None else PCMChunk(b"\x00\x10" * samples, seq))


class StreamEndBoundaryTests(unittest.TestCase):
    def make_normalizer(self):
        return TTSStreamNormalizer(_make_request(), _make_caps())

    def test_partial_frame_is_flushed_before_stream_end(self):
        n = self.make_normalizer()
        n.accept(event("PCM_CHUNK", samples=720))
        output = n.accept(event("PCM_STREAM_END", 1))
        self.assertEqual([e.kind for e in output], ["PCM_CHUNK", "PCM_STREAM_END"])
        self.assertFalse(n.done, "stream end must not release worker before DONE")
        self.assertEqual([e.kind for e in n.accept(event("DONE", 2))], ["DONE"])

    def test_short_utterance_is_not_hidden_until_done(self):
        n = self.make_normalizer()
        self.assertEqual(n.accept(event("PCM_CHUNK", samples=120)), ())
        output = n.accept(event("PCM_STREAM_END", 1))
        self.assertEqual([e.kind for e in output], ["FIRST_CHUNK", "PCM_CHUNK", "PCM_STREAM_END"])

    def test_duplicate_stream_end_is_idempotent(self):
        n = self.make_normalizer()
        n.accept(event("PCM_CHUNK", samples=480))
        n.accept(event("PCM_STREAM_END", 1))
        self.assertEqual(n.accept(event("PCM_STREAM_END", 1)), ())

    def test_pcm_after_stream_end_fails_closed(self):
        n = self.make_normalizer()
        n.accept(event("PCM_CHUNK", samples=480))
        n.accept(event("PCM_STREAM_END", 1))
        with self.assertRaises(TTSProviderPortError) as error:
            n.accept(event("PCM_CHUNK", 1, 480))
        self.assertEqual(error.exception.code, "VOICE-TTS-PCM-AFTER-STREAM-END")

    def test_legacy_done_still_flushes_tail(self):
        n = self.make_normalizer()
        n.accept(event("PCM_CHUNK", samples=120))
        self.assertEqual([e.kind for e in n.accept(event("DONE", 1))],
                         ["FIRST_CHUNK", "PCM_CHUNK", "DONE"])

    def test_other_epoch_end_does_not_close_current_stream(self):
        n = self.make_normalizer()
        wrong = TTSProviderEvent(kind="PCM_STREAM_END", speech_id="old", provider_epoch=0, sequence=0)
        self.assertEqual(n.accept(wrong), ())
        self.assertTrue(n.accept(event("PCM_CHUNK", samples=480)))


class WarmupLifecycleTests(unittest.TestCase):
    def worker(self):
        return QwenProcessWorker(QwenTTSConfig(model_dir="test-model"))

    def test_invalid_request_does_not_count_a_turn(self):
        p = self.worker()
        with self.assertRaises(TypeError):
            p.open(object())
        self.assertEqual(p.metrics()["turn_count"], 0)

    def test_rejected_open_does_not_count_a_turn(self):
        p = self.worker()
        with patch.object(p, "_command", side_effect=RuntimeError("not ready")):
            with self.assertRaises(RuntimeError):
                p.open(_make_request())
        self.assertEqual(p.metrics()["turn_count"], 0)

    def test_failed_ready_does_not_record_success_time(self):
        p = self.worker()
        p._handle_message({"type": "ready", "ok": False, "code": "FAILED"})
        self.assertIsNone(p.health()["ready_at"])
        self.assertIsNone(p.health()["model_load_ms"])

    def test_process_start_timing_and_restart_reset(self):
        p = self.worker()
        p._turn_count = 7
        p._ready_at = 5.0
        parent, child, proc = MagicMock(), MagicMock(), MagicMock()
        p._ctx = MagicMock()
        p._ctx.Pipe.return_value = (parent, child)
        p._ctx.Process.return_value = proc
        def receive_ready():
            p._handle_message({"type": "ready", "ok": True})
        fake_thread = MagicMock()
        fake_thread.start.side_effect = receive_ready
        with patch("backend.tts_qwen_process.threading.Thread", return_value=fake_thread), \
             patch("backend.tts_qwen_process.time.time", side_effect=[100.0, 117.3, 118.0]), \
             patch("backend.tts_qwen_process.time.monotonic", side_effect=[100.0, 117.3]):
            p.start()
        self.assertEqual(p.health()["model_load_ms"], 17300.0)
        self.assertEqual(p.health()["turn_count"], 0)
        self.assertFalse(p.health()["is_warm"])


class ReferenceConsumptionTests(unittest.TestCase):
    def test_take_advances_across_frames(self):
        b = PlaybackReferenceBuffer()
        b.add_frame(np.arange(6, dtype=np.float32))
        np.testing.assert_array_equal(b.take_reference(3), [0, 1, 2])
        np.testing.assert_array_equal(b.take_reference(3), [3, 4, 5])
        self.assertEqual(b.snapshot()["total_samples"], 0)

    def test_underflow_preserves_requested_length_with_silence(self):
        b = PlaybackReferenceBuffer()
        b.add_frame(np.ones(2, dtype=np.float32))
        np.testing.assert_array_equal(b.take_reference(5), [1, 1, 0, 0, 0])

    def test_buffer_owns_copy_of_callback_memory(self):
        b = PlaybackReferenceBuffer()
        block = np.ones(4, dtype=np.float32)
        b.add_frame(block)
        block.fill(0)
        np.testing.assert_array_equal(b.take_reference(4), np.ones(4))

    def test_generation_change_discards_old_reference(self):
        b = PlaybackReferenceBuffer()
        b.add_frame(np.ones(2, dtype=np.float32), generation=1)
        b.clear(generation=2)
        b.add_frame(np.ones(2, dtype=np.float32) * 9, generation=1)
        b.add_frame(np.ones(2, dtype=np.float32) * 2, generation=2)
        np.testing.assert_array_equal(b.take_reference(2), [2, 2])

    def test_oversized_frame_keeps_newest_capacity(self):
        b = PlaybackReferenceBuffer(max_duration_s=0.001, sample_rate=4000)
        b.add_frame(np.arange(10, dtype=np.float32))
        np.testing.assert_array_equal(b.take_reference(4), [6, 7, 8, 9])

    def test_stereo_reference_is_downmixed_to_mono(self):
        b = PlaybackReferenceBuffer()
        b.add_frame(np.array([[1, 3], [3, 5]], dtype=np.float32))
        np.testing.assert_array_equal(b.take_reference(2), [2, 4])


class AECLengthSafetyTests(unittest.TestCase):
    def test_short_reference_does_not_drop_microphone_tail(self):
        aec = NLMSAECAdapter(filter_length=32)
        aec.disable()
        mic = np.arange(20, dtype=np.float32) / 20
        out, _ = aec.process(mic, np.zeros(5, dtype=np.float32), 16000)
        np.testing.assert_array_equal(out, mic)

    def test_stereo_reference_does_not_crash_mono_microphone(self):
        aec = NLMSAECAdapter(filter_length=32)
        out, _ = aec.process(np.ones(20, dtype=np.float32), np.ones((20, 2), dtype=np.float32), 16000)
        self.assertEqual(out.shape, (20,))
        self.assertFalse(np.array_equal(out, np.ones(20)), "AEC must process, not swallow a shape error")



class StreamEndChainTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, *, fail_after_end=False):
        import asyncio
        from backend.test_target_chain import DualStreamSession, DualStreamProvider, FakeReasoner, FinishingPlayback, _capabilities
        from backend.target_chain import TargetVoiceChain
        release_verifier = asyncio.Event()
        class Session(DualStreamSession):
            async def audio_events(self):
                await self.committed.wait()
                req = self.request
                yield TTSProviderEvent(kind="PCM_CHUNK", speech_id=req.speech_id,
                    provider_epoch=req.provider_epoch, sequence=0, chunk=PCMChunk(b"\x00\x10" * 720, 0))
                yield TTSProviderEvent(kind="PCM_STREAM_END", speech_id=req.speech_id,
                    provider_epoch=req.provider_epoch, sequence=1)
                await release_verifier.wait()
                if fail_after_end:
                    yield TTSProviderEvent(kind="ERROR", speech_id=req.speech_id,
                        provider_epoch=req.provider_epoch, code="TEST-VERIFY-FAILED", detail="test only")
                else:
                    yield TTSProviderEvent(kind="DONE", speech_id=req.speech_id,
                        provider_epoch=req.provider_epoch, sequence=2)
        class Provider(DualStreamProvider):
            def open(self, request):
                session = Session(request)
                self.sessions.append(session)
                return session
        playback = FinishingPlayback()
        provider = Provider()
        chain = TargetVoiceChain(reasoner=FakeReasoner(), tts_provider=provider, playback=playback)
        chain.start(_capabilities())
        await chain.submit_transcript("元亨")
        submission = await chain.submit_transcript("排空尾帧测试")
        await asyncio.wait_for(playback.finish_started.wait(), timeout=1.0)
        return chain, playback, provider, submission, release_verifier

    async def test_tail_queued_before_drain_without_waiting_for_verifier(self):
        import asyncio
        chain, playback, provider, submission, release = await self.build()
        try:
            self.assertEqual(len(playback.played), 2, "both full and padded tail must be queued before drain")
            self.assertFalse(submission.task.done(), "PCM_STREAM_END alone is not terminal")
        finally:
            playback.release.set()
            release.set()
        outcome = await asyncio.wait_for(submission.task, timeout=1.0)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(len(playback.played), 2, "DONE must not emit extra PCM after drain")

    async def test_late_provider_error_is_not_hidden_by_playback_drain(self):
        import asyncio
        chain, playback, provider, submission, release = await self.build(fail_after_end=True)
        playback.release.set()
        release.set()
        outcome = await asyncio.wait_for(submission.task, timeout=1.0)
        self.assertEqual(outcome.status, "failed")

    async def test_cancel_while_waiting_for_done_remains_observable(self):
        import asyncio
        chain, playback, provider, submission, release = await self.build()
        playback.release.set()
        try:
            result = await chain.interrupt("test_cancel_during_tail_verify", timeout_s=0.5)
            self.assertFalse(result.timed_out_tasks)
            outcome = await asyncio.wait_for(submission.task, timeout=1.0)
            self.assertEqual(outcome.status, "interrupted")
            self.assertEqual(provider.sessions[0].cancelled, 1)
        finally:
            release.set()

if __name__ == "__main__":
    unittest.main()
