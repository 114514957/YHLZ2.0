"""
YHLZ Token Optimization Layer V10.1.3 - 响应缓存 (Response Cache)

职责:
    - 缓存固定知识/项目说明/常见回答/重复任务
    - 减少重复 API 调用 (Token 节省)
    - 命中率统计

设计原则:
    - 缓存键: 输入哈希 (规则可解释)
    - 缓存有界 (LRU 淘汰)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CacheError(Exception):
    """响应缓存异常"""


class ResponseCache:
    """响应缓存 (V10.1.3)

    用法:
        rc = ResponseCache(max_entries=500)
        rc.put("问题", "回答")
        hit = rc.get("问题")  # 命中返回回答, 未命中 None
    """

    def __init__(self, max_entries: int = 500,
                 enabled: bool = True):
        if max_entries <= 0:
            raise CacheError(
                f"max_entries 必须 > 0, 当前: {max_entries}"
            )
        self._lock = threading.RLock()
        self._max_entries = int(max_entries)
        self._enabled = bool(enabled)
        self._cache: Dict[str, Tuple[str, float]] = {}
        self._hit_count = 0
        self._miss_count = 0

    @staticmethod
    def _key(text: str) -> str:
        """缓存键 (SHA-256)"""
        return hashlib.sha256(
            str(text).encode("utf-8"),
        ).hexdigest()[:24]

    def put(self, text: str, response: str) -> Dict[str, Any]:
        """写入缓存"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "响应缓存停用"}
            key = self._key(text)
            self._cache[key] = (str(response), time.time())
            if len(self._cache) > self._max_entries:
                # LRU 淘汰最旧
                oldest = min(
                    self._cache, key=lambda k: self._cache[k][1],
                )
                self._cache.pop(oldest, None)
            return {"mode": "rule_based", "ok": True,
                    "cached": True, "key": key}

    def get(self, text: str) -> Optional[str]:
        """查询缓存 (命中返回回答, 未命中 None)"""
        with self._lock:
            if not self._enabled:
                return None
            key = self._key(text)
            entry = self._cache.get(key)
            if entry is None:
                self._miss_count += 1
                return None
            self._hit_count += 1
            # LRU 更新
            self._cache[key] = (entry[0], time.time())
            return entry[0]

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            total = self._hit_count + self._miss_count
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "entries": len(self._cache),
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "hit_rate": round(
                    self._hit_count / total, 4,
                ) if total else 0.0,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._cache)
            self._cache.clear()
            self._hit_count = 0
            self._miss_count = 0
            return n


__all__ = [
    "CacheError",
    "ResponseCache",
]
