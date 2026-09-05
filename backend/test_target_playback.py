"""Isolation tests for the bounded target playback port."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

import numpy as np

from backend.target_chain import AudioChunk
from backend.target_playback import (
    PlaybackConfig,
    PlaybackError,
    PlaybackEventKind,
    PlaybackState,
    SoundDevicePlaybackPort,
)


class _FakeOutputStream:
    def __init__(self, *, callback, channels, blocksize, **kwargs) -> None:
        self.callback = callback
        self.channels = channels
        self.blocksize = blocksize
        self.active = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.stopped = True
        self.active = False

    def close(self) -> None:
        self.closed = True

    def pump(self, frames=None, status=None):
        count = int(frames or self.blocksize)
        output = np.zeros((count, self.channels), dtype=np.float32)
        self.callback(output, count, {}, status)
        return output


class _FakeSoundDevice:
    def __init__(self) -> None:
        self.stream = None

    def OutputStream(self, **kwargs):
        self.stream = _FakeOutputStream(**kwargs)
        return self.stream


class _Signal:
    def __init__(self, cancelled=False) -> None:
        self.cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self.cancelled


def _lease(turn_id="turn-playback"):
    return SimpleNamespace(turn_id=turn_id)


def _chunk(frames=480, sample_rate=24_000, channels=1, fmt="pcm_s16le"):
    values = np.full(frames * channels, 8192, dtype="<i2")
    return AudioChunk(values.tobytes(), sample_rate, channels, fmt)


def _port(**overrides):
    device = _FakeSoundDevice()
    config_values = {"device": "fake", "initial_buffer_ms": 20}
    config_values.update(overrides)
    config = PlaybackConfig(**config_values)
    events = []
    port = SoundDevicePlaybackPort(config, sounddevice_module=device, on_event=events.append)
    port.start()
    return port, device, events


class TargetPlaybackTests(unittest.TestCase):
    def test_finish_waits_for_callback_drain_and_reports_physical_done(self):
        async def scenario():
            port, device, events = _port()
            self.assertEqual(port.state, PlaybackState.READY)
            await port.play(_chunk(), _lease(), _Signal())
            finish = asyncio.create_task(port.finish(_lease(), _Signal()))
            await asyncio.sleep(0)
            output = device.stream.pump()
            self.assertGreater(float(np.abs(output).sum()), 0.0)
            device.stream.pump()
            self.assertTrue(await finish)
            self.assertEqual(port.state, PlaybackState.READY)
            self.assertTrue(any(event.kind == PlaybackEventKind.STARTED.value for event in events))
            self.assertTrue(any(event.kind == PlaybackEventKind.DONE.value for event in events))
            self.assertEqual(port.health()["queue_depth"], 0)
            port.close()

        asyncio.run(scenario())

    def test_interrupt_clears_queue_and_waits_for_callback_silence(self):
        async def scenario():
            port, device, events = _port(initial_buffer_ms=300)
            await port.play(_chunk(), _lease(), _Signal())
            self.assertTrue(port.interrupt("barge_in"))
            self.assertFalse(await port.wait_stopped(0.0))
            output = device.stream.pump()
            self.assertEqual(float(np.abs(output).sum()), 0.0)
            self.assertTrue(await port.wait_stopped(0.1))
            self.assertTrue(any(event.kind == PlaybackEventKind.STOPPED.value for event in events))
            self.assertEqual(port.health()["queue_depth"], 0)
            port.close()

        asyncio.run(scenario())

    def test_backpressure_and_invalid_pcm_fail_closed(self):
        async def scenario():
            port, _, _ = _port(max_queue_blocks=1, initial_buffer_ms=500, enqueue_timeout_s=0.01)
            await port.play(_chunk(), _lease(), _Signal())
            with self.assertRaises(PlaybackError) as backpressure:
                await port.play(_chunk(), _lease(), _Signal())
            self.assertEqual(backpressure.exception.code, "VOICE-PLAYBACK-BACKPRESSURE")
            with self.assertRaises(PlaybackError) as rate:
                await port.play(_chunk(sample_rate=16_000), _lease("other"), _Signal())
            self.assertEqual(rate.exception.code, "VOICE-PLAYBACK-SAMPLE-RATE")
            with self.assertRaises(PlaybackError) as channels:
                await port.play(_chunk(channels=2), _lease("other"), _Signal())
            self.assertEqual(channels.exception.code, "VOICE-PLAYBACK-CHANNELS")
            port.close()

        asyncio.run(scenario())

    def test_cancelled_signal_does_not_enqueue_audio(self):
        async def scenario():
            port, _, _ = _port()
            self.assertFalse(await port.play(_chunk(), _lease(), _Signal(cancelled=True)))
            self.assertEqual(port.health()["queue_depth"], 0)
            port.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
