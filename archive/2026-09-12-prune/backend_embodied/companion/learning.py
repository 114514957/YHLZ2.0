"""
YHLZ Embodied AI V5.4 - 学习器 (Companion Learning)

职责:
    - 失败学习: 失败模式统计 (原因/动作/场景) → 更新失败规则表 (可解释)
    - 成功学习: 成功模式统计 → 更新成功配方规则 (可解释)
    - 学习阈值: 模式出现 N 次 → 提升为规则 (可配置)

数据模型:
    LearningRule:
    {
        pattern, action, count, last_seen, reason,
    }

设计原则:
    - 学习 = 规则统计 (禁止神经网络训练 / 梯度更新 / 黑盒优化)
    - 只统计不执行: 学习结果供修正器/策略参考
    - 不写 Agent Memory (规则表独立存储)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LearningError(Exception):
    """学习器操作异常"""


class CompanionLearning:
    """学习器 (失败/成功模式 → 规则表)

    用法:
        learner = CompanionLearning(threshold=3)
        learner.record_failure(cause="position_mismatch", action="pick")
        rules = learner.learning()
    """

    def __init__(
        self,
        enabled: bool = True,
        threshold: int = 3,
        max_rules: int = 100,
    ):
        if threshold <= 0:
            raise LearningError(f"threshold 必须 > 0, 当前: {threshold}")
        if max_rules <= 0:
            raise LearningError(f"max_rules 必须 > 0, 当前: {max_rules}")
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._threshold = int(threshold)
        self._max_rules = int(max_rules)
        # pattern_key → {count, last_seen, pattern 字段}
        self._failures: Dict[str, Dict[str, Any]] = {}
        self._successes: Dict[str, Dict[str, Any]] = {}

    # ── 模式键 (可解释) ───────────────────────────────────────────
    @staticmethod
    def _pattern_key(kind: str, cause: str, action: str,
                     scene: str = "") -> str:
        """模式键: kind/cause/action/scene (确定性)"""
        return f"{kind}|{cause or 'unknown'}|{action or 'any'}|{scene or '*' }"

    # ── 失败学习 ──────────────────────────────────────────────────
    def record_failure(
        self,
        cause: str = "unknown",
        action: str = "",
        scene: str = "",
        detail: str = "",
    ) -> Dict[str, Any]:
        """记录一次失败 (模式统计)"""
        with self._lock:
            if not self._enabled:
                return {"recorded": False, "reason": "学习已停用"}
            key = self._pattern_key("failure", cause, action, scene)
            cell = self._failures.setdefault(key, {
                "pattern": {
                    "kind": "failure", "cause": cause or "unknown",
                    "action": action or "any", "scene": scene or "*",
                },
                "count": 0, "last_seen": 0.0,
            })
            cell["count"] += 1
            cell["last_seen"] = time.time()
            cell["detail"] = detail or cell.get("detail", "")
            return {
                "recorded": True,
                "key": key,
                "count": cell["count"],
                "promoted": cell["count"] >= self._threshold,
            }

    # ── 成功学习 ──────────────────────────────────────────────────
    def record_success(
        self,
        action: str = "",
        scene: str = "",
        intent: str = "",
    ) -> Dict[str, Any]:
        """记录一次成功 (成功配方统计)"""
        with self._lock:
            if not self._enabled:
                return {"recorded": False, "reason": "学习已停用"}
            key = self._pattern_key("success", intent, action, scene)
            cell = self._successes.setdefault(key, {
                "pattern": {
                    "kind": "success", "cause": intent or "any",
                    "action": action or "any", "scene": scene or "*",
                },
                "count": 0, "last_seen": 0.0,
            })
            cell["count"] += 1
            cell["last_seen"] = time.time()
            return {
                "recorded": True,
                "key": key,
                "count": cell["count"],
                "promoted": cell["count"] >= self._threshold,
            }

    # ── 规则表 ────────────────────────────────────────────────────
    def learning(self) -> Dict[str, Any]:
        """学习结果: 失败/成功模式规则表 (可解释)

        Returns:
            {
                'enabled': bool, 'threshold': n,
                'failure_rules': [LearningRule...],   # 达阈值提升为规则
                'success_rules': [LearningRule...],
                'failure_patterns': [...],             # 全部统计 (含未达阈值)
                'success_patterns': [...],
                'mode': 'rule_based',
            }
        """
        with self._lock:
            failures = dict(self._failures)
            successes = dict(self._successes)

        def to_rules(cells: Dict[str, Dict[str, Any]],
                     promoted_only: bool) -> List[Dict[str, Any]]:
            out = []
            for key, cell in cells.items():
                if promoted_only and cell["count"] < self._threshold:
                    continue
                out.append({
                    "pattern": dict(cell["pattern"]),
                    "count": cell["count"],
                    "last_seen": cell["last_seen"],
                    "reason": (
                        f"模式出现 {cell['count']} 次"
                        + (" (达阈值, 已提升为规则)"
                           if cell["count"] >= self._threshold else "")
                    ),
                })
            out.sort(key=lambda r: -r["count"])
            return out

        return {
            "enabled": self._enabled,
            "threshold": self._threshold,
            "failure_rules": to_rules(failures, promoted_only=True),
            "success_rules": to_rules(successes, promoted_only=True),
            "failure_patterns": to_rules(failures, promoted_only=False),
            "success_patterns": to_rules(successes, promoted_only=False),
            "mode": "rule_based",
        }

    # ── 修正参考 ──────────────────────────────────────────────────
    def best_failure_rule(self, cause: str, action: str = "",
                          scene: str = "") -> Optional[Dict[str, Any]]:
        """查询最匹配失败规则 (供修正器参考)"""
        with self._lock:
            candidates = []
            for key, cell in self._failures.items():
                p = cell["pattern"]
                if p["cause"] == (cause or "unknown"):
                    score = 0
                    if p["action"] == (action or "any"):
                        score += 1
                    if p["scene"] == (scene or "*"):
                        score += 1
                    candidates.append((score, cell["count"], cell))
            if not candidates:
                return None
            candidates.sort(key=lambda c: (-c[0], -c[1]))
            best = candidates[0][2]
            return {
                "pattern": dict(best["pattern"]),
                "count": best["count"],
                "last_seen": best["last_seen"],
                "reason": "历史失败模式 (供修正参考)",
            }

    def clear(self) -> int:
        """清空学习 (测试隔离)"""
        with self._lock:
            n = len(self._failures) + len(self._successes)
            self._failures.clear()
            self._successes.clear()
            return n

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "threshold": self._threshold,
                "max_rules": self._max_rules,
            }


__all__ = [
    "CompanionLearning",
    "LearningError",
]
