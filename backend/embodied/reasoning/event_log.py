"""
YHLZ Embodied AI V4.2 - 环境事件日志 (Environment Event Log)

职责:
    - 环境事件时间线: 动作记录 / 结果记录 / 对象变化 / 主体位置
    - 从"当前状态"升级为"过去发生了什么 → 为什么发生 → 造成什么结果"
    - 支持时间线查询: get_events() / event_history()
    - JSONL 持久化 (跨进程可加载)

设计原则:
    - 只记录不执行: 本模块不产生任何动作, 仅接收事件
    - 事件不可变: 一旦记录不可修改, 保证时间线可信
    - 线程安全 (RLock)
    - 数据独立存储 (绝不写入 Agent Memory)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import json
import logging
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from backend.embodied.schema import (
    CauseType,
    EmbodiedAction,
    EnvironmentEvent,
    EventType,
    FeedbackResult,
)

logger = logging.getLogger(__name__)


class EnvironmentEventLogError(Exception):
    """环境事件日志操作异常"""


class EnvironmentEventLog:
    """环境事件日志 (时间线)

    用法:
        log = EnvironmentEventLog(max_events=200)
        log.record_action(action, result='success', change={...})
        events = log.get_events(limit=10)
        dicts = log.event_history(event_type='failure', limit=5)
        log.save_to_file(path) / log.load_from_file(path)
    """

    def __init__(self, max_events: int = 200):
        if max_events <= 0:
            raise EnvironmentEventLogError(f"max_events 必须 > 0, 当前: {max_events}")
        self._lock = threading.RLock()
        self._events: Deque[EnvironmentEvent] = deque(maxlen=max_events)
        self._max_events = max_events

    # ── 记录 ──────────────────────────────────────────────────────
    def record(
        self,
        event: EnvironmentEvent,
    ) -> str:
        """记录一条事件, 返回 event_id"""
        if event is None:
            raise EnvironmentEventLogError("事件不能为 None")
        with self._lock:
            self._events.append(event)
        logger.debug(
            f"[EventLog] 记录 event_type={event.event_type} "
            f"action_type={event.action_type} result={event.result}"
        )
        return event.event_id

    def record_action(
        self,
        action: Optional[EmbodiedAction] = None,
        result: str = FeedbackResult.SUCCESS.value,
        change: Optional[Dict[str, Any]] = None,
        cause: Optional[str] = None,
        object_changes: Optional[List[Dict[str, Any]]] = None,
        position_from: Optional[List[float]] = None,
        position_to: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录动作执行事件 (含结果 / 对象变化 / 主体位置 / 因果)"""
        change = change or {}
        summary = self._summarize_action(action, result, change, cause)
        event_type = (
            EventType.FAILURE.value
            if result == FeedbackResult.FAILURE.value
            else EventType.ACTION.value
        )
        event = EnvironmentEvent.create(
            event_type=event_type,
            action_id=action.action_id if action else "",
            action_type=action.action_type if action else "",
            target=action.target if action else "",
            result=result,
            cause=cause,
            object_changes=object_changes or [],
            position_from=position_from,
            position_to=position_to,
            summary=summary,
            metadata=metadata or {},
        )
        return self.record(event)

    def record_object_change(
        self,
        name: str,
        state_from: str,
        state_to: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录对象状态变化事件"""
        change = {
            "name": name,
            "state": {"from": state_from, "to": state_to},
        }
        event = EnvironmentEvent.create(
            event_type=EventType.OBJECT_CHANGE.value,
            object_changes=[change],
            summary=f"对象 {name} 状态变化: {state_from} → {state_to}",
            metadata=metadata or {},
        )
        return self.record(event)

    def record_move(
        self,
        position_from: Optional[List[float]],
        position_to: Optional[List[float]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录主体位置变化事件"""
        event = EnvironmentEvent.create(
            event_type=EventType.MOVE.value,
            position_from=list(position_from) if position_from else None,
            position_to=list(position_to) if position_to else None,
            summary=f"主体位置变化: {position_from} → {position_to}",
            metadata=metadata or {},
        )
        return self.record(event)

    def record_reset(
        self,
        scene: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录环境重置事件"""
        event = EnvironmentEvent.create(
            event_type=EventType.RESET.value,
            summary=f"环境已重置 (scene={scene or 'unknown'})",
            metadata=metadata or {},
        )
        return self.record(event)

    def record_observe(
        self,
        objects: int = 0,
        position: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录观察快照事件"""
        event = EnvironmentEvent.create(
            event_type=EventType.OBSERVE.value,
            summary=f"观察环境: objects={objects} position={position or {}}",
            metadata=metadata or {},
        )
        return self.record(event)

    def record_system(
        self,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录系统事件 (启用 / 停用 / 加载记忆等)"""
        event = EnvironmentEvent.create(
            event_type=EventType.SYSTEM.value,
            summary=summary,
            metadata=metadata or {},
        )
        return self.record(event)

    @staticmethod
    def _summarize_action(
        action: Optional[EmbodiedAction],
        result: str,
        change: Dict[str, Any],
        cause: Optional[str],
    ) -> str:
        """生成动作事件摘要 (供 LLM 上下文, 一句话)"""
        action_type = action.action_type if action else "unknown"
        target = action.target if action else ""
        name = str((action.parameters if action else {}).get("object") or target or "")
        event_name = change.get("event", action_type)
        if result == FeedbackResult.SUCCESS.value:
            detail = f"成功 ({event_name})"
        elif result == FeedbackResult.NO_CHANGE.value:
            detail = f"无变化 ({event_name})"
        elif result == FeedbackResult.FAILURE.value:
            detail = f"失败 ({event_name})"
        else:
            detail = f"结果={result}"
        if cause:
            detail += f" 原因={cause}"
        if name:
            detail += f" 对象={name}"
        return f"{action_type} {detail}"

    # ── 查询 ──────────────────────────────────────────────────────
    def get_events(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
        action_type: Optional[str] = None,
        result: Optional[str] = None,
    ) -> List[EnvironmentEvent]:
        """查询事件 (最新在前, 支持按类型/动作/结果过滤)"""
        if limit <= 0:
            return []
        with self._lock:
            events = list(self._events)
        out: List[EnvironmentEvent] = []
        for e in reversed(events):
            if event_type and e.event_type != event_type:
                continue
            if action_type and e.action_type != action_type:
                continue
            if result and e.result != result:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def event_history(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
        action_type: Optional[str] = None,
        result: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询事件 (dict 形式, 便于序列化进 LLM 上下文)"""
        return [
            e.to_dict()
            for e in self.get_events(
                limit=limit, event_type=event_type,
                action_type=action_type, result=result,
            )
        ]

    def get(self, event_id: str) -> Optional[EnvironmentEvent]:
        """按 event_id 查询事件"""
        with self._lock:
            for e in reversed(self._events):
                if e.event_id == event_id:
                    return e
        return None

    def count(self) -> int:
        with self._lock:
            return len(self._events)

    def stats(self) -> Dict[str, Any]:
        """统计: 各事件类型 / 结果分布"""
        with self._lock:
            events = list(self._events)
        types: Dict[str, int] = {}
        results: Dict[str, int] = {}
        causes: Dict[str, int] = {}
        for e in events:
            types[e.event_type] = types.get(e.event_type, 0) + 1
            if e.result:
                results[e.result] = results.get(e.result, 0) + 1
            if e.cause:
                causes[e.cause] = causes.get(e.cause, 0) + 1
        return {
            "total": len(events),
            "by_type": types,
            "by_result": results,
            "by_cause": causes,
        }

    def failure_events(self, limit: int = 20) -> List[EnvironmentEvent]:
        """最近失败事件 (含因果)"""
        return self.get_events(limit=limit, event_type=EventType.FAILURE.value)

    # ── 持久化 (JSONL) ────────────────────────────────────────────
    def save_to_file(self, path: str) -> int:
        """保存全部事件到 JSONL 文件 (旧 → 新)"""
        with self._lock:
            events = list(self._events)
        with open(path, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[EventLog] 已保存到 {path}, 共 {len(events)} 条")
        return len(events)

    def load_from_file(self, path: str) -> int:
        """从 JSONL 文件加载事件 (追加到时间线)"""
        loaded: List[EnvironmentEvent] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    loaded.append(EnvironmentEvent.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"[EventLog] 跳过坏行: {e}")
        with self._lock:
            for e in loaded:
                self._events.append(e)
        logger.info(f"[EventLog] 已从 {path} 加载 {len(loaded)} 条")
        return len(loaded)

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空事件, 返回清理数量"""
        with self._lock:
            n = len(self._events)
            self._events.clear()
        logger.info(f"[EventLog] 事件已清空, 清理 {n} 条")
        return n

    @property
    def max_events(self) -> int:
        with self._lock:
            return self._max_events


__all__ = ["EnvironmentEventLog", "EnvironmentEventLogError"]
