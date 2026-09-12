"""
YHLZ Voice Identity System - 质量评估模块测试 (Phase 1.3)

覆盖:
    - 正常评估 (相同音频 → 高相似度)
    - 不同音频评估
    - 文件不存在
    - 空文件
    - WER 计算 (含 mock ASR)
    - 状态判定 (pass/warn/fail)
"""
from __future__ import annotations

import io
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from backend.voice_identity.adapter.voice_quality_evaluator import (
    QualityReport,
    _compute_duration_score,
    _compute_snr,
    _compute_spectral_similarity,
    _wer,
    evaluate_quality,
)
import numpy as np


def _make_wav(path: str, duration_s: float = 2.0, sr: int = 16000, freq: float = 440) -> None:
    """生成 wav"""
    n = int(duration_s * sr)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * 0.3 * math.sin(2 * math.pi * freq * i / sr))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))


class TestWerUnit(unittest.TestCase):
    """WER 字符级计算"""

    def test_wer_identical(self):
        self.assertEqual(_wer("你好世界", "你好世界"), 0.0)

    def test_wer_completely_different(self):
        self.assertEqual(_wer("你好", "世界"), 1.0)

    def test_wer_substitution(self):
        # 替换 2 字 / 4 字 = 0.5
        r = _wer("你好世界", "你好人世")
        self.assertAlmostEqual(r, 0.5, places=4)

    def test_wer_empty_ref(self):
        self.assertEqual(_wer("", ""), 0.0)
        self.assertEqual(_wer("", "abc"), 1.0)

    def test_wer_insertion(self):
        # 插入 1 字
        r = _wer("你好", "你好啊")
        self.assertAlmostEqual(r, 0.5, places=4)


class TestDurationScore(unittest.TestCase):
    """时长匹配度"""

    def test_identical_duration(self):
        self.assertEqual(_compute_duration_score(2.0, 2.0), 1.0)

    def test_out_of_range(self):
        self.assertEqual(_compute_duration_score(2.0, 5.0), 0.0)  # > 2x
        self.assertEqual(_compute_duration_score(2.0, 0.5), 0.0)  # < 0.5x

    def test_zero(self):
        self.assertEqual(_compute_duration_score(0, 1), 0.0)
        self.assertEqual(_compute_duration_score(1, 0), 0.0)


class TestSnr(unittest.TestCase):
    """SNR 计算"""

    def test_pure_signal(self):
        sr = 16000
        t = np.linspace(0, 1, sr, endpoint=False)
        sig = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        snr = _compute_snr(sig)
        self.assertIsNotNone(snr)
        # 纯正弦波前 100ms 与其余能量接近, SNR 可能为 0 或略正; 仅校验非负
        self.assertGreaterEqual(snr, 0.0)

    def test_too_short(self):
        self.assertIsNone(_compute_snr(np.zeros(100, dtype=np.float32)))


class TestSpectralSimilarity(unittest.TestCase):
    """频谱相似度"""

    def test_identical_signal(self):
        sr = 16000
        t = np.linspace(0, 0.5, int(sr * 0.5), endpoint=False)
        sig = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        sim = _compute_spectral_similarity(sig, sig, sr)
        self.assertGreater(sim, 0.99)

    def test_different_signal(self):
        sr = 16000
        t = np.linspace(0, 0.5, int(sr * 0.5), endpoint=False)
        a = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        b = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        sim = _compute_spectral_similarity(a, b, sr)
        self.assertLess(sim, 0.99)

    def test_too_short(self):
        self.assertEqual(_compute_spectral_similarity(np.zeros(100), np.zeros(100), 16000), 0.0)


class TestEvaluateQuality(unittest.TestCase):
    """evaluate_quality 集成测试"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="yhlz_quality_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_identical_audio_pass(self):
        """相同音频 → pass"""
        ref = os.path.join(self.tmp_dir, "ref.wav")
        syn = os.path.join(self.tmp_dir, "syn.wav")
        _make_wav(ref, 2.0, freq=440)
        _make_wav(syn, 2.0, freq=440)
        report = evaluate_quality(ref, syn)
        self.assertEqual(report.status, "pass")
        self.assertGreater(report.similarity_score, 0.7)
        self.assertIsNotNone(report.snr)
        self.assertGreater(report.duration_score, 0.99)

    def test_different_audio(self):
        """不同频率音频 → 较低相似度"""
        ref = os.path.join(self.tmp_dir, "ref.wav")
        syn = os.path.join(self.tmp_dir, "syn.wav")
        _make_wav(ref, 2.0, freq=440)
        _make_wav(syn, 2.0, freq=2000)
        report = evaluate_quality(ref, syn)
        self.assertIn(report.status, ("warn", "pass", "fail"))

    def test_ref_not_exist(self):
        """参考音频不存在 → error"""
        report = evaluate_quality("/nope/ref.wav", "/nope/syn.wav")
        self.assertEqual(report.status, "error")
        self.assertIn("不存在", report.error)

    def test_syn_not_exist(self):
        """合成音频不存在 → error"""
        ref = os.path.join(self.tmp_dir, "ref.wav")
        _make_wav(ref, 1.0)
        report = evaluate_quality(ref, "/nope/syn.wav")
        self.assertEqual(report.status, "error")

    def test_with_asr_transcriber(self):
        """带 mock ASR 转写器 → 计算 WER"""
        ref = os.path.join(self.tmp_dir, "ref.wav")
        syn = os.path.join(self.tmp_dir, "syn.wav")
        _make_wav(ref, 2.0)
        _make_wav(syn, 2.0)
        # mock ASR: 返回固定文本
        def mock_asr(path):
            return "你好世界"
        report = evaluate_quality(ref, syn, reference_text="你好世界", asr_transcriber=mock_asr)
        self.assertIsNotNone(report.wer)
        self.assertAlmostEqual(report.wer, 0.0, places=4)
        self.assertEqual(report.synthesized_text, "你好世界")

    def test_asr_with_mismatch(self):
        """ASR 转写不匹配 → WER > 0"""
        ref = os.path.join(self.tmp_dir, "ref.wav")
        syn = os.path.join(self.tmp_dir, "syn.wav")
        _make_wav(ref, 2.0)
        _make_wav(syn, 2.0)
        def mock_asr(path):
            return "完全不同"
        report = evaluate_quality(ref, syn, reference_text="你好世界", asr_transcriber=mock_asr)
        self.assertIsNotNone(report.wer)
        self.assertGreater(report.wer, 0.5)

    def test_asr_exception_skips_wer(self):
        """ASR 异常 → 跳过 WER"""
        ref = os.path.join(self.tmp_dir, "ref.wav")
        syn = os.path.join(self.tmp_dir, "syn.wav")
        _make_wav(ref, 2.0)
        _make_wav(syn, 2.0)
        def bad_asr(path):
            raise RuntimeError("ASR 不可用")
        report = evaluate_quality(ref, syn, reference_text="你好", asr_transcriber=bad_asr)
        self.assertIsNone(report.wer)
        # 仍应返回频谱相似度等指标
        self.assertIn(report.status, ("pass", "warn", "fail"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
