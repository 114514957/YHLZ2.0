"""Tests for PlaybackReferenceTap (P0 AEC input)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.target_playback import (
    PlaybackConfig,
    PlaybackReferenceFrame,
    SoundDevicePlaybackPort,
)


def _make_port(ref_tap=None):
    config = PlaybackConfig(device=0, sample_rate=24000, channels=2)
    sd = MagicMock()
    sd.OutputStream.return_value = MagicMock(active=True)
    return SoundDevicePlaybackPort(config, sounddevice_module=sd, reference_tap=ref_tap)


class TestPlaybackReferenceFrame(unittest.TestCase):
    def test_frame_creation(self):
        samples = np.zeros(480, dtype=np.float32)
        f = PlaybackReferenceFrame(samples=samples, sample_rate=24000,
                                   generation=1, sequence=0)
        self.assertEqual(f.sample_rate, 24000)
        self.assertEqual(f.generation, 1)
        self.assertFalse(f.is_final)

    def test_final_frame(self):
        f = PlaybackReferenceFrame(samples=np.zeros(0, dtype=np.float32),
                                   sample_rate=24000, generation=1,
                                   sequence=0, is_final=True)
        self.assertTrue(f.is_final)


class TestReferenceTap(unittest.TestCase):
    def test_tap_called_on_enqueue(self):
        frames = []
        port = _make_port(ref_tap=frames.append)
        port.start()
        # create a mock chunk
        class FakeChunk:
            sample_rate = 24000
            channels = 1
            format = "pcm_s16le"
            samples = b"\x01\x00" * 240
        import asyncio
        signal = MagicMock()
        signal.is_cancelled.return_value = False
        lease = MagicMock()
        lease.turn_id = "t1"
        asyncio.run(port.play(FakeChunk(), lease, signal))
        self.assertEqual(len(frames), 1)
        self.assertFalse(frames[0].is_final)

    def test_tap_receives_device_rate(self):
        frames = []
        port = _make_port(ref_tap=frames.append)
        port.start()
        config = PlaybackConfig(device=0, sample_rate=24000,
                                device_sample_rate=48000, channels=2)
        sd = MagicMock()
        sd.OutputStream.return_value = MagicMock(active=True)
        port2 = SoundDevicePlaybackPort(config, sounddevice_module=sd,
                                        reference_tap=frames.append)
        port2.start()
        class FakeChunk:
            sample_rate = 24000
            channels = 1
            format = "pcm_s16le"
            samples = b"\x01\x00" * 240
        import asyncio
        signal = MagicMock()
        signal.is_cancelled.return_value = False
        lease = MagicMock()
        lease.turn_id = "t1"
        asyncio.run(port2.play(FakeChunk(), lease, signal))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].sample_rate, 48000)

    def test_tap_final_on_close(self):
        frames = []
        port = _make_port(ref_tap=frames.append)
        port.start()
        port.close()
        self.assertGreater(len(frames), 0)
        self.assertTrue(frames[-1].is_final)

    def test_no_tap_no_error(self):
        port = _make_port(ref_tap=None)
        port.start()
        port.close()  # should not raise

    def test_tap_exception_swallowed(self):
        def bad_tap(f):
            raise RuntimeError("tap error")
        port = _make_port(ref_tap=bad_tap)
        port.start()
        class FakeChunk:
            sample_rate = 24000
            channels = 1
            format = "pcm_s16le"
            samples = b"\x01\x00" * 240
        import asyncio
        signal = MagicMock()
        signal.is_cancelled.return_value = False
        lease = MagicMock()
        lease.turn_id = "t1"
        # should not raise
        asyncio.run(port.play(FakeChunk(), lease, signal))

    def test_reference_flush_on_interrupt_without_slot(self):
        frames = []
        port = _make_port(ref_tap=frames.append)
        port.start()
        port.interrupt("test")
        self.assertGreater(len(frames), 0)
        self.assertTrue(frames[-1].is_final)


if __name__ == "__main__":
    unittest.main()
