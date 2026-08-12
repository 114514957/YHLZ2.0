"""
YHLZ Embodied AI V5.7 - 经验抽取 (Experience Extractor)

职责:
    - 事件 → 分析 → 提取规律 → 生成经验 (规则驱动)
    - 从互动/执行结果抽取经验教训 (可解释)

抽取规则 (可解释):
    - 成功执行 → 成功经验 (lesson: 复用成功模式)
    - 失败执行 → 失败经验 (lesson: 避免失败原因)
    - 关系长期稳定 → 互动经验 (lesson: 维持稳定互动)
    - 改进建议 → 改进经验 (lesson: 采纳建议)

设计原则:
    - 纯规则抽取 (禁止黑盒学习)
    - 生成经验供查询/参考 (不替代决策)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.companion.experience.experience_record import (
    EXPERIENCE_TYPES,
    ExperienceError,
    ExperienceRecord,
)

logger = logging.getLogger(__name__)


class ExtractorError(Exception):
    """经验抽取操作异常"""


class ExperienceExtractor:
    """经验抽取器 (事件 → 经验)

    用法:
        extractor = ExperienceExtractor()
        record = extractor.extract(success=True, trigger="拾取台灯")
    """

    def __init__(self):
        self._lock = threading.RLock()

    # ── 从执行结果抽取 ────────────────────────────────────────────
    def extract(
        self,
        success: bool,
        trigger: str,
        source: str = "execution",
        action: str = "",
        result: str = "",
    ) -> ExperienceRecord:
        """从执行结果抽取经验 (规则驱动)

        Args:
            success: 执行是否成功
            trigger: 触发情境
            source: 来源
            action: 执行动作
            result: 执行结果

        Returns:
            ExperienceRecord (failure / improvement / interaction)
        """
        with self._lock:
            if success:
                return ExperienceRecord.create(
                    type="improvement",
                    trigger=trigger,
                    lesson=f"执行成功: {action or trigger} 的路径可复用",
                    source=source, action=action, result=result,
                    confidence=0.9, value=0.8,
                )
            return ExperienceRecord.create(
                type="failure",
                trigger=trigger,
                lesson=f"执行失败: {action or trigger} 需调整策略再试",
                source=source, action=action, result=result,
                confidence=0.8, value=0.7,
            )

    # ── 从关系状态抽取 ───────────────────────────────────────────
    def extract_from_relationship(
        self,
        trust_level: float,
        interaction_count: int,
    ) -> ExperienceRecord:
        """从关系状态抽取互动经验"""
        with self._lock:
            if trust_level >= 0.6 and interaction_count >= 20:
                return ExperienceRecord.create(
                    type="interaction",
                    trigger="长期稳定互动",
                    lesson=(
                        f"信任度 {trust_level:.2f} 且互动 {interaction_count} "
                        f"次: 维持稳定互动模式"
                    ),
                    source="relationship",
                    confidence=0.85, value=0.8,
                )
            return ExperienceRecord.create(
                type="interaction",
                trigger="互动观察",
                lesson=f"当前信任度 {trust_level:.2f}: 继续通过成功互动提升",
                source="relationship",
                confidence=0.6, value=0.4,
            )

    # ── 从决策结果抽取 ───────────────────────────────────────────
    def extract_from_decision(
        self,
        trigger: str,
        decision: str,
        outcome: str,
        success: bool,
    ) -> ExperienceRecord:
        """从决策结果抽取决策经验"""
        with self._lock:
            if success:
                lesson = f"决策 '{decision}' 有效 ({outcome}): 可复用"
                confidence, value = 0.85, 0.8
            else:
                lesson = f"决策 '{decision}' 无效 ({outcome}): 需调整"
                confidence, value = 0.8, 0.7
            return ExperienceRecord.create(
                type="decision",
                trigger=trigger,
                lesson=lesson,
                source="decision",
                action=decision,
                result=outcome,
                confidence=confidence, value=value,
            )

    # ── 手工经验 (工程经验) ──────────────────────────────────────
    def extract_engineering(
        self,
        trigger: str,
        lesson: str,
        result: str = "",
        confidence: float = 0.9,
    ) -> ExperienceRecord:
        """工程经验 (开发过程总结)"""
        with self._lock:
            return ExperienceRecord.create(
                type="engineering",
                trigger=trigger,
                lesson=lesson,
                source="engineering",
                result=result,
                confidence=confidence, value=0.85,
            )


__all__ = [
    "ExperienceExtractor",
    "ExtractorError",
]
