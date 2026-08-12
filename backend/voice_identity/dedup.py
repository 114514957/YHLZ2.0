"""
YHLZ Voice Identity System V2.2-Phase3.2 - 声音去重系统

职责:
    - 检测重复声音: 同音频/不同格式/相似声音/完全不同
    - 两级检测:
        1. 音频哈希 (文件内容 SHA256): 精确匹配同文件/同内容不同文件名
        2. 声学特征相似度 (F0 + 能量 + 语速 + SNR): 模糊匹配相似声音
    - 发现重复时返回已有 voice_id

架构层次:
    API (/voice/duplicate/check)
      ↓
    VoiceDeduplicator (本模块)
      ↓
    VoiceIdentityService.list_voice (读取已有 profile)
      ↓
    VoiceFeature 比对

去重规则:
    - audio_hash 完全匹配 → is_duplicate=True, confidence=1.0
    - 特征相似度 >= threshold (默认 0.85) → is_duplicate=True
    - 否则 → is_duplicate=False

设计原则:
    - 不引入新依赖 (stdlib hashlib + 现有 VoiceFeature)
    - 哈希基于文件内容 (非路径), 支持不同文件名同内容识别
    - 特征相似度用加权欧氏距离归一化 (F0 主导, 能量/语速/SNR 辅助)
    - 与克隆流程解耦: 可在 clone 前调用 check_duplicate 预检
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.voice_identity.clone.voice_analyzer import VoiceFeature
from backend.voice_identity.models import VoiceProfile

logger = logging.getLogger(__name__)

# 默认相似度阈值 (>= 此值视为重复)
DEFAULT_SIMILARITY_THRESHOLD: float = 0.85
# 哈希块大小 (64KB, 与 hashlib 文档推荐一致)
_HASH_CHUNK_SIZE: int = 64 * 1024


@dataclass(frozen=True)
class DuplicateResult:
    """去重检测结果

    字段:
        is_duplicate:  是否判定为重复
        confidence:    置信度 0.0~1.0 (1.0=哈希完全匹配)
        matched_voice_id: 匹配到的已有 voice_id (None 表示无匹配)
        matched_name:  匹配声音名称
        match_type:    匹配类型 (hash/feature/none)
        similarity:    最高特征相似度
        candidates:    候选匹配列表 (按相似度倒序)
        audio_hash:    输入音频的哈希
    """
    is_duplicate: bool
    confidence: float
    matched_voice_id: Optional[str] = None
    matched_name: Optional[str] = None
    match_type: str = "none"  # hash/feature/none
    similarity: float = 0.0
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    audio_hash: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "is_duplicate": self.is_duplicate,
            "confidence": round(self.confidence, 4),
            "matched_voice_id": self.matched_voice_id,
            "matched_name": self.matched_name,
            "match_type": self.match_type,
            "similarity": round(self.similarity, 4),
            "audio_hash": self.audio_hash,
            "candidates": self.candidates,
        }


# ==================================================================
# 音频哈希
# ==================================================================

def compute_audio_hash(audio_path: str) -> Optional[str]:
    """计算音频文件内容 SHA256 哈希

    参数:
        audio_path: 音频文件路径

    返回:
        SHA256 十六进制字符串; 文件不存在/读取失败返回 None
    """
    if not os.path.exists(audio_path):
        logger.warning(f"音频文件不存在, 无法计算哈希: {audio_path}")
        return None
    try:
        h = hashlib.sha256()
        with open(audio_path, "rb") as f:
            while True:
                chunk = f.read(_HASH_CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.warning(f"计算音频哈希失败: {audio_path}: {e}")
        return None


# ==================================================================
# 特征相似度
# ==================================================================

def compute_feature_similarity(feat_a: VoiceFeature, feat_b: VoiceFeature) -> float:
    """计算两个 VoiceFeature 的相似度 (0.0~1.0)

    加权维度:
        - F0 均值 (权重 0.4): 主频差异
        - 能量均值 (权重 0.25): 响度差异
        - 语速 (权重 0.2): 语速差异
        - SNR (权重 0.15): 录音质量差异

    缺失字段: 跳过该维度并重分配权重

    返回:
        相似度 0.0~1.0 (1.0=完全相同)
    """
    pairs: List[tuple] = []  # (diff, weight)
    # F0
    if feat_a.mean_f0 is not None and feat_b.mean_f0 is not None:
        f0_a, f0_b = feat_a.mean_f0, feat_b.mean_f0
        # F0 差异百分比 (相对较大值), 封顶 1.0
        denom = max(abs(f0_a), abs(f0_b), 1.0)
        diff = min(abs(f0_a - f0_b) / denom, 1.0)
        pairs.append((diff, 0.4))
    # 能量
    if feat_a.mean_energy is not None and feat_b.mean_energy is not None:
        diff = min(abs(feat_a.mean_energy - feat_b.mean_energy), 1.0)
        pairs.append((diff, 0.25))
    # 语速
    if feat_a.speech_rate is not None and feat_b.speech_rate is not None:
        sr_a, sr_b = feat_a.speech_rate, feat_b.speech_rate
        denom = max(abs(sr_a), abs(sr_b), 0.1)
        diff = min(abs(sr_a - sr_b) / denom, 1.0)
        pairs.append((diff, 0.2))
    # SNR
    if feat_a.snr_db is not None and feat_b.snr_db is not None:
        # SNR 差异 (dB, 20dB 差异视为完全不同)
        diff = min(abs(feat_a.snr_db - feat_b.snr_db) / 20.0, 1.0)
        pairs.append((diff, 0.15))

    if not pairs:
        # 无可比特征, 返回 0 (不判定为重复)
        return 0.0

    total_weight = sum(w for _, w in pairs)
    weighted_diff = sum(d * w for d, w in pairs) / total_weight
    return 1.0 - weighted_diff


# ==================================================================
# 去重器
# ==================================================================

class VoiceDeduplicator:
    """声音去重器

    构造参数:
        service: VoiceIdentityService (用于查询已有声音)
        threshold: 特征相似度阈值 (默认 0.85)
    """

    def __init__(self, service, threshold: float = DEFAULT_SIMILARITY_THRESHOLD):
        self._service = service
        self._threshold = threshold

    @property
    def threshold(self) -> float:
        return self._threshold

    def set_threshold(self, threshold: float) -> None:
        if 0.0 <= threshold <= 1.0:
            self._threshold = threshold

    # ------------------------------------------------------------------
    # 主检测入口
    # ------------------------------------------------------------------

    def check_duplicate(
        self,
        audio_path: str,
        feature: Optional[VoiceFeature] = None,
        skip_voice_ids: Optional[List[str]] = None,
    ) -> DuplicateResult:
        """检测音频是否与已有声音重复

        参数:
            audio_path: 待检测音频路径
            feature:    可选的 VoiceFeature (避免重复分析); None 时仅做哈希检测
            skip_voice_ids: 跳过这些 voice_id (如自身)

        返回:
            DuplicateResult

        流程:
            1. 计算输入音频哈希
            2. 遍历已有声音:
               a. 比对 reference_audio 哈希 (精确匹配)
               b. 比对 VoiceFeature 相似度 (模糊匹配)
            3. 取最高置信度作为结果
        """
        skip = set(skip_voice_ids or [])
        input_hash = compute_audio_hash(audio_path)

        # 获取已有声音列表
        try:
            profiles = self._service.list_voice()
        except Exception as e:
            logger.warning(f"查询已有声音失败, 跳过去重: {e}")
            return DuplicateResult(
                is_duplicate=False, confidence=0.0, audio_hash=input_hash,
            )

        candidates: List[Dict[str, Any]] = []
        best_hash_match: Optional[VoiceProfile] = None
        best_feature_match: Optional[VoiceProfile] = None
        best_similarity: float = 0.0

        for p in profiles:
            if p.voice_id in skip:
                continue
            if p.status == "deleted":
                continue

            # 1. 哈希匹配 (精确)
            hash_confidence = 0.0
            if input_hash is not None and p.reference_audio:
                existing_hash = compute_audio_hash(p.reference_audio)
                if existing_hash is not None and existing_hash == input_hash:
                    hash_confidence = 1.0
                    if best_hash_match is None:
                        best_hash_match = p

            # 2. 特征匹配 (模糊)
            feat_confidence = 0.0
            if feature is not None:
                existing_feat = self._extract_feature_from_profile(p)
                if existing_feat is not None:
                    feat_confidence = compute_feature_similarity(feature, existing_feat)
                    if feat_confidence > best_similarity:
                        best_similarity = feat_confidence
                        best_feature_match = p

            max_conf = max(hash_confidence, feat_confidence)
            if max_conf > 0:
                candidates.append({
                    "voice_id": p.voice_id,
                    "name": p.name,
                    "confidence": round(max_conf, 4),
                    "hash_match": hash_confidence == 1.0,
                    "feature_similarity": round(feat_confidence, 4),
                })

        # 候选按置信度倒序
        candidates.sort(key=lambda c: c["confidence"], reverse=True)

        # 判定结果
        if best_hash_match is not None:
            return DuplicateResult(
                is_duplicate=True,
                confidence=1.0,
                matched_voice_id=best_hash_match.voice_id,
                matched_name=best_hash_match.name,
                match_type="hash",
                similarity=best_similarity,
                candidates=candidates,
                audio_hash=input_hash,
            )
        if best_feature_match is not None and best_similarity >= self._threshold:
            return DuplicateResult(
                is_duplicate=True,
                confidence=best_similarity,
                matched_voice_id=best_feature_match.voice_id,
                matched_name=best_feature_match.name,
                match_type="feature",
                similarity=best_similarity,
                candidates=candidates,
                audio_hash=input_hash,
            )
        return DuplicateResult(
            is_duplicate=False,
            confidence=best_similarity,
            match_type="none",
            similarity=best_similarity,
            candidates=candidates,
            audio_hash=input_hash,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _extract_feature_from_profile(
        self, profile: VoiceProfile,
    ) -> Optional[VoiceFeature]:
        """从 VoiceProfile.style 重建 VoiceFeature (用于相似度比对)

        profile.style 存储了 mean_f0/mean_energy/speech_rate (由 Pipeline 写入)
        SNR 未持久化, 此处置为 None
        """
        from backend.voice_identity.clone.audio_validator import AudioInfo
        style = profile.style or {}
        if not style:
            return None
        mean_f0 = style.get("mean_f0")
        mean_energy = style.get("mean_energy")
        speech_rate = style.get("speech_rate")
        if mean_f0 is None and mean_energy is None and speech_rate is None:
            return None
        # 构造最小 AudioInfo 占位 (相似度计算不使用)
        audio_info = AudioInfo(
            path=profile.reference_audio or "",
            duration_s=0.0,
            sample_rate=16000,
            channels=1,
            frames=0,
            format="wav",
        )
        return VoiceFeature(
            audio_info=audio_info,
            mean_f0=mean_f0,
            f0_range=None,
            mean_energy=mean_energy,
            speech_rate=speech_rate,
            snr_db=None,
            embedding=None,
            extra={},
        )
