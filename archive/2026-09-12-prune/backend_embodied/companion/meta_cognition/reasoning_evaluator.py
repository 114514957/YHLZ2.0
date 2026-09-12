"""
YHLZ Embodied AI V9.5 - 推理评价器 (Reasoning Evaluator)

职责:
    - 评价: 逻辑一致性 / 证据充分性 / 推理完整性 / 偏差风险

设计原则:
    - 四维度评分可解释 (每维 0~1 + reason)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class EvaluatorError(Exception):
    """推理评价操作异常"""


# 逻辑跳跃信号 (可解释)
LOGIC_JUMP_SIGNALS: list = [
    "必然", "一定如此", "毫无疑问", "绝对正确",
    "certainly", "definitely",
]

# 证据信号 (可解释)
EVIDENCE_SIGNALS: list = [
    "根据", "来源", "数据", "证据", "记录",
    "based on", "evidence", "data",
]

# 偏差信号 (可解释)
BIAS_SIGNALS: list = [
    "总是", "从不", "所有人都", "没人能",
    "always", "never", "everyone",
]


class ReasoningEvaluator:
    """推理评价器 (认知过程 → 四维评分)

    用法:
        evaluator = ReasoningEvaluator()
        r = evaluator.evaluate(monitor_entry)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._evaluations: list = []

    # ── 评价主入口 ───────────────────────────────────────────────
    def evaluate(
        self,
        monitor_entry: Dict[str, Any],
        output_text: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """推理评价

        Args:
            monitor_entry: 认知监控记录
            output_text: 输出文本 (补充信号检测)

        Returns:
            {
                'evaluation_id', 'score', 'dimensions',
                'reason', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "推理评价停用",
                }
            entry = monitor_entry or {}
            text = str(output_text or "")
            # 1. 逻辑一致性
            consistency, consistency_reason = \
                self._consistency(text, entry)
            # 2. 证据充分性
            evidence, evidence_reason = \
                self._evidence(text, entry)
            # 3. 推理完整性
            completeness, completeness_reason = \
                self._completeness(entry)
            # 4. 偏差风险 (反向评分: 偏差少 → 高分)
            bias, bias_reason = self._bias(text)
            score = round((
                consistency + evidence + completeness + bias
            ) / 4.0, 4)
            result = {
                "evaluation_id": "re_" +
                uuid.uuid4().hex[:8],
                "score": score,
                "dimensions": {
                    "consistency": {
                        "score": consistency,
                        "reason": consistency_reason,
                    },
                    "evidence": {
                        "score": evidence,
                        "reason": evidence_reason,
                    },
                    "completeness": {
                        "score": completeness,
                        "reason": completeness_reason,
                    },
                    "bias_risk": {
                        "score": bias,
                        "reason": bias_reason,
                    },
                },
                "reason": (
                    f"推理评价 {score}: "
                    f"一致性 {consistency}, 证据 {evidence}, "
                    f"完整 {completeness}, "
                    f"偏差风险 {1 - bias}"
                ),
                "mode": "rule_based",
                "evaluated_at": now,
            }
            self._evaluations.append(result)
            return dict(result)

    # ── 维度 (可解释) ───────────────────────────────────────────
    @staticmethod
    def _consistency(text: str,
                     entry: Dict[str, Any]) -> tuple:
        """逻辑一致性 (无跳跃信号 + 高置信度)"""
        jumps = [
            s for s in LOGIC_JUMP_SIGNALS if s in text
        ]
        if jumps:
            return 0.2, f"检测到逻辑跳跃信号: {jumps}"
        confidence = float(entry.get("confidence", 0.5))
        score = round(min(1.0, 0.5 + confidence * 0.5), 4)
        return score, f"置信度 {confidence}, 无逻辑跳跃"

    @staticmethod
    def _evidence(text: str,
                  entry: Dict[str, Any]) -> tuple:
        """证据充分性"""
        signals = [
            s for s in EVIDENCE_SIGNALS if s in text
        ]
        if signals:
            return 0.9, f"有证据信号: {signals}"
        if entry.get("resources"):
            return 0.7, "有资源引用但缺证据信号"
        return 0.3, "无证据信号 (证据不足)"

    @staticmethod
    def _completeness(entry: Dict[str, Any]) -> tuple:
        """推理完整性"""
        uncertainty = str(entry.get("uncertainty", ""))
        if uncertainty:
            return 0.9, "已声明不确定性 (推理完整)"
        return 0.6, "未声明不确定性"

    @staticmethod
    def _bias(text: str) -> tuple:
        """偏差风险 (反向评分)"""
        biases = [
            s for s in BIAS_SIGNALS if s in text
        ]
        if biases:
            return 0.2, f"检测到绝对化偏差: {biases}"
        return 0.8, "无明显偏差信号"

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """评价统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "evaluation_count": len(self._evaluations),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._evaluations)
            self._evaluations.clear()
            return n


__all__ = [
    "BIAS_SIGNALS",
    "EVIDENCE_SIGNALS",
    "EvaluatorError",
    "LOGIC_JUMP_SIGNALS",
    "ReasoningEvaluator",
]
