"""
YHLZ 前端运行时控制台 (Runtime Console, 开发模式)

职责:
    - 开发模式 (Ctrl+Shift+R) 展示:
      System: Backend / Latency / GPU / Memory
      AI:     Model / Route / Token
      Memory: Read / Write / Conflict
      Trace:  Trace ID / Task ID / Runtime ID
    - 数据聚合: 从各组件收集, 只读展示

设计原则:
    - 隐藏开发模式: 普通用户不暴露后台日志
    - 只读聚合, 不干预运行
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RuntimeConsoleError(Exception):
    """运行时控制台异常"""


class RuntimeConsole:
    """运行时控制台 (V10.1 Frontend, 开发模式)

    用法:
        console = RuntimeConsole()
        console.update_system(backend="Online", latency_ms=25.3)
        console.update_ai(model="Qwen", route="Local")
        console.update_memory(read=10, write=3, conflict=0)
        report = console.report()
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._system: Dict[str, Any] = {
            "backend": "Unknown",
            "latency_ms": 0.0,
            "gpu_percent": 0.0,
            "memory_percent": 0.0,
        }
        self._ai: Dict[str, Any] = {
            "model": "",
            "route": "Local",
            "token_usage": 0,
        }
        self._memory: Dict[str, Any] = {
            "read": 0,
            "write": 0,
            "conflict": 0,
        }
        self._traces: Dict[str, Any] = {
            "trace_id": "",
            "task_id": "",
            "runtime_id": "",
        }

    def update_system(
        self,
        backend: str = "",
        latency_ms: float = 0.0,
        gpu_percent: float = 0.0,
        memory_percent: float = 0.0,
    ) -> Dict[str, Any]:
        """更新 System 区块"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "控制台停用"}
            self._system = {
                "backend": str(backend) or self._system["backend"],
                "latency_ms": float(latency_ms),
                "gpu_percent": float(gpu_percent),
                "memory_percent": float(memory_percent),
            }
            return {"mode": "rule_based", "ok": True,
                    "system": dict(self._system)}

    def update_ai(
        self,
        model: str = "",
        route: str = "",
        token_usage: int = 0,
    ) -> Dict[str, Any]:
        """更新 AI 区块"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "控制台停用"}
            self._ai = {
                "model": str(model) or self._ai["model"],
                "route": str(route) or self._ai["route"],
                "token_usage": int(token_usage),
            }
            return {"mode": "rule_based", "ok": True,
                    "ai": dict(self._ai)}

    def update_memory(
        self,
        read: int = 0,
        write: int = 0,
        conflict: int = 0,
    ) -> Dict[str, Any]:
        """更新 Memory 区块"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "控制台停用"}
            self._memory = {
                "read": int(read),
                "write": int(write),
                "conflict": int(conflict),
            }
            return {"mode": "rule_based", "ok": True,
                    "memory": dict(self._memory)}

    def update_trace(
        self,
        trace_id: str = "",
        task_id: str = "",
        runtime_id: str = "",
    ) -> Dict[str, Any]:
        """更新 Trace 区块"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "控制台停用"}
            self._traces = {
                "trace_id": str(trace_id) or self._traces["trace_id"],
                "task_id": str(task_id) or self._traces["task_id"],
                "runtime_id": str(runtime_id)
                or self._traces["runtime_id"],
            }
            return {"mode": "rule_based", "ok": True,
                    "trace": dict(self._traces)}

    def report(self) -> Dict[str, Any]:
        """控制台报告 (四区块)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "system": dict(self._system),
                "ai": dict(self._ai),
                "memory": dict(self._memory),
                "trace": dict(self._traces),
                "generated_at": time.time(),
            }

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "backend": self._system["backend"],
                "model": self._ai["model"],
            }

    def clear(self) -> int:
        """重置 (测试隔离)"""
        with self._lock:
            self._system = {
                "backend": "Unknown", "latency_ms": 0.0,
                "gpu_percent": 0.0, "memory_percent": 0.0,
            }
            self._ai = {"model": "", "route": "Local",
                        "token_usage": 0}
            self._memory = {"read": 0, "write": 0, "conflict": 0}
            self._traces = {"trace_id": "", "task_id": "",
                            "runtime_id": ""}
            return 1


__all__ = [
    "RuntimeConsole",
    "RuntimeConsoleError",
]
