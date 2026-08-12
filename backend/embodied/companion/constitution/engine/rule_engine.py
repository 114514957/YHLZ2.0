"""
YHLZ Embodied AI V8.0 - 规则引擎 (Rule Engine)

职责:
    - 组合执行治理规则 (原则/身份/安全/成长/智能)
    - 跨层冲突仲裁 (固定优先级)

治理优先级 (固定):
    Identity > Safety > Constitution > Growth
    > Intelligence Routing > Expression

低等级模块不得覆盖高等级规则。

设计原则:
    - 纯规则仲裁 (可解释)
    - 优先级固定 (禁止动态修改)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, Optional

from backend.embodied.companion.constitution.core.principles import (
    GOVERNANCE_PRIORITIES,
)

logger = logging.getLogger(__name__)


class RuleEngineError(Exception):
    """规则引擎操作异常"""


class RuleEngine:
    """规则引擎 (规则组合 + 优先级仲裁)

    用法:
        engine = RuleEngine(principles=..., safety=...)
        r = engine.evaluate(action_context)
        r = engine.arbitrate(conflict_event)
    """

    def __init__(
        self,
        principles=None,
        identity_rules=None,
        safety=None,
        growth=None,
        intelligence=None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._principles = principles
        self._identity = identity_rules
        self._safety = safety
        self._growth = growth
        self._intelligence = intelligence
        self._results: list = []
        self._arbitrations: list = []

    # ── 组合评估 ─────────────────────────────────────────────────
    def evaluate(
        self,
        action_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """组合治理评估 (按优先级依次检查)

        Args:
            action_context:
                {
                    "action_text": str,      # 行为文本
                    "change": {...},         # 拟变更字段
                    "module": str,           # 来源模块
                    "cloud_result": {...},   # 云端结果 (可选)
                    "growth_proposal": {...},# 成长建议 (可选)
                }

        Returns:
            {
                'decision' (allow/block/review),
                'priority', 'reasons', 'checked_rules',
                'mode',
            }
        """
        with self._lock:
            if not self._enabled:
                return self._finish(
                    "allow", "constitution", ["规则引擎停用"],
                    [], action_context or {},
                )
            action_context = action_context or {}
            reasons: list = []
            checked: list = []
            text = str(action_context.get(
                "action_text", "",
            ))
            change = action_context.get("change") or {}
            # 1. Identity (最高)
            if self._identity is not None:
                r = self._identity.check_change(change)
                checked.append("identity_rules")
                if not r["ok"]:
                    return self._finish(
                        "block", "identity", [r["reason"]],
                        checked, action_context,
                    )
                reasons.append(r["reason"])
            # 2. Safety
            if self._safety is not None:
                r = self._safety.check(text)
                checked.append("safety_policy")
                if not r["allowed"]:
                    return self._finish(
                        "block", "safety", [r["reason"]],
                        checked, action_context,
                    )
                reasons.append(r["reason"])
            # 3. Constitution 原则
            if self._principles is not None:
                r = self._principles.check_action(text)
                checked.append("principles")
                if not r["ok"]:
                    return self._finish(
                        "block", "constitution",
                        [r["reason"]], checked,
                        action_context,
                    )
                reasons.append(r["reason"])
            # 4. Growth (建议审查)
            proposal = action_context.get("growth_proposal")
            if proposal is not None and self._growth is not None:
                r = self._growth.review(proposal)
                checked.append("growth_policy")
                if not r["ok"]:
                    return self._finish(
                        "review", "growth", [r["reason"]],
                        checked, action_context,
                    )
                reasons.append(r["reason"])
            # 5. Intelligence (云端隔离)
            cloud = action_context.get("cloud_result")
            if cloud is not None and \
                    self._intelligence is not None:
                r = self._intelligence.check_cloud(cloud)
                checked.append("intelligence_policy")
                if not r["ok"]:
                    return self._finish(
                        "block", "intelligence",
                        [r["reason"]], checked,
                        action_context,
                    )
                reasons.append(r["reason"])
            return self._finish(
                "allow", "constitution", reasons, checked,
                action_context,
            )

    # ── 冲突仲裁 ─────────────────────────────────────────────────
    def arbitrate(
        self,
        conflict_event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """跨层冲突仲裁 (固定优先级)

        Args:
            conflict_event:
                {
                    "layers": ["growth", "intelligence"],
                    "description": "...",
                    "identity_risk": bool,
                    "safety_risk": bool,
                }

        Returns:
            {
                'winner', 'priority', 'reason',
                'priority_index', 'mode',
            }
        """
        with self._lock:
            layers = list(
                conflict_event.get("layers", []),
            )
            description = str(
                conflict_event.get("description", ""),
            )
            # 风险提升 (可解释)
            if conflict_event.get("identity_risk"):
                layers.insert(0, "identity")
            if conflict_event.get("safety_risk"):
                layers.insert(0, "safety")
            # 取最高优先级层
            winner = None
            winner_index = None
            for layer in layers:
                if layer in GOVERNANCE_PRIORITIES:
                    idx = GOVERNANCE_PRIORITIES.index(layer)
                    if winner_index is None or \
                            idx < winner_index:
                        winner = layer
                        winner_index = idx
            if winner is None:
                winner = "constitution"
                winner_index = GOVERNANCE_PRIORITIES.index(
                    "constitution",
                )
            result = {
                "mode": "rule_based",
                "winner": winner,
                "priority": winner_index,
                "priority_name": GOVERNANCE_PRIORITIES[
                    winner_index],
                "reason": (
                    f"冲突 '{description}': "
                    f"'{winner}' 优先级最高, 低等级不得覆盖"
                ),
            }
            self._arbitrations.append(result)
            return dict(result)

    def _finish(self, decision: str, priority: str,
                reasons: list, checked: list,
                context: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "mode": "rule_based",
            "decision": decision,
            "priority": priority,
            "reasons": list(reasons),
            "checked_rules": list(checked),
            "context": {
                "module": context.get("module", "unknown"),
            },
        }
        self._results.append(result)
        return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """规则引擎统计"""
        with self._lock:
            decisions: Dict[str, int] = {}
            for r in self._results:
                decisions[r["decision"]] = \
                    decisions.get(r["decision"], 0) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "evaluate_count": len(self._results),
                "arbitrate_count": len(self._arbitrations),
                "decisions": decisions,
                "priorities": list(GOVERNANCE_PRIORITIES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results) + len(self._arbitrations)
            self._results.clear()
            self._arbitrations.clear()
            return n


__all__ = [
    "RuleEngine",
    "RuleEngineError",
]
