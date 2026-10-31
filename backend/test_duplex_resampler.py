"""Offline streaming resampler invariants; no device/model/network."""
import unittest
import numpy as np
from scipy.signal import upfirdn
from backend.duplex_resampler import PolyphaseResampler, StreamingAudioResampler

class ResamplerTests(unittest.TestCase):
    def test_chunks_match_single_and_scipy(self):
        rng = np.random.default_rng(19)
        for source, target in [(24000,48000),(24000,44100),(48000,16000),(44100,16000),(16000,16000)]:
            with self.subTest(source=source,target=target):
                data = rng.normal(size=source//2).astype(np.float32)
                r = PolyphaseResampler(source,target)
                parts = [r.process(data[i:i+137]) for i in range(0,len(data),137)]
                parts.append(r.flush()); actual=np.concatenate(parts)
                expected=upfirdn(r._h,data,up=r.up,down=r.down)
                np.testing.assert_allclose(actual,expected,atol=1e-6)
                one=PolyphaseResampler(source,target)
                np.testing.assert_array_equal(actual,np.concatenate((one.process(data),one.flush())))
                self.assertEqual(len(r.flush()),0)
                with self.assertRaises(ValueError): r.process(data[:10])
                r.reset(); np.testing.assert_array_equal(r.process(data[:137]),parts[0])
    def test_hundred_chunks_do_not_replay_history(self):
        r=PolyphaseResampler(24000,44100)
        n=sum(len(r.process(np.ones(480,np.float32))) for _ in range(100))
        self.assertEqual(n,88200)
        self.assertLessEqual(len(r._carry),len(r._lags))
    def test_alias_rejection(self):
        t=np.arange(4800)/48000
        low=PolyphaseResampler(48000,16000).process(np.sin(2*np.pi*1000*t))[100:]
        high=PolyphaseResampler(48000,16000).process(np.sin(2*np.pi*12000*t))[100:]
        self.assertLess(np.sqrt(np.mean(high**2)),np.sqrt(np.mean(low**2))*.01)
    def test_rate_changes_require_reset(self):
        r=StreamingAudioResampler(); r.process(np.zeros(480),48000,16000)
        with self.assertRaises(ValueError): r.process(np.zeros(160),16000,16000)
        r.reset(); self.assertEqual(len(r.process(np.zeros(160),16000,16000)),160)
