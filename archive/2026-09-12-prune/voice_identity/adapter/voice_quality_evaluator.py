"""
YHLZ Voice Identity System - Phase 1.3 真实质量评估系统

职责:
    - 输入: 原始音频 + 合成音频 (可选参考文本)
    - 输出: QualityReport { similarity_score, wer, snr, duration_score, status }

设计:
    - SNR / duration_score: 纯 stdlib + numpy 计算, 不依赖外部模型
    - WER: 可注入 ASR 转写器 (Callable[[audio_path], str]), 缺省跳过
    - similarity_score: 基于频谱相似度 (MFCC-lite) + WER 加权
    - 所有异常不抛出, 转为 status="error" + error 字段

不依赖:
    - 不直接 import asr_engine (避免循环 + GPU 依赖)
    - 不依赖 scipy (用 numpy FFT)
"""
from __future__ import annotations

import logging
import math
import os
import wave
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ASR 转写器类型: 输入音频路径, 返回转写文本
ASRTranscriber = Callable[[str], str]


@dataclass
class QualityReport:
    """质量评估报告"""
    similarity_score: float       # 综合相似度 [0, 1]
    wer: Optional[float]          # 词错率 [0, +∞), None=未评估
    snr: Optional[float]          # 信噪比 (dB), None=无法计算
    duration_score: float         # 时长匹配度 [0, 1]
    status: str                   # pass / warn / fail / error
    reference_text: Optional[str] = None
    synthesized_text: Optional[str] = None
    error: Optional[str] = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "similarity_score": round(self.similarity_score, 4),
            "wer": round(self.wer, 4) if self.wer is not None else None,
            "snr": round(self.snr, 2) if self.snr is not None else None,
            "duration_score": round(self.duration_score, 4),
            "status": self.status,
            "reference_text": self.reference_text,
            "synthesized_text": self.synthesized_text,
            "error": self.error,
            "details": self.details,
        }


def _read_wav(path: str) -> tuple[Optional[np.ndarray], Optional[int]]:
    """读取 wav 文件 → (samples, sample_rate); 失败返 (None, None)"""
    try:
        with wave.open(path, "rb") as w:
            nch = w.getnchannels()
            sw = w.getsampwidth()
            sr = w.getframerate()
            frames = w.readframes(w.getnframes())
        if sw == 2:
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sw == 4:
            samples = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            return None, None
        if nch > 1:
            samples = samples.reshape(-1, nch).mean(axis=1)
        return samples, sr
    except Exception as e:
        logger.warning(f"读取 wav 失败: {path}: {e}")
        return None, None


def _compute_snr(samples: np.ndarray) -> Optional[float]:
    """计算信号 SNR (dB): 信号能量 / 噪声能量

    用前 100ms 估计噪声底, 其余视为信号+噪声。
    """
    if samples is None or len(samples) < 1600:
        return None
    try:
        noise_n = min(int(0.1 * len(samples)), 3200)
        noise = samples[:noise_n]
        noise_power = float(np.mean(noise ** 2)) + 1e-10
        signal = samples[noise_n:]
        signal_power = float(np.mean(signal ** 2)) + 1e-10
        if signal_power <= noise_power:
            return 0.0
        return float(10 * math.log10(signal_power / noise_power))
    except Exception:
        return None


def _compute_spectral_similarity(a: np.ndarray, b: np.ndarray, sr: int) -> float:
    """计算频谱相似度 [0, 1]

    用简单 FFT 频谱 + 余弦相似度。
    两个音频长度不同时, 对齐到较短长度。
    """
    try:
        n = min(len(a), len(b))
        if n < 512:
            return 0.0
        a_seg = a[:n]
        b_seg = b[:n]
        # FFT 幅度谱
        fa = np.abs(np.fft.rfft(a_seg))
        fb = np.abs(np.fft.rfft(b_seg))
        # 归一化
        na = np.linalg.norm(fa) + 1e-10
        nb = np.linalg.norm(fb) + 1e-10
        cos = float(np.dot(fa, fb) / (na * nb))
        # 映射 [-1, 1] → [0, 1]
        return max(0.0, min(1.0, (cos + 1) / 2))
    except Exception:
        return 0.0


def _compute_duration_score(ref_dur: float, syn_dur: float) -> float:
    """时长匹配度 [0, 1]: 1.0=完全一致, 越偏离越低"""
    if ref_dur <= 0 or syn_dur <= 0:
        return 0.0
    ratio = syn_dur / ref_dur
    # 允许 0.5~2.0 范围, 超出归零
    if ratio < 0.5 or ratio > 2.0:
        return 0.0
    # 对数距离
    dist = abs(math.log(ratio))
    return max(0.0, min(1.0, 1.0 - dist))


def _wer(reference: str, hypothesis: str) -> float:
    """计算词错率 WER (字符级, 适用于中文)

    WER = (S + D + I) / N
    """
    ref = list(reference.replace(" ", "").replace("\n", ""))
    hyp = list(hypothesis.replace(" ", "").replace("\n", ""))
    if len(ref) == 0:
        return 1.0 if len(hyp) > 0 else 0.0
    # DP
    dp = [[0] * (len(hyp) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        dp[i][0] = i
    for j in range(len(hyp) + 1):
        dp[0][j] = j
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    edits = dp[len(ref)][len(hyp)]
    return edits / len(ref)


def evaluate_quality(
    reference_audio: str,
    synthesized_audio: str,
    reference_text: Optional[str] = None,
    asr_transcriber: Optional[ASRTranscriber] = None,
) -> QualityReport:
    """评估合成音频质量

    参数:
        reference_audio: 原始参考音频路径 (wav)
        synthesized_audio: 合成音频路径 (wav)
        reference_text: 原始文本 (可选, 用于 WER)
        asr_transcriber: ASR 转写器 (可选, 输入音频路径返回文本); None 则跳过 WER

    返回:
        QualityReport
    """
    # 1. 文件存在性
    if not os.path.exists(reference_audio):
        return QualityReport(0, None, None, 0, "error", error=f"参考音频不存在: {reference_audio}")
    if not os.path.exists(synthesized_audio):
        return QualityReport(0, None, None, 0, "error", error=f"合成音频不存在: {synthesized_audio}")

    # 2. 读取音频
    ref_samples, ref_sr = _read_wav(reference_audio)
    syn_samples, syn_sr = _read_wav(synthesized_audio)
    if ref_samples is None or syn_samples is None:
        return QualityReport(0, None, None, 0, "error", error="音频读取失败 (仅支持 wav)")

    # 3. 时长
    ref_dur = len(ref_samples) / ref_sr if ref_sr else 0
    syn_dur = len(syn_samples) / syn_sr if syn_sr else 0
    duration_score = _compute_duration_score(ref_dur, syn_dur)

    # 4. SNR (合成音频)
    snr = _compute_snr(syn_samples)

    # 5. 频谱相似度
    sim = _compute_spectral_similarity(ref_samples, syn_samples, ref_sr or syn_sr or 16000)

    # 6. WER (如有 ASR 转写器)
    wer_val = None
    synth_text = None
    if asr_transcriber is not None:
        try:
            synth_text = asr_transcriber(synthesized_audio)
            if reference_text is not None:
                wer_val = _wer(reference_text, synth_text)
            else:
                # 无参考文本, 用参考音频转写
                ref_text = asr_transcriber(reference_audio)
                wer_val = _wer(ref_text, synth_text)
        except Exception as e:
            logger.warning(f"ASR 转写失败, 跳过 WER: {e}")
            wer_val = None

    # 7. 综合相似度: 频谱相似度 0.6 + 时长 0.2 + (1-WER) 0.2 (如有 WER)
    if wer_val is not None:
        wer_score = max(0.0, 1.0 - wer_val)
        similarity = 0.6 * sim + 0.2 * duration_score + 0.2 * wer_score
    else:
        similarity = 0.75 * sim + 0.25 * duration_score

    # 8. 状态判定
    if similarity >= 0.75:
        status = "pass"
    elif similarity >= 0.5:
        status = "warn"
    else:
        status = "fail"

    details = {
        "ref_duration": round(ref_dur, 3),
        "syn_duration": round(syn_dur, 3),
        "ref_sample_rate": ref_sr,
        "syn_sample_rate": syn_sr,
        "spectral_similarity": round(sim, 4),
    }
    if snr is not None:
        details["snr_db"] = round(snr, 2)

    return QualityReport(
        similarity_score=similarity,
        wer=wer_val,
        snr=snr,
        duration_score=duration_score,
        status=status,
        reference_text=reference_text,
        synthesized_text=synth_text,
        details=details,
    )
