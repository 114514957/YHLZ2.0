"""
YHLZ Voice Identity System V2.3-Phase5 - 自动质量门禁

职责:
    - 克隆完成后对参考音频 + Adapter 产物进行质量评分
    - 输出 QualityGateResult { score, status, report }
    - 状态规则:
        score >= 0.75 → READY    (可激活)
        0.5 <= score < 0.75 → WARNING (可使用但不推荐激活)
        score < 0.5 → REJECT  (禁止进入 active)

评分维度 (无合成音频时, 基于参考音频自身质量):
    - SNR (信噪比): >= 20dB 满分; < 5dB 零分
    - 时长: 5~30s 满分; < 3s 或 > 60s 扣分
    - 能量: RMS 0.1~0.7 满分; 过低/过高扣分
    - Adapter quality_score (若提供): 直接加权

设计原则:
    - 不阻塞克隆流程 (REJECT 仅标记, 不回滚 Profile)
    - 纯 stdlib + numpy, 无外部依赖
    - 评分透明: report 含各维度子分
    - 与 voice_quality_evaluator.py 互补:
        * evaluator 评估"合成音频 vs 参考音频"相似度 (事后)
        * quality_gate 评估"参考音频自身 + 克隆产物"质量 (事前门禁)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 门禁阈值
GATE_THRESHOLD_READY = 0.75
GATE_THRESHOLD_WARNING = 0.5

# 状态常量
STATUS_READY = "ready"
STATUS_WARNING = "warning"
STATUS_REJECT = "reject"


@dataclass
class QualityGateResult:
    """质量门禁结果

    字段:
        score:   综合评分 [0.0, 1.0]
        status:  ready / warning / reject
        report:  各维度子分详情
        reason:  状态判定原因 (人类可读)
    """
    score: float
    status: str
    report: Dict[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "status": self.status,
            "report": self.report,
            "reason": self.reason,
        }

    @property
    def is_reject(self) -> bool:
        return self.status == STATUS_REJECT

    @property
    def can_activate(self) -> bool:
        """是否允许进入 active (REJECT 禁止)"""
        return self.status != STATUS_REJECT


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _score_snr(snr_db: Optional[float]) -> float:
    """SNR 评分: >= 20dB → 1.0; < 5dB → 0.0; 线性插值"""
    if snr_db is None:
        return 0.5  # 未知, 中性分
    if snr_db >= 20:
        return 1.0
    if snr_db <= 5:
        return 0.0
    return _clamp((snr_db - 5) / 15)


def _score_duration(duration_s: Optional[float]) -> float:
    """时长评分: 5~30s 满分; < 3s 或 > 60s 扣分"""
    if duration_s is None:
        return 0.5
    if 5 <= duration_s <= 30:
        return 1.0
    if duration_s < 3:
        return _clamp(duration_s / 3)
    if duration_s > 60:
        return _clamp(1.0 - (duration_s - 60) / 60)
    # 3~5s 或 30~60s: 部分扣分
    if duration_s < 5:
        return 0.7 + 0.3 * (duration_s - 3) / 2
    return _clamp(1.0 - (duration_s - 30) / 60)


def _score_energy(mean_energy: Optional[float]) -> float:
    """能量评分: 0.1~0.7 满分; 过低/过高扣分"""
    if mean_energy is None:
        return 0.5
    if 0.1 <= mean_energy <= 0.7:
        return 1.0
    if mean_energy < 0.1:
        return _clamp(mean_energy / 0.1)
    # > 0.7 削波风险
    return _clamp(1.0 - (mean_energy - 0.7) / 0.3)


class QualityGate:
    """质量门禁评估器

    构造参数:
        ready_threshold:    READY 阈值 (默认 0.75)
        warning_threshold:  WARNING 阈值 (默认 0.5)
        weights:            各维度权重 (snr/duration/energy/adapter)
    """

    def __init__(
        self,
        ready_threshold: float = GATE_THRESHOLD_READY,
        warning_threshold: float = GATE_THRESHOLD_WARNING,
        weights: Optional[Dict[str, float]] = None,
    ):
        self._ready = ready_threshold
        self._warn = warning_threshold
        self._weights = weights or {
            "snr": 0.35,
            "duration": 0.20,
            "energy": 0.15,
            "adapter": 0.30,
        }

    def evaluate(
        self,
        feature=None,
        adapter_quality_score: Optional[float] = None,
        audio_info=None,
    ) -> QualityGateResult:
        """评估质量门禁

        参数:
            feature:                VoiceFeature (含 snr_db/mean_energy/audio_info)
            adapter_quality_score:  Adapter.prepare_voice 返回的质量分 (0~1)
            audio_info:             AudioInfo (含 duration_s); 缺省用 feature.audio_info

        返回:
            QualityGateResult
        """
        snr_db = None
        mean_energy = None
        duration_s = None
        if feature is not None:
            snr_db = feature.snr_db
            mean_energy = feature.mean_energy
            duration_s = feature.audio_info.duration_s if feature.audio_info else None
        if audio_info is not None and duration_s is None:
            duration_s = audio_info.duration_s

        snr_score = _score_snr(snr_db)
        dur_score = _score_duration(duration_s)
        eng_score = _score_energy(mean_energy)
        # Adapter 分: 若提供则用, 否则中性 0.5 (不奖惩)
        adp_score = adapter_quality_score if adapter_quality_score is not None else 0.5
        # 若 Adapter 未提供, 降低其权重 (避免中性分拉高总分)
        w = dict(self._weights)
        if adapter_quality_score is None:
            total_other = w["snr"] + w["duration"] + w["energy"]
            # 重新归一化: 移除 adapter 权重, 其他三项归一
            for k in ("snr", "duration", "energy"):
                w[k] = w[k] / total_other if total_other > 0 else 0
            w["adapter"] = 0.0
            adp_score = 0.0

        score = (
            w["snr"] * snr_score
            + w["duration"] * dur_score
            + w["energy"] * eng_score
            + w["adapter"] * adp_score
        )
        score = _clamp(score)

        if score >= self._ready:
            status = STATUS_READY
            reason = f"质量评分 {score:.3f} >= {self._ready} (READY)"
        elif score >= self._warn:
            status = STATUS_WARNING
            reason = f"质量评分 {score:.3f} 在 [{self._warn}, {self._ready}) (WARNING)"
        else:
            status = STATUS_REJECT
            reason = f"质量评分 {score:.3f} < {self._warn} (REJECT)"

        report = {
            "snr_score": round(snr_score, 4),
            "duration_score": round(dur_score, 4),
            "energy_score": round(eng_score, 4),
            "adapter_score": round(adp_score, 4),
            "weights": {k: round(v, 4) for k, v in w.items()},
            "snr_db": round(snr_db, 2) if snr_db is not None else None,
            "duration_s": round(duration_s, 3) if duration_s is not None else None,
            "mean_energy": round(mean_energy, 4) if mean_energy is not None else None,
            "adapter_quality_score": adapter_quality_score,
        }
        return QualityGateResult(score=score, status=status, report=report, reason=reason)


# ==================================================================
# 模块级单例
# ==================================================================

_gate: Optional[QualityGate] = None


def get_quality_gate() -> QualityGate:
    """获取全局 QualityGate 单例"""
    global _gate
    if _gate is None:
        _gate = QualityGate()
    return _gate


def reset_quality_gate() -> None:
    """重置全局单例 (测试用)"""
    global _gate
    _gate = None
