"""
YHLZ Vision Memory V1.0 - 视觉记忆 Manager

职责:
    - 管理 MemoryStore 生命周期 (注册/注销/查询)
    - 路由记忆操作到对应 Store
    - 不直接对外暴露 (Service 调用)

架构位置:
    Service → Manager → Store (Adapter / Storage)

设计原则:
    - 注册表模式: 多 Store 共存
    - 默认注册: 测试模式内存 Store / 生产 SQLite Store
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.vision.memory.interface import MemoryStore
from backend.vision.memory.schema import MemoryQuery, VisualMemoryRecord

logger = logging.getLogger(__name__)


class MemoryManagerError(Exception):
    """Memory Manager 操作异常"""


class MemoryManager:
    """视觉记忆管理器

    用法:
        mgr = MemoryManager()
        mgr.register_defaults(db_path="backend/data/vision_memories.db")
        record_id = mgr.save(record)

    职责:
        - Store 注册表
        - 路由记忆操作到对应 Store
        - 不做权限校验 (Service 层负责)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._stores: Dict[str, MemoryStore] = {}
        self._default_registered = False

    # ── 注册管理 ──────────────────────────────────────────────────
    def register_store(
        self,
        name: str,
        store: MemoryStore,
        override: bool = False,
    ) -> None:
        """注册记忆 Store

        Args:
            name: Store 名 (如 'sqlite' / 'memory')
            store: MemoryStore 实例
            override: 是否覆盖已注册的同名 Store
        """
        with self._lock:
            if name in self._stores and not override:
                raise MemoryManagerError(
                    f"MemoryStore {name} 已注册, override=False"
                )
            self._stores[name] = store
            logger.info(
                f"已注册 MemoryStore: name={name} class={store.__class__.__name__}"
            )

    def unregister_store(self, name: str) -> bool:
        with self._lock:
            store = self._stores.pop(name, None)
            if store is not None:
                logger.info(f"已注销 MemoryStore: name={name}")
                return True
            return False

    # ── 查询 ──────────────────────────────────────────────────────
    def get_store(self, name: str) -> Optional[MemoryStore]:
        with self._lock:
            return self._stores.get(name)

    def get_default_store(self) -> Optional[MemoryStore]:
        """获取默认 Store (第一个注册的)"""
        with self._lock:
            if not self._stores:
                return None
            return next(iter(self._stores.values()))

    def list_stores(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {"name": name, "class": store.__class__.__name__}
                for name, store in self._stores.items()
            ]

    def list_names(self) -> List[str]:
        with self._lock:
            return list(self._stores.keys())

    def has_store(self, name: str) -> bool:
        with self._lock:
            return name in self._stores

    # ── 执行 ──────────────────────────────────────────────────────
    def save(self, record: VisualMemoryRecord) -> str:
        """保存记录到默认 Store (None=无 Store)"""
        store = self.get_default_store()
        if store is None:
            raise MemoryManagerError("无可用 MemoryStore (default)")
        try:
            return store.save(record)
        except Exception as e:
            logger.error(f"[MemoryManager] Store {store.name} 保存异常: {e}", exc_info=True)
            raise MemoryManagerError(f"保存失败: {type(e).__name__}: {e}") from e

    # ── 默认注册 ──────────────────────────────────────────────────
    def register_defaults(
        self,
        include_memory: bool = True,
        db_path: Optional[str] = None,
    ) -> None:
        """注册默认 Store

        Args:
            include_memory: 是否包含内存 Store (测试环境必需)
            db_path: SQLite 数据库路径 (None=默认)
        """
        with self._lock:
            if self._default_registered:
                return

            # 测试模式强制内存 (YHLZ_VISION_MEMORY_TEST_MODE=true)
            import os as _os
            if _os.getenv("YHLZ_VISION_MEMORY_TEST_MODE", "false").lower() == "true":
                if include_memory:
                    self._stores["memory"] = self._build_memory_store()
                    logger.info("测试模式: 默认注册内存 MemoryStore")
                self._default_registered = True
                return

            # 生产默认 SQLite, 失败回退内存
            try:
                from backend.vision.memory.stores.sqlite_store import SQLiteMemoryStore
                self._stores["sqlite"] = SQLiteMemoryStore(db_path=db_path)
                logger.info(f"默认注册 SQLiteMemoryStore (db={db_path or '默认路径'})")
            except Exception as e:
                logger.warning(f"SQLiteMemoryStore 加载失败, 回退内存: {e}")
                if include_memory:
                    self._stores["memory"] = self._build_memory_store()
                    logger.info("回退注册内存 MemoryStore")

            self._default_registered = True

    def _build_memory_store(self) -> MemoryStore:
        from backend.vision.memory.stores.memory_store import InMemoryMemoryStore
        return InMemoryMemoryStore()

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "stores_count": len(self._stores),
                "stores": self.list_stores(),
                "default_registered": self._default_registered,
                "default_store": (
                    self.get_default_store().name if self.get_default_store() else None
                ),
            }

    def reset(self) -> None:
        """清空所有注册"""
        with self._lock:
            self._stores.clear()
            self._default_registered = False


# ── 全局单例 ─────────────────────────────────────────────────────
_global_manager: Optional[MemoryManager] = None
_manager_lock = threading.Lock()


def get_manager(db_path: Optional[str] = None) -> MemoryManager:
    """获取全局 MemoryManager 单例

    Args:
        db_path: 首次创建时指定 SQLite 数据库路径 (None=默认)
    """
    global _global_manager
    with _manager_lock:
        if _global_manager is None:
            _global_manager = MemoryManager()
            _global_manager.register_defaults(include_memory=True, db_path=db_path)
        return _global_manager


def reset_manager() -> None:
    """重置全局 Manager (测试用)"""
    global _global_manager
    with _manager_lock:
        if _global_manager is not None:
            _global_manager.reset()
        _global_manager = None


__all__ = [
    "MemoryManager",
    "MemoryManagerError",
    "get_manager",
    "reset_manager",
]
