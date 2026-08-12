"""
YHLZ Embodied AI V4.7 - 依赖关系分析 (Dependency Graph)

职责:
    - dependency_graph(): 里程碑/子目标间依赖关系
    - 输出: 前置任务 / 后续任务 / 阻塞原因
    - 阻塞计算: 前置未完成 → 后续 blocked

规则 (可解释):
    - 依赖: milestone B 依赖 milestone A → A 是 B 的前置
    - 阻塞: B 的前置存在未完成 → B 状态 = blocked
    - 循环检测: 依赖环 → 输出警告 (防止死锁)

设计原则:
    - 只读分析 (不修改状态, 状态变更由 MilestoneManager 负责)
    - 纯规则 + 可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.embodied.planning.milestone import LongGoal, Milestone

logger = logging.getLogger(__name__)


class DependencyGraphError(Exception):
    """依赖关系分析操作异常"""


class DependencyGraph:
    """依赖关系分析器

    用法:
        graph = DependencyGraph()
        graph.set_dependencies(goal, {"m2": ["m1"]})
        result = graph.dependency_graph(goal)
        blocked = graph.compute_blocked(goal)
    """

    def __init__(self):
        self._lock = threading.RLock()

    # ── 依赖设置 ──────────────────────────────────────────────────
    def set_dependencies(
        self,
        goal: LongGoal,
        deps: Dict[str, List[str]],
    ) -> LongGoal:
        """设置里程碑依赖: {milestone_id: [前置 milestone_id...]}

        校验:
            - 里程碑存在
            - 无循环依赖 (A → B → A)
        """
        with self._lock:
            ids = {m.milestone_id for m in goal.milestones}
            for mid, prereqs in deps.items():
                if mid not in ids:
                    raise DependencyGraphError(
                        f"依赖目标里程碑不存在: {mid}"
                    )
                for p in prereqs:
                    if p not in ids:
                        raise DependencyGraphError(
                            f"前置里程碑不存在: {p} (属于 {mid})"
                        )
            # 循环检测 (DFS)
            graph: Dict[str, List[str]] = {}
            for mid, prereqs in deps.items():
                graph[mid] = list(prereqs)
            if self._detect_cycle(graph):
                raise DependencyGraphError(f"依赖存在循环: {deps}")
            goal.dependencies = dict(deps)
            goal.updated_at = __import__("time").time()
            goal.explainable_reason = f"依赖关系更新: {len(deps)} 条"
            return goal

    @staticmethod
    def _detect_cycle(graph: Dict[str, List[str]]) -> bool:
        """环检测 (DFS, 可解释)"""
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def dfs(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for nxt in graph.get(node, []):
                if dfs(nxt):
                    return True
            visiting.discard(node)
            visited.add(node)
            return False

        return any(dfs(n) for n in graph)

    # ── 依赖图输出 ────────────────────────────────────────────────
    def dependency_graph(self, goal: LongGoal) -> Dict[str, Any]:
        """依赖关系图

        Returns:
            {
                'goal_id', 'rule': ...,
                'nodes': [
                    {
                        'milestone_id', 'title', 'order', 'status',
                        'prerequisites': [...],   # 前置任务
                        'successors': [...],      # 后续任务
                        'blocked': bool,
                        'blocked_reason': str,
                    }, ...
                ],
                'cycles': [...],   # 循环检测结果
            }
        """
        with self._lock:
            deps = dict(goal.dependencies)
            nodes: List[Dict[str, Any]] = []
            cycles: List[str] = []
            completed_ids = {
                m.milestone_id for m in goal.milestones
                if m.status == "completed"
            }
            for m in sorted(goal.milestones, key=lambda x: x.order):
                prereqs = deps.get(m.milestone_id, [])
                successors = [
                    mid for mid, ps in deps.items()
                    if m.milestone_id in ps
                ]
                missing = [p for p in prereqs if p not in completed_ids]
                blocked = bool(missing) and m.status != "completed"
                nodes.append({
                    "milestone_id": m.milestone_id,
                    "title": m.title,
                    "order": m.order,
                    "status": m.status,
                    "prerequisites": list(prereqs),
                    "successors": successors,
                    "blocked": blocked,
                    "blocked_reason": (
                        f"前置里程碑未完成: {missing}"
                        if missing else ""
                    ),
                })
            # 循环检测
            graph: Dict[str, List[str]] = {
                m.milestone_id: deps.get(m.milestone_id, [])
                for m in goal.milestones
            }
            visiting: Set[str] = set()
            visited: Set[str] = set()
            stack: List[str] = []

            def dfs_cycle(node: str) -> bool:
                if node in visiting:
                    cycle_start = stack[stack.index(node):]
                    cycles.append(" → ".join(cycle_start + [node]))
                    return True
                if node in visited:
                    return False
                visiting.add(node)
                stack.append(node)
                for nxt in graph.get(node, []):
                    dfs_cycle(nxt)
                visiting.discard(node)
                stack.pop()
                visited.add(node)
                return False

            for mid in graph:
                dfs_cycle(mid)
            return {
                "goal_id": goal.goal_id,
                "rule": "前置未完成 → 阻塞; 依赖环 → 警告",
                "nodes": nodes,
                "cycles": cycles,
            }

    # ── 阻塞计算 ─────────────────────────────────────────────────
    def compute_blocked(self, goal: LongGoal) -> List[str]:
        """计算被阻塞的里程碑 ID 列表 (前置未完成)"""
        with self._lock:
            completed_ids = {
                m.milestone_id for m in goal.milestones
                if m.status == "completed"
            }
            blocked: List[str] = []
            for mid, prereqs in goal.dependencies.items():
                if any(p not in completed_ids for p in prereqs):
                    blocked.append(mid)
            return blocked

    # ── 可执行顺序 (拓扑) ────────────────────────────────────────
    def execution_order(self, goal: LongGoal) -> List[Dict[str, Any]]:
        """推荐执行顺序 (拓扑排序, 依赖优先)

        Returns:
            [{'milestone_id', 'title', 'order'}, ...]
        """
        with self._lock:
            deps = dict(goal.dependencies)
            done: Set[str] = set()
            ordered: List[Dict[str, Any]] = []
            pending = sorted(goal.milestones, key=lambda x: x.order)
            while len(ordered) < len(pending):
                progress = False
                for m in pending:
                    if m.milestone_id in done:
                        continue
                    if all(p in done for p in deps.get(m.milestone_id, [])):
                        done.add(m.milestone_id)
                        ordered.append({
                            "milestone_id": m.milestone_id,
                            "title": m.title,
                            "order": m.order,
                        })
                        progress = True
                if not progress:
                    break   # 剩余为循环依赖
            return ordered


__all__ = [
    "DependencyGraph",
    "DependencyGraphError",
]
