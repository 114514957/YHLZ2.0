"""
YHLZ 前端 Runtime 层 (Runtime Observability Layer)

职责:
    - state: 伙伴运行状态 (System_Ready/Memory_Sync/Model_Switch/Task/Error)
    - event: 运行时事件总线 (发布/订阅)
    - trace: 追踪 (trace_id/task_id/runtime_id)

设计原则:
    - 前端状态机与后端解耦 (只观察, 不干预)
    - 事件驱动: Runtime Event → Frontend State → Avatar Response
    - 线程安全 (RLock)
"""
from __future__ import annotations

from frontend.runtime.state import (
    RuntimeState,
    RuntimeStateError,
)
from frontend.runtime.event import (
    RUNTIME_EVENTS,
    RuntimeEvent,
    RuntimeEventBus,
    RuntimeEventError,
)
from frontend.runtime.trace import (
    TraceManager,
    TraceManagerError,
)

__all__ = [
    "RUNTIME_EVENTS",
    "RuntimeEvent",
    "RuntimeEventBus",
    "RuntimeEventError",
    "RuntimeState",
    "RuntimeStateError",
    "TraceManager",
    "TraceManagerError",
]
