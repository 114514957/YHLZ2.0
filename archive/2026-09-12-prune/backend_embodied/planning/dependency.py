"""
YHLZ Embodied AI V4.6 - 目标关系分析 (Goal Dependency Analysis)

职责:
    - 目标分组分析: 相同 scene × goal_type × action_sequence → 目标组
    - 共享步骤识别: 多个目标共同需要的前置步骤 (如 scan) → 只规划一次
    - 信息复用分析: 一次动作的结果可供多个目标使用 (信息增益)

核心概念 (可解释, 纯规则):
    - 目标组 (Goal Group): 同场景 + 同目标类型 + 同动作序列的目标集合,
      可批量规划 (一次共享前置步骤 + 逐个执行主体动作)
    - 共享步骤 (Shared Step): 组内共同需要的前置动作,
      规划为一次执行 (如 scan 一次覆盖多个 pick)
    - 信息复用 (Information Reuse): 观察/扫描类动作的结果服务多个目标,
      减少重复感知成本

设计原则:
    - 只读分析: 本模块不修改任何状态 (规划执行由 cross_goal 模块负责)
    - 规则 + 统计 + 阈值: 纯可解释输出, 禁止黑盒学习
    - 数据独立: 不写入 Agent Memory
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from backend.embodied.schema import EmbodiedGoal

logger = logging.getLogger(__name__)

# 可共享前置动作类型 (信息复用: 一次执行服务多个目标)
SHARABLE_ACTION_TYPES: List[str] = ["scan", "observe", "explore"]


class DependencyError(Exception):
    """目标关系分析操作异常"""


def plan_action_sequence(goal: EmbodiedGoal) -> List[Dict[str, Any]]:
    """目标 → 动作序列 (规则驱动, 与 Service.plan_actions 一致的映射)

    说明:
        - 本模块不依赖 Service, 独立提供动作序列推导 (避免循环依赖)
        - 规则: intent/description 关键词 → 动作类型 (按关键词出现顺序收集)
        - 例: "扫描房间再拿起台灯" → [scan, pick]
    """
    if goal is None:
        return []
    text = (goal.description + " " + goal.intent).lower()
    seq: List[Dict[str, Any]] = []
    seen: set = set()
    for kw, action_type in (
        ("scan", "scan"), ("扫描", "scan"), ("探索", "scan"),
        ("pick", "pick"), ("拿起", "pick"), ("抓取", "pick"),
        ("place", "place"), ("放置", "place"),
        ("move", "move"), ("移动", "move"),
        ("inspect", "inspect"), ("检查", "inspect"), ("查看", "inspect"),
    ):
        if kw in text and action_type not in seen:
            seq.append({"action_type": action_type, "target": goal.target or ""})
            seen.add(action_type)
    if not seq:
        seq.append({"action_type": "explore", "target": goal.target or ""})
    return seq


def infer_goal_type_of(goal: EmbodiedGoal, sequence: List[Dict[str, Any]]) -> str:
    """目标类型推断 (规则驱动): 意图 > 主动作 (序列最后一步) > custom"""
    if goal is None:
        return ""
    if goal.intent:
        return goal.intent
    if goal.target:
        return "custom"
    if sequence:
        return sequence[-1].get("action_type", "")
    return ""


class GoalDependencyAnalyzer:
    """目标关系分析器 (分组 / 共享步骤 / 信息复用)

    用法:
        analyzer = GoalDependencyAnalyzer()
        groups = analyzer.analyze_groups(goals)
        shared = analyzer.shared_steps(groups)
        reuse = analyzer.information_reuse(goals)
    """

    def __init__(self, min_group_size: int = 1):
        if min_group_size <= 0:
            raise DependencyError(
                f"min_group_size 必须 > 0, 当前: {min_group_size}"
            )
        self._lock = threading.RLock()
        self._min_group_size = min_group_size

    # ── 1. 目标分组分析 ───────────────────────────────────────────
    def _goal_signature(self, goal: EmbodiedGoal) -> Tuple[str, str, tuple]:
        """目标签名 (可解释): (scene, goal_type, 动作类型序列)

        分组维度只使用动作类型序列 (不含 target 等目标差异),
        保证同 scene × goal_type × action_sequence 的目标归入同一组。
        """
        seq = plan_action_sequence(goal)
        frozen = tuple(step.get("action_type", "") for step in seq)
        return (goal.scene or "*", infer_goal_type_of(goal, seq), frozen)

    def analyze_groups(
        self,
        goals: List[EmbodiedGoal],
        min_group_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """目标分组分析

        规则 (可解释):
            - 相同 scene × goal_type × action_sequence → 同一目标组
            - 组大小 >= min_group_size (默认 1) 才输出

        Returns:
            {
                'rule': '相同 scene×goal_type×action_sequence → 目标组',
                'groups': [
                    {
                        'group_id', 'scene', 'goal_type', 'action_sequence',
                        'member_count', 'goal_ids': [...], 'goals': [...],
                        'batch_plan': bool,   # member_count > 1 → 可批量规划
                    }, ...
                ],
                'total': n,
                'batched_goals': n,   # 参与批量规划的目标数
            }
        """
        threshold = min_group_size or self._min_group_size
        with self._lock:
            groups_map: Dict[Tuple[str, str, tuple], List[EmbodiedGoal]] = {}
            for goal in goals:
                sig = self._goal_signature(goal)
                groups_map.setdefault(sig, []).append(goal)

        out_groups: List[Dict[str, Any]] = []
        batched = 0
        for i, (sig, members) in enumerate(sorted(
            groups_map.items(),
            key=lambda kv: (kv[0][0], kv[0][1]),
        )):
            if len(members) < threshold:
                continue
            scene, goal_type, frozen = sig
            # 还原动作序列 (动作类型列表 → 完整动作 dict)
            action_sequence = [
                {"action_type": at, "target": ""} for at in frozen
            ]
            out_groups.append({
                "group_id": f"group_{i + 1}",
                "scene": scene,
                "goal_type": goal_type,
                "action_sequence": action_sequence,
                "member_count": len(members),
                "goal_ids": [g.goal_id for g in members],
                "goals": [g.to_dict() for g in members],
                "batch_plan": len(members) > 1,
            })
            if len(members) > 1:
                batched += len(members)
        return {
            "rule": "相同 scene×goal_type×action_sequence → 目标组",
            "groups": out_groups,
            "total": len(out_groups),
            "batched_goals": batched,
        }

    # ── 2. 共享步骤识别 ───────────────────────────────────────────
    def shared_steps(self, groups: Dict[str, Any]) -> Dict[str, Any]:
        """共享步骤识别: 组内共同需要的前置步骤 → 只规划一次

        规则 (可解释):
            - 每组内: 成员共同需要的前置动作 (组动作序列中 1..n-1 个可共享动作)
            - 可共享动作类型: scan / observe / explore (信息复用型)
            - 主动作 (最后一步) 不共享 (必须逐目标执行)

        Returns:
            {
                'rule': '组内共同需要的前置 scan/observe → 只执行一次',
                'shared_steps': [
                    {
                        'group_id', 'scene', 'goal_type',
                        'action_type', 'member_count', 'saved_steps': n-1,
                        'reason': '一次 scan 服务 N 个 pick 目标',
                    }, ...
                ],
                'total_saved': n,   # 总节省步骤数
            }
        """
        with self._lock:
            out: List[Dict[str, Any]] = []
            total_saved = 0
            for g in groups.get("groups", []):
                seq = g.get("action_sequence", [])
                members = g.get("member_count", 1)
                # 找组内共同前置可共享步骤 (除最后一步主动作外)
                shared = [
                    s for s in seq[:-1]
                    if s.get("action_type") in SHARABLE_ACTION_TYPES
                ] if len(seq) > 1 else []
                for s in shared:
                    saved = members - 1
                    out.append({
                        "group_id": g["group_id"],
                        "goal_ids": list(g.get("goal_ids", [])),
                        "scene": g.get("scene"),
                        "goal_type": g.get("goal_type"),
                        "action_type": s["action_type"],
                        "member_count": members,
                        "saved_steps": saved,
                        "reason": (
                            f"一次 {s['action_type']} 服务 {members} 个目标, "
                            f"节省 {saved} 次重复执行"
                        ),
                    })
                    total_saved += saved
        return {
            "rule": "组内共同需要的前置 scan/observe/explore → 只执行一次",
            "shared_steps": out,
            "total_saved": total_saved,
        }

    # ── 3. 信息复用分析 ───────────────────────────────────────────
    def information_reuse(self, goals: List[EmbodiedGoal]) -> Dict[str, Any]:
        """信息复用分析: 观察/扫描类目标可为后续目标提供共享信息

        规则 (可解释):
            - scan/observe/explore 类目标 → 信息供给者
            - 同场景其他非 scan 目标 → 信息消费者
            - 一次感知可为 N 个消费者复用 (减少重复感知成本)

        Returns:
            {
                'rule': '感知目标 (scan) 一次执行, 同场景 N 个目标复用信息',
                'reuse_groups': [
                    {
                        'provider_goal_id', 'provider_action', 'scene',
                        'consumers': [goal_id...], 'consumer_count',
                        'saved_perceptions': n,  # 消费者-1 (自身已感知)
                        'reason': ...,
                    }, ...
                ],
                'total': n,
            }
        """
        with self._lock:
            goals = list(goals or [])
            providers = [
                g for g in goals
                if plan_action_sequence(g)[0]["action_type"] in SHARABLE_ACTION_TYPES
            ]
            consumers = [
                g for g in goals
                if plan_action_sequence(g)[0]["action_type"] not in SHARABLE_ACTION_TYPES
            ]
            reuse_groups: List[Dict[str, Any]] = []
            for p in providers:
                same_scene = [
                    c for c in consumers if (c.scene or "*") == (p.scene or "*")
                ]
                if not same_scene:
                    continue
                reuse_groups.append({
                    "provider_goal_id": p.goal_id,
                    "provider_action": plan_action_sequence(p)[0]["action_type"],
                    "scene": p.scene or "*",
                    "consumers": [c.goal_id for c in same_scene],
                    "consumer_count": len(same_scene),
                    "saved_perceptions": len(same_scene),
                    "reason": (
                        f"感知目标 {p.goal_id} ({plan_action_sequence(p)[0]['action_type']}) "
                        f"一次执行, 同场景 {len(same_scene)} 个目标复用信息"
                    ),
                })
        return {
            "rule": "感知目标 (scan/observe/explore) 一次执行, 同场景目标复用信息",
            "reuse_groups": reuse_groups,
            "total": len(reuse_groups),
        }


__all__ = [
    "DependencyError",
    "GoalDependencyAnalyzer",
    "SHARABLE_ACTION_TYPES",
    "infer_goal_type_of",
    "plan_action_sequence",
]
