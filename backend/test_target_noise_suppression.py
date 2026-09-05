"""Unit tests for the RNNoise denoiser adapter (NEKO borrow)."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

import numpy as np


def _clean_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = r"C:\Users\ACE_WAN——PROJECT\YHLZ"
    return env


class RNNoiseDenoiserTests(unittest.TestCase):
    def test_process_preserves_shape_and_range(self) -> None:
        from backend.target_noise_suppression import RNNoiseDenoiser

        d = RNNoiseDenoiser()
        chunk = (np.random.RandomState(7).rand(1600).astype("float32") * 0.4) - 0.2
        out, prob = d.process_mono(chunk)
        self.assertEqual(out.shape, chunk.shape)
        self.assertEqual(out.dtype, np.float32)
        self.assertTrue(np.isfinite(out).all())
        self.assertGreaterEqual(float(prob), 0.0)
        d.close()
        self.assertIsNone(d._state)

    def test_reset_recreates_state(self) -> None:
        from backend.target_noise_suppression import RNNoiseDenoiser

        d = RNNoiseDenoiser()
        d.reset()
        self.assertIsNotNone(d._state)
        # After reset the denoiser must still process a chunk cleanly.
        chunk = np.zeros(1600, dtype="float32")
        out, prob = d.process_mono(chunk)
        self.assertEqual(out.shape, chunk.shape)
        self.assertTrue(np.isfinite(out).all())
        d.close()

    def test_health(self) -> None:
        from backend.target_noise_suppression import RNNoiseDenoiser

        d = RNNoiseDenoiser()
        info = d.health()
        self.assertTrue(info["available"])
        self.assertEqual(info["engine"], "rnnoise")
        d.close()


if __name__ == "__main__":
    unittest.main()
