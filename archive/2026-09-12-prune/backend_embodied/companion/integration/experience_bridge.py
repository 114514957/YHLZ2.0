"""
YHLZ Embodied AI V5.9 - 经历桥接 (Experience Bridge)

职责:
    - 接入 Experience Layer (V5.7) + Verification Layer (V5.8)
    - 读取: 只 CONFIRMED Experience (未验证经验禁止进入创造流程)
    - 回写: 创造执行结果 → 新经历 + 验证 (形成新经验闭环)

设计原则:
    - 只提供 CONFIRMED 经历给创造层 (认知免疫)
    - 不直接读写其他子系统存储 (经 ExperienceManager)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExperienceBridgeError(Exception):
    """经历桥接操作异常"""


class ExperienceBridge:
    """经历桥接 (CONFIRMED 经验供给 + 新经验回写)

    用法:
        bridge = ExperienceBridge(experience_manager, verifier)
        confirmed = bridge.confirmed_experiences()
        rec = bridge.record_new_experience(trigger, lesson)
    """

    def __init__(self, experience_manager=None, verifier=None):
        self._lock = threading.RLock()
        self._manager = experience_manager
        self._verifier = verifier

    # ── CONFIRMED 经验供给 (创造依据) ────────────────────────────
    def confirmed_experiences(
        self, limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """只返回 CONFIRMED 经历 (未验证经验禁止进入创造流程)

        Args:
            limit: 返回条数上限

        Returns:
            CONFIRMED 经历 dict 列表
        """
        with self._lock:
            if self._manager is None:
                return []
            records = []
            try:
                records = self._manager._store.all()
            except Exception as e:
                logger.warning(f"[ExperienceBridge] 读取经历失败: {e}")
                return []
            if self._verifier is None:
                # 无验证器 → 保守: 返回空 (禁止未验证经验进入创造)
                logger.warning(
                    "[ExperienceBridge] 无验证器, 创造依据为空 "
                    "(只 CONFIRMED 原则)"
                )
                return []
            confirmed_ids = self._verifier.confirmed_ids()
            confirmed = [
                r.to_dict() for r in records
                if r.id in confirmed_ids
            ]
            return confirmed[:limit]

    def confirmed_by_trigger(
        self, trigger: str, limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """按触发情境查询 CONFIRMED 经历"""
        confirmed = self.confirmed_experiences(limit=limit * 5)
        return [
            r for r in confirmed
            if trigger in str(r.get("trigger", ""))
        ][:limit]

    def confirmed_count(self) -> int:
        """CONFIRMED 经历数量"""
        return len(self.confirmed_experiences(limit=10000))

    # ── 新经验回写 (执行结果 → 经历) ─────────────────────────────
    def record_new_experience(
        self, trigger: str, lesson: str,
        result: str = "", action: str = "",
    ) -> Dict[str, Any]:
        """记录创造执行结果为新经历

        Args:
            trigger: 触发情境
            lesson: 经验教训
            result: 执行结果 (成功/失败描述)
            action: 执行动作

        Returns:
            新经历 dict (含 id)
        """
        with self._lock:
            if self._manager is None:
                raise ExperienceBridgeError("未接入 ExperienceManager")
            try:
                return self._manager.store_engineering_experience(
                    trigger=trigger, lesson=lesson, result=result,
                )
            except Exception as e:
                raise ExperienceBridgeError(f"记录新经历失败: {e}")

    def verify_new_experience(
        self, experience_id: str, evidence_count: int = 1,
    ) -> Dict[str, Any]:
        """验证新经历 (证据 1 条, 无矛盾)"""
        with self._lock:
            if self._verifier is None:
                raise ExperienceBridgeError("未接入 ExperienceVerifier")
            try:
                return self._verifier.verify(
                    experience_id=experience_id,
                    evidence_count=evidence_count,
                    contradictions=0,
                    source_reliable=True,
                )
            except Exception as e:
                raise ExperienceBridgeError(f"验证新经历失败: {e}")

    def stats(self) -> Dict[str, Any]:
        """桥接统计"""
        return {
            "mode": "rule_based",
            "manager_connected": self._manager is not None,
            "verifier_connected": self._verifier is not None,
            "confirmed_count": self.confirmed_count(),
        }


__all__ = [
    "ExperienceBridge",
    "ExperienceBridgeError",
]
