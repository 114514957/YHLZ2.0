"""
YHLZ Embodied AI V8.5 - 人机协同创造 (Collaborative Creation)

职责:
    - Human (价值判断/目标选择/跳跃式创造)
    - AI (信息整合/模式发现/可行性分析)
    - 形成: Human Meta Creativity + AI Cognitive Expansion
      = Collaborative Creation

设计原则:
    - 角色分工可解释 (role_division)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CollaborativeError(Exception):
    """人机协同创造操作异常"""


class CollaborativeCreation:
    """人机协同创造 (Human + AI → 协作创造)

    用法:
        cc = CollaborativeCreation()
        r = cc.create(human_input, ai_analysis, goal)
    """

    def __init__(self, enabled: bool = True,
                 max_records: int = 500):
        if max_records <= 0:
            raise CollaborativeError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._records: list = []

    # ── 协同主入口 ───────────────────────────────────────────────
    def create(
        self,
        human_input: str,
        ai_analysis: str,
        goal: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """形成协作创造

        Args:
            human_input: 人类输入 (价值/目标/跳跃想法)
            ai_analysis: AI 分析 (整合/模式/可行性)
            goal: 目标

        Returns:
            {
                'collab_id', 'combined', 'role_division',
                'human_part', 'ai_part', 'goal', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "人机协同停用",
                }
            human = str(human_input)
            ai = str(ai_analysis)
            combined = (
                f"人类方向 '{human[:25]}' + "
                f"AI 扩展 '{ai[:25]}'"
            )
            result = {
                "collab_id": "cc_" + uuid.uuid4().hex[:8],
                "combined": combined,
                "human_part": human,
                "ai_part": ai,
                "goal": str(goal),
                "role_division": {
                    "human": "价值判断/目标选择/跳跃式创造",
                    "ai": "信息整合/模式发现/可行性分析",
                },
                "mode": "rule_based",
                "created_at": now,
            }
            self._records.append(result)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """协同统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "collab_count": len(self._records),
            }

    def history(self, limit: int = 50) -> list:
        """协同历史"""
        with self._lock:
            recent = list(reversed(self._records))
            if limit > 0:
                recent = recent[:limit]
            return [dict(r) for r in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "CollaborativeCreation",
    "CollaborativeError",
]
