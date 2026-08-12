"""
YHLZ Personality Engine V3.4 - 内存人格存储

职责:
    - 测试用 / 轻量场景的内存实现
    - 与 SQLite 实现同一接口 (PersonalityStore)
    - 容量上限 (超过删除最旧)

设计原则:
    - 线程安全 (RLock)
    - 无持久化 (进程内)
    - 查询结果按 created_at 倒序
    - 同时间戳按插入序号稳定排序
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

from backend.personality.interface import PersonalityStore, PersonalityStoreError
from backend.personality.schema import PersonalityProfile, PersonalityQuery

logger = logging.getLogger(__name__)


class InMemoryPersonalityStore(PersonalityStore):
    """内存人格存储

    用法:
        store = InMemoryPersonalityStore(max_entries=100)
        store.save(profile)
        profiles = store.query(PersonalityQuery(keyword="温暖"))
    """

    def __init__(self, max_entries: int = 100):
        self._lock = threading.RLock()
        self._max_entries = max_entries
        self._profiles: Dict[str, PersonalityProfile] = {}
        self._seq: Dict[str, int] = {}  # id → 插入序号
        self._counter = 0

    @property
    def name(self) -> str:
        return "memory"

    def save(self, profile: PersonalityProfile) -> str:
        with self._lock:
            try:
                self._counter += 1
                if profile.profile_id not in self._profiles:
                    self._seq[profile.profile_id] = self._counter
                self._profiles[profile.profile_id] = profile
                # 容量控制: 超过上限删除最旧
                if len(self._profiles) > self._max_entries:
                    overflow = len(self._profiles) - self._max_entries
                    oldest = sorted(
                        self._profiles.values(),
                        key=lambda p: (p.created_at, self._seq.get(p.profile_id, 0)),
                    )[:overflow]
                    for p in oldest:
                        self._profiles.pop(p.profile_id, None)
                        self._seq.pop(p.profile_id, None)
                return profile.profile_id
            except Exception as e:
                raise PersonalityStoreError(f"内存保存失败: {e}") from e

    def retrieve(self, profile_id: str) -> Optional[PersonalityProfile]:
        with self._lock:
            try:
                return self._profiles.get(profile_id)
            except Exception as e:
                raise PersonalityStoreError(f"内存获取失败: {e}") from e

    def update(self, profile_id: str, **fields) -> bool:
        with self._lock:
            try:
                profile = self._profiles.get(profile_id)
                if profile is None:
                    return False
                allowed = {
                    "name", "description", "traits", "tone",
                    "preferences", "guidelines", "active",
                }
                valid = {k: v for k, v in fields.items() if k in allowed}
                if not valid:
                    return False
                for key, value in valid.items():
                    setattr(profile, key, value)
                profile.updated_at = time.time()
                return True
            except Exception as e:
                raise PersonalityStoreError(f"内存更新失败: {e}") from e

    def delete(self, profile_id: str) -> bool:
        with self._lock:
            try:
                removed = self._profiles.pop(profile_id, None) is not None
                if removed:
                    self._seq.pop(profile_id, None)
                return removed
            except Exception as e:
                raise PersonalityStoreError(f"内存删除失败: {e}") from e

    def query(self, query: PersonalityQuery) -> List[PersonalityProfile]:
        with self._lock:
            try:
                profiles = list(self._profiles.values())
            except Exception as e:
                raise PersonalityStoreError(f"内存读取失败: {e}") from e
        # 过滤 (在锁外执行, 防止长查询阻塞写入)
        results = self._filter(profiles, query)
        # 排序: created_at 倒序, 同时间戳按插入顺序倒序 (最新在前)
        results.sort(
            key=lambda p: (p.created_at, self._seq.get(p.profile_id, 0)),
            reverse=True,
        )
        return results[query.offset:query.offset + query.limit]

    def _filter(
        self,
        profiles: List[PersonalityProfile],
        query: PersonalityQuery,
    ) -> List[PersonalityProfile]:
        results = []
        for p in profiles:
            if query.active_only and not p.active:
                continue
            if query.keyword:
                haystack = f"{p.name} {p.description} {p.tone}"
                if query.keyword not in haystack:
                    continue
            if query.trait_filter:
                match = True
                for trait, threshold in query.trait_filter.items():
                    if p.traits.get(trait, 0.0) < threshold:
                        match = False
                        break
                if not match:
                    continue
            results.append(p)
        return results

    def count(self) -> int:
        with self._lock:
            try:
                return len(self._profiles)
            except Exception as e:
                raise PersonalityStoreError(f"内存计数失败: {e}") from e

    def clear(self) -> int:
        with self._lock:
            try:
                n = len(self._profiles)
                self._profiles.clear()
                self._seq.clear()
                return n
            except Exception as e:
                raise PersonalityStoreError(f"内存清空失败: {e}") from e

    def close(self) -> None:
        with self._lock:
            self._profiles.clear()
            self._seq.clear()


__all__ = ["InMemoryPersonalityStore"]
