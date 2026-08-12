"""
YHLZ 前端 Runtime 事件总线 (Runtime Event Bus)

职责:
    - 发布/订阅运行时事件
    - 事件类型: SYSTEM_READY / MEMORY_SYNC / MODEL_SWITCH /
      TASK_START / TASK_END / ERROR
    - 事件驱动: Runtime Event → Frontend State → Avatar Response

设计原则:
    - 单一事件总线 (前端全局)
    - 订阅回调不抛异常 (容错隔离)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 运行时事件类型 (可解释)
RUNTIME_EVENTS: List[str] = [
    "SYSTEM_READY",   # 系统就绪
    "MEMORY_SYNC",    # 记忆同步
    "MODEL_SWITCH",   # 模型切换
    "TASK_START",     # 任务开始
    "TASK_END",       # 任务结束
    "ERROR",          # 错误
]


class RuntimeEventError(Exception):
    """运行时事件异常"""


class RuntimeEvent:
    """运行时事件"""

    def __init__(
        self,
        event_type: str,
        detail: str = "",
        data: Optional[Dict[str, Any]] = None,
    ):
        if event_type not in RUNTIME_EVENTS:
            raise RuntimeEventError(
                f"非法事件类型: {event_type} "
                f"(可选: {RUNTIME_EVENTS})"
            )
        self.event_id = "evt_" + uuid.uuid4().hex[:10]
        self.event_type = event_type
        self.detail = str(detail)
        self.data = dict(data or {})
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "detail": self.detail,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class RuntimeEventBus:
    """运行时事件总线 (V10.1 Frontend)

    用法:
        bus = RuntimeEventBus()
        bus.subscribe("SYSTEM_READY", handler)
        bus.publish(RuntimeEvent("SYSTEM_READY", "启动完成"))
    """

    def __init__(self, max_history: int = 500):
        if max_history <= 0:
            raise RuntimeEventError(
                f"max_history 必须 > 0, 当前: {max_history}"
            )
        self._lock = threading.RLock()
        self._max_history = int(max_history)
        self._subscribers: Dict[str, List[Callable]] = {}
        self._history: List[Dict[str, Any]] = []

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[RuntimeEvent], None],
    ) -> None:
        """订阅事件"""
        with self._lock:
            if event_type not in RUNTIME_EVENTS:
                raise RuntimeEventError(
                    f"非法事件类型: {event_type}"
                )
            if not callable(handler):
                raise RuntimeEventError("订阅回调必须可调用")
            self._subscribers.setdefault(
                event_type, [],
            ).append(handler)

    def unsubscribe(
        self,
        event_type: str,
        handler: Callable,
    ) -> bool:
        """取消订阅"""
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)
                return True
            return False

    def publish(self, event: RuntimeEvent) -> int:
        """发布事件 (返回送达订阅者数)"""
        with self._lock:
            entry = event.to_dict()
            self._history.append(entry)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            handlers = list(
                self._subscribers.get(event.event_type, []),
            )
        delivered = 0
        for h in handlers:
            try:
                h(event)
                delivered += 1
            except Exception as e:  # noqa: BLE001 订阅者隔离
                logger.error(
                    f"[RuntimeEvent] 订阅者处理失败: {e}"
                )
        return delivered

    def history(
        self,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """事件历史 (最新在前)"""
        with self._lock:
            records = list(self._history)
        out: List[Dict[str, Any]] = []
        for r in reversed(records):
            if event_type and r["event_type"] != event_type:
                continue
            out.append(dict(r))
            if 0 < limit <= len(out):
                break
        return out

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            by_type: Dict[str, int] = {}
            for r in self._history:
                by_type[r["event_type"]] = by_type.get(
                    r["event_type"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "total": len(self._history),
                "by_type": by_type,
                "subscriber_count": sum(
                    len(v) for v in self._subscribers.values()
                ),
            }

    def clear(self) -> int:
        """清空历史 (测试隔离)"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
            return n


__all__ = [
    "RUNTIME_EVENTS",
    "RuntimeEvent",
    "RuntimeEventBus",
    "RuntimeEventError",
]
