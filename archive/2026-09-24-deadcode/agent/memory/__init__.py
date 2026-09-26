"""
YHLZ Agent Core V3.0 - 记忆子系统

修复 V2.3 遗留问题:
    - context_manager.py 的 memory 方法全是 stub
    - main.py /memory/* API 调用不存在的方法
    - 旧 memories.db / memories_v2.db 残留无人维护

本模块提供完整的记忆系统:
    - MemoryStore: 抽象接口
    - SQLiteMemoryStore: SQLite 持久化实现
    - MemoryManager: 记忆管理器 (CRUD + 检索 + 提取 + 衰减)
    - MemoryEntry: 记忆条目数据模型

设计:
    - 短期记忆: 最近 N 条对话 (内存)
    - 长期记忆: SQLite 持久化 (按 category 分类)
    - 检索: 关键词匹配 (V3.0 不引入向量库, V3.1 可扩展)
    - 自动提取: LLM 从对话中提取值得记忆的事实
    - 衰减: 按 last_accessed_at 衰减权重
"""
from __future__ import annotations

from backend.agent.memory.base import MemoryEntry, MemoryStore, MemoryStoreError
from backend.agent.memory.sqlite_store import SQLiteMemoryStore
from backend.agent.memory.manager import (
    MemoryManager,
    MemoryManagerError,
    get_memory_manager,
    reset_memory_manager,
)

__all__ = [
    "MemoryEntry", "MemoryStore", "MemoryStoreError",
    "SQLiteMemoryStore",
    "MemoryManager", "MemoryManagerError",
    "get_memory_manager", "reset_memory_manager",
]
