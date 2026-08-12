"""
YHLZ Embodied AI V5.7 - 经验查询 (Experience Query)

职责:
    - 按类型/关键词/时间段/价值查询经验
    - 检索对当前情境最相关的经验 (供未来行为参考)

设计原则:
    - 规则检索 (可解释排序: 类型匹配 + 关键词 + 价值)
    - 只读查询 (不修改存储)
    - 不替代核心 Agent 决策 (返回参考)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.companion.experience.experience_record import (
    EXPERIENCE_TYPES,
    ExperienceRecord,
)
from backend.embodied.companion.experience.experience_store import (
    ExperienceStore,
)

logger = logging.getLogger(__name__)


class ExperienceQueryError(Exception):
    """经验查询操作异常"""


class ExperienceQuery:
    """经验查询器

    用法:
        query = ExperienceQuery(store)
        results = query.by_type("failure")
        best = query.relevant(trigger="拾取失败")
    """

    def __init__(self, store: ExperienceStore):
        if not isinstance(store, ExperienceStore):
            raise ExperienceQueryError("查询需要 ExperienceStore")
        self._lock = threading.RLock()
        self._store = store

    # ── 基础查询 ──────────────────────────────────────────────────
    def by_type(self, type: str, limit: int = 20) -> List[Dict[str, Any]]:
        """按经验类型查询"""
        if type not in EXPERIENCE_TYPES:
            raise ExperienceQueryError(
                f"非法经验类型: {type} (可选: {EXPERIENCE_TYPES})"
            )
        records = [r for r in self._store.all() if r.type == type]
        return [r.to_dict() for r in records[:limit]]

    def by_keyword(
        self, keyword: str, limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """按关键词查询 (trigger/lesson/result 匹配)"""
        kw = (keyword or "").lower()
        if not kw:
            return []
        records = [
            r for r in self._store.all()
            if kw in r.trigger.lower()
            or kw in r.lesson.lower()
            or kw in r.result.lower()
            or kw in r.action.lower()
        ]
        return [r.to_dict() for r in records[:limit]]

    def by_value(self, min_value: float = 0.5,
                 limit: int = 20) -> List[Dict[str, Any]]:
        """按价值查询 (高价值优先)"""
        if not (0.0 <= min_value <= 1.0):
            raise ExperienceQueryError(
                f"min_value 必须在 [0,1], 当前: {min_value}"
            )
        records = [
            r for r in self._store.all() if r.value >= min_value
        ]
        records.sort(key=lambda r: -r.value)
        return [r.to_dict() for r in records[:limit]]

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """近期经验 (最新在前)"""
        return [r.to_dict() for r in self._store.all()[:limit]]

    # ── 相关检索 (可解释排序) ─────────────────────────────────────
    def relevant(
        self,
        trigger: str = "",
        type: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """检索相关经验 (供未来行为参考)

        排序规则 (可解释):
            - 类型匹配: +2
            - 关键词匹配 (trigger/lesson): 每个 +1
            - 价值加权: score × value

        Returns:
            相关经验 (按相关度降序, 含 reason)
        """
        text = (trigger or "").lower()
        candidates: List[Dict[str, Any]] = []
        for r in self._store.all():
            score = 0.0
            reasons: List[str] = []
            if type is not None and r.type == type:
                score += 2.0
                reasons.append(f"类型匹配 ({type})")
            if text:
                if text in r.trigger.lower():
                    score += 1.0
                    reasons.append("trigger 匹配")
                if text in r.lesson.lower():
                    score += 1.0
                    reasons.append("lesson 匹配")
                if text in r.result.lower():
                    score += 0.5
                    reasons.append("result 匹配")
            if score <= 0:
                continue
            weighted = score * r.value
            candidates.append({
                "record": r.to_dict(),
                "score": round(weighted, 4),
                "reason": "; ".join(reasons) or "价值加权",
            })
        candidates.sort(key=lambda c: -c["score"])
        return candidates[:limit]

    def best_lesson(self, trigger: str) -> str:
        """最相关经验的经验教训 (可解释参考)"""
        results = self.relevant(trigger=trigger, limit=1)
        if not results:
            return ""
        return results[0]["record"].get("lesson", "")


__all__ = [
    "ExperienceQuery",
    "ExperienceQueryError",
]
