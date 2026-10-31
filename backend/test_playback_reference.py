"""Device-callback reference contract; no sound device is opened."""
import threading
import time
import unittest
import numpy as np
from backend.target_playback import PlaybackConfig, PlaybackReferenceFrame, SoundDevicePlaybackPort
from backend.test_target_playback import _FakeSoundDevice, _chunk, _lease, _Signal
from backend.duplex_clock import CallbackClock


class TestReferenceTap(unittest.TestCase):
    def make(self, tap=None, **config):
        frames = []
        sd = _FakeSoundDevice()
        port = SoundDevicePlaybackPort(PlaybackConfig(device=0, initial_buffer_ms=0, **config),
                                       sounddevice_module=sd, reference_tap=tap or frames.append)
        port.start()
        self.addCleanup(port.close)
        return port, sd, frames

    def pump(self, port, count=480, info=None, status=None):
        out = np.empty((count, port.config.channels), np.float32)
        port._callback(out, count, info or {"currentTime": 1., "outputBufferDacTime": 1.02}, status)
        self.assertTrue(port.wait_reference_idle())
        return out

    def test_full_reference_queue_preserves_close_boundary(self):
        entered=threading.Event(); release=threading.Event(); frames=[]
        def slow(frame):
            entered.set(); release.wait(2.); frames.append(frame)
        port,_,_=self.make(tap=slow)
        out=np.empty((480,2),np.float32)
        port._callback(out,480,{"currentTime":1.,"outputBufferDacTime":1.02},None)
        self.assertTrue(entered.wait(1.))
        try:
            for _ in range(70):
                port._callback(out,480,{"currentTime":1.,"outputBufferDacTime":1.02},None)
            port._flush_reference(0,"closed")
        finally:
            release.set()
        self.assertTrue(port.wait_reference_idle())
        self.assertEqual(frames[-1].reason,"closed")
        self.assertGreater(port.reference_health()["dropped"],0)

    def test_double_close_and_restart_leave_no_old_markers(self):
        port, _, frames = self.make()
        self.pump(port); port.close(); count=len(frames)
        port.close()
        self.assertEqual(len(frames), count)
        self.assertEqual(port._reference_queue.unfinished_tasks, 0)
        port.start(); self.pump(port)
        self.assertEqual(len(frames), count+1)

    def test_enqueue_is_not_a_playback_reference(self):
        port, _, frames = self.make()
        port._enqueue(_chunk(), _lease(), _Signal())
        self.assertTrue(port.wait_reference_idle())
        self.assertEqual(frames, [])
        out = self.pump(port)
        self.assertEqual(len(frames), 1)
        np.testing.assert_array_equal(frames[0].samples, out)
        self.assertTrue(frames[0].clock_valid)
        self.assertEqual(frames[0].dac_time, 1.02)

    def test_reference_contains_volume_channels_and_padded_silence(self):
        port, _, frames = self.make(volume=.5)
        port._enqueue(_chunk(frames=100), _lease(), _Signal())
        out = self.pump(port)
        np.testing.assert_array_equal(frames[0].samples, out)
        np.testing.assert_allclose(out[:100], .125)
        np.testing.assert_array_equal(out[100:], 0.)

    def test_cancellation_before_play_never_leaks_queued_audio(self):
        port, _, frames = self.make()
        port._enqueue(_chunk(), _lease(), _Signal())
        port.interrupt()
        out = self.pump(port)
        self.assertTrue(any(f.is_final and f.reason == "interrupted" for f in frames))
        self.assertTrue(all(not np.any(f.samples) for f in frames))
        self.assertFalse(np.any(out))

    def test_active_interrupt_boundary_then_silence_then_new_generation(self):
        port, _, frames = self.make()
        port._enqueue(_chunk(), _lease(), _Signal()); self.pump(port)
        first = frames[-1].generation
        port.interrupt(); self.pump(port)
        self.assertTrue(frames[-2].is_final)
        self.assertEqual(frames[-2].generation, first)
        self.assertFalse(np.any(frames[-1].samples))
        port._enqueue(_chunk(), _lease("next"), _Signal()); self.pump(port)
        self.assertGreater(frames[-1].generation, first)
        self.assertTrue(np.any(frames[-1].samples))

    def test_reference_is_owned_snapshot_and_consumer_is_not_audio_callback(self):
        thread_ids = []
        def tap(f): thread_ids.append(threading.get_ident())
        port, _, _ = self.make(tap=tap)
        self.pump(port)
        self.assertNotIn(threading.get_ident(), thread_ids)
        port2, _, frames = self.make()
        port2._enqueue(_chunk(), _lease(), _Signal())
        out = self.pump(port2); before = frames[-1].samples.copy(); out.fill(7)
        np.testing.assert_array_equal(frames[-1].samples, before)
        self.assertFalse(frames[-1].samples.flags.writeable)

    def test_reference_uses_device_rate(self):
        port, _, frames = self.make(device_sample_rate=48000)
        port._enqueue(_chunk(), _lease(), _Signal()); self.pump(port, 960)
        self.assertEqual(frames[-1].sample_rate, 48000)
        self.assertEqual(len(frames[-1].samples), 960)

    def test_idle_and_underflow_emit_real_zero_padded_reference(self):
        port, _, frames = self.make()
        self.pump(port); self.assertFalse(np.any(frames[-1].samples))
        port._enqueue(_chunk(), _lease(), _Signal()); self.pump(port); self.pump(port)
        self.assertFalse(np.any(frames[-1].samples))
        self.assertEqual(port.metrics()["underrun_count"], 1)

    def test_missing_clock_or_output_status_never_claims_alignment(self):
        port, _, frames = self.make()
        out = np.zeros((480, 2), np.float32)
        port._callback(out, 480, {}, None); port.wait_reference_idle()
        self.assertFalse(frames[-1].clock_valid)
        self.pump(port, status="underflow")
        self.assertFalse(frames[-1].clock_valid)

    def test_reference_exception_is_visible_and_does_not_break_playback(self):
        def bad(f): raise RuntimeError("consumer failed")
        port, _, _ = self.make(tap=bad)
        self.pump(port)
        self.assertEqual(port.reference_health()["errors"], 1)

    def test_slow_consumer_does_not_block_audio_and_queue_is_bounded(self):
        entered, release = threading.Event(), threading.Event()
        def slow(f): entered.set(); release.wait(2)
        port, _, _ = self.make(tap=slow)
        self.addCleanup(release.set)
        data = np.zeros((480, 2), np.float32)
        port._callback(data, 480, {}, None); self.assertTrue(entered.wait(1))
        for _ in range(80): port._callback(data, 480, {}, None)
        self.assertLessEqual(port.reference_health()["queue_depth"], 64)
        self.assertGreater(port.reference_health()["dropped"], 0)
        release.set(); self.assertTrue(port.wait_reference_idle())

    def test_close_flushes_final_boundary_and_joins_owned_worker(self):
        port, _, frames = self.make()
        port.close()
        self.assertTrue(frames[-1].is_final)
        self.assertEqual(frames[-1].reason, "closed")
        self.assertFalse(port.reference_health()["worker_alive"])

    def test_no_reference_tap_does_not_start_worker(self):
        sd = _FakeSoundDevice()
        port = SoundDevicePlaybackPort(PlaybackConfig(device=0), sounddevice_module=sd)
        port.start(); port.close()
        self.assertFalse(port.reference_health()["worker_alive"])


class TestCallbackClock(unittest.TestCase):
    def test_separate_stream_clock_origins_map_to_common_monotonic_time(self):
        a, b = CallbackClock(), CallbackClock()
        self.assertAlmostEqual(a.map(1.01, 1., 100.), b.map(20.01, 20., 100.))

    def test_missing_nan_and_implausible_clock_are_rejected(self):
        c = CallbackClock()
        for x,y in [(None,1.),(float("nan"),1.),(10.,1.)]: self.assertIsNone(c.map(x,y,100.))

    def test_clock_jump_is_explicit_discontinuity(self):
        c = CallbackClock(); c.map(1.,1.,100.); epoch=c.epoch
        self.assertIsNone(c.map(.1,.1,100.02)); self.assertGreater(c.epoch,epoch)
        self.assertIsNotNone(c.map(.12,.12,100.04))
