"""
YHLZ Embodied AI V5.8 - 模式发现 (Pattern Discovery)

职责:
    - 发现跨经历规律 (重复触发/行为模式/偏好)
    - 模式条件: 样本数量 / 时间跨度 / 重复程度 / 反例

限制 (可解释):
    - 禁止单次事件形成长期规则
    - 模式需: occurrences >= min_occurrences (默认 3)
      + 时间跨度 >= min_span_days (默认 1 天)
      + 反例数 <= max_contradictions (默认 0)

设计原则:
    - 纯规则统计 (禁止黑盒学习)
    - 可解释: 每模式输出 样本/跨度/重复/反例
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PatternError(Exception):
    """模式发现操作异常"""


class PatternDiscovery:
    """模式发现器 (跨经历规律)

    用法:
        pd = PatternDiscovery(min_occurrences=3)
        patterns = pd.discover(records)
    """

    def __init__(
        self,
        min_occurrences: int = 3,
        min_span_days: float = 1.0,
        max_contradictions: int = 0,
    ):
        if min_occurrences <= 0:
            raise PatternError(
                f"min_occurrences 必须 > 0, 当前: {min_occurrences}"
            )
        if min_span_days < 0:
            raise PatternError(
                f"min_span_days 必须 >= 0, 当前: {min_span_days}"
            )
        self._lock = threading.RLock()
        self._min_occurrences = int(min_occurrences)
        self._min_span_days = float(min_span_days)
        self._max_contradictions = int(max_contradictions)

    # ── 模式键 (可解释) ───────────────────────────────────────────
    @staticmethod
    def _pattern_key(trigger: str, type: str = "") -> str:
        """模式键: type + trigger 前缀 (确定性)"""
        return f"{type or 'any'}|{trigger[:40]}"

    # ── 发现模式 ──────────────────────────────────────────────────
    def discover(
        self,
        records: List[Dict[str, Any]],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发现跨经历模式

        Args:
            records: 经历记录列表 (dict, 含 trigger/type/lesson/timestamp)

        Returns:
            {
                'mode': 'rule_based',
                'patterns': [
                    {
                        'pattern_id', 'key', 'type', 'trigger',
                        'occurrences', 'span_days', 'contradictions',
                        'lesson', 'valid': bool, 'reason',
                    }, ...
                ],
                'valid_patterns': [...],   # 满足全部条件
                'total': n,
            }
        """
        now = now if now is not None else time.time()
        with self._lock:
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for r in records:
                key = self._pattern_key(
                    r.get("trigger", ""), r.get("type", ""),
                )
                groups.setdefault(key, []).append(r)

            patterns: List[Dict[str, Any]] = []
            for key, members in groups.items():
                occurrences = len(members)
                timestamps = [
                    m.get("timestamp", 0.0) for m in members
                ]
                span_days = (
                    (max(timestamps) - min(timestamps)) / 86400.0
                    if len(timestamps) > 1 else 0.0
                )
                # 反例: 同 key 下失败 vs 成功的对立 (简化: result 不一致)
                results = {m.get("result", "") for m in members}
                contradictions = len(results) - 1 if len(results) > 1 \
                    else 0
                valid = (
                    occurrences >= self._min_occurrences
                    and span_days >= self._min_span_days
                    and contradictions <= self._max_contradictions
                )
                lesson = members[-1].get("lesson", "")
                pattern = {
                    "pattern_id": "pat_" + uuid.uuid4().hex[:8],
                    "key": key,
                    "type": members[0].get("type", ""),
                    "trigger": members[0].get("trigger", ""),
                    "occurrences": occurrences,
                    "span_days": round(span_days, 2),
                    "contradictions": contradictions,
                    "lesson": lesson,
                    "valid": valid,
                    "reason": (
                        f"出现 {occurrences} 次 (需 >= {self._min_occurrences}), "
                        f"跨度 {span_days:.1f} 天 (需 >= {self._min_span_days}), "
                        f"反例 {contradictions} 个 (需 <= {self._max_contradictions})"
                    ),
                }
                patterns.append(pattern)
            patterns.sort(key=lambda p: -p["occurrences"])
            valid = [p for p in patterns if p["valid"]]
            return {
                "mode": "rule_based",
                "patterns": patterns,
                "valid_patterns": valid,
                "total": len(patterns),
                "valid_count": len(valid),
            }

    # ── 模式条件说明 ──────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        """模式条件 (可解释)"""
        with self._lock:
            return {
                "min_occurrences": self._min_occurrences,
                "min_span_days": self._min_span_days,
                "max_contradictions": self._max_contradictions,
            }


__all__ = [
    "PatternDiscovery",
    "PatternError",
]
