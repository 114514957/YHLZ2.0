"""
YHLZ Embodied AI V5.6 - 伙伴关系状态 (Relationship State)

职责:
    - 关系状态: AI 与用户关系 (trust/familiarity/communication_style/
      relationship_stage)
    - 关系更新: 根据互动更新 (成功→trust提升, 长期稳定→familiarity提升)
    - 人格-关系联动: 长期稳定互动 → trust → warmth稳定提升;
      连续失败 → patience提升 (规则驱动)

数据模型:
    {
        trust_level: 0.5,
        communication_style: "casual",
        interaction_count: 100,
        relationship_stage: "familiar",
    }

关系阶段 (可解释):
    stranger < 0.2 → acquaintance < 0.4 → familiar < 0.6
    → close < 0.8 → companion

设计原则:
    - 纯规则驱动 (禁止黑盒关系模型)
    - 联动只调整表现人格, 核心人格不变
    - 只存统计数字 (不保存聊天)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RelationshipError(Exception):
    """关系状态操作异常"""


# 关系阶段阈值 (可解释)
STAGE_THRESHOLDS: List[Dict[str, Any]] = [
    {"min": 0.0, "stage": "stranger"},
    {"min": 0.2, "stage": "acquaintance"},
    {"min": 0.4, "stage": "familiar"},
    {"min": 0.6, "stage": "close"},
    {"min": 0.8, "stage": "companion"},
]

# 沟通风格 (可解释)
COMMUNICATION_STYLES: List[str] = ["casual", "warm", "formal", "playful"]

# 关系更新规则 (可解释)
TRUST_STEP = 0.05       # 成功互动 → trust +0.05
FAMILIARITY_STEP = 0.02  # 长期稳定互动 → familiarity +0.02
TRUST_DECAY = 0.01      # 失败互动 → trust -0.01


class RelationshipState:
    """关系状态 (AI 与用户)

    Attributes:
        trust_level:        信任度 (0.0~1.0)
        familiarity:        熟悉度 (0.0~1.0)
        communication_style:沟通风格 (casual/warm/formal/playful)
        interaction_count:  互动次数
        consecutive_failures: 连续失败次数
        long_term_stable:   长期稳定互动标记
    """

    def __init__(
        self,
        trust_level: float = 0.5,
        familiarity: float = 0.3,
        communication_style: str = "casual",
    ):
        if not (0.0 <= trust_level <= 1.0):
            raise RelationshipError(
                f"trust_level 必须在 [0,1], 当前: {trust_level}"
            )
        if not (0.0 <= familiarity <= 1.0):
            raise RelationshipError(
                f"familiarity 必须在 [0,1], 当前: {familiarity}"
            )
        if communication_style not in COMMUNICATION_STYLES:
            raise RelationshipError(
                f"非法沟通风格: {communication_style} "
                f"(可选: {COMMUNICATION_STYLES})"
            )
        self.trust_level = round(float(trust_level), 4)
        self.familiarity = round(float(familiarity), 4)
        self.communication_style = communication_style
        self.interaction_count = 0
        self.consecutive_failures = 0
        self.long_term_stable = False
        self.last_update = time.time()

    @property
    def relationship_stage(self) -> str:
        """关系阶段 (基于信任度, 可解释)"""
        for t in STAGE_THRESHOLDS:
            if self.trust_level >= t["min"]:
                stage = t["stage"]
        return stage

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trust_level": self.trust_level,
            "familiarity": self.familiarity,
            "communication_style": self.communication_style,
            "interaction_count": self.interaction_count,
            "relationship_stage": self.relationship_stage,
            "consecutive_failures": self.consecutive_failures,
        }


class RelationshipManager:
    """关系管理器 (更新 + 人格联动)

    用法:
        mgr = RelationshipManager()
        result = mgr.update(success=True)
        rel = mgr.relationship()
        adj = mgr.personality_adjustment()
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._state = RelationshipState()

    # ── 关系更新 ──────────────────────────────────────────────────
    def update(self, success: bool) -> Dict[str, Any]:
        """根据互动更新关系 (规则驱动, 可解释)

        Args:
            success: 互动是否成功

        Returns:
            {
                'updated': bool, 'trust_level', 'familiarity',
                'relationship_stage', 'changes': [...], 'reason',
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "updated": False,
                    "trust_level": self._state.trust_level,
                    "familiarity": self._state.familiarity,
                    "relationship_stage": self._state.relationship_stage,
                    "changes": [], "reason": "关系系统已停用",
                }
            changes: List[str] = []
            self._state.interaction_count += 1
            if success:
                self._state.trust_level = min(
                    1.0, self._state.trust_level + TRUST_STEP,
                )
                changes.append(
                    f"成功互动: trust +{TRUST_STEP} "
                    f"→ {round(self._state.trust_level, 4)}"
                )
                self._state.consecutive_failures = 0
                # 长期稳定: 信任度 >= 0.6 且互动 >= 20 → 熟悉度提升
                if (self._state.trust_level >= 0.6
                        and self._state.interaction_count >= 20):
                    self._state.familiarity = min(
                        1.0, self._state.familiarity + FAMILIARITY_STEP,
                    )
                    self._state.long_term_stable = True
                    changes.append(
                        f"长期稳定互动: familiarity +{FAMILIARITY_STEP} "
                        f"→ {round(self._state.familiarity, 4)}"
                    )
            else:
                self._state.trust_level = max(
                    0.0, self._state.trust_level - TRUST_DECAY,
                )
                self._state.consecutive_failures += 1
                changes.append(
                    f"失败互动: trust -{TRUST_DECAY} "
                    f"→ {round(self._state.trust_level, 4)}"
                )
            self._state.last_update = time.time()
            return {
                "updated": True,
                "trust_level": self._state.trust_level,
                "familiarity": self._state.familiarity,
                "relationship_stage": self._state.relationship_stage,
                "changes": changes,
                "reason": "关系更新 (规则驱动)",
            }

    # ── 人格联动 (Task 4) ─────────────────────────────────────────
    def personality_adjustment(self) -> List[str]:
        """人格调整建议 (基于关系状态, 可解释)

        规则:
            - 长期稳定互动 → 建议 warmth 稳定提升
            - 连续失败 >= 2 → 建议 patience 提升

        Returns:
            建议列表 (情境字符串, 供人格引擎 adjust)
        """
        with self._lock:
            suggestions: List[str] = []
            if self._state.long_term_stable:
                suggestions.append(
                    "long_term_trust: 长期稳定互动, 建议 warmth 稳定提升"
                )
            if self._state.consecutive_failures >= 2:
                suggestions.append(
                    "consecutive_fail: 连续失败, 建议 patience 提升"
                )
            return suggestions

    # ── 查询 ──────────────────────────────────────────────────────
    def relationship(self) -> Dict[str, Any]:
        """关系状态"""
        with self._lock:
            return self._state.to_dict()

    def reset(self) -> None:
        """重置关系 (测试隔离)"""
        with self._lock:
            self._state = RelationshipState()

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "trust_step": TRUST_STEP,
                "familiarity_step": FAMILIARITY_STEP,
                "trust_decay": TRUST_DECAY,
            }


__all__ = [
    "COMMUNICATION_STYLES",
    "FAMILIARITY_STEP",
    "RelationshipError",
    "RelationshipManager",
    "RelationshipState",
    "STAGE_THRESHOLDS",
    "TRUST_STEP",
]
