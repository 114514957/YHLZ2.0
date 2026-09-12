"""
YHLZ Vision Memory V1.0 - 视觉记忆日志系统

职责:
    - 记录记忆操作全生命周期日志 (start / save / query / delete / fail / exception)
    - 性能指标: save_latency / query_latency / memory_count / hit_rate
    - 支持内存缓冲 + 落盘
    - 支持查询与统计

设计原则:
    - 不依赖 Store (Store 仅产生结果, Logger 单独记录)
    - 线程安全
    - 可配置保留数量
    - 结构化日志 (MemoryLogEntry dataclass)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryLogEntry:
    """视觉记忆日志条目

    字段:
        timestamp: 日志时间戳
        event:     事件类型 (start / save / query / delete / fail / exception)
        store:     Store 名
        action:    操作类型 (save / retrieve / update / delete / query / clear / context)
        memory_id: 关联的记录 id
        latency_ms:耗时 (毫秒, start 时为 0)
        status:    结果状态 (ok / denied / error / not_found)
        hit:       检索是否命中 (query 事件)
        count:     影响记录数 (save=1 / query=命中数 / delete=1 / clear=清理数)
        error:     错误描述 (失败时)
        metadata:  附加元数据
    """
    timestamp: float = field(default_factory=time.time)
    event: str = ""              # start / save / query / delete / fail / exception
    store: str = ""
    action: str = ""
    memory_id: str = ""
    latency_ms: float = 0.0
    status: str = ""
    hit: Optional[bool] = None
    count: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "store": self.store,
            "action": self.action,
            "memory_id": self.memory_id,
            "latency_ms": round(self.latency_ms, 2),
            "status": self.status,
            "hit": self.hit,
            "count": self.count,
            "error": self.error,
            "metadata": self.metadata,
        }


class MemoryLogger:
    """视觉记忆日志记录器

    用法:
        mlog = MemoryLogger(max_entries=1000)
        mlog.log_start(store="sqlite", action="save")
        # ... 处理 ...
        mlog.log_success(store="sqlite", action="save", memory_id=id, latency_ms=5.0)
        # 查询
        entries = mlog.query(event="save", limit=10)
        stats = mlog.stats()

    特性:
        - 内存环形缓冲 (deque), 防止无限增长
        - 线程安全 (Lock)
        - 同步写入 Python logging (供文件/控制台输出)
        - 可选落盘 (save_to_file)
        - 性能指标统计: save_latency / query_latency / memory_count / hit_rate
    """

    def __init__(self, max_entries: int = 1000, enable_logging: bool = True):
        self._lock = threading.RLock()
        self._entries: Deque[MemoryLogEntry] = deque(maxlen=max_entries)
        self._max_entries = max_entries
        self._enable_logging = enable_logging

    def log_start(
        self,
        store: str,
        action: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryLogEntry:
        """记录操作开始"""
        entry = MemoryLogEntry(store=store, action=action, event="start",
                               metadata=metadata or {})
        self._append(entry)
        if self._enable_logging:
            logger.info(f"[VisionMemory] 开始 store={store} action={action}")
        return entry

    def log_save(
        self,
        store: str,
        memory_id: str,
        latency_ms: float,
        status: str = "ok",
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryLogEntry:
        """记录保存操作"""
        entry = MemoryLogEntry(
            store=store, action="save", event="save", memory_id=memory_id,
            latency_ms=latency_ms, status=status, error=error, count=1,
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            (logger.info if status == "ok" else logger.warning)(
                f"[VisionMemory] 保存 memory_id={memory_id} status={status} "
                f"latency={latency_ms:.1f}ms error={error or ''}"
            )
        return entry

    def log_query(
        self,
        store: str,
        latency_ms: float,
        hit_count: int,
        status: str = "ok",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryLogEntry:
        """记录检索操作"""
        entry = MemoryLogEntry(
            store=store, action="query", event="query",
            latency_ms=latency_ms, status=status, hit=hit_count > 0,
            count=hit_count, metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(
                f"[VisionMemory] 检索 hits={hit_count} status={status} "
                f"latency={latency_ms:.1f}ms"
            )
        return entry

    def log_delete(
        self,
        store: str,
        action: str,
        memory_id: str,
        latency_ms: float,
        status: str = "ok",
        count: int = 0,
        error: Optional[str] = None,
    ) -> MemoryLogEntry:
        """记录删除 / 清空操作"""
        entry = MemoryLogEntry(
            store=store, action=action, event="delete", memory_id=memory_id,
            latency_ms=latency_ms, status=status, count=count, error=error,
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(
                f"[VisionMemory] {action} memory_id={memory_id} status={status} "
                f"count={count} latency={latency_ms:.1f}ms"
            )
        return entry

    def log_fail(
        self,
        store: str,
        action: str,
        status: str,
        error: str,
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryLogEntry:
        """记录操作失败"""
        entry = MemoryLogEntry(
            store=store, action=action, event="fail",
            latency_ms=latency_ms, status=status, error=error,
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.warning(
                f"[VisionMemory] 失败 action={action} status={status} "
                f"error={error} latency={latency_ms:.1f}ms"
            )
        return entry

    def log_exception(
        self,
        store: str,
        action: str,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryLogEntry:
        """记录异常"""
        entry = MemoryLogEntry(
            store=store, action=action, event="exception", error=error,
            metadata=metadata or {},
        )
        self._append(entry)
        logger.error(
            f"[VisionMemory] 异常 store={store} action={action} error={error}"
        )
        return entry

    def _append(self, entry: MemoryLogEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def query(
        self,
        event: Optional[str] = None,
        action: Optional[str] = None,
        store: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[MemoryLogEntry]:
        """查询日志条目 (按条件过滤)"""
        with self._lock:
            entries = list(self._entries)
        result = []
        for e in reversed(entries):  # 最新的在前
            if event and e.event != event:
                continue
            if action and e.action != action:
                continue
            if store and e.store != store:
                continue
            if status and e.status != status:
                continue
            result.append(e)
            if len(result) >= limit:
                break
        return result

    def stats(self) -> Dict[str, Any]:
        """统计信息 + 性能指标 (save_latency / query_latency / memory_count / hit_rate)"""
        with self._lock:
            entries = list(self._entries)
        total = len(entries)
        if total == 0:
            return {
                "total": 0, "success": 0, "fail": 0, "exception": 0,
                "success_rate": 0.0,
                "save_latency_ms": 0.0, "query_latency_ms": 0.0,
                "memory_count": 0, "hit_rate": 0.0,
                "save_count": 0, "query_count": 0, "delete_count": 0,
            }
        fail = sum(1 for e in entries if e.event == "fail")
        exception = sum(1 for e in entries if e.event == "exception")
        save_entries = [e for e in entries if e.action == "save" and e.status == "ok"]
        query_entries = [e for e in entries if e.action == "query" and e.status == "ok"]
        save_latency = (
            sum(e.latency_ms for e in save_entries) / len(save_entries)
            if save_entries else 0.0
        )
        query_latency = (
            sum(e.latency_ms for e in query_entries) / len(query_entries)
            if query_entries else 0.0
        )
        hits = sum(1 for e in query_entries if e.hit)
        hit_rate = (hits / len(query_entries) * 100.0) if query_entries else 0.0
        success = total - fail - exception
        return {
            "total": total,
            "success": success,
            "fail": fail,
            "exception": exception,
            "success_rate": round((success / total * 100.0) if total else 0.0, 2),
            "save_latency_ms": round(save_latency, 2),
            "query_latency_ms": round(query_latency, 2),
            "memory_count": sum(e.count for e in save_entries if e.status == "ok"),
            "hit_rate": round(hit_rate, 2),
            "save_count": len(save_entries),
            "query_count": len(query_entries),
            "delete_count": sum(1 for e in entries if e.action in ("delete", "clear")),
        }

    def clear(self) -> int:
        """清空日志, 返回清理数量"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[VisionMemory] 日志已清空, 清理 {n} 条")
        return n

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def save_to_file(self, path: str) -> int:
        """保存日志到文件 (JSON Lines)"""
        import json
        with self._lock:
            entries = list(self._entries)
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[VisionMemory] 日志已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)


__all__ = ["MemoryLogEntry", "MemoryLogger"]
