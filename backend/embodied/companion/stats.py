"""
YHLZ Embodied AI V5.1 - 伙伴协同统计 (Companion Coordination Stats)

职责:
    - 记录每次委派: Agent 组合 / 耗时 / 成功率
    - 聚合统计: 委派次数 / 成功率 / 平均耗时 / Top 组合 / 每 Agent 统计
    - 可解释: 全部统计为规则计数

设计原则:
    - 内存环形统计 (deque, 可配置上限)
    - 纯计数 + 聚合 (禁止黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter, deque
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


class StatsError(Exception):
    """协同统计操作异常"""


class CompanionStats:
    """伙伴协同统计器

    用法:
        stats = CompanionStats(max_records=500)
        stats.record(assigned_agents, ok_count, total, latency_ms)
        report = stats.summary()
    """

    def __init__(self, max_records: int = 500):
        if max_records <= 0:
            raise StatsError(f"max_records 必须 > 0, 当前: {max_records}")
        self._lock = threading.RLock()
        self._records: Deque[Dict[str, Any]] = deque(maxlen=max_records)
        self._max_records = max_records

    # ── 记录 ──────────────────────────────────────────────────────
    def record(
        self,
        assigned_agents: List[str],
        ok_count: int,
        total: int,
        latency_ms: float,
        parallel: bool = False,
    ) -> Dict[str, Any]:
        """记录一次委派"""
        entry = {
            "timestamp": time.time(),
            "agents": list(assigned_agents),
            "ok_count": int(ok_count),
            "total": int(total),
            "latency_ms": round(float(latency_ms), 2),
            "parallel": bool(parallel),
        }
        with self._lock:
            self._records.append(entry)
        return entry

    def clear(self) -> int:
        """清空统计 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n

    # ── 聚合 ──────────────────────────────────────────────────────
    def summary(self) -> Dict[str, Any]:
        """协同统计汇总

        Returns:
            {
                'mode': 'rule_based',
                'total_delegations': n,
                'total_agents_invoked': n,
                'success_rate': 0.0~1.0,
                'avg_latency_ms': float,
                'parallel_ratio': 0.0~1.0,
                'top_combinations': [{'agents': [...], 'count': n}, ...],
                'per_agent': {'name': {'invocations', 'successes', 'failures',
                                       'success_rate'}, ...},
                'recent': [...],
            }
        """
        with self._lock:
            records = list(self._records)
        if not records:
            return {
                "mode": "rule_based",
                "total_delegations": 0,
                "total_agents_invoked": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "parallel_ratio": 0.0,
                "top_combinations": [],
                "per_agent": {},
                "recent": [],
            }
        total = len(records)
        ok_total = sum(r["ok_count"] for r in records)
        invoked_total = sum(r["total"] for r in records)
        success_rate = (
            round(ok_total / invoked_total, 4) if invoked_total else 0.0
        )
        avg_latency = round(
            sum(r["latency_ms"] for r in records) / total, 2,
        )
        parallel_count = sum(1 for r in records if r["parallel"])
        # Top 组合 (按次数降序)
        combo_counter: Counter = Counter(
            tuple(sorted(r["agents"])) for r in records
        )
        top_combinations = [
            {"agents": list(agents), "count": count}
            for agents, count in combo_counter.most_common(5)
        ]
        # 每 Agent 统计
        per_agent: Dict[str, Dict[str, Any]] = {}
        for r in records:
            for agent in r["agents"]:
                cell = per_agent.setdefault(agent, {
                    "invocations": 0, "successes": 0, "failures": 0,
                })
                cell["invocations"] += 1
        # 每 Agent 成功数 (需按结果归属, 简化: 用 ok_count 比例近似)
        for r in records:
            if not r["agents"]:
                continue
            # 按 agent 数均摊 ok (近似, 可解释)
            share = r["ok_count"] / len(r["agents"])
            for agent in r["agents"]:
                cell = per_agent[agent]
                cell["successes"] += share
        for agent, cell in per_agent.items():
            cell["successes"] = int(round(cell["successes"]))
            cell["failures"] = max(0, cell["invocations"] - cell["successes"])
            cell["success_rate"] = round(
                cell["successes"] / cell["invocations"], 4,
            ) if cell["invocations"] else 0.0
        return {
            "mode": "rule_based",
            "total_delegations": total,
            "total_agents_invoked": invoked_total,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency,
            "parallel_ratio": round(parallel_count / total, 4),
            "top_combinations": top_combinations,
            "per_agent": per_agent,
            "recent": list(reversed(records))[:10],
        }

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._records)


__all__ = [
    "CompanionStats",
    "StatsError",
]
