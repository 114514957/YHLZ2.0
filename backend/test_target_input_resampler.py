"""Contract tests for the target 48 kHz to 16 kHz processing boundary."""

from __future__ import annotations

import unittest

import numpy as np

from backend.media_adapter import DeviceDescriptor, MediaAdapter
from backend.session_kernel import AudioRoute, ProviderCapabilities
from backend.target_input_resampler import InputResamplerError, TargetInputResampler


class _Source:
    def start(self, callback, device):
        self.callback = callback

    def stop(self):
        return None

    def health(self):
        return {"ok": True}


class _VAD:
    def __init__(self):
        self.calls = []

    def detect_speech(self, audio, sample_rate):
        self.calls.append((np.asarray(audio).copy(), sample_rate))
        return False


def _capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        continuous_capture=True,
        concurrent_input_output=False,
        audio_route=AudioRoute.UNKNOWN.value,
    )


class TargetInputResamplerTests(unittest.TestCase):
    def test_exact_three_to_one_length_and_continuity_across_capture_frames(self):
        samples = (0.2 * np.sin(2 * np.pi * 1000 * np.arange(9_600) / 48_000)).astype(np.float32)
        continuous = TargetInputResampler().process(samples, 48_000, 16_000)

        streaming = TargetInputResampler()
        first = streaming.process(samples[:4_800], 48_000, 16_000)
        second = streaming.process(samples[4_800:], 48_000, 16_000)
        combined = np.concatenate((first, second), axis=0)

        self.assertEqual(continuous.shape, (3_200, 1))
        self.assertEqual(first.shape, (1_600, 1))
        self.assertEqual(second.shape, (1_600, 1))
        self.assertEqual(combined.dtype, np.float32)
        self.assertTrue(np.allclose(combined, continuous, rtol=1e-5, atol=1e-6))
        self.assertEqual(streaming.health()["metrics"]["output_samples"], 3_200)

    def test_rejects_wrong_rate_or_stereo_input_without_silent_downmix(self):
        resampler = TargetInputResampler()
        with self.assertRaises(InputResamplerError) as rate:
            resampler.process(np.zeros((4_800, 1), dtype=np.float32), 44_100, 16_000)
        self.assertEqual(rate.exception.code, "RESAMPLER-RATE-MISMATCH")
        with self.assertRaises(InputResamplerError) as stereo:
            resampler.process(np.zeros((4_800, 2), dtype=np.float32), 48_000, 16_000)
        self.assertEqual(stereo.exception.code, "RESAMPLER-FORMAT-CHANNELS")

    def test_media_adapter_passes_resampled_metadata_to_vad_and_segments(self):
        async def scenario() -> None:
            vad = _VAD()
            adapter = MediaAdapter(
                source=_Source(),
                vad=vad,
                resampler=TargetInputResampler(),
                target_sample_rate=16_000,
            )
            device = DeviceDescriptor("wasapi", "native capture", 1, 0, sample_rate=48_000)
            adapter.start(device, _capabilities())
            self.assertTrue(adapter.ingest(np.zeros((4_800, 1), dtype=np.float32), duration_ms=100))
            processed = await adapter.process_one()
            self.assertEqual(processed.frame.sample_rate, 16_000)
            self.assertEqual(processed.frame.channels, 1)
            self.assertEqual(processed.frame.duration_ms, 100)
            self.assertEqual(np.asarray(processed.samples).shape, (1_600, 1))
            self.assertEqual(vad.calls[0][1], 16_000)
            adapter.stop()

        import asyncio
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
