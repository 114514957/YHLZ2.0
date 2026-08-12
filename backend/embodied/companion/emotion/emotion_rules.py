"""
YHLZ Embodied AI V6.1.1 - 情绪规则表 (Emotion Rules)

职责:
    - 情境 → 维度变化规则 (规则驱动, 禁止 LLM 情绪推断)
    - 情境白名单:
      success / failure / consecutive_fail / creative_done /
      creative_rejected / relationship_up / relationship_down / idle

规则 (可解释):
    success:            positivity + / energy +
    failure:            positivity - / energy -
    consecutive_fail:   positivity - (幅度减半, 有限)
    creative_done:      positivity + / energy + / warmth +
    creative_rejected:  positivity - (幅度减半)
    relationship_up:    warmth + / positivity +
    relationship_down:  warmth -
    idle:               不产生事件影响 (衰减由 Decay 处理)

设计原则:
    - 纯规则表 (无黑盒)
    - 步长由配置驱动 (引擎注入)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RulesError(Exception):
    """情绪规则操作异常"""


# 情境白名单 (可解释)
EMOTION_CONTEXTS: List[str] = [
    "success",            # 任务成功
    "failure",            # 任务失败
    "consecutive_fail",   # 连续失败
    "creative_done",      # 创造完成
    "creative_rejected",  # 创造方案被拒
    "relationship_up",    # 关系提升
    "relationship_down",  # 关系下降
    "idle",               # 空闲 (无事件)
]

# 规则表: 情境 → 维度方向 (正值=上升, 负值=下降, 幅度系数) (可解释)
# 步长 = update_step * 幅度系数
EMOTION_RULES: Dict[str, Dict[str, Any]] = {
    "success": {
        "deltas": {"positivity": 1.0, "energy": 0.5, "warmth": 0.0},
        "reason": "任务成功: 积极与活跃上升",
    },
    "failure": {
        "deltas": {"positivity": -1.0, "energy": -0.5, "warmth": 0.0},
        "reason": "任务失败: 积极与活跃下降",
    },
    "consecutive_fail": {
        "deltas": {"positivity": -0.5, "energy": -0.25, "warmth": 0.0},
        "reason": "连续失败: 有限下降 (防无限跌落)",
    },
    "creative_done": {
        "deltas": {"positivity": 1.0, "energy": 0.5, "warmth": 0.3},
        "reason": "创造完成: 积极/活跃/关系温度上升",
    },
    "creative_rejected": {
        "deltas": {"positivity": -0.5, "energy": -0.25, "warmth": -0.1},
        "reason": "创造方案被拒: 有限下降",
    },
    "relationship_up": {
        "deltas": {"positivity": 0.3, "energy": 0.0, "warmth": 1.0},
        "reason": "关系提升: 关系温度上升",
    },
    "relationship_down": {
        "deltas": {"positivity": -0.3, "energy": 0.0, "warmth": -1.0},
        "reason": "关系下降: 关系温度下降",
    },
    "idle": {
        "deltas": {"positivity": 0.0, "energy": 0.0, "warmth": 0.0},
        "reason": "空闲: 无事件影响 (衰减由 Decay 处理)",
    },
}


def rule_for(context: str) -> Dict[str, Any]:
    """查询情境规则 (可解释)"""
    if context not in EMOTION_CONTEXTS:
        raise RulesError(
            f"非法情境: {context} (可选: {EMOTION_CONTEXTS})"
        )
    rule = EMOTION_RULES[context]
    return {
        "context": context,
        "deltas": dict(rule["deltas"]),
        "reason": rule["reason"],
    }


__all__ = [
    "EMOTION_CONTEXTS",
    "EMOTION_RULES",
    "RulesError",
    "rule_for",
]
