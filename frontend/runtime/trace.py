"""
YHLZ 前端 Runtime 追踪 (Runtime Trace)

职责:
    - 生成/维护 trace_id / task_id / runtime_id
    - 追踪记录: 事件序列 → 可回放
    - 供开发模式 Runtime Console 展示

设计原则:
    - 单例式运行时 ID (进程级)
    - trace 记录有界
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TraceManagerError(Exception):
    """追踪管理器异常"""


class TraceManager:
    """运行时追踪管理器 (V10.1 Frontend)

    用法:
        tm = TraceManager()
        runtime_id = tm.runtime_id
        task_id = tm.begin_task("对话")
        tm.trace(task_id, "SYSTEM_READY", "启动完成")
        history = tm.history(task_id)
    """

    def __init__(self, max_records: int = 1000):
        if max_records <= 0:
            raise TraceManagerError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._max_records = int(max_records)
        self._runtime_id = "rt_" + uuid.uuid4().hex[:10]
        self._records: List[Dict[str, Any]] = []
        self._tasks: Dict[str, str] = {}

    @property
    def runtime_id(self) -> str:
        """进程级运行时 ID"""
        return self._runtime_id

    def begin_task(self, name: str) -> str:
        """开始任务, 返回 task_id"""
        with self._lock:
            task_id = "task_" + uuid.uuid4().hex[:10]
            self._tasks[task_id] = str(name)
            return task_id

    def trace(
        self,
        task_id: str,
        event: str,
        detail: str = "",
    ) -> Dict[str, Any]:
        """记录追踪条目"""
        with self._lock:
            entry = {
                "trace_id": "tr_" + uuid.uuid4().hex[:10],
                "task_id": str(task_id),
                "task_name": self._tasks.get(str(task_id), ""),
                "runtime_id": self._runtime_id,
                "event": str(event),
                "detail": str(detail),
                "timestamp": time.time(),
            }
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return dict(entry)

    def history(
        self,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """追踪历史 (最新在前)"""
        with self._lock:
            records = list(self._records)
        out: List[Dict[str, Any]] = []
        for r in reversed(records):
            if task_id and r["task_id"] != task_id:
                continue
            out.append(dict(r))
            if 0 < limit <= len(out):
                break
        return out

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "runtime_id": self._runtime_id,
                "total_records": len(self._records),
                "active_tasks": len(self._tasks),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            self._tasks.clear()
            return n


__all__ = [
    "TraceManager",
    "TraceManagerError",
]
