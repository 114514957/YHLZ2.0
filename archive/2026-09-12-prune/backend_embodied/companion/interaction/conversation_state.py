"""
YHLZ Embodied AI V10.1 - 会话状态管理器 (Conversation State Manager)

职责:
    - 保存当前会话结构化状态: 当前目标 / 任务阶段 / 未完成事项 /
      当前交互上下文
    - 只保存结构化摘要, 不保存全部聊天内容 (防膨胀)
    - 状态可重置 / 可审计

流程 (DEMO 交互协议):
    User Input → Intent Understanding → Conversation State →
    Task Progress → Response

设计原则:
    - 有界保存: 状态字段固定 + 上下文摘要裁剪 (不无限保存)
    - 上下文 ≠ 长期记忆 (只存当前会话, 筛选后保留)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConversationStateError(Exception):
    """会话状态操作异常"""


# 任务阶段枚举 (可解释)
TASK_STAGES: List[str] = [
    "init",       # 初始
    "understand", # 理解意图
    "planning",   # 规划
    "executing",  # 执行中
    "reviewing",  # 复核
    "done",       # 完成
    "aborted",    # 中止
]

# 交流模式枚举
COMMUNICATION_MODES: List[str] = [
    "casual",     # 闲聊
    "task",       # 任务协作
    "planning",   # 规划讨论
    "review",     # 复盘讨论
]


class ConversationStateManager:
    """会话状态管理器 (V10.1)

    用法:
        csm = ConversationStateManager(max_context_len=200)
        csm.begin(goal="...")
        csm.update_stage("planning")
        csm.add_pending("确认方案")
        state = csm.snapshot()
    """

    def __init__(
        self,
        max_context_len: int = 200,
        max_pending: int = 20,
        enabled: bool = True,
    ):
        if max_context_len <= 0:
            raise ConversationStateError(
                f"max_context_len 必须 > 0, 当前: {max_context_len}"
            )
        if max_pending <= 0:
            raise ConversationStateError(
                f"max_pending 必须 > 0, 当前: {max_pending}"
            )
        self._lock = threading.RLock()
        self._max_context_len = int(max_context_len)
        self._max_pending = int(max_pending)
        self._enabled = bool(enabled)
        self._goal: str = ""
        self._stage: str = "init"
        self._mode: str = "casual"
        self._pending: List[str] = []
        self._context: str = ""
        self._started_at: float = 0.0
        self._updated_at: float = 0.0

    # ── 会话生命周期 ────────────────────────────────────────────
    def begin(self, goal: str = "", mode: str = "casual") -> Dict[str, Any]:
        """开始会话 (设置目标与交流模式)"""
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "会话状态管理器停用",
                }
            if mode not in COMMUNICATION_MODES:
                raise ConversationStateError(
                    f"非法交流模式: {mode} (可选: {COMMUNICATION_MODES})"
                )
            self._goal = str(goal)
            self._mode = mode
            self._stage = "init"
            self._pending = []
            self._context = ""
            self._started_at = time.time()
            self._updated_at = self._started_at
            return {
                "mode": "rule_based",
                "ok": True,
                "goal": self._goal,
                "mode_name": self._mode,
                "stage": self._stage,
            }

    def reset(self) -> Dict[str, Any]:
        """重置会话 (清空状态)"""
        with self._lock:
            self._goal = ""
            self._stage = "init"
            self._mode = "casual"
            self._pending = []
            self._context = ""
            self._started_at = 0.0
            self._updated_at = 0.0
            return {"mode": "rule_based", "ok": True,
                    "reset": True}

    # ── 状态更新 ────────────────────────────────────────────────
    def update_stage(self, stage: str) -> Dict[str, Any]:
        """更新任务阶段"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "会话状态管理器停用"}
            if stage not in TASK_STAGES:
                raise ConversationStateError(
                    f"非法任务阶段: {stage} (可选: {TASK_STAGES})"
                )
            old = self._stage
            self._stage = stage
            self._updated_at = time.time()
            return {
                "mode": "rule_based", "ok": True,
                "from": old, "to": stage,
            }

    def update_mode(self, mode: str) -> Dict[str, Any]:
        """更新交流模式"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "会话状态管理器停用"}
            if mode not in COMMUNICATION_MODES:
                raise ConversationStateError(
                    f"非法交流模式: {mode} (可选: {COMMUNICATION_MODES})"
                )
            old = self._mode
            self._mode = mode
            self._updated_at = time.time()
            return {
                "mode": "rule_based", "ok": True,
                "from": old, "to": mode,
            }

    def set_context(self, context: str) -> Dict[str, Any]:
        """设置当前交互上下文 (筛选后摘要, 裁剪到上限)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "会话状态管理器停用"}
            self._context = self._clip(str(context))
            self._updated_at = time.time()
            return {
                "mode": "rule_based", "ok": True,
                "context_len": len(self._context),
                "clipped": len(str(context)) > self._max_context_len,
            }

    def add_pending(self, item: str) -> Dict[str, Any]:
        """添加未完成事项 (有界)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "会话状态管理器停用"}
            if not item.strip():
                raise ConversationStateError("未完成事项不能为空")
            self._pending.append(str(item).strip())
            if len(self._pending) > self._max_pending:
                self._pending = self._pending[-self._max_pending:]
            self._updated_at = time.time()
            return {
                "mode": "rule_based", "ok": True,
                "pending_count": len(self._pending),
            }

    def resolve_pending(self, item: str) -> bool:
        """移除已完成事项"""
        with self._lock:
            if item in self._pending:
                self._pending.remove(item)
                self._updated_at = time.time()
                return True
            return False

    # ── 查询 ────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        """会话状态快照 (结构化)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "goal": self._goal,
                "stage": self._stage,
                "mode_name": self._mode,
                "pending": list(self._pending),
                "context": self._context,
                "context_len": len(self._context),
                "started_at": self._started_at,
                "updated_at": self._updated_at,
            }

    def _clip(self, text: str) -> str:
        """上下文裁剪 (保留头部与尾部, 中间省略)"""
        if len(text) <= self._max_context_len:
            return text
        head = self._max_context_len // 2
        tail = self._max_context_len - head - 3
        return text[:head] + "..." + text[-tail:]

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "max_context_len": self._max_context_len,
                "max_pending": self._max_pending,
                "active": bool(self._goal),
                "stage": self._stage,
                "pending_count": len(self._pending),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._pending)
            self.reset()
            return n


__all__ = [
    "COMMUNICATION_MODES",
    "ConversationStateError",
    "ConversationStateManager",
    "TASK_STAGES",
]
