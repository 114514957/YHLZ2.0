"""
YHLZ Embodied AI V6.1.1 - 成长触发器 (Growth Trigger)

职责:
    - 自动成长触发条件判断:
      条件1: 经验数量达到阈值
      条件2: 距离上次整理超过 N 天
    - 输出触发原因 (可解释)

设计原则:
    - 纯规则 (无黑盒)
    - 阈值配置驱动 (禁止魔法数字)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TriggerError(Exception):
    """成长触发操作异常"""


# 触发条件白名单 (可解释)
TRIGGER_CONDITIONS: List[str] = [
    "experience_threshold",  # 经验数量达阈值
    "consolidation_days",    # 距上次整理超天数
]


class GrowthTrigger:
    """成长触发器 (阈值 + 天数)

    用法:
        trigger = GrowthTrigger(consolidate_threshold=20,
                                consolidate_days=7)
        reasons = trigger.check(experience_count=25,
                                last_consolidation_days=10)
    """

    def __init__(self, consolidate_threshold: int = 20,
                 consolidate_days: int = 7):
        if consolidate_threshold <= 0:
            raise TriggerError(
                f"consolidate_threshold 必须 > 0, 当前: "
                f"{consolidate_threshold}"
            )
        if consolidate_days <= 0:
            raise TriggerError(
                f"consolidate_days 必须 > 0, 当前: {consolidate_days}"
            )
        self._lock = threading.RLock()
        self._threshold = int(consolidate_threshold)
        self._days = int(consolidate_days)

    # ── 条件检查 ─────────────────────────────────────────────────
    def check(
        self,
        experience_count: int = 0,
        last_consolidation_days: float = 0.0,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """检查全部触发条件

        Args:
            experience_count: 当前经验数量
            last_consolidation_days: 距上次整理天数

        Returns:
            触发条件列表 [{condition, triggered, reason}]
        """
        with self._lock:
            results: List[Dict[str, Any]] = []
            # 条件1: 经验数量
            if experience_count >= self._threshold:
                results.append({
                    "condition": "experience_threshold",
                    "triggered": True,
                    "reason": (
                        f"经验数量 {experience_count} ≥ "
                        f"阈值 {self._threshold}"
                    ),
                })
            else:
                results.append({
                    "condition": "experience_threshold",
                    "triggered": False,
                    "reason": (
                        f"经验数量 {experience_count} < "
                        f"阈值 {self._threshold}"
                    ),
                })
            # 条件2: 整理天数
            if last_consolidation_days >= self._days:
                results.append({
                    "condition": "consolidation_days",
                    "triggered": True,
                    "reason": (
                        f"距上次整理 {last_consolidation_days:.1f} 天 "
                        f"≥ {self._days} 天"
                    ),
                })
            else:
                results.append({
                    "condition": "consolidation_days",
                    "triggered": False,
                    "reason": (
                        f"距上次整理 {last_consolidation_days:.1f} 天 "
                        f"< {self._days} 天"
                    ),
                })
            return results

    def should_run(self, experience_count: int = 0,
                   last_consolidation_days: float = 0.0) -> bool:
        """是否应触发整理 (任一条件满足)"""
        results = self.check(experience_count,
                             last_consolidation_days)
        return any(r["triggered"] for r in results)

    # ── 查询 ─────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        """当前阈值 (可解释)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "consolidate_threshold": self._threshold,
                "consolidate_days": self._days,
                "conditions": list(TRIGGER_CONDITIONS),
            }


__all__ = [
    "TRIGGER_CONDITIONS",
    "GrowthTrigger",
    "TriggerError",
]
