"""
YHLZ Vision Memory V1.0 - 视觉记忆存储接口

职责:
    - 定义统一存储抽象 (MemoryStore ABC)
    - 定义存储异常 (MemoryStoreError)
    - 不包含任何实现 (实现位于 stores/ 目录)

架构位置:
    Service → Manager → Store (Adapter / Storage)

设计原则:
    - 接口最小化: save / retrieve / delete / update / query / count / clear / close
    - 与实现解耦: SQLite / 内存 / 未来向量库均可实现
    - 纯抽象, 无业务逻辑
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from backend.vision.memory.schema import MemoryQuery, VisualMemoryRecord


class MemoryStoreError(Exception):
    """记忆存储操作异常"""


class MemoryStore(ABC):
    """视觉记忆存储抽象接口

    用法:
        class MyStore(MemoryStore):
            def save(self, record): ...
            ...

    实现要求:
        - 线程安全 (RLock)
        - 异常包装为 MemoryStoreError (不泄漏底层异常)
        - 查询结果按 created_at 倒序 (最新在前)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """存储名 (如 'sqlite' / 'memory')"""

    @abstractmethod
    def save(self, record: VisualMemoryRecord) -> str:
        """保存记录, 返回记录 id (已存在则覆盖)"""

    @abstractmethod
    def retrieve(self, memory_id: str) -> Optional[VisualMemoryRecord]:
        """按 id 获取记录 (None=不存在)"""

    @abstractmethod
    def update(self, memory_id: str, **fields) -> bool:
        """字段级更新 (白名单), 返回是否更新成功"""

    @abstractmethod
    def delete(self, memory_id: str) -> bool:
        """删除记录, 返回是否删除成功"""

    @abstractmethod
    def query(self, query: MemoryQuery) -> List[VisualMemoryRecord]:
        """按条件检索, 结果按 created_at 倒序 (最新在前)"""

    @abstractmethod
    def count(self) -> int:
        """记录总数"""

    @abstractmethod
    def clear(self) -> int:
        """清空所有记录, 返回清理数量"""

    def close(self) -> None:
        """关闭存储 (释放资源)"""


__all__ = ["MemoryStore", "MemoryStoreError"]
