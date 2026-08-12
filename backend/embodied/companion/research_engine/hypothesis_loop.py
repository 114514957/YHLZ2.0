"""
YHLZ Embodied AI V9.0 - 假设循环 (Hypothesis Loop)

职责:
    - 流程: Question → Hypothesis → Analysis → Result
      → Validation → Knowledge Update
    - 失败结果也属于有效探索数据

设计原则:
    - 循环可追踪 (loop 记录)
    - 结果含验证状态
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class LoopError(Exception):
    """假设循环操作异常"""


class HypothesisLoop:
    """假设循环器 (问题 → 知识更新)

    用法:
        loop = HypothesisLoop()
        r = loop.run("如何提升体验", hypothesis="陪伴提升信任",
                     analysis="分析结果", validated=True)
    """

    def __init__(self, enabled: bool = True,
                 max_records: int = 1000):
        if max_records <= 0:
            raise LoopError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._loops: list = []

    # ── 循环主入口 ───────────────────────────────────────────────
    def run(
        self,
        question: str,
        hypothesis: str,
        analysis: str = "",
        validated: bool = False,
        validation_reason: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """运行一次假设循环

        Args:
            question: 问题
            hypothesis: 假设
            analysis: 分析结果
            validated: 是否验证通过
            validation_reason: 验证原因

        Returns:
            {
                'loop_id', 'question', 'hypothesis',
                'analysis', 'result', 'validation',
                'knowledge_update', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "假设循环停用",
                }
            # Result (失败也是有效探索数据)
            result = (
                f"假设 '{hypothesis[:25]}' 验证"
                f"{'通过' if validated else '失败'}"
            )
            # Knowledge Update (仅验证通过才更新知识)
            knowledge_update = bool(validated)
            loop = {
                "loop_id": "hl_" + uuid.uuid4().hex[:8],
                "question": str(question),
                "hypothesis": str(hypothesis),
                "analysis": str(analysis),
                "result": result,
                "validation": {
                    "ok": bool(validated),
                    "reason": str(validation_reason),
                },
                "knowledge_update": knowledge_update,
                "mode": "rule_based",
                "created_at": now,
            }
            self._loops.append(loop)
            if len(self._loops) > self._max_records:
                self._loops = self._loops[-self._max_records:]
            return dict(loop)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """循环统计"""
        with self._lock:
            by_validation: Dict[str, int] = {}
            updates = 0
            for l in self._loops:
                key = "ok" if l["validation"]["ok"] else "fail"
                by_validation[key] = by_validation.get(
                    key, 0,
                ) + 1
                if l["knowledge_update"]:
                    updates += 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "loop_count": len(self._loops),
                "by_validation": by_validation,
                "knowledge_updates": updates,
            }

    def history(self, limit: int = 50) -> list:
        """循环历史"""
        with self._lock:
            recent = list(reversed(self._loops))
            if limit > 0:
                recent = recent[:limit]
            return [dict(l) for l in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._loops)
            self._loops.clear()
            return n


__all__ = [
    "HypothesisLoop",
    "LoopError",
]
