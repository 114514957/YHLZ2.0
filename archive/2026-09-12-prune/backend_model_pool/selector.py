"""
YHLZ Model Pool Router V10.1.3 - 模型选择器 (Model Selector)

职责:
    - 依据任务类型/上下文/Token/成本/延迟 选择最佳模型
    - Token 状态: GREEN / YELLOW / RED
    - 自动切换触发: Token不足/API异常/模型不可用/延迟过高

选择优先级:
    1. 任务匹配度 (capability)
    2. 上下文能力 (token_limit)
    3. 剩余 Token
    4. 成本
    5. 响应速度

设计原则:
    - 规则可解释 (rule/reason)
    - 只选择不执行 (执行经外部)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ModelSelectorError(Exception):
    """模型选择器异常"""


# Token 状态 (可解释)
TOKEN_LEVELS: List[str] = [
    "GREEN",   # 正常
    "YELLOW",  # 预警
    "RED",     # 切换
]

# 默认阈值 (可解释, 百分比)
TOKEN_YELLOW_THRESHOLD: float = 0.3   # 剩余 < 30% → YELLOW
TOKEN_RED_THRESHOLD: float = 0.1      # 剩余 < 10% → RED


class ModelSelector:
    """模型选择器 (V10.1.3)

    用法:
        sel = ModelSelector()
        r = sel.select(registry_entries, task_type="CODING")
        level = sel.token_level(remaining, limit)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._select_count = 0

    def select(
        self,
        entries: List[Dict[str, Any]],
        task_type: str = "CHAT",
    ) -> Dict[str, Any]:
        """选择最佳模型

        Args:
            entries: 模型条目 dict 列表 (registry.list())
            task_type: 任务类型 (TASK_TYPES)

        Returns:
            {
                'mode', 'selected': {...} 或 None,
                'candidates': [...],
                'reason': 选择理由,
            }
        """
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "模型选择器停用"}
            available = [
                e for e in entries
                if e.get("status") == "active"
                and e.get("remaining_token", 0) > 0
            ]
            if not available:
                self._select_count += 1
                return {
                    "mode": "rule_based", "ok": False,
                    "selected": None,
                    "candidates": [],
                    "reason": "无可用模型 (全部停用或 Token 耗尽)",
                }
            scored = []
            for e in available:
                score = self._score(e, task_type)
                scored.append((score, e))
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score, best = scored[0]
            self._select_count += 1
            return {
                "mode": "rule_based", "ok": True,
                "selected": best,
                "candidates": [
                    {"model_id": e["model_id"], "score": round(s, 4)}
                    for s, e in scored
                ],
                "reason": (
                    f"任务 {task_type}: 选择 {best['model_id']} "
                    f"(score={round(best_score, 4)})"
                ),
            }

    def _score(
        self, entry: Dict[str, Any], task_type: str,
    ) -> float:
        """模型评分

        Model Score = Capability + Context + Cost + Availability
        """
        # 1. 能力匹配 (0~1): 任务类型 ∈ capability → 1.0
        caps = entry.get("capability", [])
        task_map = {
            "CHAT": "chat", "KNOWLEDGE": "chat",
            "CODING": "code", "ENGINEERING": "code",
            "REASONING": "reasoning", "VISION": "vision",
            "MEMORY": "memory", "SUMMARY": "summary",
        }
        need = task_map.get(task_type, "chat")
        capability = 1.0 if need in caps else 0.3

        # 2. 上下文能力 (token_limit, 归一化)
        limit = float(entry.get("token_limit", 1_000_000))
        context = min(limit / 1_000_000.0, 1.0)

        # 3. 剩余 Token (剩余率)
        remaining = float(entry.get("remaining_token", 0))
        availability_token = (
            remaining / limit if limit > 0 else 0.0
        )

        # 4. 成本 (越低越好, 归一化 0~1)
        cost = float(entry.get("cost_per_1k", 0.0))
        cost_score = 1.0 - min(cost / 0.1, 1.0)

        # 5. 延迟 (越低越好)
        latency = float(entry.get("latency_ms", 0.0))
        latency_score = 1.0 - min(latency / 3000.0, 1.0)

        return round(
            capability * 0.4
            + context * 0.15
            + availability_token * 0.15
            + cost_score * 0.15
            + latency_score * 0.15, 4,
        )

    @staticmethod
    def token_level(
        remaining: float, limit: float,
    ) -> str:
        """Token 状态 (GREEN/YELLOW/RED)"""
        if limit <= 0:
            return "GREEN"
        ratio = remaining / limit
        if ratio < TOKEN_RED_THRESHOLD:
            return "RED"
        if ratio < TOKEN_YELLOW_THRESHOLD:
            return "YELLOW"
        return "GREEN"

    @staticmethod
    def should_switch(
        entry: Dict[str, Any],
        error_count_threshold: int = 5,
        latency_threshold_ms: float = 5000.0,
    ) -> Dict[str, Any]:
        """是否应切换模型 (自动切换触发条件)"""
        reasons: List[str] = []
        remaining = float(entry.get("remaining_token", 0))
        limit = float(entry.get("token_limit", 1))
        if limit > 0 and remaining / limit < TOKEN_RED_THRESHOLD:
            reasons.append("Token 不足 (RED)")
        errors = int(entry.get("error_count", 0))
        if errors >= error_count_threshold:
            reasons.append(
                f"API 异常 (错误 {errors} 次 >= {error_count_threshold})"
            )
        if entry.get("status") == "disabled":
            reasons.append("模型不可用 (disabled)")
        latency = float(entry.get("latency_ms", 0.0))
        if latency >= latency_threshold_ms:
            reasons.append(
                f"延迟过高 ({latency}ms >= {latency_threshold_ms}ms)"
            )
        return {
            "switch": len(reasons) > 0,
            "reasons": reasons,
            "triggered": reasons,
        }

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "select_count": self._select_count,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = self._select_count
            self._select_count = 0
            return n


__all__ = [
    "TOKEN_LEVELS",
    "TOKEN_RED_THRESHOLD",
    "TOKEN_YELLOW_THRESHOLD",
    "ModelSelector",
    "ModelSelectorError",
]
