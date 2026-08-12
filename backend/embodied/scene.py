"""
YHLZ Embodied AI V4.3 - 场景生命周期管理器 (Scene Lifecycle Manager)

职责:
    - 记录场景迁移 (switch_environment 的迁移元数据)
    - 场景摘要 (Scene Summary): 活动对象 / 事件数 / 失败数 / 主体位置 / 条件
    - 同名对象状态变化检测 (P1 场景迁移认知)
    - 只记录与查询, 不执行动作 (切换流程由 Service 编排)

设计原则:
    - 迁移记录不可变: 记录后不修改, 保证复盘可信
    - 数据独立存储: 绝不写入 Agent Memory
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from backend.embodied.schema import EnvironmentObject, EnvironmentState

logger = logging.getLogger(__name__)


class SceneManagerError(Exception):
    """场景管理器操作异常"""


class SceneManager:
    """场景迁移记录器 (V4.3)

    用法:
        mgr = SceneManager(max_migrations=20)
        mgr.record_migration({...})
        latest = mgr.latest()
    """

    def __init__(self, max_migrations: int = 20):
        if max_migrations <= 0:
            raise SceneManagerError(f"max_migrations 必须 > 0, 当前: {max_migrations}")
        self._lock = threading.RLock()
        self._migrations: Deque[Dict[str, Any]] = deque(maxlen=max_migrations)
        self._max_migrations = max_migrations

    # ── 迁移记录 ──────────────────────────────────────────────────
    def record_migration(self, migration: Dict[str, Any]) -> str:
        """记录一次场景迁移, 返回 migration_id

        Args:
            migration: 迁移信息 (from / to / previous_scene / new_scene /
                       same_name_changes / events_count / failures / active_objects)
        """
        if migration is None:
            raise SceneManagerError("迁移信息不能为 None")
        migration_id = uuid.uuid4().hex
        record = dict(migration)
        record["migration_id"] = migration_id
        record.setdefault("timestamp", time.time())
        with self._lock:
            self._migrations.append(record)
        logger.info(
            f"[Scene] 场景迁移记录: {record.get('from')} → {record.get('to')}"
        )
        return migration_id

    # ── 查询 ──────────────────────────────────────────────────────
    def latest(self) -> Optional[Dict[str, Any]]:
        """最近一次场景迁移 (None=从未切换)"""
        with self._lock:
            if not self._migrations:
                return None
            return self._migrations[-1]

    def migrations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """迁移历史 (最新在前)"""
        with self._lock:
            out = list(reversed(self._migrations))
        return out[:limit] if limit > 0 else out

    def count(self) -> int:
        with self._lock:
            return len(self._migrations)

    # ── 同名对象状态变化检测 (P1 场景迁移认知) ────────────────────
    @staticmethod
    def same_name_object_changes(
        previous_objects: List[EnvironmentObject],
        new_objects: List[EnvironmentObject],
    ) -> List[Dict[str, Any]]:
        """检测场景切换后同名对象的状态/位置变化

        Args:
            previous_objects: 切换前场景对象
            new_objects:      切换后场景对象

        Returns:
            [{'name': 'door', 'state': {'from': 'open', 'to': 'closed'},
              'position': {'from': {...}, 'to': {...}}}, ...]
        """
        prev_by_name: Dict[str, EnvironmentObject] = {}
        for obj in previous_objects or []:
            if obj.name not in prev_by_name:
                prev_by_name[obj.name] = obj

        changes: List[Dict[str, Any]] = []
        for obj in new_objects or []:
            prev = prev_by_name.get(obj.name)
            if prev is None:
                continue
            if obj.state != prev.state or obj.position != prev.position:
                changes.append({
                    "name": obj.name,
                    "state": {"from": prev.state, "to": obj.state},
                    "position": {"from": prev.position, "to": obj.position},
                })
        return changes

    # ── 场景摘要 ──────────────────────────────────────────────────
    @staticmethod
    def build_summary(
        env_name: str,
        scene: str,
        state: Optional[EnvironmentState],
        events_stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建场景摘要 (Scene Summary)

        内容: 环境 / 场景 / 活动对象 / 对象数 / 事件数 / 失败数 / 位置 / 条件
        """
        objects = list(state.objects) if state is not None else []
        events = events_stats or {}
        by_result = events.get("by_result", {}) or {}
        return {
            "environment": env_name,
            "scene": scene,
            "active_objects": [o.name for o in objects],
            "object_count": len(objects),
            "events_count": int(events.get("total", 0)),
            "failures": int(by_result.get("failure", 0)),
            "location": state.location if state is not None else {},
            "conditions": state.conditions if state is not None else {},
            "timestamp": time.time(),
        }

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        with self._lock:
            n = len(self._migrations)
            self._migrations.clear()
        logger.info(f"[Scene] 迁移记录已清空, 清理 {n} 条")
        return n

    @property
    def max_migrations(self) -> int:
        with self._lock:
            return self._max_migrations


__all__ = ["SceneManager", "SceneManagerError"]
