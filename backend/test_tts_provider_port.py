"""Contract tests for the isolated TTSProviderPort boundary."""

from __future__ import annotations

import time
import unittest

from backend.tts_provider_port import (
    PCM_FRAME_BYTES,
    PCM_FRAME_SAMPLES,
    PCMChunk,
    PCMFrameRepacker,
    TTSEventKind,
    TTSProviderCapabilities,
    TTSProviderEvent,
    TTSProviderPortError,
    TTSRequest,
    TTSStreamNormalizer,
    coerce_provider_event,
)


def _request(epoch: int = 4) -> TTSRequest:
    return TTSRequest(
        session_id="sess-test",
        turn_id="turn-test",
        speech_id="speech-test",
        provider_epoch=epoch,
        voice_id="voice-new",
        style={"text": "must redact", "rate": 1.0},
    )


def _caps(**kwargs) -> TTSProviderCapabilities:
    values = {
        "provider_id": "fake-local",
        "true_audio_stream": True,
        "text_stream": True,
        "cancel_observable": True,
        "worker_isolated": True,
        "worker_persistent": True,
    }
    values.update(kwargs)
    return TTSProviderCapabilities(**values)


class TTSProviderPortTests(unittest.TestCase):
    def test_repacker_emits_fixed_frames_and_pads_only_on_flush(self):
        repacker = PCMFrameRepacker()
        first = repacker.feed(PCMChunk(b"\x01\x00" * 100, 0))
        self.assertEqual(first, ())
        second = repacker.feed(PCMChunk(b"\x02\x00" * (PCM_FRAME_SAMPLES - 100), 1))
        self.assertEqual(len(second), 1)
        self.assertEqual(len(second[0].data), PCM_FRAME_BYTES)
        self.assertEqual(second[0].sequence, 0)
        tail = repacker.feed(PCMChunk(b"\x03\x00" * 3, 2))
        self.assertEqual(tail, ())
        flushed = repacker.flush()
        self.assertEqual(len(flushed), 1)
        self.assertEqual(len(flushed[0].data), PCM_FRAME_BYTES)
        self.assertEqual(flushed[0].data[:6], b"\x03\x00" * 3)
        self.assertEqual(flushed[0].data[6:], b"\x00" * (PCM_FRAME_BYTES - 6))

    def test_normalizer_owns_first_chunk_and_done(self):
        request = _request()
        normalizer = TTSStreamNormalizer(request, _caps(), started_at=time.monotonic() - 0.012)
        pcm = PCMChunk(b"\x01\x00" * PCM_FRAME_SAMPLES, 0)
        events = normalizer.accept(
            TTSProviderEvent(TTSEventKind.PCM_CHUNK, request.speech_id, request.provider_epoch, chunk=pcm)
        )
        self.assertEqual([event.kind for event in events], ["FIRST_CHUNK", "PCM_CHUNK"])
        self.assertGreaterEqual(normalizer.first_chunk_ms, 0)
        done = normalizer.accept(
            TTSProviderEvent(TTSEventKind.DONE, request.speech_id, request.provider_epoch)
        )
        self.assertEqual([event.kind for event in done], ["DONE"])
        self.assertTrue(normalizer.done)
        metrics = normalizer.metrics().to_dict()
        self.assertEqual(metrics["output_frame_count"], 1)
        self.assertEqual(metrics["pcm_duration_ms"], 20)

    def test_stale_epoch_is_dropped_without_playback_event(self):
        request = _request(epoch=9)
        normalizer = TTSStreamNormalizer(request, _caps())
        stale = TTSProviderEvent(
            TTSEventKind.PCM_CHUNK,
            request.speech_id,
            provider_epoch=8,
            chunk=PCMChunk(b"\x01\x00" * PCM_FRAME_SAMPLES, 0),
        )
        self.assertEqual(normalizer.accept(stale), ())
        self.assertEqual(normalizer.metrics().stale_event_count, 1)

    def test_sequence_gap_fails_closed_and_duplicate_is_ignored(self):
        request = _request()
        normalizer = TTSStreamNormalizer(request, _caps())
        with self.assertRaises(TTSProviderPortError) as context:
            normalizer.accept(
                TTSProviderEvent(
                    TTSEventKind.PCM_CHUNK,
                    request.speech_id,
                    request.provider_epoch,
                    chunk=PCMChunk(b"\x01\x00", 2),
                )
            )
        self.assertEqual(context.exception.code, "VOICE-TTS-PCM-SEQUENCE-GAP")

        # A duplicate of an already accepted provider sequence is harmless.
        normalizer = TTSStreamNormalizer(request, _caps())
        block = TTSProviderEvent(
            TTSEventKind.PCM_CHUNK,
            request.speech_id,
            request.provider_epoch,
            chunk=PCMChunk(b"\x01\x00", 0),
        )
        normalizer.accept(block)
        self.assertEqual(normalizer.accept(block), ())
        self.assertEqual(normalizer.metrics().duplicate_chunk_count, 1)

    def test_all_silent_provider_output_cannot_complete_normally(self):
        request = _request()
        normalizer = TTSStreamNormalizer(request, _caps())
        normalizer.accept(
            TTSProviderEvent(
                TTSEventKind.PCM_CHUNK,
                request.speech_id,
                request.provider_epoch,
                chunk=PCMChunk(b"\x00\x00" * PCM_FRAME_SAMPLES, 0),
            )
        )
        with self.assertRaises(TTSProviderPortError) as context:
            normalizer.accept(
                TTSProviderEvent(TTSEventKind.DONE, request.speech_id, request.provider_epoch)
            )
        self.assertEqual(context.exception.code, "VOICE-TTS-NO-EFFECTIVE-PCM")
        self.assertFalse(normalizer.done)

    def test_mapping_conversion_uses_request_identity_and_redacts_style(self):
        request = _request()
        event = coerce_provider_event(
            {
                "kind": "PCM_CHUNK",
                "chunk": {"data": b"\x01\x00", "sequence": 0},
                "payload": {"text": "secret", "queue_depth": 2},
            },
            request=request,
        )
        self.assertEqual(event.speech_id, request.speech_id)
        self.assertEqual(event.provider_epoch, request.provider_epoch)
        self.assertEqual(event.chunk.data, b"\x01\x00")
        self.assertEqual(event.to_dict()["payload"]["text"], "[redacted]")
        self.assertEqual(request.to_dict()["style"]["text"], "[redacted]")

    def test_capability_declaration_is_not_silent_about_text_stream(self):
        caps = _caps(text_stream=False)
        self.assertFalse(caps.c_candidate)
        self.assertIn("text_stream", caps.missing_for_candidate())
        self.assertFalse(_caps().to_dict()["native_emotion"])

    def test_provider_capabilities_must_describe_normalized_pcm(self):
        with self.assertRaises(ValueError):
            _caps(output_sample_rate=48_000)
        with self.assertRaises(ValueError):
            _caps(output_channels=2)

    def test_silent_input_is_counted_once(self):
        request = _request()
        normalizer = TTSStreamNormalizer(request, _caps())
        normalizer.accept(
            TTSProviderEvent(
                TTSEventKind.PCM_CHUNK,
                request.speech_id,
                request.provider_epoch,
                chunk=PCMChunk(b"\x00\x00" * PCM_FRAME_SAMPLES, 0),
            )
        )
        self.assertEqual(normalizer.metrics().silent_chunk_count, 1)

    def test_leading_silence_is_filtered_without_an_output_sequence_gap(self):
        request = _request()
        normalizer = TTSStreamNormalizer(request, _caps())
        leading_silence = PCMChunk(b"\x00\x00" * PCM_FRAME_SAMPLES, 0)
        effective = PCMChunk(b"\x01\x00" * PCM_FRAME_SAMPLES, 1)
        self.assertEqual(
            normalizer.accept(
                TTSProviderEvent(
                    TTSEventKind.PCM_CHUNK,
                    request.speech_id,
                    request.provider_epoch,
                    chunk=leading_silence,
                )
            ),
            (),
        )
        events = normalizer.accept(
            TTSProviderEvent(
                TTSEventKind.PCM_CHUNK,
                request.speech_id,
                request.provider_epoch,
                chunk=effective,
            )
        )
        pcm_events = [event for event in events if event.kind == TTSEventKind.PCM_CHUNK.value]
        self.assertEqual([event.sequence for event in pcm_events], [0])
        first = [event for event in events if event.kind == TTSEventKind.FIRST_CHUNK.value]
        self.assertEqual([event.sequence for event in first], [0])

    def test_mapping_event_accepts_enum_kind(self):
        event = coerce_provider_event(
            {"kind": TTSEventKind.READY},
            request=_request(),
        )
        self.assertEqual(event.kind, TTSEventKind.READY.value)

    def test_mapping_event_derives_sequence_from_top_level_pcm(self):
        request = _request()
        event = coerce_provider_event(
            {
                "kind": "PCM_CHUNK",
                "data": b"\x01\x00",
                "sequence": 7,
            },
            request=request,
        )
        self.assertEqual(event.sequence, 7)
        self.assertEqual(event.chunk.sequence, 7)

    def test_pcm_event_preserves_transport_and_provider_sequences(self):
        request = _request()
        event = TTSProviderEvent(
            TTSEventKind.PCM_CHUNK,
            request.speech_id,
            request.provider_epoch,
            sequence=1,
            chunk=PCMChunk(b"\x01\x00", 0),
        )
        self.assertEqual(event.sequence, 1)
        self.assertEqual(event.chunk.sequence, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
