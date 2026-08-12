"""
YHLZ Token Optimization Layer V10.1.3 - Token 预算管理 (Token Budget)

职责:
    - 预算分区: Daily / Monthly / Emergency
    - 状态: GREEN / YELLOW / RED (消耗过高自动降级)
    - 消耗记录 (每日/每月)

设计原则:
    - 预算可解释 (rule/reason)
    - 成本控制规则: 消耗过高 → 降低模型等级/增加摘要/减少上下文
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BudgetError(Exception):
    """Token 预算异常"""


class TokenBudget:
    """Token 预算管理器 (V10.1.3)

    用法:
        tb = TokenBudget(daily_limit=100_000, monthly_limit=2_000_000,
                         emergency_limit=50_000)
        tb.spend(5000)
        state = tb.check()
    """

    def __init__(
        self,
        daily_limit: int = 100_000,
        monthly_limit: int = 2_000_000,
        emergency_limit: int = 50_000,
        enabled: bool = True,
    ):
        if daily_limit <= 0 or monthly_limit <= 0:
            raise BudgetError("预算必须 > 0")
        self._lock = threading.RLock()
        self._daily_limit = int(daily_limit)
        self._monthly_limit = int(monthly_limit)
        self._emergency_limit = int(emergency_limit)
        self._enabled = bool(enabled)
        self._used: List[Dict[str, Any]] = []

    def spend(self, tokens: int) -> Dict[str, Any]:
        """消耗 Token"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "Token 预算停用"}
            if tokens < 0:
                raise BudgetError(f"消耗不能为负: {tokens}")
            entry = {
                "timestamp": time.time(),
                "tokens": int(tokens),
            }
            self._used.append(entry)
            if len(self._used) > 10000:
                self._used = self._used[-10000:]
            return {
                "mode": "rule_based", "ok": True,
                "spent": int(tokens),
                "today": self._today_usage(),
                "month": self._month_usage(),
            }

    def _today_usage(self) -> int:
        """今日消耗"""
        day_start = time.time() - (time.time() % 86400)
        return sum(
            e["tokens"] for e in self._used
            if e["timestamp"] >= day_start
        )

    def _month_usage(self) -> int:
        """本月消耗"""
        month_start = time.time() - (
            (time.localtime().tm_mday - 1) * 86400
        ) - (time.time() % 86400)
        return sum(
            e["tokens"] for e in self._used
            if e["timestamp"] >= month_start
        )

    def check(self) -> Dict[str, Any]:
        """预算状态"""
        with self._lock:
            today = self._today_usage()
            month = self._month_usage()
            daily_ratio = today / self._daily_limit
            monthly_ratio = month / self._monthly_limit
            # 状态判定 (可解释)
            if daily_ratio >= 0.8 or monthly_ratio >= 0.8:
                level = "RED"
                suggestion = (
                    "消耗过高: 降低模型等级 / 增加摘要频率 / "
                    "减少上下文长度 / 启用应急预算"
                )
            elif daily_ratio >= 0.5 or monthly_ratio >= 0.5:
                level = "YELLOW"
                suggestion = "消耗偏高: 监控趋势, 考虑缓存/压缩"
            else:
                level = "GREEN"
                suggestion = "预算充足"
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "level": level,
                "daily_usage": today,
                "daily_limit": self._daily_limit,
                "daily_ratio": round(daily_ratio, 4),
                "monthly_usage": month,
                "monthly_limit": self._monthly_limit,
                "monthly_ratio": round(monthly_ratio, 4),
                "emergency_limit": self._emergency_limit,
                "suggestion": suggestion,
            }

    def stats(self) -> Dict[str, Any]:
        """统计"""
        return self.check()

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._used)
            self._used.clear()
            return n


__all__ = [
    "BudgetError",
    "TokenBudget",
]
