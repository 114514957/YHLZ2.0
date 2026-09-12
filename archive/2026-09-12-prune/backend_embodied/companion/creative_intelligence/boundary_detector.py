"""
YHLZ Embodied AI V8.5 - 思维断口检测器 (Thought Boundary Detector)

职责:
    - 检测思维断口 (当前知识无法继续推进的位置)
    - 输出: Known Area → Unknown Boundary → Exploration Direction

原则 (未知不是错误):
    - 未知是探索入口
    - 禁止假装已知 (区分已知/未知)

设计原则:
    - 纯规则 (可解释)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BoundaryError(Exception):
    """思维断口操作异常"""


class ThoughtBoundaryDetector:
    """思维断口检测器 (已知 → 未知边界 → 探索方向)

    用法:
        detector = ThoughtBoundaryDetector(graph=graph)
        r = detector.detect(problem)
    """

    def __init__(self, graph=None, enabled: bool = True):
        self._lock = threading.RLock()
        self._graph = graph
        self._enabled = bool(enabled)
        self._detect_count = 0

    # ── 检测主入口 ───────────────────────────────────────────────
    def detect(
        self,
        problem: str,
        known_concepts: Optional[List[str]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """检测思维断口

        Args:
            problem: 当前问题
            known_concepts: 已知概念 (None → 从知识图)

        Returns:
            {
                'boundary_id', 'known_area', 'unknown_boundary',
                'exploration_direction', 'confidence', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "rule_based",
                    "boundary_id": "bd_" +
                    uuid.uuid4().hex[:8],
                    "known_area": [],
                    "unknown_boundary": [],
                    "exploration_direction": [],
                    "confidence": 0.0,
                    "reason": "边界检测停用",
                }
            known: List[str] = []
            if known_concepts:
                known = [str(c) for c in known_concepts]
            elif self._graph is not None:
                known = [
                    n["concept"]
                    for n in self._graph._nodes.values()
                ]
            # 1. Known Area (与问题相关的已知概念)
            problem_keywords = [
                kw for kw in known
                if kw and kw in str(problem)
            ]
            known_area = problem_keywords or known[:3]
            # 2. Unknown Boundary (未连接/缺失)
            unknown_boundary = []
            if self._graph is not None:
                for node in self._graph.unconnected(limit=5):
                    unknown_boundary.append({
                        "concept": node["concept"],
                        "reason": "无既有关系连接",
                    })
            # 3. Exploration Direction
            directions = []
            for u in unknown_boundary:
                directions.append(
                    f"探索 '{u['concept']}' 与问题 "
                    f"'{problem[:15]}' 的连接",
                )
            if not directions:
                directions.append(
                    f"已知区域 '{known_area[:2]}' 已覆盖, "
                    f"转向未知领域",
                )
            self._detect_count += 1
            return {
                "mode": "rule_based",
                "boundary_id": "bd_" + uuid.uuid4().hex[:8],
                "known_area": known_area,
                "unknown_boundary": unknown_boundary,
                "exploration_direction": directions,
                "confidence": round(
                    min(1.0, 0.4 + 0.1 * len(directions)),
                    4,
                ),
                "reason": (
                    f"已知 {len(known_area)} 项, "
                    f"未知边界 {len(unknown_boundary)} 项, "
                    f"探索方向 {len(directions)} 个"
                ),
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """边界检测统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "detect_count": self._detect_count,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._detect_count = 0
            return 0


__all__ = [
    "BoundaryError",
    "ThoughtBoundaryDetector",
]
