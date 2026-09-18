"""Mic segment -> wav helper tests (audio-direct voice chain, ledger 0408)."""
import tempfile
import unittest
from pathlib import Path

from tools.voice_dialog_probe import _segment_gate, _write_segment_wav


class SegmentGateTest(unittest.TestCase):
    def test_vad_and_energy_both_required(self):
        self.assertTrue(_segment_gate(0.2, True, 0.01))
        self.assertFalse(_segment_gate(0.2, False, 0.01))    # VAD says no
        self.assertFalse(_segment_gate(0.001, True, 0.01))   # too quiet

    def test_noise_floor_raises_the_gate(self):
        # floor 0.05 -> gate 0.15; a 0.10 background no longer passes
        self.assertFalse(_segment_gate(0.10, True, 0.05))
        self.assertTrue(_segment_gate(0.20, True, 0.05))

    def test_abs_min_applies_when_floor_is_unknown(self):
        self.assertFalse(_segment_gate(0.001, True, 0.0, abs_min_rms=0.004))
        self.assertTrue(_segment_gate(0.01, True, 0.0, abs_min_rms=0.004))


class VoiceClipTest(unittest.TestCase):
    def test_writes_16k_mono_wav(self):
        import numpy as np
        import soundfile as sf

        frames = [np.zeros(3200, dtype="float32"),
                  np.full(3200, 0.5, dtype="float32")]
        out = Path(tempfile.mkdtemp()) / "seg.wav"
        self.assertTrue(_write_segment_wav(out, frames, 16000))
        info = sf.info(str(out))
        self.assertEqual(info.samplerate, 16000)
        self.assertEqual(info.channels, 1)
        self.assertAlmostEqual(info.duration, 0.4, places=2)

    def test_rejects_empty_or_too_short(self):
        import numpy as np

        out = Path(tempfile.mkdtemp()) / "seg.wav"
        self.assertFalse(_write_segment_wav(out, [], 16000))
        self.assertFalse(_write_segment_wav(out, [np.zeros(100, dtype="float32")], 16000))
        self.assertFalse(out.exists())

    def test_tts_condition_peak_normalizes_and_trims(self):
        import numpy as np
        import soundfile as sf

        from tools.voice_dialog_probe import _condition_tts_wav

        sr = 24000
        speech = np.full(sr // 2, 0.2, dtype="float32")
        silence = np.zeros(sr, dtype="float32")
        out = Path(tempfile.mkdtemp()) / "t.wav"
        sf.write(str(out), np.concatenate([speech, silence]), sr, subtype="PCM_16")
        _condition_tts_wav(out)
        y, _ = sf.read(str(out), dtype="float32")
        self.assertLess(len(y), len(speech) + sr)  # trailing silence trimmed
        self.assertAlmostEqual(float(np.max(np.abs(y))), 0.85, places=2)


class VoiceDspTest(unittest.TestCase):
    """Shared NEKO-derived DSP helpers (ledger 0422)."""

    def test_limiter_caps_peaks(self):
        import numpy as np

        from tools.voice_dsp import limiter_int16

        x = np.full(4800, 32000, dtype=np.int16)
        y = limiter_int16(x)
        self.assertLess(int(np.max(np.abs(y))), 32000)
        self.assertGreater(int(np.max(np.abs(y))), 30000)

    def test_agc_never_amplifies_silence(self):
        import numpy as np

        from tools.voice_dsp import agc_int16

        x = np.zeros(4800, dtype=np.int16)
        np.testing.assert_array_equal(agc_int16(x), x)

    def test_segment_dsp_off_identity_lim_caps(self):
        import numpy as np

        from tools.voice_dsp import segment_dsp

        x = np.full(4800, 32000, dtype=np.int16)
        np.testing.assert_array_equal(segment_dsp(x, "off"), x)
        self.assertLess(int(np.max(np.abs(segment_dsp(x, "lim")))), 32000)

    def test_stream_resampler_44k_to_16k(self):
        import numpy as np

        from tools.voice_dsp import StreamResampler

        rs = StreamResampler(44100, 16000)
        total = rs.process(np.zeros(4410, dtype="float32")).size
        total += rs.process(np.zeros(4410, dtype="float32")).size
        tail = rs.flush()
        self.assertIsInstance(tail, np.ndarray)
        total += tail.size
        # 8820 samples @44.1k -> ~3200 @16k (soxr holds back a little, flush
        # returns it); allow for filter latency.
        self.assertGreater(total, 3000)
        self.assertLess(total, 3400)


    def test_spoken_text_strips_markers_and_reasoning(self):
        from tools.voice_dialog_probe import _spoken_text

        self.assertEqual(_spoken_text("[[voice]]\n今晚吃什么？"), "今晚吃什么？")
        leak = "哦。\n（思考模式启动）**分析用户意图：** 一大堆分析内容"
        self.assertEqual(_spoken_text(leak), "哦。")
        self.assertEqual(_spoken_text(""), "")


if __name__ == "__main__":
    unittest.main()
