"""
YHLZ Embodied AI V4.1 - 世界模型 (World Model / State)

职责:
    - 环境状态保存 (内存历史)
    - 环境状态更新 (追加最新快照 + 记录状态变化历史)
    - 状态比较 (diff: 对象/位置/条件变化)
    - 状态查询 (最新 / 按 id / 按对象条件)
    - 为主体 (Agent) 提供环境状态认知

设计原则:
    - 内存存储 (本版本不落盘, 独立于 Agent Memory)
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
    - 只保存与比较, 不决策 (决策在 Service 层)
    - World Model 禁止直接执行 Action (必须经 Action Planner → Permission → Executor)
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from backend.embodied.schema import (
    EnvironmentObject,
    EnvironmentState,
    WorldStateHistory,
)

logger = logging.getLogger(__name__)


class WorldModelError(Exception):
    """世界模型操作异常"""


class WorldModel:
    """世界模型: 环境状态记忆与差异分析

    用法:
        wm = WorldModel(max_history=100)
        wm.update(state)                    # 保存 + 自动记录状态变化历史
        latest = wm.get_latest()
        diff = wm.diff_states(prev, curr)   # 状态比较
        changes = wm.state_changes(limit=5) # 最近变化历史
    """

    def __init__(self, max_history: int = 100):
        if max_history <= 0:
            raise WorldModelError(f"max_history 必须 > 0, 当前: {max_history}")
        self._lock = threading.RLock()
        self._states: Deque[EnvironmentState] = deque(maxlen=max_history)
        self._changes: Deque[WorldStateHistory] = deque(maxlen=max_history)
        self._max_history = max_history

    # ── 状态保存 / 更新 ───────────────────────────────────────────
    def update(self, state: EnvironmentState) -> str:
        """保存 / 更新状态快照, 返回 state_id

        自动与最新快照比较, 记录 WorldStateHistory (含变化摘要)
        """
        if state is None:
            raise WorldModelError("状态不能为 None")
        with self._lock:
            previous = self._states[-1] if self._states else None
            change: Dict[str, Any] = {}
            if previous is not None:
                change = self.diff_states(previous, state)
            self._states.append(state)
            if previous is not None:
                self._changes.append(WorldStateHistory.create(
                    previous_state=previous, current_state=state, change=change,
                ))
        logger.debug(
            f"[WorldModel] 已保存状态 state_id={state.state_id} "
            f"objects={len(state.objects)} change={change}"
        )
        return state.state_id

    # ── 状态比较 ──────────────────────────────────────────────────
    @staticmethod
    def diff_states(previous: EnvironmentState, current: EnvironmentState) -> Dict[str, Any]:
        """比较两个状态, 返回变化摘要

        Returns:
            {
                'added':    新增对象列表,
                'removed':  消失对象列表,
                'modified': 状态变化对象列表,
                'location': 主体位置变化 (None=未变),
                'conditions': 条件变化 (None=未变),
                'relations': 关系变化数量,
            }
        """
        if previous is None or current is None:
            return {"error": "状态缺失, 无法比较"}

        prev_objs = {o.object_id: o for o in previous.objects}
        curr_objs = {o.object_id: o for o in current.objects}

        added = [
            o.to_dict() for oid, o in curr_objs.items() if oid not in prev_objs
        ]
        removed = [
            o.to_dict() for oid, o in prev_objs.items() if oid not in curr_objs
        ]
        modified = []
        for oid, o in curr_objs.items():
            po = prev_objs.get(oid)
            if po is None:
                continue
            if (po.state != o.state or po.position != o.position
                    or po.properties != o.properties):
                modified.append({
                    "object_id": oid,
                    "name": o.name,
                    "state": {"from": po.state, "to": o.state},
                    "position": {"from": po.position, "to": o.position},
                })

        location_change: Optional[Dict[str, Any]] = None
        if previous.location != current.location:
            location_change = {"from": previous.location, "to": current.location}

        conditions_change: Optional[Dict[str, Any]] = None
        if previous.conditions != current.conditions:
            conditions_change = {"from": previous.conditions, "to": current.conditions}

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "location": location_change,
            "conditions": conditions_change,
            "relations_changed": len(previous.relations) != len(current.relations),
        }

    def compare(self, state_id_a: str, state_id_b: str) -> Dict[str, Any]:
        """按 state_id 比较两个历史状态

        Raises:
            WorldModelError: 任一状态不存在
        """
        a = self.get_state(state_id_a)
        b = self.get_state(state_id_b)
        if a is None:
            raise WorldModelError(f"状态不存在: {state_id_a}")
        if b is None:
            raise WorldModelError(f"状态不存在: {state_id_b}")
        return self.diff_states(a, b)

    def state_changes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近状态变化历史 (旧 → 新)"""
        with self._lock:
            changes = list(self._changes)
        if limit > 0:
            changes = changes[-limit:]
        return [c.to_dict() for c in changes]

    # ── 查询 ──────────────────────────────────────────────────────
    def get_latest(self) -> Optional[EnvironmentState]:
        """获取最新状态快照 (None=尚无状态)"""
        with self._lock:
            if not self._states:
                return None
            return self._states[-1]

    def get_state(self, state_id: str) -> Optional[EnvironmentState]:
        """按 state_id 查询状态 (None=未找到)"""
        with self._lock:
            for s in reversed(self._states):
                if s.state_id == state_id:
                    return s
        return None

    def history(self, limit: Optional[int] = None) -> List[EnvironmentState]:
        """获取历史状态 (旧 → 新)"""
        with self._lock:
            states = list(self._states)
        if limit is not None and limit > 0:
            states = states[-limit:]
        return states

    def history_dicts(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取历史状态 (dict 形式, 便于序列化)"""
        return [s.to_dict() for s in self.history(limit=limit)]

    # ── 对象查询 ──────────────────────────────────────────────────
    def find_objects(
        self,
        name: Optional[str] = None,
        category: Optional[str] = None,
        state: Optional[str] = None,
        use_latest: bool = True,
    ) -> List[EnvironmentObject]:
        """按条件查询对象 (默认查最新状态)"""
        with self._lock:
            sources: List[EnvironmentState] = []
            if use_latest:
                if self._states:
                    sources = [self._states[-1]]
            else:
                sources = list(self._states)

        results: List[EnvironmentObject] = []
        for s in sources:
            for obj in s.objects:
                if name and obj.name != name:
                    continue
                if category and obj.category != category:
                    continue
                if state and obj.state != state:
                    continue
                results.append(obj)
        return results

    def object_count(self) -> int:
        """最新状态中的对象数量 (0=无状态)"""
        latest = self.get_latest()
        if latest is None:
            return 0
        return len(latest.objects)

    # ── 统计 / 生命周期 ───────────────────────────────────────────
    def count(self) -> int:
        """历史状态数量"""
        with self._lock:
            return len(self._states)

    def change_count(self) -> int:
        """状态变化历史数量"""
        with self._lock:
            return len(self._changes)

    def reset(self) -> int:
        """清空历史, 返回清理数量"""
        with self._lock:
            n = len(self._states) + len(self._changes)
            self._states.clear()
            self._changes.clear()
        logger.info(f"[WorldModel] 历史已清空, 清理 {n} 条")
        return n

    @property
    def max_history(self) -> int:
        with self._lock:
            return self._max_history


__all__ = ["WorldModel", "WorldModelError"]
