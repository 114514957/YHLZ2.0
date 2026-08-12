"""
YHLZ Voice Identity System V2.1 - Voice Analyzer 声音分析器

职责:
    - 从验证通过的音频中提取声音特征
    - 生成 VoiceFeature 用于 VoiceProfile.style/metadata
    - 为后续 Cache 提取 (Qwen3 embedding / GPT-SoVITS 权重) 准备元数据

API:
    analyze_voice(audio_info) → Result[VoiceFeature]
    VoiceFeature: dataclass, 携带 embedding / 基本声学特征 / 引擎特定元数据

设计原则:
    - 不直接调用 TTS 引擎 (经 Cache 间接, 对齐 V1.4 Manager 约束)
    - 优先 librosa 提取声学特征 (F0/能量/语速); 缺失时返回降级特征
    - 预留 embedding 字段 (str): 由 Pipeline 后续调 Cache.prepare 时填充
    - 返回 Result, 不抛异常
    - 引擎无关: 同一 VoiceFeature 可服务 qwen3 / gpt_sovits / edge
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from backend.voice_identity.clone.audio_validator import AudioInfo
from backend.voice_identity.clone.result import Err, Ok, Result

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceFeature:
    """声音特征快照 (引擎无关)

    字段:
        audio_info:      原始音频元信息
        mean_f0:         平均基频 (Hz), None 表示无法估计
        f0_range:        (min, max) 基频范围
        mean_energy:     平均 RMS 能量 (0-1 归一化)
        speech_rate:     语速估计 (音节/秒), None 表示无法估计
        snr_db:          信噪比估计 (dB), None 表示无法估计
        embedding:       说话人向量占位 (由 Pipeline 后续填充)
        extra:           引擎特定元数据 (如 gpt_sovits 的 sovits_model 路径)
    """
    audio_info: AudioInfo
    mean_f0: Optional[float] = None
    f0_range: Optional[tuple] = None
    mean_energy: Optional[float] = None
    speech_rate: Optional[float] = None
    snr_db: Optional[float] = None
    embedding: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "audio": self.audio_info.to_dict(),
            "mean_f0": self.mean_f0,
            "f0_range": list(self.f0_range) if self.f0_range else None,
            "mean_energy": self.mean_energy,
            "speech_rate": self.speech_rate,
            "snr_db": self.snr_db,
            "has_embedding": self.embedding is not None,
            "extra": self.extra,
        }

    def to_style_metadata(self) -> dict:
        """转为 VoiceProfile.style 字段 (供克隆时写入)"""
        style: Dict[str, Any] = {}
        if self.mean_f0 is not None:
            style["mean_f0"] = round(self.mean_f0, 2)
        if self.mean_energy is not None:
            style["mean_energy"] = round(self.mean_energy, 4)
        if self.speech_rate is not None:
            style["speech_rate"] = round(self.speech_rate, 2)
        return style


def _extract_with_librosa(audio_info: AudioInfo) -> Optional[Dict[str, Any]]:
    """用 librosa 提取声学特征; 不可用或失败返回 None"""
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
        y, sr = librosa.load(audio_info.path, sr=None, mono=True)
        if len(y) == 0:
            return None

        # 基频 F0 (pyin 比 piptrack 更稳)
        try:
            f0, voiced_flag, _ = librosa.pyin(
                y, fmin=80, fmax=400,
                sr=sr, frame_length=1024,
            )
            voiced_f0 = f0[voiced_flag & ~np.isnan(f0)] if f0 is not None else np.array([])
            if len(voiced_f0) > 0:
                mean_f0 = float(np.mean(voiced_f0))
                f0_range = (float(np.min(voiced_f0)), float(np.max(voiced_f0)))
            else:
                mean_f0 = None
                f0_range = None
        except Exception:
            mean_f0 = None
            f0_range = None

        # RMS 能量
        try:
            rms = librosa.feature.rms(y=y)[0]
            mean_energy = float(np.mean(rms))
        except Exception:
            mean_energy = None

        # 语速估计: 用 spectral_flux 或 onset 检测近似
        try:
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            n_onsets = int(np.sum(onset_env > np.mean(onset_env) + np.std(onset_env)))
            speech_rate = n_onsets / audio_info.duration_s
        except Exception:
            speech_rate = None

        # SNR 估计: 高频能量 / 低频噪声 简化比
        try:
            spec = np.abs(librosa.stft(y))
            power = spec ** 2
            total = float(np.mean(power))
            noise_floor = float(np.percentile(power, 10))
            if noise_floor > 0 and total > 0:
                snr_db = 10 * math.log10(total / noise_floor)
            else:
                snr_db = None
        except Exception:
            snr_db = None

        return {
            "mean_f0": mean_f0,
            "f0_range": f0_range,
            "mean_energy": mean_energy,
            "speech_rate": speech_rate,
            "snr_db": snr_db,
        }
    except Exception as e:
        logger.debug(f"librosa 提取失败: {e}")
        return None


def _extract_fallback(audio_info: AudioInfo) -> Dict[str, Any]:
    """降级特征 (无 librosa): 仅返回基本字段, 全为 None"""
    return {
        "mean_f0": None,
        "f0_range": None,
        "mean_energy": None,
        "speech_rate": None,
        "snr_db": None,
    }


def analyze_voice(audio_info: AudioInfo) -> Result[VoiceFeature]:
    """分析声音特征

    输入: validate_audio 返回的 AudioInfo
    输出: Ok(VoiceFeature) / Err(原因)

    流程:
        1. 优先 librosa 提取 F0/能量/语速/SNR
        2. librosa 不可用 → 降级 (字段全 None, 仍返 Ok)
        3. embedding 字段留空, 由 Pipeline 后续调 Cache.prepare 填充

    V2.3-Phase6: TEST_MODE 下跳过 librosa (避免首次加载 numba/JIT 卡住)
    """
    if not isinstance(audio_info, AudioInfo):
        return Err(f"audio_info 类型错误: {type(audio_info).__name__}")

    # V2.3-Phase6: TEST_MODE 下直接降级 (librosa 首次加载可能很慢)
    feats = None
    try:
        from backend.voice_identity.mock_loader import is_test_mode
        if is_test_mode():
            logger.info("TEST_MODE: 跳过 librosa, 使用降级特征")
            feats = _extract_fallback(audio_info)
    except ImportError:
        pass

    if feats is None:
        feats = _extract_with_librosa(audio_info)
        if feats is None:
            logger.info("librosa 不可用, 使用降级特征提取")
            feats = _extract_fallback(audio_info)
        else:
            logger.debug(f"librosa 提取成功: {feats}")

    feature = VoiceFeature(
        audio_info=audio_info,
        mean_f0=feats.get("mean_f0"),
        f0_range=feats.get("f0_range"),
        mean_energy=feats.get("mean_energy"),
        speech_rate=feats.get("speech_rate"),
        snr_db=feats.get("snr_db"),
        embedding=None,
        extra={},
    )
    return Ok(feature)
