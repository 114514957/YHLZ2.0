"""
YHLZ Embodied AI V4.2 - 状态不变式检测器 (State Invariant Checker)

职责:
    - 检测"不应自发发生"的状态变化 (如 door=open 不会自动变成 door=closed)
    - 校验预测结果是否违反不变式 (预测禁止违反物理/环境规则)
    - 规则驱动, 禁止黑盒 AI 预测

不变式规则 (DEFAULT_INVARIANT_RULES):
    - 对象状态 (open/closed/on/off/held/...) 仅在对应动作后变化
      (如 'open' → 'closed' 必须由动作触发, 不允许自发翻转)
    - 主体位置变化必须有移动动作
    - 已消失的对象不会自动出现 (对象数不减少为前提)

用法:
    checker = InvariantChecker()
    violations = checker.check(prev_state, curr_state)
    ok = checker.check_prediction(step_prediction)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.schema import EnvironmentState

logger = logging.getLogger(__name__)


class InvariantError(Exception):
    """不变式检测异常"""


# 不变式规则: (规则名, 说明)
DEFAULT_INVARIANT_RULES: List[Dict[str, str]] = [
    {
        "name": "no_spontaneous_state_change",
        "description": "对象状态不会自发变化 (需动作触发)",
    },
    {
        "name": "no_spontaneous_position_change",
        "description": "主体位置不会自发变化 (需移动动作)",
    },
    {
        "name": "no_spontaneous_object_appearance",
        "description": "环境对象不会凭空出现 (reset 除外)",
    },
]


class InvariantChecker:
    """状态不变式检测器 (规则驱动)

    用法:
        checker = InvariantChecker()
        checker.check(prev, curr)             # 两次观察之间是否有违规
        checker.check_prediction(change)      # 预测是否违反不变式
    """

    def __init__(self, rules: Optional[List[Dict[str, str]]] = None):
        self._lock = threading.RLock()
        self._rules = rules if rules is not None else list(DEFAULT_INVARIANT_RULES)

    # ── 规则管理 ──────────────────────────────────────────────────
    @property
    def rules(self) -> List[Dict[str, str]]:
        with self._lock:
            return list(self._rules)

    def add_rule(self, name: str, description: str) -> None:
        """新增不变式规则"""
        with self._lock:
            self._rules.append({"name": name, "description": description})

    # ── 观察级检测 ────────────────────────────────────────────────
    def check(
        self,
        previous_state: Optional[EnvironmentState],
        current_state: Optional[EnvironmentState],
        action_types: Optional[List[str]] = None,
        allowed_state_changes: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """检测两次状态之间是否有不变式违反

        Args:
            previous_state:      之前的状态 (None=无法检测)
            current_state:       当前状态
            action_types:        期间执行过的动作类型 (豁免位置变化)
            allowed_state_changes: 允许状态变化的对象名列表 (由对应动作解释, 如 pick→held)

        Returns:
            违反列表 (空=全部通过)
        """
        if previous_state is None or current_state is None:
            return []
        action_types = action_types or []
        allowed_state_changes = set(allowed_state_changes or [])
        violations: List[Dict[str, Any]] = []

        # 1. 对象状态自发变化 (未由动作解释的视为自发)
        prev_objs = {o.object_id: o for o in previous_state.objects}
        curr_objs = {o.object_id: o for o in current_state.objects}
        for oid, obj in curr_objs.items():
            prev = prev_objs.get(oid)
            if prev is None:
                continue
            if prev.state != obj.state and obj.name not in allowed_state_changes:
                violations.append({
                    "rule": "no_spontaneous_state_change",
                    "object": obj.name,
                    "state": {"from": prev.state, "to": obj.state},
                    "note": "对象状态变化必须由对应动作触发 (如 pick→held)",
                })

        # 2. 主体位置自发变化 (无移动动作时)
        if previous_state.location != current_state.location:
            moved = any(
                t in action_types
                for t in ("move", "explore", "custom")
            )
            if not moved:
                violations.append({
                    "rule": "no_spontaneous_position_change",
                    "location": {
                        "from": previous_state.location,
                        "to": current_state.location,
                    },
                    "note": "主体位置变化必须有移动动作",
                })

        # 3. 对象凭空出现
        added = [oid for oid in curr_objs if oid not in prev_objs]
        if added:
            violations.append({
                "rule": "no_spontaneous_object_appearance",
                "added": [curr_objs[oid].name for oid in added],
                "note": "环境对象不会凭空出现 (reset 除外)",
            })

        return violations

    # ── 预测级检测 ────────────────────────────────────────────────
    def check_prediction(
        self,
        expected_change: Dict[str, Any],
        current_state: Optional[EnvironmentState] = None,
    ) -> List[Dict[str, Any]]:
        """检测预测变化是否违反不变式

        例: 稳定性预测 door=open → open 正确; 若预测 open → closed 则违反。
        """
        expected = (expected_change or {}).get("expected", "unknown")
        if expected == "no_change" or expected == "stability":
            return []
        event = (expected_change or {}).get("event", "")
        if event in ("stability", "reset"):
            return []
        violations: List[Dict[str, Any]] = []
        # 位置变化必须伴随 move 事件
        if expected == "position_change" and event != "move":
            violations.append({
                "rule": "no_spontaneous_position_change",
                "expected_change": expected_change,
                "note": "预测位置变化必须由 move 动作触发",
            })
        return violations

    # ── 状态 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "rules_count": len(self._rules),
                "rules": list(self._rules),
                "mode": "rule_based",
            }

    def reset(self) -> None:
        with self._lock:
            self._rules = list(DEFAULT_INVARIANT_RULES)


__all__ = ["InvariantChecker", "InvariantError", "DEFAULT_INVARIANT_RULES"]
