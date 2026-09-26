"""
YHLZ Agent Core V3.0 - 记忆管理器

职责:
    - 包装 MemoryStore, 提供业务级 API
    - 异步接口 (asyncio.to_thread 包装同步 SQLite)
    - 对话记忆自动存储 (store_dialogue)
    - 记忆自动提取 (LLM 从对话中提取事实)
    - 记忆衰减 (长期未访问降权)
    - 短期记忆 (内存, 最近 N 条对话)

设计:
    - 不直接暴露 MemoryStore, 通过 Manager 统一访问
    - 异步接口供 AgentBrain 调用
    - Mock 模式: 自动提取用规则代替 LLM
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any, Dict, List, Optional

from backend.agent.memory.base import MemoryEntry, MemoryStore, MemoryStoreError
from backend.agent.memory.sqlite_store import SQLiteMemoryStore

logger = logging.getLogger(__name__)


class MemoryManagerError(Exception):
    """记忆管理器错误"""


_VALID_CATEGORIES = {"fact", "preference", "event", "dialogue", "skill"}


class MemoryManager:
    """记忆管理器

    用法:
        mgr = MemoryManager()
        await mgr.add_async(MemoryEntry.create("用户喜欢咖啡", "preference"))
        results = await mgr.search_async("咖啡")
        await mgr.store_dialogue_async("我喜欢红茶", "好的, 记住了")
    """

    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        llm_adapter: Optional[Any] = None,
        short_term_size: int = 20,
        enable_auto_extract: bool = True,
    ):
        self._store = store or SQLiteMemoryStore()
        self._llm = llm_adapter
        self._short_term: deque = deque(maxlen=short_term_size)
        self._enable_auto_extract = enable_auto_extract

    @property
    def store(self) -> MemoryStore:
        return self._store

    # ------------------------------------------------------------------
    # 同步包装
    # ------------------------------------------------------------------

    def add(self, content: str, category: str = "fact", source: str = "system",
            metadata: Optional[Dict[str, Any]] = None) -> str:
        """添加记忆 (同步)"""
        if category not in _VALID_CATEGORIES:
            raise MemoryManagerError(f"无效 category: {category}, 应为 { _VALID_CATEGORIES}")
        entry = MemoryEntry.create(content=content, category=category, source=source, metadata=metadata)
        try:
            return self._store.add(entry)
        except MemoryStoreError as e:
            raise MemoryManagerError(str(e)) from e

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        try:
            return self._store.get(memory_id)
        except MemoryStoreError as e:
            raise MemoryManagerError(str(e)) from e

    def update(self, memory_id: str, **fields) -> bool:
        try:
            return self._store.update(memory_id, **fields)
        except MemoryStoreError as e:
            raise MemoryManagerError(str(e)) from e

    def delete(self, memory_id: str) -> bool:
        try:
            return self._store.delete(memory_id)
        except MemoryStoreError as e:
            raise MemoryManagerError(str(e)) from e

    def list_all(self, category: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[MemoryEntry]:
        try:
            return self._store.list_all(category=category, limit=limit, offset=offset)
        except MemoryStoreError as e:
            raise MemoryManagerError(str(e)) from e

    def search(self, query: str, limit: int = 5, category: Optional[str] = None) -> List[MemoryEntry]:
        try:
            return self._store.search(query, limit=limit, category=category)
        except MemoryStoreError as e:
            raise MemoryManagerError(str(e)) from e

    def count(self, category: Optional[str] = None) -> int:
        try:
            return self._store.count(category=category)
        except MemoryStoreError as e:
            raise MemoryManagerError(str(e)) from e

    def clear(self) -> int:
        try:
            n = self._store.clear()
            self._short_term.clear()
            return n
        except MemoryStoreError as e:
            raise MemoryManagerError(str(e)) from e

    # ------------------------------------------------------------------
    # 异步接口
    # ------------------------------------------------------------------

    async def add_async(self, content: str, category: str = "fact", source: str = "system",
                        metadata: Optional[Dict[str, Any]] = None) -> str:
        return await asyncio.to_thread(self.add, content, category, source, metadata)

    async def get_async(self, memory_id: str) -> Optional[MemoryEntry]:
        return await asyncio.to_thread(self.get, memory_id)

    async def update_async(self, memory_id: str, **fields) -> bool:
        return await asyncio.to_thread(self.update, memory_id, **fields)

    async def delete_async(self, memory_id: str) -> bool:
        return await asyncio.to_thread(self.delete, memory_id)

    async def list_async(self, category: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[MemoryEntry]:
        return await asyncio.to_thread(self.list_all, category, limit, offset)

    async def search_async(self, query: str, limit: int = 5, category: Optional[str] = None) -> List[MemoryEntry]:
        return await asyncio.to_thread(self.search, query, limit, category)

    async def count_async(self, category: Optional[str] = None) -> int:
        return await asyncio.to_thread(self.count, category)

    async def clear_async(self) -> int:
        return await asyncio.to_thread(self.clear)

    # ------------------------------------------------------------------
    # 对话存储 + 自动提取
    # ------------------------------------------------------------------

    async def store_dialogue_async(
        self,
        user_input: str,
        assistant_response: str,
        extract: Optional[bool] = None,
    ) -> int:
        """存储一次对话, 返回存储的记忆条数

        Args:
            user_input: 用户输入
            assistant_response: 助手回复
            extract: 是否自动提取事实 (None=用默认)
        """
        # 1. 短期记忆
        self._short_term.append({
            "user": user_input,
            "assistant": assistant_response,
            "timestamp": time.time(),
        })

        # 2. 长期对话记忆
        dialogue_text = f"用户: {user_input}\n元亨: {assistant_response}"
        try:
            await self.add_async(
                content=dialogue_text,
                category="dialogue",
                source="system",
                metadata={"user": user_input, "assistant": assistant_response},
            )
        except Exception as e:
            logger.warning(f"存储对话记忆失败: {e}")
            return 0

        stored = 1

        # 3. 自动提取事实 (可选)
        should_extract = self._enable_auto_extract if extract is None else extract
        if should_extract:
            try:
                facts = await self._extract_facts_async(user_input, assistant_response)
                for fact in facts:
                    try:
                        await self.add_async(content=fact, category="fact", source="assistant")
                        stored += 1
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"自动提取事实失败: {e}")

        return stored

    async def _extract_facts_async(self, user_input: str, assistant_response: str) -> List[str]:
        """从对话中提取值得记忆的事实"""
        # Mock / 无 LLM: 规则提取
        if self._llm is None:
            return self._rule_extract_facts(user_input, assistant_response)

        # LLM 提取
        try:
            from backend.agent.schemas import Message
            prompt = f"""从以下对话中提取值得长期记忆的事实 (用户偏好、个人信息、重要决定等)。
            如果没有值得记忆的事实, 返回空数组 []。
            输出 JSON 数组, 每项是一个字符串, 不要其他文字。

            对话:
            用户: {user_input}
            元亨: {assistant_response}"""
            text = await self._llm.generate(
                [Message.user(prompt)], temperature=0.1, max_tokens=256
            )
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            facts = json.loads(text)
            if isinstance(facts, list):
                return [str(f) for f in facts if f]
            return []
        except Exception as e:
            logger.warning(f"LLM 提取事实失败, 退化规则: {e}")
            return self._rule_extract_facts(user_input, assistant_response)

    def _rule_extract_facts(self, user_input: str, assistant_response: str) -> List[str]:
        """规则提取 (无 LLM 时)"""
        facts: List[str] = []
        # 偏好关键词
        preferences = ["喜欢", "爱好", "最爱", "讨厌", "想要", "希望", "需要"]
        for kw in preferences:
            if kw in user_input:
                # 截取关键词所在句
                idx = user_input.find(kw)
                end = user_input.find("。", idx)
                if end == -1:
                    end = len(user_input)
                snippet = user_input[max(0, idx-5):end].strip()
                facts.append(f"用户{snippet}")
                break
        # 姓名/身份
        if "我叫" in user_input:
            idx = user_input.find("我叫") + 2
            end = user_input.find("，", idx)
            if end == -1:
                end = min(idx + 10, len(user_input))
            name = user_input[idx:end].strip("，。！？ ")
            if name:
                facts.append(f"用户名字: {name}")
        return facts[:3]  # 最多 3 条

    # ------------------------------------------------------------------
    # 短期记忆
    # ------------------------------------------------------------------

    def get_short_term(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取短期记忆 (最近对话)"""
        items = list(self._short_term)
        return items[-limit:] if limit < len(items) else items

    def clear_short_term(self) -> None:
        """清空短期记忆"""
        self._short_term.clear()

    # ------------------------------------------------------------------
    # 衰减
    # ------------------------------------------------------------------

    def decay(self, threshold_seconds: float = 30 * 86400, decay_weight: float = 0.5) -> int:
        """衰减长期未访问的记忆权重

        Args:
            threshold_seconds: 阈值秒数 (默认 30 天)
            decay_weight: 衰减后的权重 (默认 0.5)

        Returns:
            衰减的记忆数
        """
        # 直接 SQL 批量更新
        try:
            store = self._store
            if not hasattr(store, "_conn") or store._conn is None:
                return 0
            now = time.time()
            cutoff = now - threshold_seconds
            cur = store._conn.execute(
                "UPDATE agent_memories SET weight = ? WHERE last_accessed_at < ? AND weight > ?",
                (decay_weight, cutoff, decay_weight),
            )
            return cur.rowcount
        except Exception as e:
            logger.warning(f"衰减失败: {e}")
            return 0

    def close(self) -> None:
        try:
            self._store.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# 全局单例
# ----------------------------------------------------------------------

_manager_instance: Optional[MemoryManager] = None
_manager_lock = None  # 延迟初始化, 避免无事件循环时报错


def _get_lock():
    import threading
    global _manager_lock
    if _manager_lock is None:
        _manager_lock = threading.Lock()
    return _manager_lock


def get_memory_manager() -> MemoryManager:
    """获取全局记忆管理器"""
    global _manager_instance
    if _manager_instance is not None:
        return _manager_instance
    with _get_lock():
        if _manager_instance is not None:
            return _manager_instance
        _manager_instance = MemoryManager()
        return _manager_instance


def reset_memory_manager() -> None:
    """重置全局管理器 (测试用)"""
    global _manager_instance
    with _get_lock():
        if _manager_instance is not None:
            try:
                _manager_instance.close()
            except Exception:
                pass
        _manager_instance = None


__all__ = [
    "MemoryManager", "MemoryManagerError",
    "get_memory_manager", "reset_memory_manager",
]
