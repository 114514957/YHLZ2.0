"""
YHLZ Embodied AI V10.1 - 记忆稳定化审计 (Stabilization Audit)

职责:
    - 记录记忆稳定化全生命周期: 压缩 / 淘汰 / 冲突标记
    - 每条记录: timestamp / action / record_ids / reason / result
    - 支持查询 / 回放 / 统计

设计原则:
    - 热机可追踪铁律: 来源 / 原因 / 修改内容 / 验证结果 全程记录
    - 线程安全 (RLock)
    - 内存 deque + 可选落盘 (JSONL)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

# 稳定化动作类型 (可解释)
STABILIZE_ACTIONS: List[str] = [
    "compress",    # 压缩合并
    "prune",       # 淘汰
    "conflict",    # 冲突标记
    "evaluate",    # 权重评估
]


class StabilizationAuditError(Exception):
    """记忆稳定化审计异常"""


class StabilizationAudit:
    """记忆稳定化审计 (deque + 可选 JSONL)"""

    def __init__(self, max_records: int = 2000,
                 path: str = ""):
        if max_records <= 0:
            raise StabilizationAuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: Deque[Dict[str, Any]] = deque(
            maxlen=int(max_records),
        )
        self._max_records = int(max_records)
        self._path = path

    def record(
        self,
        action: str,
        record_ids: Optional[List[str]] = None,
        reason: str = "",
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录一条稳定化审计

        Args:
            action: 动作类型 (compress / prune / conflict / evaluate)
            record_ids: 涉及记录 ID 列表
            reason: 原因 (可解释)
            result: 结果 (合并来源 / 淘汰状态 / 冲突标记等)

        Returns:
            审计条目:
                {
                    "audit_id", "timestamp", "action",
                    "record_ids", "reason", "result",
                }
        """
        with self._lock:
            if action not in STABILIZE_ACTIONS:
                raise StabilizationAuditError(
                    f"非法动作类型: {action} "
                    f"(可选: {STABILIZE_ACTIONS})"
                )
            entry = {
                "audit_id": "stb_" + __import__("uuid").uuid4().hex[:8],
                "timestamp": time.time(),
                "action": action,
                "record_ids": list(record_ids or []),
                "reason": str(reason),
                "result": dict(result or {}),
            }
            self._records.append(entry)
            logger.info(
                f"[Stabilize] {action} records={entry['record_ids']} "
                f"reason={entry['reason']}"
            )
            return dict(entry)

    def query(
        self,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询审计 (最新在前, limit<=0 表示不限)"""
        with self._lock:
            records = list(self._records)
        out: List[Dict[str, Any]] = []
        for r in reversed(records):
            if action and r["action"] != action:
                continue
            out.append(dict(r))
            if 0 < limit <= len(out):
                break
        return out

    def replay(self, limit: int = 100) -> List[Dict[str, Any]]:
        """回放审计 (同 query)"""
        return self.query(limit=limit)

    def stats(self) -> Dict[str, Any]:
        """统计 (按动作类型分布)"""
        with self._lock:
            records = list(self._records)
        by_action: Dict[str, int] = {}
        for r in records:
            by_action[r["action"]] = by_action.get(
                r["action"], 0,
            ) + 1
        return {
            "mode": "rule_based",
            "enabled": True,
            "total": len(records),
            "by_action": by_action,
            "max_records": self._max_records,
        }

    def save_to_file(self, path: str) -> int:
        """保存审计到 JSONL"""
        with self._lock:
            records = list(self._records)
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        logger.info(
            f"[Stabilize] 审计已保存到 {path}, 共 {len(records)} 条"
        )
        return len(records)

    def clear(self) -> int:
        """清空审计"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "STABILIZE_ACTIONS",
    "StabilizationAudit",
    "StabilizationAuditError",
]
