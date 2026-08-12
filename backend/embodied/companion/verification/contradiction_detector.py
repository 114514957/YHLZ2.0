"""
YHLZ Embodied AI V5.8 - 矛盾检测器 (Contradiction Detector)

职责:
    - 发现经验冲突 (经验A vs 经验B)
    - 冲突处理: 不简单覆盖 → 生成 Context-dependent Experience
      (场景相关经验)

示例:
    经验A: 用户喜欢简短回答
    经验B: 用户喜欢详细工程方案
    → 冲突: 按场景区分 (日常→简短, 工程→详细)

设计原则:
    - 纯规则检测 (可解释)
    - 冲突 → 场景化 (不覆盖)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContradictionError(Exception):
    """矛盾检测操作异常"""


class ContradictionDetector:
    """矛盾检测器 (经验冲突 → 场景化)

    用法:
        detector = ContradictionDetector()
        result = detector.check(lesson_a="用户喜欢简短回答",
                                lesson_b="用户喜欢详细工程方案",
                                context_a="日常聊天",
                                context_b="工程开发")
        merged = detector.merge_context(lesson_a, lesson_b,
                                        context_a, context_b)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._detections: List[Dict[str, Any]] = []

    # ── 矛盾检测 (关键词对立) ─────────────────────────────────────
    @staticmethod
    def _opposite_keywords() -> Dict[str, str]:
        """对立关键词表 (可解释)"""
        return {
            "简短": "详细",
            "快速": "缓慢",
            "少": "多",
            "避免": "偏好",
            "不要": "要",
            "拒绝": "接受",
            "short": "detailed",
        }

    def check(
        self,
        lesson_a: str,
        lesson_b: str,
        context_a: str = "",
        context_b: str = "",
    ) -> Dict[str, Any]:
        """检测两条经验是否矛盾

        Returns:
            {
                'conflict': bool,
                'opposites': [{'word_a', 'word_b'}, ...],
                'context_dependent': bool,
                'suggestion': str,
                'reason': str,
            }
        """
        with self._lock:
            opposites: List[Dict[str, str]] = []
            for wa, wb in self._opposite_keywords().items():
                if wa in lesson_a and wb in lesson_b:
                    opposites.append({"word_a": wa, "word_b": wb})
                elif wb in lesson_a and wa in lesson_b:
                    opposites.append({"word_a": wb, "word_b": wa})
            conflict = bool(opposites)
            context_dependent = conflict and bool(context_a) \
                and bool(context_b) and context_a != context_b
            result = {
                "conflict": conflict,
                "opposites": opposites,
                "context_dependent": context_dependent,
                "suggestion": (
                    self._build_suggestion(
                        lesson_a, lesson_b, context_a, context_b,
                        context_dependent,
                    )
                    if conflict else ""
                ),
                "reason": (
                    f"发现对立词: {opposites}" if conflict
                    else "无矛盾"
                ),
            }
            if conflict:
                self._detections.append({
                    "detection_id": "cd_" + uuid.uuid4().hex[:8],
                    "lesson_a": lesson_a,
                    "lesson_b": lesson_b,
                    "context_dependent": context_dependent,
                    "timestamp": time.time(),
                })
            return result

    @staticmethod
    def _build_suggestion(lesson_a: str, lesson_b: str,
                          context_a: str, context_b: str,
                          context_dependent: bool) -> str:
        """生成处理建议 (可解释)"""
        if context_dependent:
            return (
                f"经验矛盾但场景不同: '{lesson_a}' 适用于 [{context_a}], "
                f"'{lesson_b}' 适用于 [{context_b}]. "
                f"建议合并为场景相关经验 (Context-dependent)"
            )
        return (
            f"经验矛盾且场景相同: '{lesson_a}' vs '{lesson_b}'. "
            f"建议保留证据更多/置信度更高者, 其余标记 REJECTED"
        )

    # ── 场景化合并 (Context-dependent Experience) ────────────────
    @staticmethod
    def merge_context(
        lesson_a: str,
        lesson_b: str,
        context_a: str,
        context_b: str,
    ) -> Dict[str, Any]:
        """合并为场景相关经验 (不覆盖)"""
        return {
            "mode": "rule_based",
            "type": "context_dependent",
            "rules": [
                {"context": context_a, "lesson": lesson_a},
                {"context": context_b, "lesson": lesson_b},
            ],
            "reason": (
                f"场景 [{context_a}] → {lesson_a}; "
                f"场景 [{context_b}] → {lesson_b}"
            ),
        }

    # ── 统计 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """检测统计"""
        with self._lock:
            total = len(self._detections)
            context_dependent = sum(
                1 for d in self._detections if d["context_dependent"]
            )
            return {
                "mode": "rule_based",
                "total_detections": total,
                "context_dependent": context_dependent,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._detections)
            self._detections.clear()
            return n


__all__ = [
    "ContradictionDetector",
    "ContradictionError",
]
