"""
YHLZ Embodied AI V6.5 - 模式分析器 (Pattern Analyzer)

职责:
    - 统计驱动长期模式发现 (禁止无依据推理)
    - 连续任务成功 → 有效策略
    - 连续失败 → 问题模式

设计原则:
    - 统计驱动 (样本量/连续次数/比例)
    - 可解释 (每条模式含依据)
    - 禁止单次事件形成模式
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PatternError(Exception):
    """模式分析操作异常"""


# 模式类型 (可解释)
PATTERN_TYPES: List[str] = [
    "success_strategy",  # 有效策略 (连续成功)
    "problem_pattern",   # 问题模式 (连续失败)
    "repetition",        # 重复行为
]


class PatternAnalyzer:
    """模式分析器 (统计驱动)

    用法:
        analyzer = PatternAnalyzer(min_samples=3,
                                   min_streak=2)
        patterns = analyzer.analyze(records)
    """

    def __init__(self, min_samples: int = 3,
                 min_streak: int = 2,
                 min_success_rate: float = 0.7,
                 max_patterns: int = 20):
        if min_samples < 2:
            raise PatternError(
                f"min_samples 必须 >= 2, 当前: {min_samples}"
            )
        if min_streak < 2:
            raise PatternError(
                f"min_streak 必须 >= 2, 当前: {min_streak}"
            )
        if not (0.0 <= min_success_rate <= 1.0):
            raise PatternError(
                f"min_success_rate 必须在 [0,1], 当前: "
                f"{min_success_rate}"
            )
        self._lock = threading.RLock()
        self._min_samples = int(min_samples)
        self._min_streak = int(min_streak)
        self._min_rate = float(min_success_rate)
        self._max = int(max_patterns)
        self._patterns: List[Dict[str, Any]] = []

    # ── 分析主入口 ───────────────────────────────────────────────
    def analyze(
        self, records: List[Dict[str, Any]],
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """统计驱动模式发现

        Args:
            records: 经历列表 (trigger/type/result/timestamp)

        Returns:
            模式列表
        """
        with self._lock:
            now = now if now is not None else time.time()
            if len(records) < self._min_samples:
                return []
            patterns: List[Dict[str, Any]] = []
            # 按触发器分组
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for r in records:
                key = str(r.get("trigger", "")).strip()
                if key:
                    groups.setdefault(key, []).append(r)
            for trigger, group in groups.items():
                if len(group) < self._min_samples:
                    continue
                success = sum(
                    1 for r in group
                    if str(r.get("result", "")).find("成功") >= 0
                    or r.get("type") in ("interaction", "improvement",
                                         "engineering")
                )
                rate = success / len(group)
                # 连续成功/失败分析
                max_streak_success = self._max_streak(
                    group, success_key=True,
                )
                max_streak_failure = self._max_streak(
                    group, success_key=False,
                )
                if rate >= self._min_rate and \
                        max_streak_success >= self._min_streak:
                    patterns.append(self._build(
                        "success_strategy", trigger, len(group),
                        rate, max_streak_success, now,
                    ))
                elif rate <= 1.0 - self._min_rate and \
                        max_streak_failure >= self._min_streak:
                    patterns.append(self._build(
                        "problem_pattern", trigger, len(group),
                        rate, max_streak_failure, now,
                    ))
                elif max_streak_success >= self._min_streak:
                    patterns.append(self._build(
                        "repetition", trigger, len(group),
                        rate, max_streak_success, now,
                    ))
            # 按置信度排序 + 上限
            patterns.sort(key=lambda p: p["confidence"],
                          reverse=True)
            patterns = patterns[:self._max]
            self._patterns.extend(patterns)
            return [dict(p) for p in patterns]

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _max_streak(group: List[Dict[str, Any]],
                    success_key: bool) -> int:
        """连续成功/失败最大次数"""
        records = sorted(
            group, key=lambda r: float(r.get("timestamp", 0.0)),
        )
        max_streak = 0
        current = 0
        for r in records:
            is_success = (
                str(r.get("result", "")).find("成功") >= 0
                or r.get("type") in ("interaction", "improvement",
                                     "engineering")
            )
            if is_success == success_key:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def _build(ptype: str, trigger: str, samples: int,
               rate: float, streak: int,
               now: float) -> Dict[str, Any]:
        """构建模式 (可解释)"""
        if ptype == "success_strategy":
            meaning = f"'{trigger}' 连续成功 {streak} 次, 有效策略"
        elif ptype == "problem_pattern":
            meaning = f"'{trigger}' 连续失败 {streak} 次, 问题模式"
        else:
            meaning = f"'{trigger}' 重复出现 {samples} 次"
        confidence = min(0.95, 0.4 + 0.1 * streak +
                         0.15 * samples / 10.0)
        return {
            "pattern_id": "pat_" + uuid.uuid4().hex[:8],
            "type": ptype,
            "trigger": trigger,
            "samples": samples,
            "success_rate": round(rate, 4),
            "max_streak": streak,
            "meaning": meaning,
            "confidence": round(confidence, 4),
            "evidence": f"{samples} 条经历, 成功率 {rate:.0%}",
            "timestamp": now,
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def by_type(self, ptype: str) -> List[Dict[str, Any]]:
        """按类型查询"""
        if ptype not in PATTERN_TYPES:
            raise PatternError(
                f"非法模式类型: {ptype} (可选: {PATTERN_TYPES})"
            )
        with self._lock:
            return [
                dict(p) for p in self._patterns
                if p["type"] == ptype
            ]

    def stats(self) -> Dict[str, Any]:
        """模式统计"""
        with self._lock:
            patterns = list(self._patterns)
        by_type: Dict[str, int] = {}
        for p in patterns:
            by_type[p["type"]] = by_type.get(p["type"], 0) + 1
        return {
            "mode": "rule_based",
            "pattern_count": len(patterns),
            "by_type": by_type,
            "avg_confidence": round(
                sum(p["confidence"] for p in patterns)
                / len(patterns) if patterns else 0.0, 4,
            ),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._patterns)
            self._patterns.clear()
            return n


__all__ = [
    "PATTERN_TYPES",
    "PatternAnalyzer",
    "PatternError",
]
