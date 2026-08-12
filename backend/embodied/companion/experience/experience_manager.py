"""
YHLZ Embodied AI V5.7 - 经历管理器 (Experience Manager)

职责:
    - 统一入口: store / retrieve / update / decay / forget / query
    - 经验抽取: 事件 → 经验 (规则驱动)
    - Reflection Report: 主动输出 (Observation / 发现 / Suggestion)
    - 经验影响未来行为: relevant() 供参考

集成:
    RelationshipManager / PersonalityAuditRecord / InteractionWindow
    → Interaction → Relationship → Personality → Experience 闭环

设计原则:
    - 只记录经历与经验 (不记录聊天, 不写 Agent Memory)
    - 不替代核心 Agent 决策 (经验仅供参考)
    - 高价值长期保存, 低价值衰减遗忘
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.companion.experience.experience_audit import (
    ExperienceAudit,
)
from backend.embodied.companion.experience.experience_extractor import (
    ExperienceExtractor,
)
from backend.embodied.companion.experience.experience_query import (
    ExperienceQuery,
)
from backend.embodied.companion.experience.experience_record import (
    ExperienceRecord,
)
from backend.embodied.companion.experience.experience_store import (
    ExperienceStore,
)

logger = logging.getLogger(__name__)


class ExperienceManagerError(Exception):
    """经历管理器操作异常"""


class ExperienceManager:
    """经历管理器 (经历 → 记录 → 总结 → 学习 → 改进)

    用法:
        mgr = ExperienceManager()
        mgr.store_from_event(success=True, trigger="拾取台灯")
        lessons = mgr.relevant(trigger="拾取")
        report = mgr.reflection_report()
    """

    def __init__(
        self,
        store: Optional[ExperienceStore] = None,
        extractor: Optional[ExperienceExtractor] = None,
        query: Optional[ExperienceQuery] = None,
        audit: Optional[ExperienceAudit] = None,
    ):
        self._lock = threading.RLock()
        self._store = store or ExperienceStore()
        self._extractor = extractor or ExperienceExtractor()
        self._query = query or ExperienceQuery(self._store)
        self._audit = audit or ExperienceAudit()

    # ── 生命周期 (store/retrieve/update/decay/forget) ─────────────
    def store(self, record: ExperienceRecord) -> Dict[str, Any]:
        """存储经历"""
        with self._lock:
            self._store.store(record)
            self._audit.record(
                action="store", record_id=record.id,
                trigger=record.trigger,
            )
            return record.to_dict()

    def retrieve(self, record_id: str) -> Optional[Dict[str, Any]]:
        """检索经历"""
        with self._lock:
            rec = self._store.retrieve(record_id)
            if rec is not None:
                self._audit.record(
                    action="retrieve", record_id=record_id,
                    trigger=rec.trigger,
                )
            return rec.to_dict() if rec else None

    def update(
        self,
        record_id: str,
        lesson: Optional[str] = None,
        value: Optional[float] = None,
        confidence: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """更新经历"""
        with self._lock:
            rec = self._store.update(
                record_id, lesson=lesson, value=value,
                confidence=confidence,
            )
            if rec is not None:
                self._audit.record(
                    action="update", record_id=record_id,
                    trigger=rec.trigger,
                )
            return rec.to_dict() if rec else None

    def decay(self, decay_rate: float = 0.1,
              min_value: float = 0.1) -> List[str]:
        """价值衰减 (低价值遗忘)"""
        with self._lock:
            forgotten = self._store.decay(
                decay_rate=decay_rate, min_value=min_value,
            )
            for rid in forgotten:
                self._audit.record(action="forget", record_id=rid,
                                   detail="低价值衰减遗忘")
            return forgotten

    def forget(self, record_id: str) -> bool:
        """遗忘经历"""
        with self._lock:
            ok = self._store.forget(record_id)
            if ok:
                self._audit.record(action="forget", record_id=record_id,
                                   detail="手动遗忘")
            return ok

    # ── 经验抽取 (事件 → 经验) ───────────────────────────────────
    def store_from_event(
        self,
        success: bool,
        trigger: str,
        source: str = "execution",
        action: str = "",
        result: str = "",
    ) -> Dict[str, Any]:
        """从执行事件抽取并存储经验"""
        with self._lock:
            record = self._extractor.extract(
                success=success, trigger=trigger,
                source=source, action=action, result=result,
            )
            self._audit.record(
                action="extract", record_id=record.id,
                trigger=record.trigger, detail=f"type={record.type}",
            )
            return self.store(record)

    def store_relationship_experience(
        self, trust_level: float, interaction_count: int,
    ) -> Dict[str, Any]:
        """从关系状态抽取并存储互动经验"""
        with self._lock:
            record = self._extractor.extract_from_relationship(
                trust_level, interaction_count,
            )
            return self.store(record)

    def store_engineering_experience(
        self, trigger: str, lesson: str, result: str = "",
    ) -> Dict[str, Any]:
        """存储工程经验"""
        with self._lock:
            record = self._extractor.extract_engineering(
                trigger=trigger, lesson=lesson, result=result,
            )
            return self.store(record)

    # ── 查询 ──────────────────────────────────────────────────────
    def by_type(self, type: str, limit: int = 20) -> List[Dict[str, Any]]:
        """按类型查询"""
        with self._lock:
            self._audit.record(action="query", trigger=f"type={type}")
            return self._query.by_type(type, limit=limit)

    def relevant(self, trigger: str, type: Optional[str] = None,
                 limit: int = 5) -> List[Dict[str, Any]]:
        """相关经验 (供未来行为参考)"""
        with self._lock:
            self._audit.record(action="query", trigger=trigger)
            return self._query.relevant(
                trigger=trigger, type=type, limit=limit,
            )

    def stats(self) -> Dict[str, Any]:
        """经历统计"""
        with self._lock:
            return self._store.stats()

    # ── Reflection Report (主动输出) ──────────────────────────────
    def reflection_report(self) -> Dict[str, Any]:
        """反思报告: Observation / 发现 / Suggestion

        规则 (可解释):
            - Observation: 高频失败类型观察
            - 发现: 失败类型统计 + 低价值经验比例
            - Suggestion: 针对高频失败的建议

        Returns:
            {
                'mode': 'rule_based', 'generated_at',
                'observation': str,
                'findings': [str...],
                'suggestion': str,
                'failure_stats': {...},
            }
        """
        with self._lock:
            stats = self._store.stats()
            failures = self._query.by_type("failure", limit=100)
            by_failure_trigger: Dict[str, int] = {}
            for f in failures:
                key = f["trigger"][:30]
                by_failure_trigger[key] = by_failure_trigger.get(key, 0) + 1
            total = stats["total"]
            low_value = sum(
                1 for r in self._store.all() if r.value < 0.5
            )
            findings = [
                f"已记录 {total} 条经历, 类型分布: {stats['by_type']}",
                f"低价值经验 {low_value} 条 (将逐渐衰减遗忘)",
            ]
            if by_failure_trigger:
                top = max(by_failure_trigger.items(),
                          key=lambda kv: kv[1])
                findings.append(
                    f"高频失败情境: '{top[0]}' 出现 {top[1]} 次"
                )
                suggestion = (
                    f"针对高频失败 '{top[0]}': 建议调整执行策略后再试, "
                    f"或先感知环境补充信息"
                )
            else:
                suggestion = "暂无高频失败, 保持当前策略并持续记录"
            return {
                "mode": "rule_based",
                "generated_at": __import__("time").time(),
                "observation": (
                    f"观察 {total} 条经历中的失败模式与改进机会"
                ),
                "findings": findings,
                "suggestion": suggestion,
                "failure_stats": by_failure_trigger,
            }

    # ── 审计 ──────────────────────────────────────────────────────
    def audit(self, limit: int = 100) -> Dict[str, Any]:
        """经历审计报告"""
        with self._lock:
            return self._audit.report(limit=limit)

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = self._store.clear()
            self._audit.clear()
            return n


__all__ = [
    "ExperienceManager",
    "ExperienceManagerError",
]
