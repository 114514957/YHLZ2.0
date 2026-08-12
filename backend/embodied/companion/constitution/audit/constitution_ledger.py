"""
YHLZ Embodied AI V8.0 - 治理总账 (Constitution Ledger)

职责:
    - 记录所有治理行为 (可查询/可回放/可审计)
    - 结构: {time, module, action, decision, rule, reason}

设计原则:
    - 独立总账 (全程可追溯)
    - 不可静默 (任何治理行为必须记录)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LedgerError(Exception):
    """治理总账操作异常"""


class ConstitutionLedger:
    """治理总账 (跨模块治理审计)

    用法:
        ledger = ConstitutionLedger()
        ledger.record(module="growth", action="review",
                      decision="approve", rule="growth_policy",
                      reason="...")
        report = ledger.report()
    """

    def __init__(self, max_records: int = 5000,
                 enabled: bool = True):
        if max_records <= 0:
            raise LedgerError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)
        self._enabled = bool(enabled)

    # ── 记录 ─────────────────────────────────────────────────────
    def record(
        self,
        module: str = "",
        action: str = "",
        decision: str = "",
        rule: str = "",
        reason: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记录一次治理行为"""
        if not self._enabled:
            return {}
        entry = {
            "ledger_id": "cl_" + uuid.uuid4().hex[:8],
            "time": now if now is not None else time.time(),
            "module": str(module),
            "action": str(action),
            "decision": str(decision),
            "rule": str(rule),
            "reason": str(reason),
        }
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
        return dict(entry)

    # ── 查询 ─────────────────────────────────────────────────────
    def report(self, limit: int = 100) -> Dict[str, Any]:
        """总账报告"""
        with self._lock:
            records = list(self._records)
        by_module: Dict[str, int] = {}
        by_decision: Dict[str, int] = {}
        for r in records:
            by_module[r["module"]] = by_module.get(
                r["module"], 0,
            ) + 1
            by_decision[r["decision"]] = by_decision.get(
                r["decision"], 0,
            ) + 1
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": len(records),
            "by_module": by_module,
            "by_decision": by_decision,
            "recent": recent,
        }

    def replay(self, limit: int = 100) -> Dict[str, Any]:
        """回放 (治理过程可追踪)"""
        with self._lock:
            records = list(reversed(self._records))
            if limit > 0:
                records = records[:limit]
            return {
                "mode": "rule_based",
                "replay_count": len(records),
                "sequence": [
                    {
                        "ledger_id": r["ledger_id"],
                        "time": r["time"],
                        "module": r["module"],
                        "action": r["action"],
                        "decision": r["decision"],
                        "rule": r["rule"],
                    }
                    for r in records
                ],
            }

    def stats(self) -> Dict[str, Any]:
        """总账统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "record_count": len(self._records),
                "max_records": self._max_records,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "ConstitutionLedger",
    "LedgerError",
]
