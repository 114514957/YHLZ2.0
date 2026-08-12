"""
YHLZ Voice Identity System V2.3-Phase9 - Voice Security 安全增强

职责:
    - 上传音频安全校验 (独立于 audio_validator, 聚焦安全维度)
    - 文件大小限制 (max_size)
    - 格式白名单 (allowed_format)
    - 时长上限 (max_duration)
    - 内容哈希 (SHA256, 用于去重/审计/完整性校验)
    - 可疑特征检测 (静音/削波/异常采样率)

API:
    VoiceSecurityConfig:  安全策略配置 (dataclass)
    SecurityReport:       安全检查报告 (dataclass)
    VoiceSecurityChecker: 安全检查器
    check_audio_security(path, config=None) → SecurityReport

设计原则:
    - 纯 stdlib, 无新依赖
    - 不抛异常, 返回 SecurityReport (含 violations 列表)
    - 与 audio_validator 互补: validator 关注可用性, security 关注安全性
    - 可集成到 clone pipeline / API 上传层
"""
from __future__ import annotations

import hashlib
import logging
import os
import wave
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 默认阈值 ──
DEFAULT_MAX_SIZE_MB: int = 50            # 最大 50MB
DEFAULT_MAX_DURATION_S: float = 120.0    # 最长 120 秒 (安全上限, 比 validator 的 60s 更宽松)
DEFAULT_MIN_DURATION_S: float = 1.0      # 最短 1 秒 (安全下限)
DEFAULT_ALLOWED_FORMATS: Tuple[str, ...] = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
DEFAULT_HASH_CHUNK_SIZE: int = 65536     # 64KB

# 安全违规等级
SEVERITY_INFO: str = "info"
SEVERITY_WARNING: str = "warning"
SEVERITY_CRITICAL: str = "critical"


@dataclass
class VoiceSecurityConfig:
    """安全策略配置"""
    max_size_mb: int = DEFAULT_MAX_SIZE_MB
    max_duration_s: float = DEFAULT_MAX_DURATION_S
    min_duration_s: float = DEFAULT_MIN_DURATION_S
    allowed_formats: Tuple[str, ...] = DEFAULT_ALLOWED_FORMATS
    enable_hash: bool = True
    enable_silence_check: bool = True
    silence_threshold: float = 0.01      # RMS 能量低于此值视为静音
    silence_max_ratio: float = 0.8        # 静音帧占比超过此值视为可疑
    enable_clipping_check: bool = True
    clipping_threshold: float = 0.99      # 样本绝对值超过此值视为削波

    def to_dict(self) -> dict:
        return {
            "max_size_mb": self.max_size_mb,
            "max_duration_s": self.max_duration_s,
            "min_duration_s": self.min_duration_s,
            "allowed_formats": list(self.allowed_formats),
            "enable_hash": self.enable_hash,
            "enable_silence_check": self.enable_silence_check,
            "silence_threshold": self.silence_threshold,
            "silence_max_ratio": self.silence_max_ratio,
            "enable_clipping_check": self.enable_clipping_check,
            "clipping_threshold": self.clipping_threshold,
        }


@dataclass
class SecurityViolation:
    """安全违规项"""
    code: str
    severity: str
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class SecurityReport:
    """安全检查报告"""
    path: str
    passed: bool
    file_hash: Optional[str] = None
    file_size: Optional[int] = None
    duration_s: Optional[float] = None
    format: Optional[str] = None
    sample_rate: Optional[int] = None
    violations: List[SecurityViolation] = field(default_factory=list)
    warnings: List[SecurityViolation] = field(default_factory=list)
    info: List[SecurityViolation] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(v.severity == SEVERITY_CRITICAL for v in self.violations)

    @property
    def is_safe(self) -> bool:
        """是否通过安全检查 (无 critical 违规)"""
        return not self.has_critical

    def add_violation(self, code: str, severity: str, message: str, **detail) -> None:
        v = SecurityViolation(code=code, severity=severity, message=message, detail=detail)
        if severity == SEVERITY_CRITICAL:
            self.violations.append(v)
        elif severity == SEVERITY_WARNING:
            self.warnings.append(v)
        else:
            self.info.append(v)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "passed": self.passed,
            "is_safe": self.is_safe,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "duration_s": round(self.duration_s, 3) if self.duration_s is not None else None,
            "format": self.format,
            "sample_rate": self.sample_rate,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": [v.to_dict() for v in self.warnings],
            "info": [v.to_dict() for v in self.info],
        }


class VoiceSecurityChecker:
    """音频安全检查器

    使用:
        checker = VoiceSecurityChecker()
        report = checker.check("/path/to/audio.wav")
        if not report.is_safe:
            print("不安全:", report.violations)
    """

    def __init__(self, config: Optional[VoiceSecurityConfig] = None):
        self._config = config or VoiceSecurityConfig()

    @property
    def config(self) -> VoiceSecurityConfig:
        return self._config

    def check(self, path: str) -> SecurityReport:
        """执行完整安全检查"""
        report = SecurityReport(path=path, passed=True)

        # 1. 路径存在性
        if not path or not isinstance(path, str):
            report.add_violation(
                code="INVALID_PATH", severity=SEVERITY_CRITICAL,
                message="音频路径为空或非字符串",
            )
            report.passed = False
            return report

        if not os.path.exists(path):
            report.add_violation(
                code="FILE_NOT_FOUND", severity=SEVERITY_CRITICAL,
                message=f"音频文件不存在: {path}",
            )
            report.passed = False
            return report

        if os.path.isdir(path):
            report.add_violation(
                code="IS_DIRECTORY", severity=SEVERITY_CRITICAL,
                message=f"路径是目录不是文件: {path}",
            )
            report.passed = False
            return report

        # 2. 文件大小
        try:
            size = os.path.getsize(path)
            report.file_size = size
        except OSError as e:
            report.add_violation(
                code="SIZE_READ_FAILED", severity=SEVERITY_CRITICAL,
                message=f"无法读取文件大小: {e}",
            )
            report.passed = False
            return report

        max_size_bytes = self._config.max_size_mb * 1024 * 1024
        if size > max_size_bytes:
            report.add_violation(
                code="FILE_TOO_LARGE", severity=SEVERITY_CRITICAL,
                message=f"文件过大: {size / 1024 / 1024:.2f}MB > {self._config.max_size_mb}MB",
                size_bytes=size, max_size_bytes=max_size_bytes,
            )
            report.passed = False

        if size == 0:
            report.add_violation(
                code="FILE_EMPTY", severity=SEVERITY_CRITICAL,
                message="文件为空 (0 字节)",
            )
            report.passed = False
            return report

        # 3. 格式白名单
        ext = os.path.splitext(path)[1].lower()
        report.format = ext
        if ext not in self._config.allowed_formats:
            report.add_violation(
                code="FORMAT_NOT_ALLOWED", severity=SEVERITY_CRITICAL,
                message=f"格式 '{ext}' 不在允许列表: {list(self._config.allowed_formats)}",
                format=ext, allowed=list(self._config.allowed_formats),
            )
            report.passed = False

        # 4. 音频元信息 (采样率/时长/通道)
        sr, frames, channels = self._read_audio_meta(path)
        if sr is not None:
            report.sample_rate = sr
        if sr is not None and sr > 0 and frames is not None:
            duration = frames / sr
            report.duration_s = duration

            # 时长上限
            if duration > self._config.max_duration_s:
                report.add_violation(
                    code="DURATION_TOO_LONG", severity=SEVERITY_CRITICAL,
                    message=f"时长过长: {duration:.2f}s > {self._config.max_duration_s}s",
                    duration_s=duration, max_duration_s=self._config.max_duration_s,
                )
                report.passed = False

            # 时长下限
            if duration < self._config.min_duration_s:
                report.add_violation(
                    code="DURATION_TOO_SHORT", severity=SEVERITY_WARNING,
                    message=f"时长过短: {duration:.2f}s < {self._config.min_duration_s}s",
                    duration_s=duration, min_duration_s=self._config.min_duration_s,
                )

        # 5. 内容哈希 (SHA256)
        if self._config.enable_hash:
            file_hash = self._compute_hash(path)
            if file_hash:
                report.file_hash = file_hash
            else:
                report.add_violation(
                    code="HASH_FAILED", severity=SEVERITY_WARNING,
                    message="计算文件哈希失败",
                )

        # 6. 静音/削波检测 (仅 WAV, 避免引入解码依赖)
        if ext == ".wav" and sr is not None and frames is not None:
            self._check_audio_content(path, report, sr, frames)

        logger.debug(
            f"安全检查完成: {path} passed={report.passed} "
            f"violations={len(report.violations)} warnings={len(report.warnings)}"
        )
        return report

    def _read_audio_meta(self, path: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """读取音频元信息 (采样率/帧数/通道数)"""
        # 优先 soundfile
        try:
            import soundfile as sf  # type: ignore
            info = sf.info(path)
            return (info.samplerate, info.frames, info.channels)
        except Exception:
            pass

        # 回退 wave (仅 .wav)
        try:
            with wave.open(path, "rb") as w:
                return (w.getframerate(), w.getnframes(), w.getnchannels())
        except Exception:
            pass

        return (None, None, None)

    def _compute_hash(self, path: str) -> Optional[str]:
        """计算文件 SHA256"""
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(DEFAULT_HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception as e:
            logger.warning(f"计算哈希失败 {path}: {e}")
            return None

    def _check_audio_content(self, path: str, report: SecurityReport, sr: int, frames: int) -> None:
        """静音/削波检测 (仅 WAV, 采样读取避免大内存)"""
        try:
            import struct
            import math
            with wave.open(path, "rb") as w:
                n_channels = w.getnchannels()
                sampwidth = w.getsampwidth()
                if sampwidth != 2:
                    return  # 仅处理 16bit

                total_frames = w.getnframes()
                if total_frames == 0:
                    return

                # 采样检测 (每 100ms 取一个采样点, 避免全量读取)
                chunk_frames = int(sr * 0.1)  # 100ms
                chunks_to_check = min(100, total_frames // chunk_frames) if chunk_frames > 0 else 0
                if chunks_to_check == 0:
                    return

                silence_count = 0
                clipping_count = 0
                total_checked = 0

                for i in range(chunks_to_check):
                    pos = (total_frames // chunks_to_check) * i
                    w.setpos(pos)
                    raw = w.readframes(chunk_frames)
                    if not raw:
                        continue

                    # 解析 16bit 样本
                    n_samples = len(raw) // 2
                    if n_samples == 0:
                        continue

                    samples = struct.unpack(f"<{n_samples}h", raw)
                    # 归一化到 [-1, 1]
                    norm = [s / 32768.0 for s in samples]

                    # RMS 能量
                    rms = math.sqrt(sum(s * s for s in norm) / len(norm))

                    if self._config.enable_silence_check:
                        if rms < self._config.silence_threshold:
                            silence_count += 1

                    if self._config.enable_clipping_check:
                        clip_count = sum(
                            1 for s in norm if abs(s) >= self._config.clipping_threshold
                        )
                        if clip_count > len(norm) * 0.01:  # 1% 以上削波
                            clipping_count += 1

                    total_checked += 1

                if total_checked > 0:
                    # 静音占比
                    silence_ratio = silence_count / total_checked
                    if silence_ratio > self._config.silence_max_ratio:
                        report.add_violation(
                            code="EXCESSIVE_SILENCE", severity=SEVERITY_WARNING,
                            message=f"静音占比过高: {silence_ratio:.1%} > {self._config.silence_max_ratio:.1%}",
                            silence_ratio=silence_ratio,
                        )

                    # 削波占比
                    clipping_ratio = clipping_count / total_checked
                    if clipping_ratio > 0.3:  # 30% 以上 chunk 有削波
                        report.add_violation(
                            code="EXCESSIVE_CLIPPING", severity=SEVERITY_WARNING,
                            message=f"削波占比过高: {clipping_ratio:.1%}",
                            clipping_ratio=clipping_ratio,
                        )

        except Exception as e:
            logger.debug(f"音频内容检测失败 {path}: {e}")


# ==================================================================
# 模块级单例
# ==================================================================

_security_checker: Optional[VoiceSecurityChecker] = None
_security_lock = __import__("threading").Lock()


def get_security_checker(config: Optional[VoiceSecurityConfig] = None) -> VoiceSecurityChecker:
    """获取全局 VoiceSecurityChecker 单例"""
    global _security_checker
    with _security_lock:
        if _security_checker is None or config is not None:
            _security_checker = VoiceSecurityChecker(config)
        return _security_checker


def reset_security_checker() -> None:
    """重置全局单例 (测试用)"""
    global _security_checker
    with _security_lock:
        _security_checker = None


def check_audio_security(
    path: str, config: Optional[VoiceSecurityConfig] = None
) -> SecurityReport:
    """便捷函数: 检查音频文件安全性"""
    checker = get_security_checker(config)
    return checker.check(path)


def compute_file_hash(path: str) -> Optional[str]:
    """便捷函数: 计算文件 SHA256 (与 dedup.compute_audio_hash 一致, 重新导出便于统一调用)"""
    checker = VoiceSecurityChecker()
    return checker._compute_hash(path)
