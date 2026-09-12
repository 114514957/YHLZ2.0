"""
YHLZ Embodied AI V10.1 - 伙伴交互状态 (Partner Interaction State)

职责:
    - 保存伙伴交互状态: 当前协作目标 / 当前交流模式 / 当前任务关系
    - 交互状态 ≠ 人格 (人格属于 Identity Layer, 交互状态只描述协作关系)
    - 状态可查询 / 可重置 / 可审计

设计原则:
    - 交互状态不修改人格 / 不写 Identity
    - 只记录协作关系, 不记录情感表演
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PartnerStateError(Exception):
    """伙伴交互状态异常"""


# 任务关系枚举 (可解释)
TASK_RELATIONS: List[str] = [
    "none",       # 无协作
    "collaborate",# 协作中
    "guide",      # 伙伴引导用户
    "follow",     # 伙伴跟随用户
    "review",     # 复盘关系
]


class PartnerInteractionState:
    """伙伴交互状态管理器 (V10.1)

    用法:
        p = PartnerInteractionState()
        p.set_goal("共同完成项目")
        p.set_relation("collaborate")
        state = p.snapshot()
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._goal: str = ""
        self._relation: str = "none"
        self._mode: str = "casual"
        self._session_count: int = 0
        self._last_activity: float = 0.0

    def set_goal(self, goal: str) -> Dict[str, Any]:
        """设置当前协作目标"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "伙伴交互状态停用"}
            self._goal = str(goal).strip()
            self._touch()
            return {
                "mode": "rule_based", "ok": True,
                "goal": self._goal,
            }

    def set_relation(self, relation: str) -> Dict[str, Any]:
        """设置当前任务关系"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "伙伴交互状态停用"}
            if relation not in TASK_RELATIONS:
                raise PartnerStateError(
                    f"非法任务关系: {relation} "
                    f"(可选: {TASK_RELATIONS})"
                )
            old = self._relation
            self._relation = relation
            self._touch()
            return {
                "mode": "rule_based", "ok": True,
                "from": old, "to": relation,
            }

    def set_mode(self, mode: str) -> Dict[str, Any]:
        """设置当前交流模式"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "伙伴交互状态停用"}
            old = self._mode
            self._mode = str(mode).strip() or "casual"
            self._touch()
            return {
                "mode": "rule_based", "ok": True,
                "from": old, "to": self._mode,
            }

    def mark_session(self) -> Dict[str, Any]:
        """标记一次交互会话 (只计数, 不存内容)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "伙伴交互状态停用"}
            self._session_count += 1
            self._touch()
            return {
                "mode": "rule_based", "ok": True,
                "session_count": self._session_count,
            }

    def reset(self) -> Dict[str, Any]:
        """重置交互状态 (不重置人格)"""
        with self._lock:
            self._goal = ""
            self._relation = "none"
            self._mode = "casual"
            self._last_activity = 0.0
            return {"mode": "rule_based", "ok": True,
                    "reset": True}

    def snapshot(self) -> Dict[str, Any]:
        """伙伴交互状态快照"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "goal": self._goal,
                "relation": self._relation,
                "mode_name": self._mode,
                "session_count": self._session_count,
                "last_activity": self._last_activity,
            }

    def _touch(self) -> None:
        self._last_activity = time.time()

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "session_count": self._session_count,
                "active": bool(self._goal),
                "relation": self._relation,
            }

    def clear(self) -> int:
        """清空计数 (测试隔离)"""
        with self._lock:
            n = self._session_count
            self.reset()
            return n


__all__ = [
    "PartnerInteractionState",
    "PartnerStateError",
    "TASK_RELATIONS",
]
