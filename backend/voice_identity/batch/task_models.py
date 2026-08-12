"""
YHLZ Voice Identity System V2.2-Phase3.1 - 批量任务数据模型

职责:
    - 定义批量克隆任务的数据结构 (CloneTask / TaskItem)
    - 任务状态枚举与流转 (pending → running → completed/partial/failed)
    - 提供序列化方法 (to_dict) 供 API 返回
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(str, Enum):
    """任务状态

    流转:
        pending  → running → completed   (全部成功)
                  → partial  (部分成功)
                  → failed   (全部失败)
        running  → cancelled (手动取消, 当前版本不实现)
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class TaskItem:
    """批量任务中的单个克隆项

    字段:
        audio_path: 参考音频路径
        name:       声音展示名
        engine:     引擎 (qwen3/gpt_sovits)
        language:   主语言
        metadata:   扩展元数据
        status:     单项状态 (pending/running/success/failed)
        voice_id:   成功时返回的 voice_id
        error:      失败原因
        started_at: 开始时间 (ISO 字符串)
        ended_at:   结束时间 (ISO 字符串)
    """
    audio_path: str
    name: str
    engine: str = "qwen3"
    language: str = "zh"
    metadata: Dict[str, Any] = field(default_factory=dict)
    voice_id: Optional[str] = None
    status: str = "pending"  # pending/running/success/failed
    error: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "audio_path": self.audio_path,
            "name": self.name,
            "engine": self.engine,
            "language": self.language,
            "metadata": self.metadata,
            "voice_id": self.voice_id,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


@dataclass
class CloneTask:
    """批量克隆任务

    字段:
        task_id:    任务唯一 ID
        items:      任务项列表
        status:     整体任务状态
        created_at: 创建时间
        started_at: 开始执行时间
        ended_at:   结束时间
        owner:      任务发起者 (用于审计)
        total:      总项数
        success_count: 成功数
        failed_count:  失败数
    """
    task_id: str
    items: List[TaskItem] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    owner: str = "system"
    success_count: int = 0
    failed_count: int = 0

    @property
    def total(self) -> int:
        return len(self.items)

    def update_counts(self) -> None:
        """根据 items 状态刷新 success/failed 计数"""
        self.success_count = sum(1 for it in self.items if it.status == "success")
        self.failed_count = sum(1 for it in self.items if it.status == "failed")

    def compute_status(self) -> TaskStatus:
        """根据 items 状态推断整体状态"""
        self.update_counts()
        if self.success_count == 0 and self.failed_count == 0:
            return TaskStatus.PENDING if any(
                it.status == "pending" for it in self.items
            ) else TaskStatus.RUNNING
        if self.failed_count == 0:
            return TaskStatus.COMPLETED
        if self.success_count == 0:
            return TaskStatus.FAILED
        return TaskStatus.PARTIAL

    def to_dict(self) -> dict:
        self.update_counts()
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "owner": self.owner,
            "total": self.total,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "items": [it.to_dict() for it in self.items],
        }


@dataclass
class TaskSummary:
    """任务摘要 (列表查询用, 不含 items 详情)"""
    task_id: str
    status: str
    total: int
    success_count: int
    failed_count: int
    created_at: Optional[str]
    ended_at: Optional[str]

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "total": self.total,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
        }
