"""
YHLZ Personality Engine V3.4 - 人格存储接口

职责:
    - 定义统一存储抽象 (PersonalityStore ABC)
    - 定义存储异常 (PersonalityStoreError)
    - 不包含任何实现 (实现位于 stores/ 目录)

架构位置:
    Service → Manager → Store (Adapter / Storage)

设计原则:
    - 接口最小化: save / retrieve / update / delete / query / count / clear / close
    - 与实现解耦: SQLite / 内存均可实现
    - 纯抽象, 无业务逻辑
    - 人格数据独立存储 (绝不写入 Agent Memory)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from backend.personality.schema import PersonalityProfile, PersonalityQuery


class PersonalityStoreError(Exception):
    """人格存储操作异常"""


class PersonalityStore(ABC):
    """人格存储抽象接口

    用法:
        class MyStore(PersonalityStore):
            def save(self, profile): ...
            ...

    实现要求:
        - 线程安全 (RLock)
        - 异常包装为 PersonalityStoreError (不泄漏底层异常)
        - 查询结果按 created_at 倒序 (最新在前)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """存储名 (如 'sqlite' / 'memory')"""

    @abstractmethod
    def save(self, profile: PersonalityProfile) -> str:
        """保存档案, 返回 profile_id (已存在则覆盖)"""

    @abstractmethod
    def retrieve(self, profile_id: str) -> Optional[PersonalityProfile]:
        """按 id 获取档案 (None=不存在)"""

    @abstractmethod
    def update(self, profile_id: str, **fields) -> bool:
        """字段级更新 (白名单), 返回是否更新成功"""

    @abstractmethod
    def delete(self, profile_id: str) -> bool:
        """删除档案, 返回是否删除成功"""

    @abstractmethod
    def query(self, query: PersonalityQuery) -> List[PersonalityProfile]:
        """按条件检索, 结果按 created_at 倒序 (最新在前)"""

    @abstractmethod
    def count(self) -> int:
        """档案总数"""

    @abstractmethod
    def clear(self) -> int:
        """清空所有档案, 返回清理数量"""

    def close(self) -> None:
        """关闭存储 (释放资源)"""


__all__ = ["PersonalityStore", "PersonalityStoreError"]
