"""
YHLZ Agent Core V3.0 - 记忆抽象接口
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


class MemoryStoreError(Exception):
    """记忆存储错误"""


@dataclass
class MemoryEntry:
    """记忆条目

    Attributes:
        id: 唯一 ID
        content: 记忆内容
        category: 分类 (fact / preference / event / dialogue / skill)
        source: 来源 (user / assistant / system)
        metadata: 额外元数据
        created_at: 创建时间戳
        last_accessed_at: 最后访问时间戳
        access_count: 访问次数
        weight: 权重 (0-1, 用于检索排序)
    """
    id: str
    content: str
    category: str = "fact"
    source: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    weight: float = 1.0

    @classmethod
    def create(
        cls,
        content: str,
        category: str = "fact",
        source: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "MemoryEntry":
        return cls(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            content=content,
            category=category,
            source=source,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def touch(self) -> None:
        """更新访问时间和次数"""
        self.last_accessed_at = time.time()
        self.access_count += 1


class MemoryStore:
    """记忆存储抽象接口

    子类需实现所有方法。所有方法均为同步 (SQLite 同步即可),
    MemoryManager 会用 asyncio.to_thread 包装。
    """

    def add(self, entry: MemoryEntry) -> str:
        """添加记忆, 返回 ID"""
        raise NotImplementedError

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        """按 ID 获取"""
        raise NotImplementedError

    def update(self, memory_id: str, **fields) -> bool:
        """更新字段"""
        raise NotImplementedError

    def delete(self, memory_id: str) -> bool:
        """删除, 返回是否成功"""
        raise NotImplementedError

    def list_all(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[MemoryEntry]:
        """列出记忆"""
        raise NotImplementedError

    def search(
        self,
        query: str,
        limit: int = 5,
        category: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """搜索记忆 (关键词匹配)"""
        raise NotImplementedError

    def count(self, category: Optional[str] = None) -> int:
        """计数"""
        raise NotImplementedError

    def clear(self) -> int:
        """清空, 返回删除数"""
        raise NotImplementedError

    def close(self) -> None:
        """关闭存储"""
        pass


__all__ = ["MemoryEntry", "MemoryStore", "MemoryStoreError"]
