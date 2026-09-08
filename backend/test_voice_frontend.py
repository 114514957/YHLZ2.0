"""VoiceFrontend tests (刀1): weak-speech AGC lift + noise-floor-relative
speech decision + no trigger on noise-only frames."""
import sys
import unittest

sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ")

import numpy as np

from backend.voice_frontend import VoiceFrontend

RNG = np.random.default_rng(7)


def _frames(seconds: float) -> int:
    return int(seconds * 10)  # 100 ms frames


class TestVoiceFrontend(unittest.TestCase):
    def _weak_speech_stream(self):
        """0.5 s of weak speech (RMS 0.002 = user level from 0158 doc) on a
        quiet floor, preceded/followed by noise-only frames."""
        rng = RNG
        nf = 0.0004
        frames = []
        # 0.4 s noise only
        for _ in range(4):
            frames.append(rng.normal(0, nf, 1600).astype("float32"))
        # 0.5 s speech at rms ~0.002
        t = np.arange(1600) / 16000.0
        tone = 0.0028 * np.sin(2 * np.pi * 220 * t)
        for _ in range(5):
            frames.append((tone + rng.normal(0, nf, 1600)).astype("float32"))
        # 0.4 s trailing noise
        for _ in range(4):
            frames.append(rng.normal(0, nf, 1600).astype("float32"))
        return frames

    def test_weak_speech_is_lifted_and_detected(self):
        fe = VoiceFrontend()
        seen_speech = False
        speech_out_rms = 0.0
        for i, f in enumerate(self._weak_speech_stream()):
            out, is_speech = fe.process(f)
            if 4 <= i < 9:  # the speech region
                speech_out_rms = max(speech_out_rms, float(np.sqrt(np.mean(out ** 2))))
            if is_speech:
                seen_speech = True
        self.assertTrue(seen_speech, "weak speech should be flagged")
        # AGC should have lifted output well above the original 0.002 level
        self.assertGreater(speech_out_rms, 0.02)

    def test_noise_only_does_not_speech(self):
        fe = VoiceFrontend()
        flagged = 0
        rng = RNG
        for _ in range(12):
            f = rng.normal(0, 0.0003, 1600).astype("float32")
            _, s = fe.process(f)
            flagged += 1 if s else 0
        self.assertEqual(flagged, 0)

    def test_loud_speech_not_overamplified(self):
        fe = VoiceFrontend()
        t = np.arange(1600) / 16000.0
        loud = (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32")
        # prime noise floor then feed loud frame
        for _ in range(3):
            fe.process(np.zeros(1600, dtype="float32") + 1e-5)
        out, s = fe.process(loud)
        self.assertTrue(s)
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)


if __name__ == "__main__":
    unittest.main()
