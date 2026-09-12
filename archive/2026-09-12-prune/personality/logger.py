"""
YHLZ Personality Engine V3.4 - 人格日志系统

职责:
    - 记录人格操作全生命周期日志 (start / load / switch / save / delete / fail / exception)
    - 性能指标: load_latency / switch_latency / consistency_score / profile_count
    - 支持内存缓冲 + 落盘
    - 支持查询与统计

设计原则:
    - 不依赖 Store (Store 仅产生结果, Logger 单独记录)
    - 线程安全
    - 可配置保留数量
    - 结构化日志 (PersonalityLogEntry dataclass)
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
class PersonalityLogEntry:
    """人格日志条目

    字段:
        timestamp:     日志时间戳
        event:         事件类型 (start / load / switch / save / delete / fail / exception)
        store:         Store 名
        action:        操作类型 (load / switch / save / update / delete / query / clear / style / assess)
        profile_id:    关联档案 id
        profile_name:  档案名称
        latency_ms:    耗时 (毫秒, start 时为 0)
        status:        结果状态 (ok / denied / error / not_found / invalid)
        consistency:   一致性评分 (assess 事件)
        error:         错误描述 (失败时)
        metadata:      附加元数据
    """
    timestamp: float = field(default_factory=time.time)
    event: str = ""              # start / load / switch / save / delete / fail / exception
    store: str = ""
    action: str = ""
    profile_id: str = ""
    profile_name: str = ""
    latency_ms: float = 0.0
    status: str = ""
    consistency: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "store": self.store,
            "action": self.action,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "latency_ms": round(self.latency_ms, 2),
            "status": self.status,
            "consistency": self.consistency,
            "error": self.error,
            "metadata": self.metadata,
        }


class PersonalityLogger:
    """人格日志记录器

    用法:
        plog = PersonalityLogger(max_entries=1000)
        plog.log_start(store="sqlite", action="switch")
        # ... 处理 ...
        plog.log_switch(store="sqlite", profile_id=pid, latency_ms=2.0)
        # 查询
        entries = plog.query(action="switch", limit=10)
        stats = plog.stats()

    特性:
        - 内存环形缓冲 (deque), 防止无限增长
        - 线程安全 (Lock)
        - 同步写入 Python logging
        - 可选落盘 (save_to_file)
        - 性能指标: load_latency / switch_latency / consistency_score / profile_count
    """

    def __init__(self, max_entries: int = 1000, enable_logging: bool = True):
        self._lock = threading.RLock()
        self._entries: Deque[PersonalityLogEntry] = deque(maxlen=max_entries)
        self._max_entries = max_entries
        self._enable_logging = enable_logging

    def log_start(
        self,
        store: str,
        action: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PersonalityLogEntry:
        """记录操作开始"""
        entry = PersonalityLogEntry(store=store, action=action, event="start",
                                    metadata=metadata or {})
        self._append(entry)
        if self._enable_logging:
            logger.info(f"[Personality] 开始 store={store} action={action}")
        return entry

    def log_success(
        self,
        store: str,
        action: str,
        profile_id: str = "",
        profile_name: str = "",
        latency_ms: float = 0.0,
        status: str = "ok",
        consistency: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PersonalityLogEntry:
        """记录操作成功 (load / switch / save / delete / style / assess)"""
        entry = PersonalityLogEntry(
            store=store, action=action, event="success",
            profile_id=profile_id, profile_name=profile_name,
            latency_ms=latency_ms, status=status, consistency=consistency,
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(
                f"[Personality] {action} profile={profile_name or profile_id} "
                f"status={status} latency={latency_ms:.1f}ms"
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
    ) -> PersonalityLogEntry:
        """记录操作失败"""
        entry = PersonalityLogEntry(
            store=store, action=action, event="fail",
            latency_ms=latency_ms, status=status, error=error,
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.warning(
                f"[Personality] 失败 action={action} status={status} "
                f"error={error} latency={latency_ms:.1f}ms"
            )
        return entry

    def log_exception(
        self,
        store: str,
        action: str,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PersonalityLogEntry:
        """记录异常"""
        entry = PersonalityLogEntry(
            store=store, action=action, event="exception", error=error,
            metadata=metadata or {},
        )
        self._append(entry)
        logger.error(
            f"[Personality] 异常 store={store} action={action} error={error}"
        )
        return entry

    def _append(self, entry: PersonalityLogEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def query(
        self,
        event: Optional[str] = None,
        action: Optional[str] = None,
        store: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[PersonalityLogEntry]:
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
        """统计信息 + 性能指标 (load_latency / switch_latency / consistency_score / profile_count)"""
        with self._lock:
            entries = list(self._entries)
        total = len(entries)
        if total == 0:
            return {
                "total": 0, "success": 0, "fail": 0, "exception": 0,
                "success_rate": 0.0,
                "load_latency_ms": 0.0, "switch_latency_ms": 0.0,
                "consistency_score": 0.0, "profile_count": 0,
                "load_count": 0, "switch_count": 0,
            }
        fail = sum(1 for e in entries if e.event == "fail")
        exception = sum(1 for e in entries if e.event == "exception")
        loads = [e for e in entries if e.action == "load" and e.status == "ok"]
        switches = [e for e in entries if e.action == "switch" and e.status == "ok"]
        load_latency = (
            sum(e.latency_ms for e in loads) / len(loads) if loads else 0.0
        )
        switch_latency = (
            sum(e.latency_ms for e in switches) / len(switches) if switches else 0.0
        )
        scores = [e.consistency for e in entries if e.consistency is not None]
        avg_score = (sum(scores) / len(scores)) if scores else 0.0
        profile_count = sum(
            1 for e in entries if e.action == "save" and e.status == "ok"
        )
        success = total - fail - exception
        return {
            "total": total,
            "success": success,
            "fail": fail,
            "exception": exception,
            "success_rate": round((success / total * 100.0) if total else 0.0, 2),
            "load_latency_ms": round(load_latency, 2),
            "switch_latency_ms": round(switch_latency, 2),
            "consistency_score": round(avg_score, 2),
            "profile_count": profile_count,
            "load_count": len(loads),
            "switch_count": len(switches),
        }

    def clear(self) -> int:
        """清空日志, 返回清理数量"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[Personality] 日志已清空, 清理 {n} 条")
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
        logger.info(f"[Personality] 日志已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)


__all__ = ["PersonalityLogEntry", "PersonalityLogger"]
