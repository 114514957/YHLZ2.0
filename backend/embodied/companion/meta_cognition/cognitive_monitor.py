"""
YHLZ Embodied AI V9.5 - 认知监控器 (Cognitive Monitor)

职责:
    - 记录认知过程: 任务 / 推理类型 / 置信度 / 不确定性 /
      使用资源
    - 为推理评价/错误检测提供输入

注意:
    - 元认知不是自我意识
    - 它是对推理过程的分析能力

设计原则:
    - 纯规则记录 (可解释)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MonitorError(Exception):
    """认知监控操作异常"""


# 推理类型 (可解释)
REASONING_TYPES: list = [
    "deductive",     # 演绎
    "inductive",     # 归纳
    "analogical",    # 类比
    "abductive",     # 溯因
    "rules",         # 规则
]


class CognitiveMonitor:
    """认知监控器 (过程记录)

    用法:
        monitor = CognitiveMonitor()
        entry = monitor.record("任务", "deductive",
                               confidence=0.8)
    """

    def __init__(self, enabled: bool = True,
                 max_records: int = 2000):
        if max_records <= 0:
            raise MonitorError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._records: list = []

    # ── 记录主入口 ───────────────────────────────────────────────
    def record(
        self,
        task: str,
        reasoning_type: str = "rules",
        confidence: float = 0.5,
        uncertainty: str = "",
        resources: Optional[List[str]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记录一次认知过程

        Args:
            task: 任务描述
            reasoning_type: 推理类型
            confidence: 置信度 (0~1)
            uncertainty: 不确定性说明
            resources: 使用资源

        Returns:
            监控记录
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "认知监控停用",
                }
            if reasoning_type not in REASONING_TYPES:
                raise MonitorError(
                    f"非法推理类型: {reasoning_type} "
                    f"(可选: {REASONING_TYPES})"
                )
            try:
                conf = float(confidence)
            except (TypeError, ValueError):
                conf = 0.5
            entry = {
                "monitor_id": "cm_" + uuid.uuid4().hex[:8],
                "task": str(task),
                "reasoning_type": reasoning_type,
                "confidence": round(min(
                    1.0, max(0.0, conf),
                ), 4),
                "uncertainty": str(uncertainty),
                "resources": list(resources or []),
                "timestamp": now,
            }
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return dict(entry)

    # ── 查询 ─────────────────────────────────────────────────────
    def records(self, limit: int = 100) -> list:
        """监控记录"""
        with self._lock:
            recent = list(reversed(self._records))
            if limit > 0:
                recent = recent[:limit]
            return [dict(r) for r in recent]

    def stats(self) -> Dict[str, Any]:
        """监控统计"""
        with self._lock:
            by_type: Dict[str, int] = {}
            for r in self._records:
                by_type[r["reasoning_type"]] = by_type.get(
                    r["reasoning_type"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "record_count": len(self._records),
                "by_reasoning_type": by_type,
                "avg_confidence": round(
                    sum(r["confidence"]
                        for r in self._records) /
                    len(self._records)
                    if self._records else 0.0, 4,
                ),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "CognitiveMonitor",
    "MonitorError",
    "REASONING_TYPES",
]
