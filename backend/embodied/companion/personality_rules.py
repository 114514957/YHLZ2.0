"""
YHLZ Embodied AI V5.5 - 人格规则系统 (Personality Rules)

职责:
    - 情境 → 人格维度调整规则 (纯规则, 可解释)
    - 成功/连续失败/轻松交流等情境的维度调整

规则表 (可解释):
    - success           成功:       warmth +step, humor +step/2
    - consecutive_fail  连续失败:   patience +step*2, humor -step/2
    - casual_chat       轻松交流:   humor +step
    - serious_task      严肃任务:   serious +step, humor -step/2
    - failure           单次失败:   patience +step
    - reset             重置:       恢复基础维度

设计原则:
    - 纯规则 (禁止模型训练 / 黑盒人格优化)
    - 调整步长可配置 (companion_personality_adjust_step, 默认 0.1)
    - 维度范围限制 [0.0, 1.0]
    - 核心人格 (base) 不可修改
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class PersonalityRuleError(Exception):
    """人格规则操作异常"""


# 人格维度白名单
PERSONALITY_DIMENSIONS: List[str] = [
    "warmth",    # 热情
    "patience",  # 耐心
    "humor",     # 幽默
    "serious",   # 严肃
]

# 基础人格维度 (核心人格, 重置目标)
BASE_DIMENSIONS: Dict[str, float] = {
    "warmth": 0.8,
    "patience": 0.7,
    "humor": 0.6,
    "serious": 0.4,
}

# 情境 → 维度调整规则 (可解释)
# 格式: {情境: {维度: 步长倍数}}
PERSONALITY_RULES: Dict[str, Dict[str, float]] = {
    "success": {
        "warmth": 1.0,    # 成功 → 热情 +1.0*step
        "humor": 0.5,     # 成功 → 幽默 +0.5*step
    },
    "failure": {
        "patience": 1.0,  # 单次失败 → 耐心 +1.0*step
    },
    "consecutive_fail": {
        "patience": 2.0,  # 连续失败 → 耐心 +2.0*step
        "humor": -0.5,    # 连续失败 → 幽默 -0.5*step
    },
    "casual_chat": {
        "humor": 1.0,     # 轻松交流 → 幽默 +1.0*step
    },
    "serious_task": {
        "serious": 1.0,   # 严肃任务 → 严肃 +1.0*step
        "humor": -0.5,    # 严肃任务 → 幽默 -0.5*step
    },
}

# 情境白名单 (供校验)
PERSONALITY_CONTEXTS: List[str] = list(PERSONALITY_RULES.keys())


def rule_for(context: str) -> Dict[str, float]:
    """情境 → 调整规则 (可解释)

    Args:
        context: 情境 (success / failure / consecutive_fail /
                  casual_chat / serious_task)

    Returns:
        {维度: 步长倍数}

    Raises:
        PersonalityRuleError: 非法情境
    """
    if context not in PERSONALITY_RULES:
        raise PersonalityRuleError(
            f"非法情境: {context} (可选: {PERSONALITY_CONTEXTS})"
        )
    return dict(PERSONALITY_RULES[context])


def apply_adjustment(
    dimensions: Dict[str, float],
    context: str,
    step: float = 0.1,
) -> Dict[str, float]:
    """应用人格调整 (维度范围限制 [0.0, 1.0])

    Args:
        dimensions: 当前维度 (warmth/patience/humor/serious)
        context: 情境
        step: 调整步长 (companion_personality_adjust_step, 默认 0.1)

    Returns:
        调整后的维度 (新 dict, 不修改原对象)
    """
    if step <= 0:
        raise PersonalityRuleError(f"step 必须 > 0, 当前: {step}")
    rules = rule_for(context)
    updated = dict(dimensions)
    for dim, factor in rules.items():
        if dim not in PERSONALITY_DIMENSIONS:
            continue
        value = updated.get(dim, 0.0) + factor * step
        updated[dim] = round(max(0.0, min(1.0, value)), 4)
    return updated


def adjustment_reason(context: str, step: float = 0.1) -> str:
    """调整原因 (可解释)"""
    rules = rule_for(context)
    parts = []
    for dim, factor in rules.items():
        delta = factor * step
        direction = "提升" if delta >= 0 else "降低"
        parts.append(
            f"{dim} {direction} {abs(delta):.2f}"
        )
    return f"情境 [{context}]: " + ", ".join(parts)


__all__ = [
    "BASE_DIMENSIONS",
    "PERSONALITY_CONTEXTS",
    "PERSONALITY_DIMENSIONS",
    "PERSONALITY_RULES",
    "PersonalityRuleError",
    "adjustment_reason",
    "apply_adjustment",
    "rule_for",
]
