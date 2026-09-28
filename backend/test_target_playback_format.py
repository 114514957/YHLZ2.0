"""Tests for P0-2 (format negotiation) and P0-3 (streaming resampler)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.target_playback import (
    PlaybackConfig,
    PlaybackError,
    _StreamResampler,
    negotiate_output_format,
)


class TestPlaybackConfigRates(unittest.TestCase):
    def test_default_no_resample(self):
        c = PlaybackConfig(device=3)
        self.assertEqual(c.sample_rate, 24000)
        self.assertEqual(c.resolved_device_sample_rate, 24000)
        self.assertFalse(c.needs_resample)

    def test_device_rate_differs(self):
        c = PlaybackConfig(device=3, sample_rate=24000, device_sample_rate=48000)
        self.assertEqual(c.resolved_device_sample_rate, 48000)
        self.assertTrue(c.needs_resample)
        self.assertEqual(c.block_frames, 960)  # 48000 * 20ms

    def test_block_frames_uses_device_rate(self):
        c = PlaybackConfig(device=3, sample_rate=24000, device_sample_rate=48000)
        self.assertEqual(c.block_frames, 960)
        c2 = PlaybackConfig(device=3, sample_rate=24000, device_sample_rate=44100)
        self.assertEqual(c2.block_frames, 882)  # 44100 * 20ms

    def test_invalid_device_rate(self):
        with self.assertRaises(ValueError):
            PlaybackConfig(device=3, device_sample_rate=0)

    def test_to_dict_includes_both_rates(self):
        c = PlaybackConfig(device=3, sample_rate=24000, device_sample_rate=48000)
        d = c.to_dict()
        self.assertEqual(d["sample_rate"], 24000)
        self.assertEqual(d["device_sample_rate"], 48000)


class TestStreamResampler(unittest.TestCase):
    def test_24k_to_48k(self):
        r = _StreamResampler(24000, 48000)
        mono = np.sin(2 * np.pi * 440 * np.arange(2400) / 24000).astype(np.float32)
        out = r.process(mono)
        self.assertEqual(len(out), 4800)  # 2x upsample

    def test_24k_to_44k1(self):
        r = _StreamResampler(24000, 44100)
        mono = np.sin(2 * np.pi * 440 * np.arange(2400) / 24000).astype(np.float32)
        out = r.process(mono)
        expected = round(2400 * 44100 / 24000)
        self.assertLess(abs(len(out) - expected), 10)  # ±carry

    def test_identity_passthrough(self):
        r = _StreamResampler(24000, 24000)
        mono = np.ones(100, dtype=np.float32)
        out = r.process(mono)
        np.testing.assert_array_equal(out, mono)

    def test_stateful_carry(self):
        r = _StreamResampler(24000, 48000)
        chunk1 = np.ones(100, dtype=np.float32)
        chunk2 = np.ones(100, dtype=np.float32)
        out1 = r.process(chunk1)
        out2 = r.process(chunk2)
        self.assertGreater(len(out1), 150)  # includes carry expansion
        self.assertGreater(len(out2), 150)

    def test_flush(self):
        r = _StreamResampler(24000, 48000)
        mono = np.ones(100, dtype=np.float32)
        r.process(mono)
        tail = r.flush()
        self.assertGreater(len(tail), 0)
        # after flush, carry is empty
        self.assertEqual(len(r.flush()), 0)

    def test_reset(self):
        r = _StreamResampler(24000, 48000)
        mono = np.ones(100, dtype=np.float32)
        r.process(mono)
        r.reset()
        self.assertEqual(len(r._carry), 0)

    def test_duration_preserved(self):
        """Resampling must preserve time duration, not change speed."""
        r = _StreamResampler(24000, 48000)
        mono = np.sin(2 * np.pi * 440 * np.arange(24000) / 24000).astype(np.float32)
        out = r.process(mono)
        self.assertAlmostEqual(len(out) / 48000, 1.0, places=1)


class TestNegotiateOutputFormat(unittest.TestCase):
    def test_accepts_preferred_rate(self):
        sd = MagicMock()
        sd.check_output_settings.return_value = None
        rate = negotiate_output_format(sd, 3, preferred_rates=(24000, 48000))
        self.assertEqual(rate, 24000)

    def test_falls_back_to_second_rate(self):
        sd = MagicMock()
        sd.check_output_settings.side_effect = [
            RuntimeError("Invalid sample rate"),  # 24k rejected
            None,  # 48k accepted
        ]
        rate = negotiate_output_format(sd, 3, preferred_rates=(24000, 48000))
        self.assertEqual(rate, 48000)

    def test_all_rates_rejected(self):
        sd = MagicMock()
        sd.check_output_settings.side_effect = RuntimeError("Invalid sample rate")
        with self.assertRaisesRegex(PlaybackError, "NEGOTIATION-FAILED"):
            negotiate_output_format(sd, 3, preferred_rates=(24000, 48000))

    def test_wapi_24k_rejected_48k_accepted(self):
        """Simulates the real WASAPI Realtek scenario."""
        sd = MagicMock()
        sd.check_output_settings.side_effect = [
            RuntimeError("Invalid sample rate"),  # 24k rejected by WASAPI
            None,  # 48k accepted
        ]
        rate = negotiate_output_format(sd, 8, preferred_rates=(24000, 48000, 44100))
        self.assertEqual(rate, 48000)


if __name__ == "__main__":
    unittest.main()
