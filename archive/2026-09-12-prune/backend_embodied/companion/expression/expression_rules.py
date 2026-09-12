"""
YHLZ Embodied AI V6.2 - 表达规则表 (Expression Rules)

职责:
    - 表达风格规则: Emotion/Relationship/Task Context → 表达建议
    - 规则驱动 (禁止黑盒情绪生成)

规则 (可解释):
    - positivity ≥ threshold        → more_positive_expression
    - energy < threshold            → reduce_expression_intensity
    - warmth ≥ threshold            → increase_personal_style
    - relationship trust ≥ threshold→ friendlier_style
    - task failure 上下文           → patient_style

设计原则:
    - 纯规则 (无黑盒)
    - 每条规则含 reason
    - 规则可组合 (多条件命中合并)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RulesError(Exception):
    """表达规则操作异常"""


# 表达风格白名单 (可解释)
EXPRESSION_STYLES: List[str] = [
    "more_positive",          # 更积极
    "reduce_intensity",       # 降低强度
    "personal",               # 更个人化
    "friendly",               # 更友好
    "patient",                # 更耐心
    "neutral",                # 中性 (基线)
]

# 语气白名单 (可解释)
EXPRESSION_TONES: List[str] = [
    "warm",     # 温暖
    "calm",     # 平静
    "cheerful", # 愉快
    "gentle",   # 温和
    "neutral",  # 中性
]

# 规则表 (可解释)
EXPRESSION_RULES: Dict[str, Dict[str, Any]] = {
    "high_positivity": {
        "condition": "positivity >= threshold",
        "style": "more_positive",
        "tone": "cheerful",
        "reason": "高积极状态 → 更积极的表达",
    },
    "low_energy": {
        "condition": "energy < threshold",
        "style": "reduce_intensity",
        "tone": "calm",
        "reason": "低能量状态 → 降低表达强度",
    },
    "high_warmth": {
        "condition": "warmth >= threshold",
        "style": "personal",
        "tone": "warm",
        "reason": "高关系温度 → 增加个人化风格",
    },
    "high_trust": {
        "condition": "relationship.trust >= threshold",
        "style": "friendly",
        "tone": "warm",
        "reason": "高信任关系 → 更友好风格",
    },
    "task_failure": {
        "condition": "task.result == failure",
        "style": "patient",
        "tone": "gentle",
        "reason": "任务失败 → 更耐心表达",
    },
}


class ExpressionRules:
    """表达规则器 (规则查询/命中)

    用法:
        rules = ExpressionRules(threshold=0.7)
        hits = rules.match(context)
    """

    def __init__(self, threshold: float = 0.7):
        if not (0.0 <= threshold <= 1.0):
            raise RulesError(
                f"threshold 必须在 [0,1], 当前: {threshold}"
            )
        self._threshold = float(threshold)

    # ── 命中 ─────────────────────────────────────────────────────
    def match(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """按上下文命中规则 (可解释)

        Args:
            context: 表达上下文 (emotion/relationship/task)

        Returns:
            命中规则列表 [{rule, style, tone, reason}]
        """
        emotion = context.get("emotion", {}) or {}
        relationship = context.get("relationship", {}) or {}
        task = context.get("task", {}) or {}
        hits: List[Dict[str, Any]] = []
        # 1. 高积极 (仅在提供 positivity 时判断)
        if "positivity" in emotion:
            positivity = float(emotion.get("positivity", 0.0))
            if positivity >= self._threshold:
                hits.append(self._hit("high_positivity"))
        # 2. 低能量 (仅在提供 energy 时判断)
        if "energy" in emotion:
            energy = float(emotion.get("energy", 0.5))
            if energy < self._threshold:
                hits.append(self._hit("low_energy"))
        # 3. 高关系温度 (仅在提供 warmth 时判断)
        if "warmth" in emotion:
            warmth = float(emotion.get("warmth", 0.0))
            if warmth >= self._threshold:
                hits.append(self._hit("high_warmth"))
        # 4. 高信任 (仅在提供 trust 时判断)
        if "trust" in relationship:
            trust = float(relationship.get("trust", 0.0))
            if trust >= self._threshold:
                hits.append(self._hit("high_trust"))
        # 5. 任务失败
        if str(task.get("result", "")).find("failure") >= 0 or \
                task.get("status") == "failure":
            hits.append(self._hit("task_failure"))
        return hits

    def _hit(self, rule_name: str) -> Dict[str, Any]:
        """构造命中条目"""
        rule = EXPRESSION_RULES[rule_name]
        return {
            "rule": rule_name,
            "style": rule["style"],
            "tone": rule["tone"],
            "reason": rule["reason"],
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def threshold(self) -> float:
        """当前阈值"""
        return self._threshold

    def rules(self) -> Dict[str, Any]:
        """规则表快照"""
        return {
            "mode": "rule_based",
            "threshold": self._threshold,
            "rules": {
                k: dict(v) for k, v in EXPRESSION_RULES.items()
            },
        }


__all__ = [
    "EXPRESSION_RULES",
    "EXPRESSION_STYLES",
    "EXPRESSION_TONES",
    "ExpressionRules",
    "RulesError",
]
