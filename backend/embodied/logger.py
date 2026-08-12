"""
YHLZ Embodied AI V4.1 - 具身日志系统

职责:
    - 记录具身全生命周期日志 (goal / observe / action / feedback / exception)
    - 性能指标: goal_count / success_rate / failure_rate / execution_latency / observe_count
    - 支持查询与统计
    - 内存缓冲 + 可选落盘

设计原则:
    - 不依赖 Environment / Executor (仅记录事件)
    - 线程安全 (RLock)
    - 结构化日志 (EmbodiedLogEntry dataclass)
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
class EmbodiedLogEntry:
    """具身日志条目

    字段:
        timestamp:   日志时间戳
        event:       事件类型 (goal_start / goal_success / goal_fail / observe / action_start / action_success / action_fail / exception / cancel)
        goal_id:     关联目标 id
        action_id:   关联动作 id
        action_type: 动作类型
        status:      结果状态 (ok / denied / invalid / awaiting_confirm / ...)
        risk_level:  风险等级
        latency_ms:  耗时 (毫秒)
        error:       错误描述 (失败时)
        metadata:    附加元数据
    """
    timestamp: float = field(default_factory=time.time)
    event: str = ""
    goal_id: str = ""
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
            "goal_id": self.goal_id,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "status": self.status,
            "risk_level": self.risk_level,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
            "metadata": self.metadata,
        }


class EmbodiedLogger:
    """具身日志记录器

    用法:
        elog = EmbodiedLogger(max_entries=1000)
        elog.log_goal_start(goal_id=gid)
        elog.log_action_success(action_id=aid, action_type="scan", latency_ms=2.0)
        stats = elog.stats()
    """

    def __init__(self, max_entries: int = 1000, enable_logging: bool = True):
        self._lock = threading.RLock()
        self._entries: Deque[EmbodiedLogEntry] = deque(maxlen=max_entries)
        self._max_entries = max_entries
        self._enable_logging = enable_logging

    # ── 目标事件 ──────────────────────────────────────────────────
    def log_goal_start(self, goal_id: str, intent: str = "") -> EmbodiedLogEntry:
        return self._log("goal_start", goal_id=goal_id, metadata={"intent": intent})

    def log_goal_success(self, goal_id: str, iterations: int, latency_ms: float = 0.0) -> EmbodiedLogEntry:
        return self._log(
            "goal_success", goal_id=goal_id, status="ok", latency_ms=latency_ms,
            metadata={"iterations": iterations},
        )

    def log_goal_fail(self, goal_id: str, status: str, error: str, latency_ms: float = 0.0) -> EmbodiedLogEntry:
        return self._log(
            "goal_fail", goal_id=goal_id, status=status, error=error,
            latency_ms=latency_ms,
        )

    # ── 观察事件 ──────────────────────────────────────────────────
    def log_observe(self, environment: str, objects: int, latency_ms: float = 0.0) -> EmbodiedLogEntry:
        return self._log(
            "observe", metadata={"environment": environment, "objects": objects},
            latency_ms=latency_ms,
        )

    # ── 动作事件 ──────────────────────────────────────────────────
    def log_action_start(self, action_id: str, action_type: str, risk_level: str = "low") -> EmbodiedLogEntry:
        return self._log(
            "action_start", action_id=action_id, action_type=action_type,
            risk_level=risk_level,
        )

    def log_action_success(
        self,
        action_id: str,
        action_type: str,
        status: str = "ok",
        risk_level: str = "low",
        latency_ms: float = 0.0,
    ) -> EmbodiedLogEntry:
        return self._log(
            "action_success", action_id=action_id, action_type=action_type,
            status=status, risk_level=risk_level, latency_ms=latency_ms,
        )

    def log_action_fail(
        self,
        action_id: str,
        action_type: str,
        status: str,
        error: str,
        risk_level: str = "low",
        latency_ms: float = 0.0,
    ) -> EmbodiedLogEntry:
        return self._log(
            "action_fail", action_id=action_id, action_type=action_type,
            status=status, error=error, risk_level=risk_level, latency_ms=latency_ms,
        )

    # ── 其他事件 ──────────────────────────────────────────────────
    def log_exception(
        self,
        error: str,
        action_id: str = "",
        action_type: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EmbodiedLogEntry:
        return self._log(
            "exception", action_id=action_id, action_type=action_type,
            error=error, metadata=metadata or {},
        )

    def log_cancel(self, action_id: str, latency_ms: float = 0.0) -> EmbodiedLogEntry:
        return self._log(
            "cancel", action_id=action_id, status="cancelled", latency_ms=latency_ms,
        )

    def _log(
        self,
        event: str,
        goal_id: str = "",
        action_id: str = "",
        action_type: str = "",
        status: str = "",
        risk_level: str = "low",
        latency_ms: float = 0.0,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EmbodiedLogEntry:
        entry = EmbodiedLogEntry(
            event=event, goal_id=goal_id, action_id=action_id,
            action_type=action_type, status=status, risk_level=risk_level,
            latency_ms=latency_ms, error=error, metadata=metadata or {},
        )
        with self._lock:
            self._entries.append(entry)
        if self._enable_logging:
            logger.info(
                f"[Embodied] {event} goal={goal_id or '-'} action={action_id or '-'} "
                f"type={action_type or '-'} status={status or '-'} latency={latency_ms:.1f}ms"
            )
        return entry

    # ── 查询 ──────────────────────────────────────────────────────
    def query(
        self,
        event: Optional[str] = None,
        action_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[EmbodiedLogEntry]:
        """查询日志 (按条件过滤, 最新在前)"""
        with self._lock:
            entries = list(self._entries)
        out: List[EmbodiedLogEntry] = []
        for e in reversed(entries):
            if event and e.event != event:
                continue
            if action_type and e.action_type != action_type:
                continue
            if status and e.status != status:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def query_dicts(self, **kwargs) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self.query(**kwargs)]

    # ── 统计 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """统计信息 + 性能指标

        指标:
            total:           日志总数
            goal_count:      目标执行次数 (goal_success + goal_fail)
            goal_success_rate: 目标成功率
            action_count:    动作执行次数 (action_success + action_fail)
            action_success_rate: 动作成功率
            avg_action_latency_ms: 动作平均耗时
            observe_count:   观察次数
            exception_count: 异常次数
        """
        with self._lock:
            entries = list(self._entries)
        total = len(entries)
        if total == 0:
            return {
                "total": 0, "goal_count": 0, "goal_success_rate": 0.0,
                "action_count": 0, "action_success_rate": 0.0,
                "avg_action_latency_ms": 0.0, "observe_count": 0,
                "exception_count": 0,
            }

        goal_success = sum(1 for e in entries if e.event == "goal_success")
        goal_fail = sum(1 for e in entries if e.event == "goal_fail")
        goal_count = goal_success + goal_fail

        action_ok = sum(1 for e in entries if e.event == "action_success" and e.status == "ok")
        action_attempts = [e for e in entries if e.event in ("action_success", "action_fail")]
        action_count = len(action_attempts)
        latencies = [e.latency_ms for e in action_attempts if e.latency_ms > 0]

        return {
            "total": total,
            "goal_count": goal_count,
            "goal_success_rate": round(goal_success / goal_count, 4) if goal_count else 0.0,
            "action_count": action_count,
            "action_success_rate": round(action_ok / action_count, 4) if action_count else 0.0,
            "avg_action_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "observe_count": sum(1 for e in entries if e.event == "observe"),
            "exception_count": sum(1 for e in entries if e.event == "exception"),
        }

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空日志, 返回清理数量"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[Embodied] 日志已清空, 清理 {n} 条")
        return n

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def save_to_file(self, path: str) -> int:
        """保存日志到 JSONL 文件"""
        with self._lock:
            entries = list(self._entries)
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[Embodied] 日志已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)


__all__ = ["EmbodiedLogEntry", "EmbodiedLogger"]
