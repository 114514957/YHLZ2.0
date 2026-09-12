"""
YHLZ Embodied AI V4.4 - 趋势统计系统 (Trend Stats)

职责:
    - 长期趋势观察: 场景成功率 (room / warehouse / custom) + 目标成功率 (pick/move/place/inspect/scan)
    - 数据来源: GoalTraceStore (GoalTrace 轨迹)
    - 统计维度: success / failure / duration (平均耗时)
    - 滚动窗口: 每个维度取最近 N 次 (默认 10)

设计原则:
    - 只统计不学习: 纯规则聚合, 输出可解释趋势
    - 数据独立存储: 绝不写入 Agent Memory
    - 线程安全 (RLock)
    - 窗口 / 维度全部可配置
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 目标类型白名单 (规划意图 → 目标类型)
GOAL_TYPES: List[str] = ["pick", "move", "place", "inspect", "scan"]

# 目标类型关键字规则表 (可解释, 与 plan_actions 一致)
GOAL_TYPE_KEYWORDS: List[tuple] = [
    ("pick", ("pick", "拾取", "拿起", "抓取")),
    ("move", ("move", "移动")),
    ("place", ("place", "放置")),
    ("inspect", ("inspect", "检查", "查看")),
    ("scan", ("scan", "扫描", "探索")),
]


class TrendStatsError(Exception):
    """趋势统计操作异常"""


def infer_goal_type(goal: Dict[str, Any], plan: Optional[List[Any]] = None) -> str:
    """从目标推断 goal_type (可解释规则)

    规则:
        - 目标 dict 携带 goal_type → 直接返回
        - 否则按关键字规则表匹配 description / intent
        - 否则取计划首动作类型 (recipe 语义)
        - 均未匹配 → ''
    """
    if goal:
        explicit = goal.get("goal_type", "")
        if explicit in GOAL_TYPES:
            return explicit
        text = " ".join([
            str(goal.get("description", "")),
            str(goal.get("intent", "")),
        ]).lower()
        for gtype, kws in GOAL_TYPE_KEYWORDS:
            for kw in kws:
                if kw in text:
                    return gtype
    if plan:
        first = plan[0] if plan else None
        if first is not None:
            at = (
                getattr(first, "action_type", None)
                or (first.get("action_type") if isinstance(first, dict) else "")
            )
            if at in GOAL_TYPES:
                return at
    return ""


class TrendStats:
    """趋势统计 (基于 GoalTraceStore 数据源)

    用法:
        trends = TrendStats(window=10)
        report = trends.trend_stats(traces)   # traces: List[GoalTrace]
    """

    def __init__(self, window: int = 10):
        if window <= 0:
            raise TrendStatsError(f"window 必须 > 0, 当前: {window}")
        self._lock = threading.RLock()
        self._window = window

    # ── 聚合 (滚动窗口, 每个维度最近 N 次) ─────────────────────────
    def trend_stats(self, traces) -> Dict[str, Any]:
        """趋势统计报告

        Args:
            traces: GoalTrace 列表 (来自 GoalTraceStore.all(), 最旧在前)

        Returns:
            {
                'window': 10,
                'overall': {'total', 'success', 'failure', 'success_rate',
                            'avg_duration_ms', 'total_failures'},
                'by_scene': {'room': {'total', 'success', 'failure',
                                      'success_rate', 'avg_duration_ms'}, ...},
                'by_goal_type': {'pick': {...}, ...},
                'mode': 'rule_based',
            }
        """
        traces = list(traces or [])
        overall = self._aggregate(traces)
        by_scene: Dict[str, List[Any]] = {}
        by_goal: Dict[str, List[Any]] = {}
        for t in traces:
            scene = t.environment or "custom"
            by_scene.setdefault(scene, []).append(t)
            goal_type = infer_goal_type(t.goal or {}, t.plan)
            if goal_type:
                by_goal.setdefault(goal_type, []).append(t)
        return {
            "window": self._window,
            "overall": overall,
            "by_scene": {
                scene: self._aggregate(v)
                for scene, v in by_scene.items()
            },
            "by_goal_type": {
                gt: self._aggregate(v)
                for gt, v in by_goal.items()
            },
            "mode": "rule_based",
        }

    def _aggregate(self, traces: List[Any]) -> Dict[str, Any]:
        """聚合统计 (滚动窗口: 仅最近 self._window 条参与)"""
        recent = traces[-self._window:] if self._window > 0 else traces
        success = sum(1 for t in recent if t.success)
        total = len(recent)
        durations = [t.duration_ms for t in recent if t.duration_ms > 0]
        return {
            "total": total,
            "success": success,
            "failure": total - success,
            "success_rate": round(success / total, 4) if total else 0.0,
            "avg_duration_ms": (
                round(sum(durations) / len(durations), 2) if durations else 0.0
            ),
            "total_failures": sum(t.failures for t in recent),
        }

    def scene_success_rate(self, traces, scene: str) -> Dict[str, Any]:
        """指定场景成功率 (最近 N 次滚动窗口)"""
        subset = [t for t in (traces or []) if (t.environment or "custom") == scene]
        return self._aggregate(subset)

    def goal_type_success_rate(self, traces, goal_type: str) -> Dict[str, Any]:
        """指定目标类型成功率 (最近 N 次滚动窗口)"""
        if goal_type not in GOAL_TYPES:
            return self._aggregate([])
        subset = [
            t for t in (traces or [])
            if infer_goal_type(t.goal or {}, t.plan) == goal_type
        ]
        return self._aggregate(subset)

    @property
    def window(self) -> int:
        with self._lock:
            return self._window


__all__ = ["TrendStats", "TrendStatsError", "GOAL_TYPES", "infer_goal_type"]
