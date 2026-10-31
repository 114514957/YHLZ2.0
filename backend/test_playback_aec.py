"""Offline AEC tests: playback-only, voice-only, double-talk (Phase9 step 3)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.playback_aec import NLMSAECAdapter, PlaybackReferenceBuffer, make_speaker_mic_aec

SR = 16000
DUR_S = 0.5
N = int(SR * DUR_S)


def _tone(freq: float, n: int = N, sr: int = SR) -> np.ndarray:
    return np.sin(2 * np.pi * freq * np.arange(n) / sr).astype(np.float32)


def _silence(n: int = N) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


class TestNLMSAECAdapter(unittest.TestCase):
    def test_playback_only(self):
        """Speaker playing, user silent: AEC should suppress echo."""
        aec = make_speaker_mic_aec()
        ref = _tone(440)
        mic = ref * 0.5  # echo with attenuation
        enhanced, erl = aec.process(mic, ref, SR)
        self.assertEqual(len(enhanced), N)  # same length as input
        self.assertIsInstance(erl, float)
        # echo should be somewhat suppressed (ERL > 0)
        self.assertGreater(erl, 0)

    def test_voice_only(self):
        """User speaking, speaker silent: AEC should preserve voice."""
        aec = make_speaker_mic_aec()
        mic = _tone(220)
        ref = _silence()
        enhanced, erl = aec.process(mic, ref, SR)
        # voice should survive (energy not zero)
        self.assertGreater(np.max(np.abs(enhanced)), 0.1)

    def test_double_talk(self):
        """Both speaking: AEC should not destroy the voice completely."""
        aec = make_speaker_mic_aec()
        voice = _tone(220) * 0.3
        echo = _tone(440) * 0.2
        mic = voice + echo
        ref = _tone(440)
        enhanced, erl = aec.process(mic, ref, SR)
        self.assertGreater(np.max(np.abs(enhanced)), 0.01)

    def test_reset(self):
        aec = make_speaker_mic_aec()
        ref = _tone(440)
        mic = ref * 0.5
        aec.process(mic, ref, SR)
        aec.reset()
        self.assertTrue(np.all(aec._aec.w == 0))

    def test_enable_disable(self):
        aec = make_speaker_mic_aec()
        ref = _tone(440)
        mic = ref * 0.5
        aec.disable()
        out, _ = aec.process(mic, ref, SR)
        np.testing.assert_array_equal(out, mic)  # passthrough when disabled
        aec.enable()
        out2, _ = aec.process(mic, ref, SR)
        self.assertFalse(np.array_equal(out2, mic))  # processing happens

    def test_different_lengths(self):
        """mic and ref of different lengths should not crash."""
        aec = make_speaker_mic_aec()
        mic = _tone(220, n=1000)
        ref = _tone(440, n=500)
        enhanced, erl = aec.process(mic, ref, SR)
        self.assertEqual(len(enhanced), len(mic))

    def test_empty_input(self):
        aec = make_speaker_mic_aec()
        mic = _silence(0)
        ref = _silence(0)
        enhanced, erl = aec.process(mic, ref, SR)
        self.assertEqual(len(enhanced), 0)


class TestPlaybackReferenceBuffer(unittest.TestCase):
    def test_add_and_take(self):
        buf = PlaybackReferenceBuffer(sample_rate=16000)
        buf.add_frame(_tone(440, n=100))
        ref = buf.take_reference(50)
        self.assertEqual(len(ref), 50)

    def test_multiple_frames(self):
        buf = PlaybackReferenceBuffer(sample_rate=16000)
        buf.add_frame(np.ones(100, dtype=np.float32))
        buf.add_frame(np.ones(100, dtype=np.float32) * 2)
        ref = buf.take_reference(200)
        self.assertEqual(len(ref), 200)

    def test_overflow(self):
        buf = PlaybackReferenceBuffer(max_duration_s=0.1, sample_rate=16000)
        for _ in range(10):
            buf.add_frame(np.ones(100, dtype=np.float32))
        snap = buf.snapshot()
        self.assertLessEqual(snap["total_samples"], snap["max_samples"])

    def test_clear(self):
        buf = PlaybackReferenceBuffer(sample_rate=16000)
        buf.add_frame(np.ones(100, dtype=np.float32))
        buf.clear()
        snap = buf.snapshot()
        self.assertEqual(snap["frames"], 0)

    def test_thread_safety(self):
        import threading
        buf = PlaybackReferenceBuffer(sample_rate=16000)
        def worker():
            for _ in range(100):
                buf.add_frame(np.ones(10, dtype=np.float32))
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = buf.snapshot()
        self.assertEqual(snap["total_samples"], 4 * 100 * 10)


if __name__ == "__main__":
    unittest.main()
