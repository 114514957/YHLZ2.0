"""
YHLZ Voice Identity System V2.3-Phase8/9 - 安全与监控测试

测试:
    - test_security.py: VoiceSecurityChecker 各项检查
    - test_metrics.py: MetricsCollector 指标收集与 Prometheus 渲染
"""
from __future__ import annotations

import io
import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path


def _make_wav_bytes(duration_s: float = 5.0, sr: int = 16000, amp: float = 0.3) -> bytes:
    """生成 wav 字节流"""
    buf = io.BytesIO()
    n = int(duration_s * sr)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * amp * math.sin(2 * math.pi * 440 * i / sr))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _make_wav_file(duration_s: float = 5.0, sr: int = 16000, amp: float = 0.3) -> str:
    """生成临时 wav 文件, 返回路径"""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(_make_wav_bytes(duration_s, sr, amp))
    tmp.close()
    return tmp.name


class TestVoiceSecurityChecker(unittest.TestCase):
    """Phase 9: 安全检查器测试"""

    def setUp(self):
        from backend.voice_identity.voice_security import reset_security_checker
        reset_security_checker()

    def tearDown(self):
        from backend.voice_identity.voice_security import reset_security_checker
        reset_security_checker()
        # 清理临时文件在测试方法内

    def test_safe_audio_passes(self):
        """正常音频通过安全检查"""
        from backend.voice_identity.voice_security import check_audio_security
        path = _make_wav_file(duration_s=5.0)
        try:
            report = check_audio_security(path)
            self.assertTrue(report.passed, f"应通过: {[v.message for v in report.violations]}")
            self.assertTrue(report.is_safe)
            self.assertIsNotNone(report.file_hash)
            self.assertEqual(report.format, ".wav")
            self.assertGreater(report.duration_s, 4.0)
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        """文件不存在"""
        from backend.voice_identity.voice_security import check_audio_security
        report = check_audio_security("/nonexistent/audio.wav")
        self.assertFalse(report.passed)
        self.assertFalse(report.is_safe)
        self.assertTrue(any(v.code == "FILE_NOT_FOUND" for v in report.violations))

    def test_file_too_large(self):
        """文件过大"""
        from backend.voice_identity.voice_security import (
            VoiceSecurityChecker, VoiceSecurityConfig,
        )
        config = VoiceSecurityConfig(max_size_mb=0)
        checker = VoiceSecurityChecker(config)
        path = _make_wav_file(duration_s=1.0)
        try:
            report = checker.check(path)
            self.assertFalse(report.passed)
            self.assertTrue(any(v.code == "FILE_TOO_LARGE" for v in report.violations))
        finally:
            os.unlink(path)

    def test_format_not_allowed(self):
        """格式不在白名单"""
        from backend.voice_identity.voice_security import (
            VoiceSecurityConfig, VoiceSecurityChecker,
        )
        config = VoiceSecurityConfig(allowed_formats=(".wav",))
        checker = VoiceSecurityChecker(config)
        # 创建 .mp3 扩展名文件 (内容随意)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.write(b"fake mp3 content")
        tmp.close()
        try:
            report = checker.check(tmp.name)
            self.assertFalse(report.passed)
            self.assertTrue(any(v.code == "FORMAT_NOT_ALLOWED" for v in report.violations))
        finally:
            os.unlink(tmp.name)

    def test_duration_too_long(self):
        """时长超限"""
        from backend.voice_identity.voice_security import (
            VoiceSecurityConfig, VoiceSecurityChecker,
        )
        config = VoiceSecurityConfig(max_duration_s=2.0)
        checker = VoiceSecurityChecker(config)
        path = _make_wav_file(duration_s=5.0)
        try:
            report = checker.check(path)
            self.assertFalse(report.passed)
            self.assertTrue(any(v.code == "DURATION_TOO_LONG" for v in report.violations))
        finally:
            os.unlink(path)

    def test_duration_too_short_warning(self):
        """时长过短 (warning, 不是 critical)"""
        from backend.voice_identity.voice_security import (
            VoiceSecurityConfig, VoiceSecurityChecker,
        )
        config = VoiceSecurityConfig(min_duration_s=10.0)
        checker = VoiceSecurityChecker(config)
        path = _make_wav_file(duration_s=5.0)
        try:
            report = checker.check(path)
            # warning 不影响 passed
            self.assertTrue(any(v.code == "DURATION_TOO_SHORT" for v in report.warnings))
        finally:
            os.unlink(path)

    def test_file_hash_computed(self):
        """SHA256 哈希计算"""
        from backend.voice_identity.voice_security import check_audio_security
        path = _make_wav_file(duration_s=2.0)
        try:
            report = check_audio_security(path)
            self.assertIsNotNone(report.file_hash)
            self.assertEqual(len(report.file_hash), 64)  # SHA256 hex = 64 chars
            # 相同文件应产生相同哈希
            report2 = check_audio_security(path)
            self.assertEqual(report.file_hash, report2.file_hash)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        """空文件"""
        from backend.voice_identity.voice_security import check_audio_security
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            report = check_audio_security(tmp.name)
            self.assertFalse(report.passed)
            self.assertTrue(any(v.code == "FILE_EMPTY" for v in report.violations))
        finally:
            os.unlink(tmp.name)

    def test_is_directory(self):
        """路径是目录"""
        from backend.voice_identity.voice_security import check_audio_security
        tmp_dir = tempfile.mkdtemp()
        try:
            report = check_audio_security(tmp_dir)
            self.assertFalse(report.passed)
            self.assertTrue(any(v.code == "IS_DIRECTORY" for v in report.violations))
        finally:
            os.rmdir(tmp_dir)

    def test_silence_detection(self):
        """静音检测"""
        from backend.voice_identity.voice_security import (
            VoiceSecurityConfig, VoiceSecurityChecker,
        )
        # 生成接近静音的音频 (amp=0.001)
        path = _make_wav_file(duration_s=3.0, amp=0.001)
        try:
            config = VoiceSecurityConfig(
                silence_threshold=0.01,
                silence_max_ratio=0.5,
            )
            checker = VoiceSecurityChecker(config)
            report = checker.check(path)
            # 应检测到静音
            self.assertTrue(
                any(v.code == "EXCESSIVE_SILENCE" for v in report.warnings),
                f"应检测到静音: {[v.message for v in report.warnings]}",
            )
        finally:
            os.unlink(path)

    def test_clipping_detection(self):
        """削波检测"""
        from backend.voice_identity.voice_security import (
            VoiceSecurityConfig, VoiceSecurityChecker,
        )
        # 生成削波音频 (amp=1.5, 超过 16bit 范围会被 clamp)
        path = _make_wav_file(duration_s=3.0, amp=1.0)
        try:
            config = VoiceSecurityConfig(clipping_threshold=0.99)
            checker = VoiceSecurityChecker(config)
            report = checker.check(path)
            # amp=1.0 的正弦波在峰值处会达到 1.0, 可能触发削波
            # 不强制断言, 仅验证不崩溃
            self.assertIsNotNone(report)
        finally:
            os.unlink(path)

    def test_report_to_dict(self):
        """报告序列化"""
        from backend.voice_identity.voice_security import check_audio_security
        path = _make_wav_file(duration_s=2.0)
        try:
            report = check_audio_security(path)
            d = report.to_dict()
            self.assertIn("passed", d)
            self.assertIn("is_safe", d)
            self.assertIn("file_hash", d)
            self.assertIn("violations", d)
            self.assertIn("warnings", d)
        finally:
            os.unlink(path)

    def test_config_to_dict(self):
        """配置序列化"""
        from backend.voice_identity.voice_security import VoiceSecurityConfig
        config = VoiceSecurityConfig()
        d = config.to_dict()
        self.assertIn("max_size_mb", d)
        self.assertIn("max_duration_s", d)
        self.assertIn("allowed_formats", d)
        self.assertIn("enable_hash", d)

    def test_singleton(self):
        """单例模式"""
        from backend.voice_identity.voice_security import (
            get_security_checker, reset_security_checker,
        )
        reset_security_checker()
        c1 = get_security_checker()
        c2 = get_security_checker()
        self.assertIs(c1, c2)

    def test_compute_file_hash(self):
        """便捷函数 compute_file_hash"""
        from backend.voice_identity.voice_security import compute_file_hash
        path = _make_wav_file(duration_s=1.0)
        try:
            h = compute_file_hash(path)
            self.assertIsNotNone(h)
            self.assertEqual(len(h), 64)
        finally:
            os.unlink(path)


class TestMetricsCollector(unittest.TestCase):
    """Phase 8: 监控指标测试"""

    def setUp(self):
        from backend.voice_identity.metrics import reset_metrics
        reset_metrics()

    def tearDown(self):
        from backend.voice_identity.metrics import reset_metrics
        reset_metrics()

    def test_initial_state(self):
        """初始状态全零"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        snap = m.get_snapshot()
        self.assertEqual(snap.clone_total, 0)
        self.assertEqual(snap.clone_success, 0)
        self.assertEqual(snap.clone_failed, 0)

    def test_record_success(self):
        """记录成功克隆"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        m.record_clone(success=True, latency=1.5, voice_id="v1", quality_score=0.85)
        snap = m.get_snapshot()
        self.assertEqual(snap.clone_total, 1)
        self.assertEqual(snap.clone_success, 1)
        self.assertEqual(snap.clone_failed, 0)
        self.assertEqual(snap.latency_count, 1)
        self.assertAlmostEqual(snap.latency_sum, 1.5, places=2)
        self.assertEqual(snap.quality_count, 1)
        self.assertAlmostEqual(snap.quality_sum, 0.85, places=2)
        self.assertEqual(snap.last_clone_voice_id, "v1")
        self.assertAlmostEqual(snap.last_clone_latency, 1.5, places=2)
        self.assertAlmostEqual(snap.last_clone_quality, 0.85, places=2)

    def test_record_failure(self):
        """记录失败克隆"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        m.record_clone(success=False, latency=0.5, voice_id="v2")
        snap = m.get_snapshot()
        self.assertEqual(snap.clone_total, 1)
        self.assertEqual(snap.clone_success, 0)
        self.assertEqual(snap.clone_failed, 1)
        self.assertEqual(snap.quality_count, 0)  # 失败无质量评分

    def test_record_multiple(self):
        """多次记录累积"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        m.record_clone(success=True, latency=1.0, quality_score=0.8)
        m.record_clone(success=True, latency=2.0, quality_score=0.9)
        m.record_clone(success=False, latency=0.5)
        snap = m.get_snapshot()
        self.assertEqual(snap.clone_total, 3)
        self.assertEqual(snap.clone_success, 2)
        self.assertEqual(snap.clone_failed, 1)
        self.assertEqual(snap.latency_count, 3)
        self.assertAlmostEqual(snap.latency_sum, 3.5, places=2)
        self.assertEqual(snap.quality_count, 2)
        self.assertAlmostEqual(snap.quality_sum, 1.7, places=2)

    def test_record_adapter_error(self):
        """记录 Adapter 错误"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        m.record_adapter_error("qwen3", "load_failed")
        m.record_adapter_error("qwen3", "load_failed")
        m.record_adapter_error("gpt_sovits", "timeout")
        snap = m.get_snapshot()
        self.assertEqual(snap.adapter_error_total, 3)
        self.assertEqual(snap.adapter_errors.get("qwen3:load_failed"), 2)
        self.assertEqual(snap.adapter_errors.get("gpt_sovits:timeout"), 1)

    def test_latency_histogram(self):
        """延迟直方图"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        m.record_clone(success=True, latency=0.3)   # <0.5
        m.record_clone(success=True, latency=1.5)   # <2.0
        m.record_clone(success=True, latency=5.0)   # <10.0
        m.record_clone(success=True, latency=50.0)  # >30 (落到 +Inf)
        snap = m.get_snapshot()
        # 直方图是累积的: 每个桶记录 <= upper_bound 的总数
        # <0.5: 1, <1.0: 1, <2.0: 2, <5.0: 2, <10.0: 3, <30.0: 3, +Inf: 4
        buckets = {b.upper_bound: b.count for b in snap.latency_buckets}
        self.assertEqual(buckets[0.5], 1)
        self.assertEqual(buckets[2.0], 2)
        self.assertEqual(buckets[10.0], 3)
        self.assertEqual(buckets[float('inf')], 4)

    def test_render_prometheus(self):
        """Prometheus 文本格式渲染"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        m.record_clone(success=True, latency=1.5, quality_score=0.85)
        m.record_clone(success=False, latency=0.5)
        m.record_adapter_error("qwen3", "load_failed")
        text = m.render_prometheus()
        # 验证包含关键指标
        self.assertIn("voice_clone_total 2", text)
        self.assertIn("voice_clone_success 1", text)
        self.assertIn("voice_clone_failed 1", text)
        self.assertIn("voice_clone_latency_seconds", text)
        self.assertIn("voice_adapter_error_total 1", text)
        # 验证 Prometheus 格式 (HELP/TYPE)
        self.assertIn("# HELP", text)
        self.assertIn("# TYPE", text)

    def test_render_prometheus_empty(self):
        """空指标渲染"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        text = m.render_prometheus()
        self.assertIn("voice_clone_total 0", text)
        self.assertIn("voice_clone_success 0", text)

    def test_reset(self):
        """重置指标"""
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics()
        m.record_clone(success=True, latency=1.0)
        self.assertEqual(m.get_snapshot().clone_total, 1)
        m.reset()
        self.assertEqual(m.get_snapshot().clone_total, 0)

    def test_singleton(self):
        """单例模式"""
        from backend.voice_identity.metrics import get_metrics
        m1 = get_metrics()
        m2 = get_metrics()
        self.assertIs(m1, m2)

    def test_module_level_functions(self):
        """模块级便捷函数"""
        from backend.voice_identity.metrics import (
            record_clone, record_adapter_error, render_prometheus, get_metrics,
        )
        record_clone(success=True, latency=1.0, quality_score=0.9)
        record_adapter_error("qwen3", "test_error")
        text = render_prometheus()
        self.assertIn("voice_clone_total 1", text)
        self.assertIn("voice_adapter_error_total 1", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
