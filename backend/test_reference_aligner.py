"""Tests for PlaybackReferenceAligner (P3 AEC integration)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.playback_aec import PlaybackReferenceAligner


class TestPlaybackReferenceAligner(unittest.TestCase):
    def test_add_and_get(self):
        a = PlaybackReferenceAligner(buffer_ms=500, sample_rate=16000)
        a.add_playback_frame(np.ones(100, dtype=np.float32), generation=1)
        ref = a.get_reference_for(50)
        self.assertEqual(len(ref), 50)

    def test_multiple_frames(self):
        a = PlaybackReferenceAligner(buffer_ms=500, sample_rate=16000)
        a.add_playback_frame(np.ones(100, dtype=np.float32), generation=1)
        a.add_playback_frame(np.ones(100, dtype=np.float32) * 2, generation=1)
        ref = a.get_reference_for(150)
        self.assertEqual(len(ref), 150)

    def test_buffer_overflow(self):
        a = PlaybackReferenceAligner(buffer_ms=10, sample_rate=16000)  # 160 samples
        for _ in range(10):
            a.add_playback_frame(np.ones(100, dtype=np.float32))
        snap = a.snapshot()
        self.assertLessEqual(snap["frames"], 2)  # only recent frames kept

    def test_delay_tracking(self):
        import time
        a = PlaybackReferenceAligner(buffer_ms=500, sample_rate=16000)
        a.add_playback_frame(np.ones(100, dtype=np.float32), timestamp=time.monotonic())
        a.get_reference_for(50)
        self.assertIsNotNone(a.last_delay_ms)

    def test_clear(self):
        a = PlaybackReferenceAligner(buffer_ms=500, sample_rate=16000)
        a.add_playback_frame(np.ones(100, dtype=np.float32))
        a.clear()
        snap = a.snapshot()
        self.assertEqual(snap["frames"], 0)

    def test_empty_get(self):
        a = PlaybackReferenceAligner(buffer_ms=500, sample_rate=16000)
        ref = a.get_reference_for(50)
        self.assertEqual(len(ref), 0)

    def test_generation_tracking(self):
        a = PlaybackReferenceAligner(buffer_ms=500, sample_rate=16000)
        a.add_playback_frame(np.ones(100, dtype=np.float32), generation=1)
        a.add_playback_frame(np.ones(100, dtype=np.float32), generation=2)
        snap = a.snapshot()
        self.assertEqual(snap["frames"], 2)


if __name__ == "__main__":
    unittest.main()
