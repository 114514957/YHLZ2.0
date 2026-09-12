"""
YHLZ Embodied AI V6.4 - 反事实验证 (Counterfactual Check)

职责:
    - 降低幻觉进入 Memory
    - 接口: counterfactual_check()
    - 检查: 如果该感知不存在, 结论是否仍成立?
    - 示例: OCR "支付成功" 验证失败 → 不得形成经验

规则 (可解释):
    - 高风险结论 (支付/授权/删除等) + 单一来源 → 不成立 (拒绝)
    - 低置信度 + 无重复证据 → 不成立
    - 有重复证据/高置信度 → 成立

设计原则:
    - 纯规则 (无黑盒)
    - 检查结果可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CounterfactualError(Exception):
    """反事实验证操作异常"""


# 高风险结论关键词 (可解释)
HIGH_STAKE_KEYWORDS: List[str] = [
    "支付", "授权", "删除", "转账", "提交", "确认",
    "成功", "完成",
]


class CounterfactualCheck:
    """反事实验证器

    用法:
        checker = CounterfactualCheck()
        result = checker.check(candidate)
    """

    def __init__(self, min_confidence: float = 0.7,
                 min_occurrences: int = 2,
                 enabled: bool = True):
        if not (0.0 <= min_confidence <= 1.0):
            raise CounterfactualError(
                f"min_confidence 必须在 [0,1], 当前: "
                f"{min_confidence}"
            )
        if min_occurrences <= 1:
            raise CounterfactualError(
                f"min_occurrences 必须 > 1, 当前: "
                f"{min_occurrences}"
            )
        self._lock = threading.RLock()
        self._min_conf = float(min_confidence)
        self._min_occ = int(min_occurrences)
        self._enabled = bool(enabled)
        self._history: List[Dict[str, Any]] = []

    # ── 检查主入口 ───────────────────────────────────────────────
    def check(
        self,
        candidate: Dict[str, Any],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """反事实验证

        Args:
            candidate: 感知候选

        Returns:
            {
                'check_id', 'status': holds/fails/neutral,
                'reason', 'score', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                result = {
                    "check_id": "cc_" + uuid.uuid4().hex[:8],
                    "status": "neutral",
                    "reason": "反事实验证停用",
                    "score": 0.5,
                    "mode": "rule_based",
                }
                self._history.append(result)
                return dict(result)
            summary = str(candidate.get("summary", ""))
            confidence = float(candidate.get("confidence", 0.0))
            raw_occ = candidate.get("occurrence_count")
            occurrence = int(raw_occ) if raw_occ is not None else 1
            high_stake = any(
                k in summary for k in HIGH_STAKE_KEYWORDS
            )
            # 规则1: 高风险结论 + 单一来源 → 不成立
            if high_stake and occurrence < self._min_occ:
                status, reason, score = "fails", (
                    f"高风险结论 '{summary[:20]}' 仅出现 "
                    f"{occurrence} 次, 单一来源不足以确认"
                ), 0.2
            # 规则2: 低置信度 + 无重复 → 不成立
            elif confidence < self._min_conf and \
                    occurrence < self._min_occ:
                status, reason, score = "fails", (
                    f"置信度 {confidence} 低于 "
                    f"{self._min_conf} 且无重复证据"
                ), 0.3
            # 规则3: 重复证据 → 成立
            elif occurrence >= self._min_occ:
                status, reason, score = "holds", (
                    f"重复出现 {occurrence} 次, 反事实结论仍成立"
                ), 0.9
            else:
                status, reason, score = "holds", (
                    f"置信度 {confidence} 充足, 结论成立"
                ), 0.8
            result = {
                "check_id": "cc_" + uuid.uuid4().hex[:8],
                "status": status,
                "reason": reason,
                "score": score,
                "mode": "rule_based",
                "checked_at": now,
            }
            self._history.append(result)
            return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """检查统计"""
        with self._lock:
            history = list(self._history)
        by_status: Dict[str, int] = {}
        for h in history:
            by_status[h["status"]] = by_status.get(h["status"], 0) + 1
        return {
            "mode": "rule_based",
            "check_count": len(history),
            "by_status": by_status,
            "holds_count": by_status.get("holds", 0),
            "fails_count": by_status.get("fails", 0),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
            return n


__all__ = [
    "HIGH_STAKE_KEYWORDS",
    "CounterfactualCheck",
    "CounterfactualError",
]
