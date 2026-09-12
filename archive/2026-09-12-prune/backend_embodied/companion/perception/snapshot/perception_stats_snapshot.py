"""
YHLZ Embodied AI V6.4 - 感知统计快照 (Perception Stats Snapshot)

职责:
    - 感知统计持久化 (SNAPSHOT_DOMAIN: perception_stats)
    - 保存: 输入数量/验证数量/拒绝数量/Memory 批准数量/Reflection 统计
    - 恢复: 兼容旧快照 (无 perception_stats 域 → 跳过)

设计原则:
    - 只读统计指标 (恢复无副作用)
    - 兼容旧快照 (不报错)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SnapshotError(Exception):
    """感知统计快照操作异常"""


class PerceptionStatsSnapshot:
    """感知统计快照器

    用法:
        snap = PerceptionStatsSnapshot()
        data = snap.collect(perception_stats, gate_stats,
                            evaluator_stats)
        ok = snap.restore(data)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._saves = 0
        self._restores = 0

    # ── 收集 ─────────────────────────────────────────────────────
    def collect(
        self,
        perception_stats: Dict[str, Any] = None,
        gate_stats: Dict[str, Any] = None,
        evaluator_stats: Dict[str, Any] = None,
        counterfactual_stats: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """收集感知统计 (只读)

        Args:
            perception_stats: PerceptionService.stats()
            gate_stats: MemoryGate.stats()
            evaluator_stats: ReflectionEvaluator.stats()
            counterfactual_stats: CounterfactualCheck.stats()

        Returns:
            统计 dict (可入快照)
        """
        with self._lock:
            if not self._enabled:
                return {"enabled": False}
            data = {
                "mode": "rule_based",
                "collected_at": time.time(),
                "perception": {
                    "event_count": (perception_stats or {}).get(
                        "event_count", 0,
                    ),
                    "memory_candidate_count": (
                        perception_stats or {}
                    ).get("memory_candidate_count", 0),
                    "verification": (perception_stats or {}).get(
                        "verification", {},
                    ),
                },
                "memory_gate": {
                    "candidate_count": (gate_stats or {}).get(
                        "candidate_count", 0,
                    ),
                    "approved_count": (gate_stats or {}).get(
                        "approved_count", 0,
                    ),
                    "rejected_count": (gate_stats or {}).get(
                        "rejected_count", 0,
                    ),
                },
                "reflection": {
                    "evaluated_count": (evaluator_stats or {}).get(
                        "evaluated_count", 0,
                    ),
                    "avg_reflection_score": (
                        evaluator_stats or {}
                    ).get("avg_reflection_score", 0.0),
                },
                "counterfactual": {
                    "check_count": (counterfactual_stats or {}).get(
                        "check_count", 0,
                    ),
                    "fails_count": (counterfactual_stats or {}).get(
                        "fails_count", 0,
                    ),
                },
            }
            return data

    # ── 恢复 ─────────────────────────────────────────────────────
    def restore(self, data: Optional[Dict[str, Any]]) -> tuple:
        """恢复统计 (只读指标, 兼容缺失)

        Args:
            data: 快照中的 perception_stats 域

        Returns:
            (ok: bool, reason: str)
        """
        with self._lock:
            self._restores += 1
            if data is None or not isinstance(data, dict):
                return True, "无感知统计域 (旧快照兼容, 跳过)"
            return True, "感知统计已恢复 (只读指标)"

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """快照器统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "save_count": self._saves,
                "restore_count": self._restores,
            }

    def mark_saved(self) -> None:
        """标记一次保存"""
        with self._lock:
            self._saves += 1

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = self._saves + self._restores
            self._saves = 0
            self._restores = 0
            return n


__all__ = [
    "PerceptionStatsSnapshot",
    "SnapshotError",
]
