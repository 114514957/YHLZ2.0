"""Isolated tests for target-chain media ingress and C/B evidence."""

from __future__ import annotations

import asyncio
import unittest

import numpy as np

from backend.media_adapter import (
    DeviceDescriptor,
    MediaAdapter,
    MediaError,
    MediaEventKind,
    MediaState,
    SoundDeviceInputSource,
)
from backend.session_kernel import AudioRoute, DuplexMode, ProviderCapabilities


class FakeSource:
    def __init__(self, fail_start: bool = False) -> None:
        self.fail_start = fail_start
        self.callback = None
        self.started = False
        self.stopped = False

    def start(self, callback, device) -> None:
        if self.fail_start:
            raise OSError("source unavailable")
        self.callback = callback
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def health(self) -> dict:
        return {"ok": self.started and not self.stopped, "kind": "fake"}


class FakeVAD:
    def __init__(self, values) -> None:
        self.values = list(values)
        self.calls = []

    def detect_speech(self, audio, sample_rate: int) -> bool:
        self.calls.append((audio, sample_rate))
        return bool(self.values.pop(0)) if self.values else False


class FakeAEC:
    def __init__(self) -> None:
        self.calls = []

    def process(self, mic, reference, sample_rate: int):
        self.calls.append((mic, reference, sample_rate))
        return ("enhanced:" + str(mic), 14.0)


def _caps(route: str) -> ProviderCapabilities:
    return ProviderCapabilities(
        continuous_capture=True,
        concurrent_input_output=True,
        audio_route=route,
        audio_route_verified=True,
        vad_verified=True,
        wake_word_verified=True,
        aec_reference_available=route == AudioRoute.SPEAKER_MIC.value,
        aec_verified=route == AudioRoute.SPEAKER_MIC.value,
        echo_isolation_verified=route == AudioRoute.HEADSET.value,
        asr_tts_concurrent=True,
        cancel_asr=True,
        cancel_generation=True,
        cancel_tts=True,
        cancel_playback=True,
        playback_verified=True,
        resource_budget_verified=True,
    )


class MediaAdapterTests(unittest.TestCase):
    def test_sounddevice_enumeration_does_not_infer_speaker_mic_route(self) -> None:
        class FakeSoundDevice:
            def query_devices(self):
                return [
                    {
                        "name": "combined endpoint",
                        "max_input_channels": 1,
                        "max_output_channels": 2,
                        "default_samplerate": 48_000,
                    }
                ]

        devices = SoundDeviceInputSource(FakeSoundDevice()).enumerate_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["route"], AudioRoute.UNKNOWN.value)
        self.assertFalse(devices[0]["reference_available"])

    def test_declared_route_mismatch_cannot_remain_c_capable(self) -> None:
        source = FakeSource()
        adapter = MediaAdapter(source=source, vad=FakeVAD([]))
        device = DeviceDescriptor(
            "headset-1",
            "test headset",
            1,
            2,
            route=AudioRoute.HEADSET.value,
        )
        assessment = adapter.start(device, _caps(AudioRoute.SPEAKER_MIC.value))
        self.assertEqual(assessment.mode, DuplexMode.B)
        self.assertIn("audio_route_verified", assessment.missing_for_c)
        self.assertEqual(adapter.capabilities.audio_route, AudioRoute.HEADSET.value)
        adapter.stop()

    def test_headset_ingress_reports_vad_edges_and_ordered_events(self) -> None:
        async def scenario() -> None:
            source = FakeSource()
            vad = FakeVAD([True, True, False])
            frames = []
            events = []
            adapter = MediaAdapter(
                source=source,
                vad=vad,
                on_frame=frames.append,
                on_event=events.append,
            )
            device = DeviceDescriptor("headset-1", "test headset", 1, 2, route=AudioRoute.HEADSET.value)
            assessment = adapter.start(device, _caps(AudioRoute.HEADSET.value))
            self.assertEqual(assessment.mode, DuplexMode.C)

            worker = asyncio.create_task(adapter.run())
            self.assertTrue(adapter.ingest(b"a"))
            self.assertTrue(adapter.ingest(b"b"))
            self.assertTrue(adapter.ingest(b"c"))
            await adapter.wait_idle()
            self.assertEqual([item.speech for item in frames], [True, True, False])
            kinds = [event.kind for event in events]
            self.assertIn(MediaEventKind.STARTED.value, kinds)
            self.assertIn(MediaEventKind.SPEECH_STARTED.value, kinds)
            self.assertIn(MediaEventKind.SPEECH_ENDED.value, kinds)
            event_sequences = [event.event_seq for event in events]
            self.assertEqual(event_sequences, sorted(event_sequences))
            self.assertEqual(len(event_sequences), len(set(event_sequences)))

            adapter.stop()
            await asyncio.wait_for(worker, timeout=1.0)
            self.assertEqual(adapter.state, MediaState.STOPPED)
            self.assertTrue(source.stopped)

        asyncio.run(scenario())

    def test_missing_speaker_reference_degrades_to_b_without_mutating_samples(self) -> None:
        async def scenario() -> None:
            source = FakeSource()
            aec = FakeAEC()
            frames = []
            events = []
            adapter = MediaAdapter(
                source=source,
                vad=FakeVAD([True]),
                aec=aec,
                on_frame=frames.append,
                on_event=events.append,
            )
            device = DeviceDescriptor(
                "speaker-1",
                "test speakers",
                1,
                2,
                route=AudioRoute.SPEAKER_MIC.value,
                reference_available=True,
            )
            self.assertEqual(adapter.start(device, _caps(AudioRoute.SPEAKER_MIC.value)).mode, DuplexMode.C)
            self.assertTrue(adapter.ingest(b"raw"))
            await adapter.process_one()

            self.assertEqual(frames[0].samples, b"raw")
            self.assertFalse(frames[0].aec_applied)
            self.assertEqual(aec.calls, [])
            self.assertEqual(adapter.assessment.mode, DuplexMode.B)
            self.assertFalse(adapter.health()["c_verified"])
            self.assertTrue(any(event.code == "MEDIA-AEC-REFERENCE-MISSING" for event in events))
            adapter.stop()

        asyncio.run(scenario())

    def test_speaker_reference_is_processed_before_vad(self) -> None:
        async def scenario() -> None:
            aec = FakeAEC()
            vad = FakeVAD([True])
            frames = []
            adapter = MediaAdapter(source=FakeSource(), vad=vad, aec=aec, on_frame=frames.append)
            device = DeviceDescriptor(
                "speaker-2",
                "test speaker mic",
                1,
                2,
                route=AudioRoute.SPEAKER_MIC.value,
                reference_available=True,
            )
            self.assertEqual(adapter.start(device, _caps(AudioRoute.SPEAKER_MIC.value)).mode, DuplexMode.C)
            self.assertTrue(adapter.ingest(b"mic", reference_samples=b"ref"))
            result = await adapter.process_one()
            self.assertEqual(result.samples, "enhanced:b'mic'")
            self.assertTrue(result.aec_applied)
            self.assertEqual(aec.calls, [(b"mic", b"ref", 16_000)])
            self.assertEqual(vad.calls[0][0], "enhanced:b'mic'")
            adapter.stop()

        asyncio.run(scenario())

    def test_source_callback_preserves_selected_channel_count(self) -> None:
        async def scenario() -> None:
            source = FakeSource()
            frames = []
            adapter = MediaAdapter(source=source, vad=FakeVAD([True]), on_frame=frames.append)
            device = DeviceDescriptor(
                "stereo",
                "stereo input",
                2,
                2,
                route=AudioRoute.HEADSET.value,
            )
            adapter.start(device, _caps(AudioRoute.HEADSET.value))
            worker = asyncio.create_task(adapter.run())
            source.callback("stereo-frame", 1, None, None)
            await adapter.wait_idle()
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].frame.channels, 2)
            adapter.stop()
            await asyncio.wait_for(worker, timeout=1.0)

        asyncio.run(scenario())

    def test_source_status_is_a_visible_b_degradation(self) -> None:
        source = FakeSource()
        events = []
        adapter = MediaAdapter(source=source, vad=FakeVAD([False]), on_event=events.append)
        device = DeviceDescriptor("status", "status input", 1, 2, route=AudioRoute.HEADSET.value)
        self.assertEqual(adapter.start(device, _caps(AudioRoute.HEADSET.value)).mode, DuplexMode.C)
        source.callback(np.zeros((1, 1), dtype=np.float32), 1, None, "input_overflow")
        self.assertEqual(adapter.assessment.mode, DuplexMode.B)
        self.assertTrue(any(event.code == "MEDIA-SOURCE-STATUS" for event in events))
        adapter.stop()

    def test_sounddevice_source_copies_callback_buffer_before_returning(self) -> None:
        class Stream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                self.active = False

            def start(self):
                self.active = True

            def stop(self):
                self.active = False

            def close(self):
                return None

        class SoundDevice:
            def __init__(self):
                self.stream = None

            def InputStream(self, **kwargs):
                self.stream = Stream(**kwargs)
                return self.stream

        from backend.media_adapter import SoundDeviceInputSource

        sounddevice = SoundDevice()
        source = SoundDeviceInputSource(sounddevice)
        received = []
        source.start(lambda *args: received.append(args), DeviceDescriptor("copy", "copy input", 1, 0))
        callback_buffer = np.ones((4, 1), dtype=np.float32)
        sounddevice.stream.callback(callback_buffer, 4, None, None)
        callback_buffer[:] = 0
        self.assertTrue(np.all(received[0][0] == 1))
        source.stop()

    def test_queue_backpressure_and_stale_generation_are_explicit(self) -> None:
        adapter = MediaAdapter(source=FakeSource(), vad=FakeVAD([False]), queue_capacity=1)
        device = DeviceDescriptor("q", "queue", 1, 1, route=AudioRoute.HEADSET.value)
        adapter.start(device, _caps(AudioRoute.HEADSET.value))
        self.assertTrue(adapter.ingest(b"one"))
        self.assertFalse(adapter.ingest(b"two"))
        self.assertFalse(adapter.ingest(b"old", generation=adapter.generation - 1))
        health = adapter.health()
        self.assertEqual(health["dropped_frames"], 1)
        self.assertGreaterEqual(health["queue_depth"], 1)
        adapter.stop()

    def test_duration_budget_rejects_long_frames_and_resets_on_stop(self) -> None:
        adapter = MediaAdapter(
            source=FakeSource(),
            vad=FakeVAD([False]),
            queue_capacity=10,
            max_queue_duration_ms=100,
        )
        device = DeviceDescriptor("duration", "duration", 1, 1, route=AudioRoute.HEADSET.value)
        adapter.start(device, _caps(AudioRoute.HEADSET.value))
        # PCM16 mono at 16 kHz: 2,560 bytes = 80 ms; the next 40 ms exceeds 100 ms.
        self.assertTrue(adapter.ingest(b"a" * 2_560))
        self.assertFalse(adapter.ingest(b"b" * 1_280))
        self.assertEqual(adapter.health()["queue_duration_ms"], 80)
        self.assertEqual(adapter.health()["dropped_frames"], 1)
        adapter.stop()
        self.assertEqual(adapter.health()["queue_duration_ms"], 0)

    def test_source_failure_is_fail_closed(self) -> None:
        adapter = MediaAdapter(source=FakeSource(fail_start=True), vad=FakeVAD([False]))
        device = DeviceDescriptor("bad", "bad source", 1, 1, route=AudioRoute.HEADSET.value)
        with self.assertRaises(MediaError):
            adapter.start(device, _caps(AudioRoute.HEADSET.value))
        self.assertEqual(adapter.state, MediaState.FAILED)
        self.assertFalse(adapter.ingest(b"discard"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
