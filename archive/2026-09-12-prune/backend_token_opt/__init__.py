"""
YHLZ Token Optimization Layer V10.1.3 - Token 优化门面 (Token Optimizer)

职责:
    - 统一入口: 压缩 / 缓存 / 预算 / 效率指标
    - Token 价值率: 每日Token消耗 / 有效任务数 / 解决问题数 /
      产生记忆数 / 用户评分
    - 优化目标: 同等效果减少 50%+ Token

流程:
    Input → Context Manager → Memory Retrieval → Compression Layer
    → Prompt Builder → Model → Response → Memory Update

设计原则:
    - 不是减少交流, 是减少无价值重复
    - 本地优先: 分类/检索/简单摘要不调 API
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.token_opt.budget import TokenBudget
from backend.token_opt.cache import ResponseCache
from backend.token_opt.compressor import ConversationCompressor

logger = logging.getLogger(__name__)


class TokenOptimizerError(Exception):
    """Token 优化器异常"""


class TokenOptimizer:
    """Token 优化器 (V10.1.3)

    用法:
        opt = TokenOptimizer()
        opt.record_task(done=True, solved=True, memory_added=1)
        eff = opt.efficiency()
    """

    def __init__(
        self,
        compressor: Optional[ConversationCompressor] = None,
        cache: Optional[ResponseCache] = None,
        budget: Optional[TokenBudget] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._compressor = compressor or ConversationCompressor()
        self._cache = cache or ResponseCache()
        self._budget = budget or TokenBudget()
        self._tasks: List[Dict[str, Any]] = []

    # ── 对话压缩 ────────────────────────────────────────────────
    def compress_conversation(
        self,
        text: str,
        key_points: Optional[List[str]] = None,
        decisions: Optional[List[str]] = None,
        open_questions: Optional[List[str]] = None,
        next_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """对话压缩 (不保存全部聊天)"""
        with self._lock:
            return self._compressor.compress(
                text, key_points, decisions,
                open_questions, next_steps,
            )

    # ── 响应缓存 ────────────────────────────────────────────────
    def cached_response(self, text: str) -> Optional[str]:
        """查询缓存"""
        return self._cache.get(text)

    def cache_response(self, text: str, response: str) -> Dict[str, Any]:
        """写入缓存"""
        with self._lock:
            return self._cache.put(text, response)

    # ── 预算 ────────────────────────────────────────────────────
    def spend_token(self, tokens: int) -> Dict[str, Any]:
        """消耗 Token (预算 + 效率记录)"""
        with self._lock:
            r = self._budget.spend(tokens)
            if r.get("ok"):
                self._tasks.append({
                    "timestamp": time.time(),
                    "tokens": int(tokens),
                    "done": False,
                    "solved": False,
                    "memory_added": 0,
                    "user_rating": 0,
                })
                if len(self._tasks) > 10000:
                    self._tasks = self._tasks[-10000:]
            return r

    def budget_status(self) -> Dict[str, Any]:
        """预算状态"""
        with self._lock:
            return self._budget.check()

    # ── 效率指标 ────────────────────────────────────────────────
    def record_task(
        self,
        done: bool = False,
        solved: bool = False,
        memory_added: int = 0,
        user_rating: int = 0,
    ) -> Dict[str, Any]:
        """记录任务结果 (对应最近一次消耗)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "Token 优化器停用"}
            if not self._tasks:
                return {"mode": "rule_based", "ok": True,
                        "recorded": False,
                        "reason": "无待记录消耗"}
            latest = self._tasks[-1]
            latest["done"] = bool(done)
            latest["solved"] = bool(solved)
            latest["memory_added"] = int(memory_added)
            latest["user_rating"] = int(user_rating)
            return {"mode": "rule_based", "ok": True,
                    "recorded": True}

    def efficiency(self) -> Dict[str, Any]:
        """Token 效率指标 (价值率)"""
        with self._lock:
            if not self._tasks:
                return {
                    "mode": "rule_based", "enabled": self._enabled,
                    "total_token": 0, "effective_tasks": 0,
                    "solved_tasks": 0, "memory_added": 0,
                    "token_value_rate": 0.0,
                    "cache_hit_rate": self._cache.stats()["hit_rate"],
                    "compression_saved": self._compressor.stats()[
                        "saved_ratio"],
                }
            total_token = sum(t["tokens"] for t in self._tasks)
            effective = sum(1 for t in self._tasks if t["done"])
            solved = sum(1 for t in self._tasks if t["solved"])
            memory = sum(t["memory_added"] for t in self._tasks)
            # Token 价值率 = 有效产出 / 消耗
            value = (effective * 10 + solved * 20 + memory * 5) / (
                total_token / 1000
            ) if total_token else 0.0
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "total_token": total_token,
                "effective_tasks": effective,
                "solved_tasks": solved,
                "memory_added": memory,
                "token_value_rate": round(value, 4),
                "cache_hit_rate": self._cache.stats()["hit_rate"],
                "compression_saved": self._compressor.stats()[
                    "saved_ratio"],
            }

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "compressor": self._compressor.stats(),
                "cache": self._cache.stats(),
                "budget": self._budget.stats(),
                "task_records": len(self._tasks),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._tasks)
            self._tasks.clear()
            n += self._compressor.clear()
            n += self._cache.clear()
            n += self._budget.clear()
            return n


__all__ = [
    "TokenOptimizer",
    "TokenOptimizerError",
]
