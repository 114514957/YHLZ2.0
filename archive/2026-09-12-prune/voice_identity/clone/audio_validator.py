"""
YHLZ Voice Identity System V2.1 - Audio Validator 音频验证器

职责:
    - 验证输入音频是否适合用于声音克隆
    - 检查项: 文件存在 / 可读 / 格式 / 采样率 / 时长 / 通道 / 非空

API:
    validate_audio(path) → Result[AudioInfo]
    AudioInfo: dataclass, 携带采样率/时长/通道/样本数

设计原则:
    - 优先 soundfile (libsndfile), 缺失时回退 wave (stdlib)
    - 不依赖 librosa (重依赖), 仅做格式校验
    - 返回 Result, 不抛异常; Pipeline 链式处理
    - 阈值可配置: MIN_DURATION_S / MAX_DURATION_S / MIN_SAMPLE_RATE
"""
from __future__ import annotations

import logging
import os
import wave
from dataclasses import dataclass
from typing import Optional

from backend.voice_identity.clone.result import Err, Ok, Result

logger = logging.getLogger(__name__)

# ── 阈值常量 (可调整) ──
MIN_DURATION_S: float = 3.0       # 最短 3 秒 (克隆参考音频建议 5-10s, 下限 3s)
MAX_DURATION_S: float = 60.0      # 最长 60 秒 (过长无收益且拖慢提取)
MIN_SAMPLE_RATE: int = 16000      # 最低 16kHz
SUPPORTED_FORMATS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


@dataclass(frozen=True)
class AudioInfo:
    """音频元信息 (验证通过后返回)"""
    path: str
    sample_rate: int
    duration_s: float
    channels: int
    frames: int
    format: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "sample_rate": self.sample_rate,
            "duration_s": round(self.duration_s, 3),
            "channels": self.channels,
            "frames": self.frames,
            "format": self.format,
        }


def _read_with_soundfile(path: str) -> Optional[tuple]:
    """用 soundfile 读取; 不可用或失败返回 None"""
    try:
        import soundfile as sf  # type: ignore
        info = sf.info(path)
        return (info.samplerate, info.frames, info.channels, info.format)
    except Exception:
        return None


def _read_with_wave(path: str) -> Optional[tuple]:
    """用 stdlib wave 读取 (仅 .wav); 失败返回 None"""
    try:
        with wave.open(path, "rb") as w:
            frames = w.getnframes()
            sr = w.getframerate()
            channels = w.getnchannels()
            return (sr, frames, channels, "WAV")
    except Exception:
        return None


def validate_audio(path: str) -> Result[AudioInfo]:
    """验证音频文件

    检查项 (按顺序):
        1. 路径非空 + 文件存在 + 非目录
        2. 文件非空 (size > 0)
        3. 扩展名在支持列表
        4. 可读取元信息 (soundfile → wave)
        5. 采样率 ≥ MIN_SAMPLE_RATE
        6. 时长在 [MIN_DURATION_S, MAX_DURATION_S]
        7. 通道数 ≥ 1

    成功返回 Ok(AudioInfo); 失败返回 Err(原因字符串)
    """
    # 1. 路径存在性
    if not path or not isinstance(path, str):
        return Err("音频路径为空或非字符串")
    if not os.path.exists(path):
        return Err(f"音频文件不存在: {path}")
    if os.path.isdir(path):
        return Err(f"路径是目录不是文件: {path}")

    # 2. 文件非空
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return Err(f"无法读取文件大小: {e}")
    if size == 0:
        return Err(f"音频文件为空 (0 字节): {path}")

    # 3. 扩展名
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_FORMATS:
        return Err(
            f"不支持的音频格式 '{ext}', 支持: {sorted(SUPPORTED_FORMATS)}"
        )

    # 4. 读取元信息
    info = _read_with_soundfile(path)
    if info is None:
        info = _read_with_wave(path)
    if info is None:
        return Err(
            f"无法解析音频元信息 (soundfile 与 wave 均失败): {path}"
        )

    sr, frames, channels, fmt = info

    # 5. 采样率
    if sr < MIN_SAMPLE_RATE:
        return Err(
            f"采样率过低: {sr}Hz < {MIN_SAMPLE_RATE}Hz (最低要求)"
        )

    # 6. 时长
    if sr <= 0:
        return Err(f"采样率非法: {sr}")
    duration = frames / sr
    if duration < MIN_DURATION_S:
        return Err(
            f"音频过短: {duration:.2f}s < {MIN_DURATION_S}s (克隆参考音频建议 5-10s)"
        )
    if duration > MAX_DURATION_S:
        return Err(
            f"音频过长: {duration:.2f}s > {MAX_DURATION_S}s (无额外收益且拖慢提取)"
        )

    # 7. 通道
    if channels < 1:
        return Err(f"通道数非法: {channels}")

    audio_info = AudioInfo(
        path=path, sample_rate=sr, duration_s=duration,
        channels=channels, frames=frames, format=fmt,
    )
    logger.debug(f"音频验证通过: {audio_info.to_dict()}")
    return Ok(audio_info)
