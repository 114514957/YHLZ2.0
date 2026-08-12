"""
YHLZ Voice Identity System V2.3-Phase2 - 批量克隆任务系统

模块结构:
    batch/
    ├── __init__.py        ← 本文件: 统一导出
    ├── task_models.py     ← 任务数据模型 (CloneTask / TaskItem / TaskStatus)
    ├── task_queue.py      ← TaskQueue (线程池 worker + 状态查询 + 持久化挂载)
    └── task_store.py      ← TaskStore (SQLite 持久化, 服务重启恢复)

架构层次:
    API (/voice/clone/batch)
      ↓
    TaskQueue (内存执行) + TaskStore (持久化)
      ↓
    VoiceIdentityService.clone_voice_with_adapter
      ↓
    VoiceClonePipeline → Manager/Registry/Cache/Adapter

设计原则:
    - 单进程内存任务队列 (不引入 Redis/Celery, 与项目规模匹配)
    - 线程池 worker (clone_voice 为同步阻塞调用, 用线程避免阻塞事件循环)
    - V2.3 任务持久化到 voice_clone_tasks 表 (服务重启可恢复)
    - 单任务失败不影响其他任务 (partial 状态)
"""
from __future__ import annotations

from backend.voice_identity.batch.task_models import (
    CloneTask,
    TaskItem,
    TaskStatus,
    TaskSummary,
)
from backend.voice_identity.batch.task_queue import (
    BatchTaskError,
    TaskQueue,
    get_task_queue,
    reset_task_queue,
)
from backend.voice_identity.batch.task_store import (
    TaskStore,
    get_task_store,
    reset_task_store,
)

__all__ = [
    # 模型
    "CloneTask",
    "TaskItem",
    "TaskStatus",
    "TaskSummary",
    # 队列
    "TaskQueue",
    "BatchTaskError",
    "get_task_queue",
    "reset_task_queue",
    # 持久化 (V2.3-Phase2)
    "TaskStore",
    "get_task_store",
    "reset_task_store",
]

__version__ = "2.3.0"
