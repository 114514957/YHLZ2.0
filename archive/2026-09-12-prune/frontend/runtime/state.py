"""
YHLZ 前端 Runtime 状态 (Runtime State)

职责:
    - 伙伴运行状态机: IDLE → INITIALIZING → ONLINE
      (ONLINE 下细分: THINKING / LEARNING / WAITING)
    - 连接状态: 正常 / 断线 / 重连
    - 状态可查询 / 可订阅变更

设计原则:
    - 只表达伙伴状态, 不干预后端
    - 状态变更通知 (回调列表)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class RuntimeStateError(Exception):
    """运行时状态异常"""


# 伙伴状态枚举 (可解释)
COMPANION_STATES: List[str] = [
    "idle",          # 待机 (启动前)
    "initializing",  # 初始化中
    "online",        # 在线
    "thinking",      # 思考中
    "learning",      # 学习中
    "waiting",       # 等待中
    "error",         # 错误
]

# 连接状态枚举
CONNECTION_STATES: List[str] = [
    "disconnected",  # 未连接
    "connecting",    # 连接中
    "connected",     # 已连接
    "reconnecting",  # 重连中
]


class RuntimeState:
    """伙伴运行时状态 (V10.1 Frontend)

    用法:
        rs = RuntimeState()
        rs.set_state("online")
        rs.set_connection("connected")
        snap = rs.snapshot()
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._state: str = "idle"
        self._connection: str = "disconnected"
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._changed_at: float = 0.0

    def set_state(self, state: str) -> Dict[str, Any]:
        """设置伙伴状态"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "运行时状态停用"}
            if state not in COMPANION_STATES:
                raise RuntimeStateError(
                    f"非法状态: {state} (可选: {COMPANION_STATES})"
                )
            old = self._state
            self._state = state
            self._changed_at = time.time()
            snapshot = self.snapshot()
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(snapshot)
            except Exception as e:  # noqa: BLE001 监听者隔离
                logger.error(f"[RuntimeState] 监听者失败: {e}")
        return {
            "mode": "rule_based", "ok": True,
            "from": old, "to": state,
        }

    def set_connection(self, connection: str) -> Dict[str, Any]:
        """设置连接状态"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "运行时状态停用"}
            if connection not in CONNECTION_STATES:
                raise RuntimeStateError(
                    f"非法连接状态: {connection} "
                    f"(可选: {CONNECTION_STATES})"
                )
            old = self._connection
            self._connection = connection
            self._changed_at = time.time()
            snapshot = self.snapshot()
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(snapshot)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[RuntimeState] 监听者失败: {e}")
        return {
            "mode": "rule_based", "ok": True,
            "from": old, "to": connection,
        }

    def on_change(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        """订阅状态变更"""
        with self._lock:
            if not callable(listener):
                raise RuntimeStateError("监听者必须可调用")
            self._listeners.append(listener)

    def snapshot(self) -> Dict[str, Any]:
        """状态快照"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "state": self._state,
                "connection": self._connection,
                "changed_at": self._changed_at,
                "online": self._state == "online",
            }

    def reset(self) -> Dict[str, Any]:
        """重置为待机"""
        with self._lock:
            self._state = "idle"
            self._connection = "disconnected"
            return {"mode": "rule_based", "ok": True,
                    "reset": True}

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "state": self._state,
                "connection": self._connection,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._listeners)
            self._listeners.clear()
            self.reset()
            return n


__all__ = [
    "COMPANION_STATES",
    "CONNECTION_STATES",
    "RuntimeState",
    "RuntimeStateError",
]
