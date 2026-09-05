"""No-hardware tests for the bounded target microphone/VAD probe."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.target_input_probe import run_input_probe


class _FakeVAD:
    def __init__(self) -> None:
        self.running = False
        self.stopped = True

    def start(self) -> None:
        self.running = True
        self.stopped = False

    def detect_speech(self, audio, sample_rate):
        if not self.running:
            raise RuntimeError("not running")
        return False

    def stop(self, reason="shutdown") -> None:
        self.running = False
        self.stopped = True

    def wait_stopped(self, timeout_s):
        return self.stopped

    def health(self):
        return {"state": "stopped" if self.stopped else "ready", "available": True}


class _FakeStream:
    def __init__(self, **kwargs) -> None:
        self.callback = kwargs["callback"]
        self.device = kwargs["device"]
        self.active = False
        self.closed = False

    def start(self) -> None:
        self.active = True
        self.callback(np.zeros((1_600, 1), dtype=np.float32), 1_600, None, None)

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True


class _FakeSoundDevice:
    def __init__(self) -> None:
        self.checked = []
        self.stream = None

    def query_devices(self, device_id):
        self.device_id = device_id
        return {"name": "fake microphone", "max_input_channels": 2, "max_output_channels": 0}

    def check_input_settings(self, **kwargs):
        self.checked.append(kwargs)

    def InputStream(self, **kwargs):
        self.stream = _FakeStream(**kwargs)
        return self.stream


class TargetInputProbeTests(unittest.TestCase):
    def test_probe_uses_mono_float32_and_never_starts_asr_or_playback(self):
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                sounddevice = _FakeSoundDevice()
                summary = await run_input_probe(
                    Path(directory) / "input",
                    device_id=7,
                    duration_s=0.01,
                    sounddevice_module=sounddevice,
                    provider_factory=_FakeVAD,
                )
                self.assertEqual(summary["status"], "passed")
                self.assertEqual(summary["frame_count"], 1)
                self.assertFalse(summary["audio_persisted"])
                self.assertFalse(summary["asr_started"])
                self.assertFalse(summary["playback_started"])
                self.assertTrue(summary["stop_confirmed"])
                self.assertEqual(sounddevice.checked[0]["channels"], 1)
                self.assertEqual(sounddevice.checked[0]["dtype"], "float32")
                self.assertEqual(sounddevice.stream.device, 7)
                self.assertTrue(sounddevice.stream.closed)

        asyncio.run(scenario())

    def test_probe_rejects_a_duration_beyond_the_hard_budget(self):
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    await run_input_probe(
                        Path(directory) / "input",
                        device_id=1,
                        duration_s=5.1,
                        sounddevice_module=_FakeSoundDevice(),
                        provider_factory=_FakeVAD,
                    )

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
