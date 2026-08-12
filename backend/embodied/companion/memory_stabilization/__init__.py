"""
YHLZ Embodied AI V10.1 - 记忆稳定化引擎 (Memory Stabilization Engine)

职责:
    - 热机最高优先级: 解决记忆膨胀 / 重复信息 / 错误积累 / 无价值数据
    - 四能力: 压缩 (compress) / 淘汰 (prune) / 权重评估 (evaluate) /
      冲突检测 (detect_conflicts)
    - 审计: 合并 / 淘汰 / 冲突 全程记录 (热机可追踪铁律)

流程 (Phase1 Prompt 定义):
    Memory Input → Evaluation → Classification → Storage → Maintenance

设计原则:
    - 纯增量: 不替换既有 MemoryIndex / MemoryConsolidation
    - 淘汰默认只出候选, 执行必须显式 (禁止自动删除)
    - 规则可解释 (rule/reason)
    - 线程安全 (RLock)

用法:
    engine = MemoryStabilizationEngine(config=...)
    report = engine.stabilize(records, confirmed_ids)
    candidates = engine.prune_candidates(records, confirmed_ids)
    result = engine.prune_execute(record_ids, forget_fn, records)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from backend.embodied.companion.memory_stabilization.compressor import (
    MemoryCompressor,
)
from backend.embodied.companion.memory_stabilization.conflict_detector import (
    MemoryConflictDetector,
)
from backend.embodied.companion.memory_stabilization.pruner import (
    MemoryPruner,
)
from backend.embodied.companion.memory_stabilization.stabilization_audit import (
    STABILIZE_ACTIONS,
    StabilizationAudit,
)
from backend.embodied.companion.memory_stabilization.weighter import (
    MemoryWeighter,
)

logger = logging.getLogger(__name__)


class MemoryStabilizationError(Exception):
    """记忆稳定化引擎异常"""


class MemoryStabilizationEngine:
    """记忆稳定化引擎 (V10.1, 统一入口)

    用法:
        engine = MemoryStabilizationEngine(config=...)
        report = engine.stabilize(records, confirmed_ids)
        candidates = engine.prune_candidates(records, confirmed_ids)
        result = engine.prune_execute(record_ids, forget_fn, records)
    """

    def __init__(
        self,
        compressor: Optional[MemoryCompressor] = None,
        pruner: Optional[MemoryPruner] = None,
        weighter: Optional[MemoryWeighter] = None,
        conflict_detector: Optional[MemoryConflictDetector] = None,
        audit: Optional[StabilizationAudit] = None,
        config: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        cfg = dict(config or {})
        self._enabled = bool(enabled)
        self._config = cfg
        self._compressor = compressor or MemoryCompressor(
            similarity_threshold=float(cfg.get(
                "companion_memory_stabilize_compress_similarity",
                0.9,
            )),
            enabled=self._enabled,
        )
        self._pruner = pruner or MemoryPruner(
            value_threshold=float(cfg.get(
                "companion_memory_stabilize_prune_value_threshold",
                0.3,
            )),
            age_days=int(cfg.get(
                "companion_memory_stabilize_prune_age_days",
                90,
            )),
            enabled=self._enabled,
        )
        self._weighter = weighter or MemoryWeighter(
            enabled=self._enabled,
        )
        self._detector = conflict_detector or MemoryConflictDetector(
            enabled=self._enabled,
        )
        self._audit = audit or StabilizationAudit(
            max_records=int(cfg.get(
                "companion_memory_stabilize_audit_max",
                2000,
            )),
        )

    # ── 权重评估 ────────────────────────────────────────────────
    def evaluate(
        self,
        record: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记忆动态权重评估"""
        with self._lock:
            result = self._weighter.evaluate(record, context)
            if result.get("mode") != "error_frame":
                self._audit.record(
                    action="evaluate",
                    record_ids=[record.get("id", "")],
                    reason=result.get("reason", ""),
                    result={
                        "weight": result.get("weight"),
                        "base_value": result.get("base_value"),
                    },
                )
            return result

    # ── 压缩 ────────────────────────────────────────────────────
    def compress(
        self,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """压缩方案: 同触发词 / 同内容合并 (不直接改存储)"""
        with self._lock:
            plan = self._compressor.compress(records)
            if plan.get("mode") != "error_frame":
                for m in plan["merged"]:
                    self._audit.record(
                        action="compress",
                        record_ids=[m["primary_id"]] + m["merged_ids"],
                        reason=m["reason"],
                        result={
                            "similarity": m["similarity"],
                            "merged_from": m["merged_ids"],
                        },
                    )
            return plan

    # ── 淘汰 ────────────────────────────────────────────────────
    def prune_candidates(
        self,
        records: List[Dict[str, Any]],
        confirmed_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """淘汰候选 (只出方案, 不执行)"""
        with self._lock:
            return self._pruner.candidates(records, confirmed_ids)

    def prune_execute(
        self,
        record_ids: List[str],
        forget_fn: Callable[[str], bool],
        records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """显式执行淘汰 (调用 forget 回调 + 审计)"""
        with self._lock:
            result = self._pruner.execute(
                record_ids, forget_fn, records,
            )
            if result.get("mode") != "error_frame":
                for rid in result["removed_ids"]:
                    self._audit.record(
                        action="prune",
                        record_ids=[rid],
                        reason="显式淘汰执行 (低价值/超龄/未确认)",
                        result={
                            "removed": True,
                            "requested": result["requested"],
                        },
                    )
            return result

    # ── 冲突检测 ────────────────────────────────────────────────
    def detect_conflicts(
        self,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """冲突检测: 同触发组正反结论标记 (不自动删除)"""
        with self._lock:
            report = self._detector.detect(records)
            if report.get("mode") != "error_frame":
                for c in report["conflicts"]:
                    self._audit.record(
                        action="conflict",
                        record_ids=c["record_ids"],
                        reason=c["reason"],
                        result={
                            "conflict_type": c["conflict_type"],
                            "trigger": c["trigger"],
                        },
                    )
            return report

    # ── 稳定化总报告 (Evaluation → Classification → Report) ─────
    def stabilize(
        self,
        records: List[Dict[str, Any]],
        confirmed_ids: Optional[List[str]] = None,
        referenced_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """记忆稳定化总报告 (压缩 + 权重 + 冲突, 不执行淘汰)

        Args:
            records: 记忆记录 dict 列表
            confirmed_ids: CONFIRMED 记忆 ID (权重评估/淘汰保护)
            referenced_ids: 被引用记忆 ID (权重评估加成)

        Returns:
            {
                "mode", "enabled", "total",
                "compression": {...},
                "prune_candidates": {...},
                "evaluation": [...],
                "conflicts": {...},
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "记忆稳定化停用",
                }
            confirmed = set(confirmed_ids or [])
            referenced = set(referenced_ids or [])

            # 1. 压缩
            compression = self._compressor.compress(records)
            # 2. 淘汰候选
            candidates = self._pruner.candidates(
                records, list(confirmed),
            )
            # 3. 权重评估 (全量)
            context_map: Dict[str, Dict[str, Any]] = {}
            for rec in records:
                rid = rec.get("id", "")
                context_map[rid] = {
                    "frequency": 1,
                    "confirmed": rid in confirmed,
                    "referenced": rid in referenced,
                }
            evaluations = self._weighter.evaluate_many(
                records, context_map,
            )
            # 4. 冲突检测
            conflicts = self._detector.detect(records)

            # 审计: 压缩/冲突记录
            for m in compression["merged"]:
                self._audit.record(
                    action="compress",
                    record_ids=[m["primary_id"]] + m["merged_ids"],
                    reason=m["reason"],
                    result={"similarity": m["similarity"]},
                )
            for c in conflicts["conflicts"]:
                self._audit.record(
                    action="conflict",
                    record_ids=c["record_ids"],
                    reason=c["reason"],
                    result={
                        "conflict_type": c["conflict_type"],
                        "trigger": c["trigger"],
                    },
                )

            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "total": len(records),
                "compression": compression,
                "prune_candidates": candidates,
                "evaluation": evaluations,
                "conflicts": conflicts,
            }

    # ── 统计 / 审计查询 ─────────────────────────────────────────
    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """稳定化审计报告"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "stats": self._audit.stats(),
                "recent": self._audit.query(limit=limit),
            }

    def stats(self) -> Dict[str, Any]:
        """稳定化引擎统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "compressor": self._compressor.stats(),
                "pruner": self._pruner.stats(),
                "weighter": self._weighter.stats(),
                "conflict_detector": self._detector.stats(),
                "audit": self._audit.stats(),
            }

    def clear(self) -> int:
        """清空计数与审计 (测试隔离)"""
        with self._lock:
            n = 0
            n += self._compressor.clear()
            n += self._pruner.clear()
            n += self._weighter.clear()
            n += self._detector.clear()
            n += self._audit.clear()
            return n


__all__ = [
    "MemoryStabilizationEngine",
    "MemoryStabilizationError",
    "STABILIZE_ACTIONS",
    "StabilizationAudit",
]
