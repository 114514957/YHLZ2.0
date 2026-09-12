"""
YHLZ Embodied AI V6.0 - 记忆整合 (Memory Consolidation)

职责:
    - 经验/记忆生命周期:
      Active → Cold → Archive → Recycle
    - 规则 (可解释):
        Active:   近期 + 参与 Reflection/Creation
        Cold:     超期低访问 (保留查询)
        Archive:  高价值低频 (压缩保存)
        Recycle:  低价值长期无用 (删除并记录审计, 高价值禁止)

设计原则:
    - 高价值记忆 (importance protected) 禁止自动回收
    - 归档为摘要压缩 (保留核心信息)
    - 回收必须审计
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.embodied.companion.memory.memory_index import (
    MEMORY_STAGES,
    MemoryIndex,
)

logger = logging.getLogger(__name__)


class ConsolidationError(Exception):
    """记忆整合操作异常"""


# 生命周期转移 (可解释)
CONSOLIDATION_TRANSITIONS: Dict[str, List[str]] = {
    "active": ["cold", "archive"],
    "cold": ["active", "archive", "recycle"],
    "archive": ["active", "recycle"],
    "recycle": [],
}


class MemoryConsolidation:
    """记忆整合器 (生命周期管理)

    用法:
        cons = MemoryConsolidation(archive_days=30,
                                   recycle_value=0.3)
        report = cons.consolidate(records, importance_scores)
    """

    def __init__(
        self,
        archive_days: int = 30,
        recycle_value: float = 0.3,
        archive_keep_value: float = 0.7,
        index: Optional[MemoryIndex] = None,
    ):
        if archive_days <= 0:
            raise ConsolidationError(
                f"archive_days 必须 > 0, 当前: {archive_days}"
            )
        if not (0.0 <= recycle_value <= 1.0):
            raise ConsolidationError(
                f"recycle_value 必须在 [0,1], 当前: {recycle_value}"
            )
        self._lock = threading.RLock()
        self._archive_days = int(archive_days)
        self._recycle_value = float(recycle_value)
        self._keep_value = float(archive_keep_value)
        self._index = index or MemoryIndex()
        self._changes: List[Dict[str, Any]] = []

    # ── 整理主入口 ───────────────────────────────────────────────
    def consolidate(
        self,
        records: List[Dict[str, Any]],
        importance: Optional[Dict[str, Dict[str, Any]]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记忆整理: 分类 + 转移 + 回收

        Args:
            records: 记忆记录列表 (id/trigger/value/timestamp/...)
            importance: record_id → importance 评分结果
                (受保护记忆禁止回收)
            now: 当前时间

        Returns:
            {
                'consolidation_id', 'stages': {...},
                'transitions': [...], 'recycled': [...],
                'archived': [...], 'skipped': [...], 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            importance = importance or {}
            stages: Dict[str, List[str]] = {
                s: [] for s in MEMORY_STAGES
            }
            transitions: List[Dict[str, Any]] = []
            recycled: List[str] = []
            archived: List[str] = []
            skipped: List[str] = []
            for rec in records:
                rid = rec.get("id", "")
                if not rid:
                    skipped.append(rid)
                    continue
                imp = importance.get(rid, {})
                protected = bool(imp.get("protected"))
                value = float(rec.get("value", 0.0))
                target = self._assess(rec, value, protected, now)
                current = self._index.get(rid)
                prev_stage = current["stage"] if current else None
                self._index.register(
                    rid,
                    self._type_for(rec),
                    stage=target,
                    value=value,
                    importance=float(imp.get("importance_score", 0.0)),
                    timestamp=float(rec.get("timestamp", time.time())),
                )
                stages[target].append(rid)
                if prev_stage and prev_stage != target:
                    transitions.append({
                        "record_id": rid, "from": prev_stage,
                        "to": target,
                        "reason": self._transition_reason(
                            rec, target, protected, value,
                        ),
                    })
                # 归档: 压缩保存摘要
                if target == "archive" and prev_stage != "archive":
                    archived.append(rid)
                # 回收: 删除并记录
                if target == "recycle":
                    if protected:
                        # 受保护: 强制留在 archive
                        self._index.update(rid, stage="archive")
                        skipped.append(rid)
                        stages["recycle"].remove(rid)
                        stages["archive"].append(rid)
                        continue
                    self._index.unregister(rid)
                    recycled.append(rid)
            result = {
                "consolidation_id": "cons_" +
                __import__("uuid").uuid4().hex[:8],
                "stages": stages,
                "transitions": transitions,
                "recycled": recycled,
                "archived": archived,
                "skipped": skipped,
                "mode": "rule_based",
                "consolidated_at": now,
            }
            self._changes.append(result)
            return dict(result)

    # ── 阶段判定 (可解释) ───────────────────────────────────────
    def _assess(
        self, rec: Dict[str, Any], value: float,
        protected: bool, now: float,
    ) -> str:
        """判定目标阶段"""
        age_days = (now - float(rec.get("timestamp", now))) / 86400.0
        if protected or value >= self._keep_value:
            # 高价值: 近期活跃, 超期归档
            if age_days > self._archive_days:
                return "archive"
            return "active"
        # 中低价值
        if age_days > self._archive_days * 2:
            return "recycle" if value < self._recycle_value \
                else "cold"
        if age_days > self._archive_days:
            return "cold"
        return "active"

    @staticmethod
    def _transition_reason(
        rec: Dict[str, Any], target: str, protected: bool,
        value: float,
    ) -> str:
        """转移原因 (可解释)"""
        if target == "archive":
            return "高价值低频 → 归档压缩保存"
        if target == "recycle":
            return f"低价值长期无用 (value={value}) → 回收"
        if target == "cold":
            return "超期低访问 → 冷数据 (保留查询)"
        return "重新活跃"

    @staticmethod
    def _type_for(rec: Dict[str, Any]) -> str:
        """记录类型 → 记忆类型"""
        source = str(rec.get("source", ""))
        rtype = str(rec.get("type", ""))
        if "creative" in source or rtype == "creative":
            return "creative"
        if rtype in ("reflection",):
            return "reflection"
        if rtype == "relationship":
            return "relationship"
        if source == "identity":
            return "identity"
        return "experience"

    # ── 查询 ─────────────────────────────────────────────────────
    def stages(self) -> Dict[str, Any]:
        """当前阶段分布 (经索引)"""
        return self._index.stats()["by_stage"]

    def changes(self, limit: int = 20) -> List[Dict[str, Any]]:
        """近期整理记录"""
        with self._lock:
            recent = list(reversed(self._changes))
            if limit > 0:
                recent = recent[:limit]
            return [dict(c) for c in recent]

    def stats(self) -> Dict[str, Any]:
        """整合统计"""
        with self._lock:
            changes = list(self._changes)
        recycled_total = sum(
            len(c["recycled"]) for c in changes
        )
        archived_total = sum(
            len(c["archived"]) for c in changes
        )
        return {
            "mode": "rule_based",
            "consolidation_count": len(changes),
            "recycled_total": recycled_total,
            "archived_total": archived_total,
            "stages": self.stages(),
            "index_total": self._index.stats()["total"],
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._changes)
            self._changes.clear()
            self._index.clear()
            return n


__all__ = [
    "CONSOLIDATION_TRANSITIONS",
    "ConsolidationError",
    "MemoryConsolidation",
]
