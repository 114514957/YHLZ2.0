"""
YHLZ Vision Action V1.0 - 行动日志系统

职责:
    - 记录行动全生命周期日志 (start / success / fail / cancel / exception)
    - 性能指标: action_count / success_rate / approval_rate / execution_latency / failure_rate
    - 支持查询与统计
    - 支持内存缓冲 + 落盘

设计原则:
    - 不依赖 Executor (Executor 仅产生结果, Logger 单独记录)
    - 线程安全
    - 可配置保留数量
    - 结构化日志 (ActionLogEntry dataclass)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ActionLogEntry:
    """行动日志条目

    字段:
        timestamp:   日志时间戳
        event:       事件类型 (start / success / fail / cancel / exception)
        action_id:   关联行动 id
        action_type: 行动类型
        status:      结果状态 (ok / denied / invalid / awaiting_confirm / ...)
        risk_level:  风险等级
        latency_ms:  耗时 (毫秒)
        error:       错误描述 (失败时)
        metadata:    附加元数据
    """
    timestamp: float = field(default_factory=time.time)
    event: str = ""              # start / success / fail / cancel / exception
    action_id: str = ""
    action_type: str = ""
    status: str = ""
    risk_level: str = "low"
    latency_ms: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "status": self.status,
            "risk_level": self.risk_level,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
            "metadata": self.metadata,
        }


class ActionLogger:
    """行动日志记录器

    用法:
        alog = ActionLogger(max_entries=1000)
        alog.log_start(action_id=aid, action_type="check")
        # ... 处理 ...
        alog.log_success(action_id=aid, action_type="check", latency_ms=2.0)
        stats = alog.stats()

    指标:
        action_count / success_rate / approval_rate / execution_latency / failure_rate
    """

    def __init__(self, max_entries: int = 1000, enable_logging: bool = True):
        self._lock = threading.RLock()
        self._entries: Deque[ActionLogEntry] = deque(maxlen=max_entries)
        self._max_entries = max_entries
        self._enable_logging = enable_logging

    def log_start(
        self,
        action_id: str,
        action_type: str,
        risk_level: str = "low",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionLogEntry:
        """记录行动开始"""
        entry = ActionLogEntry(
            event="start", action_id=action_id, action_type=action_type,
            risk_level=risk_level, metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(f"[Action] 开始 id={action_id} type={action_type}")
        return entry

    def log_success(
        self,
        action_id: str,
        action_type: str,
        status: str = "ok",
        risk_level: str = "low",
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionLogEntry:
        """记录行动成功 (含 awaiting_confirm / approved 等非失败状态)"""
        entry = ActionLogEntry(
            event="success", action_id=action_id, action_type=action_type,
            status=status, risk_level=risk_level, latency_ms=latency_ms,
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(
                f"[Action] {status} id={action_id} type={action_type} "
                f"latency={latency_ms:.1f}ms"
            )
        return entry

    def log_fail(
        self,
        action_id: str,
        action_type: str,
        status: str,
        error: str,
        risk_level: str = "low",
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionLogEntry:
        """记录行动失败"""
        entry = ActionLogEntry(
            event="fail", action_id=action_id, action_type=action_type,
            status=status, risk_level=risk_level, latency_ms=latency_ms,
            error=error, metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.warning(
                f"[Action] 失败 id={action_id} status={status} error={error}"
            )
        return entry

    def log_cancel(
        self,
        action_id: str,
        action_type: str,
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionLogEntry:
        """记录行动取消"""
        entry = ActionLogEntry(
            event="cancel", action_id=action_id, action_type=action_type,
            status="cancelled", latency_ms=latency_ms, metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(f"[Action] 取消 id={action_id} type={action_type}")
        return entry

    def log_exception(
        self,
        action_id: str,
        action_type: str,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionLogEntry:
        """记录异常"""
        entry = ActionLogEntry(
            event="exception", action_id=action_id, action_type=action_type,
            error=error, metadata=metadata or {},
        )
        self._append(entry)
        logger.error(
            f"[Action] 异常 id={action_id} type={action_type} error={error}"
        )
        return entry

    def _append(self, entry: ActionLogEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def query(
        self,
        event: Optional[str] = None,
        action_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[ActionLogEntry]:
        """查询日志条目 (按条件过滤, 最新在前)"""
        with self._lock:
            entries = list(self._entries)
        result = []
        for e in reversed(entries):
            if event and e.event != event:
                continue
            if action_type and e.action_type != action_type:
                continue
            if status and e.status != status:
                continue
            result.append(e)
            if len(result) >= limit:
                break
        return result

    def stats(self) -> Dict[str, Any]:
        """统计信息 + 性能指标

        指标:
            action_count:       执行尝试总数 (success + fail 事件)
            success_rate:       ok 占比
            approval_rate:      放行占比 (1 - denied 占比)
            execution_latency:  ok 执行平均耗时 (ms)
            failure_rate:       (denied + error + invalid + unsupported + timeout) 占比
        """
        with self._lock:
            entries = list(self._entries)
        total = len(entries)
        if total == 0:
            return {
                "total": 0, "action_count": 0, "success_rate": 0.0,
                "approval_rate": 0.0, "execution_latency_ms": 0.0,
                "failure_rate": 0.0, "ok_count": 0, "denied_count": 0,
                "fail_count": 0, "cancel_count": 0, "exception_count": 0,
            }

        # 执行尝试 = 所有 success 事件 + fail 事件 (排除 start / cancel / exception)
        attempts = [e for e in entries if e.event in ("success", "fail")]
        if not attempts:
            action_count = 0
            ok_count = 0
            denied_count = 0
            failure_count = 0
            latencies = []
        else:
            action_count = len(attempts)
            ok_count = sum(1 for e in attempts if e.status == "ok")
            denied_count = sum(1 for e in attempts if e.status == "denied")
            failure_statuses = {"denied", "error", "invalid", "unsupported", "timeout"}
            failure_count = sum(1 for e in attempts if e.status in failure_statuses)
            latencies = [e.latency_ms for e in attempts if e.status == "ok"]

        fail_events = sum(1 for e in entries if e.event == "fail")
        exception_events = sum(1 for e in entries if e.event == "exception")
        cancel_events = sum(1 for e in entries if e.event == "cancel")

        return {
            "total": total,
            "action_count": action_count,
            "success_rate": round((ok_count / action_count) if action_count else 0.0, 4),
            "approval_rate": round(((action_count - denied_count) / action_count) if action_count else 0.0, 4),
            "execution_latency_ms": round((sum(latencies) / len(latencies)) if latencies else 0.0, 2),
            "failure_rate": round((failure_count / action_count) if action_count else 0.0, 4),
            "ok_count": ok_count,
            "denied_count": denied_count,
            "fail_count": fail_events,
            "cancel_count": cancel_events,
            "exception_count": exception_events,
        }

    def clear(self) -> int:
        """清空日志, 返回清理数量"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[Action] 日志已清空, 清理 {n} 条")
        return n

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def save_to_file(self, path: str) -> int:
        """保存日志到文件 (JSON Lines)"""
        with self._lock:
            entries = list(self._entries)
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[Action] 日志已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)


__all__ = ["ActionLogEntry", "ActionLogger"]
