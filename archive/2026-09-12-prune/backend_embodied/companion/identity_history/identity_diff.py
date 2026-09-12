"""
YHLZ Embodied AI V6.0 - 身份差异 (Identity Diff)

职责:
    - 身份状态字段级差异分析
    - 忽略噪声字段 (时间戳/计数等)
    - 输出差异摘要 (可解释)

设计原则:
    - 纯规则, 无黑盒
    - 差异可回溯 (before/after)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class DiffError(Exception):
    """身份差异操作异常"""


# 噪声字段 (忽略比较) (可解释)
NOISE_FIELDS: List[str] = [
    "timestamp", "created_at", "updated_at", "last_change",
    "interaction_count", "handled_count", "last_adjust",
]


class IdentityDiff:
    """身份差异分析器

    用法:
        diff = IdentityDiff()
        diffs = diff.compare(before, after)
        summary = diff.summarize(diffs)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._results: List[Dict[str, Any]] = []

    # ── 差异分析 ─────────────────────────────────────────────────
    def compare(self, before: Dict[str, Any],
                after: Dict[str, Any]) -> List[Dict[str, Any]]:
        """字段级差异 (忽略噪声字段)

        Args:
            before: 之前身份状态
            after: 之后身份状态

        Returns:
            [{field, before, after, changed}]
        """
        with self._lock:
            if not isinstance(before, dict) or \
                    not isinstance(after, dict):
                raise DiffError("身份状态必须是 dict")
            diffs: List[Dict[str, Any]] = []
            keys = set(list(before.keys()) + list(after.keys()))
            for key in sorted(keys):
                if key in NOISE_FIELDS:
                    continue
                b = before.get(key)
                a = after.get(key)
                changed = b != a
                diffs.append({
                    "field": key,
                    "before": b,
                    "after": a,
                    "changed": changed,
                })
            self._results.append({
                "diff_id": "diff_" +
                __import__("uuid").uuid4().hex[:8],
                "changed_fields": [
                    d["field"] for d in diffs if d["changed"]
                ],
                "total_fields": len(diffs),
            })
            return diffs

    # ── 摘要 ─────────────────────────────────────────────────────
    def summarize(self, diffs: List[Dict[str, Any]]) -> str:
        """差异摘要文本"""
        with self._lock:
            changed = [d for d in diffs if d["changed"]]
            if not changed:
                return "身份状态无变化"
            parts = []
            for d in changed[:5]:
                parts.append(
                    f"{d['field']}: {d['before']} → {d['after']}"
                )
            summary = "; ".join(parts)
            if len(changed) > 5:
                summary += f" 等共 {len(changed)} 处变化"
            return summary

    def changed_fields(self, diffs: List[Dict[str, Any]]) -> List[str]:
        """变化字段列表"""
        return [d["field"] for d in diffs if d["changed"]]

    def stats(self) -> Dict[str, Any]:
        """差异统计"""
        with self._lock:
            results = list(self._results)
        return {
            "mode": "rule_based",
            "compare_count": len(results),
            "avg_changed": round(
                sum(len(r["changed_fields"]) for r in results)
                / len(results) if results else 0.0, 2,
            ),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "DiffError",
    "IdentityDiff",
    "NOISE_FIELDS",
]
