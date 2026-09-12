"""
YHLZ Embodied AI V6.0 - 记忆索引 (Memory Index)

职责:
    - 长期记忆体系的统一索引
    - 登记 / 更新 / 注销记忆条目
    - 按类型 / 阶段 / 价值查询
    - 记忆类型: identity / relationship / experience / reflection /
      creative

设计原则:
    - 索引只存元数据 (id/type/stage/value/importance)
    - 查询规则可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class IndexError(Exception):
    """记忆索引操作异常"""


# 记忆类型白名单 (可解释)
MEMORY_TYPES: List[str] = [
    "identity",       # 身份记忆
    "relationship",   # 关系记忆
    "experience",     # 经历记忆
    "reflection",     # 反思记忆
    "creative",       # 创造记忆
]

# 记忆阶段白名单 (可解释)
MEMORY_STAGES: List[str] = [
    "active",     # 活跃
    "cold",       # 冷数据
    "archive",    # 归档
    "recycle",    # 回收
]


class MemoryIndex:
    """记忆索引器

    用法:
        idx = MemoryIndex()
        idx.register("exp_1", "experience", stage="active",
                     value=0.8, importance=1.2)
        hits = idx.query(type="experience", stage="active")
    """

    def __init__(self, max_entries: int = 10000):
        if max_entries <= 0:
            raise IndexError(
                f"max_entries 必须 > 0, 当前: {max_entries}"
            )
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._max = int(max_entries)

    # ── 登记 ─────────────────────────────────────────────────────
    def register(
        self, record_id: str, mtype: str,
        stage: str = "active",
        value: float = 0.0,
        importance: float = 0.0,
        timestamp: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """登记记忆条目"""
        with self._lock:
            if not record_id:
                raise IndexError("记录 ID 不能为空")
            if mtype not in MEMORY_TYPES:
                raise IndexError(
                    f"非法记忆类型: {mtype} "
                    f"(可选: {MEMORY_TYPES})"
                )
            if stage not in MEMORY_STAGES:
                raise IndexError(
                    f"非法记忆阶段: {stage} "
                    f"(可选: {MEMORY_STAGES})"
                )
            if not (0.0 <= value <= 1.0):
                raise IndexError(
                    f"value 必须在 [0,1], 当前: {value}"
                )
            if record_id not in self._entries and \
                    len(self._entries) >= self._max:
                raise IndexError("索引条目已达上限")
            entry = {
                "record_id": record_id,
                "type": mtype,
                "stage": stage,
                "value": round(float(value), 4),
                "importance": round(float(importance), 4),
                "timestamp": timestamp if timestamp is not None
                else time.time(),
                "meta": dict(meta or {}),
            }
            self._entries[record_id] = entry
            return dict(entry)

    # ── 更新 ─────────────────────────────────────────────────────
    def update(self, record_id: str,
               stage: Optional[str] = None,
               value: Optional[float] = None,
               importance: Optional[float] = None) -> Optional[Dict]:
        """更新条目 (可空字段)"""
        with self._lock:
            entry = self._entries.get(record_id)
            if entry is None:
                return None
            if stage is not None:
                if stage not in MEMORY_STAGES:
                    raise IndexError(
                        f"非法记忆阶段: {stage} "
                        f"(可选: {MEMORY_STAGES})"
                    )
                entry["stage"] = stage
            if value is not None:
                if not (0.0 <= value <= 1.0):
                    raise IndexError(
                        f"value 必须在 [0,1], 当前: {value}"
                    )
                entry["value"] = round(float(value), 4)
            if importance is not None:
                entry["importance"] = round(float(importance), 4)
            return dict(entry)

    # ── 注销 ─────────────────────────────────────────────────────
    def unregister(self, record_id: str) -> bool:
        """注销条目 (回收时)"""
        with self._lock:
            return self._entries.pop(record_id, None) is not None

    # ── 查询 ─────────────────────────────────────────────────────
    def get(self, record_id: str) -> Optional[Dict[str, Any]]:
        """查询条目"""
        with self._lock:
            e = self._entries.get(record_id)
            return dict(e) if e else None

    def query(
        self,
        mtype: Optional[str] = None,
        stage: Optional[str] = None,
        value_min: Optional[float] = None,
        importance_min: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """组合查询 (全部条件取交集)"""
        with self._lock:
            hits = []
            for e in self._entries.values():
                if mtype and e["type"] != mtype:
                    continue
                if stage and e["stage"] != stage:
                    continue
                if value_min is not None and e["value"] < value_min:
                    continue
                if importance_min is not None and \
                        e["importance"] < importance_min:
                    continue
                hits.append(dict(e))
            hits.sort(key=lambda e: (e["importance"], e["value"]),
                      reverse=True)
            return hits[:limit]

    def stats(self) -> Dict[str, Any]:
        """索引统计"""
        with self._lock:
            entries = list(self._entries.values())
        by_type: Dict[str, int] = {}
        by_stage: Dict[str, int] = {}
        for e in entries:
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1
            by_stage[e["stage"]] = by_stage.get(e["stage"], 0) + 1
        return {
            "mode": "rule_based",
            "total": len(entries),
            "by_type": by_type,
            "by_stage": by_stage,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n


__all__ = [
    "MEMORY_STAGES",
    "MEMORY_TYPES",
    "IndexError",
    "MemoryIndex",
]
