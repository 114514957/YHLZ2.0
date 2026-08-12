"""
YHLZ Embodied AI V8.5 - 假设引擎 (Hypothesis Engine)

职责:
    - 从火花/重组 → 可验证假设
    - 每个假设必须包含:
      {hypothesis, foundation, reasoning, confidence, verification}

原则 (Falsifiability):
    - 所有重要创造必须允许被证伪
    - 假设必须区分: 事实/推论/假设/未知

设计原则:
    - 纯规则 (可解释)
    - 无依据不生成假设 (Evidence Based)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HypothesisError(Exception):
    """假设引擎操作异常"""


class HypothesisEngine:
    """假设引擎 (火花/重组 → 可验证假设)

    用法:
        engine = HypothesisEngine()
        h = engine.build(spark, fusion)
    """

    def __init__(self, enabled: bool = True,
                 max_records: int = 500):
        if max_records <= 0:
            raise HypothesisError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._hypotheses: list = []

    # ── 构建主入口 ───────────────────────────────────────────────
    def build(
        self,
        spark: Optional[Dict[str, Any]] = None,
        fusion: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """构建假设 (火花或重组为基础)

        Args:
            spark: 思维火花 (可空)
            fusion: 概念重组结果 (可空)

        Returns:
            {
                'hypothesis_id', 'hypothesis', 'foundation',
                'reasoning', 'confidence', 'verification',
                'falsifiable', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "假设引擎停用",
                }
            # 基础 (foundation)
            foundation_parts = []
            if spark is not None:
                foundation_parts.append(
                    f"火花: {spark.get('idea', '')[:30]}"
                )
            if fusion is not None:
                foundation_parts.append(
                    f"重组: {fusion.get('new_concept', '')}"
                )
            if not foundation_parts:
                raise HypothesisError(
                    "无基础 (火花/重组至少一项)"
                )
            foundation = "; ".join(foundation_parts)
            # 假设文本
            if fusion is not None:
                hypothesis = (
                    f"{fusion.get('new_concept', '')} "
                    f"在 {fusion.get('new_context', '新情境')}"
                    f"中可能产生新的可验证效果"
                )
            else:
                hypothesis = (
                    f"{spark.get('idea', '')} 可验证为"
                    f"有效的创造性方向"
                )
            # 推理 (reasoning)
            reasoning = self._reasoning(spark, fusion)
            # 置信度 (基于基础)
            confidence = round(min(
                1.0, max(0.1, 0.5 + 0.1 * len(
                    foundation_parts,
                ))), 4)
            # 验证方案 (verification)
            verification = (
                f"通过模拟/实验验证: {hypothesis[:25]}"
            )
            result = {
                "hypothesis_id": "hy_" + uuid.uuid4().hex[:8],
                "hypothesis": hypothesis,
                "foundation": foundation,
                "reasoning": reasoning,
                "confidence": confidence,
                "verification": verification,
                "falsifiable": True,
                "mode": "rule_based",
                "created_at": now,
            }
            self._hypotheses.append(result)
            if len(self._hypotheses) > self._max_records:
                self._hypotheses = \
                    self._hypotheses[-self._max_records:]
            return dict(result)

    # ── 推理 (可解释) ───────────────────────────────────────────
    @staticmethod
    def _reasoning(spark, fusion) -> str:
        """推理链"""
        steps = []
        if spark is not None:
            steps.append(
                f"火花 '{spark.get('idea', '')[:20]}' "
                f"基于 {spark.get('basis', '观察')}"
            )
        if fusion is not None:
            steps.append(
                f"重组 '{fusion.get('derivation', '')[:30]}'"
            )
        steps.append("结论为可证伪假设, 需验证后采纳")
        return " → ".join(steps)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """假设统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "hypothesis_count": len(self._hypotheses),
            }

    def history(self, limit: int = 50) -> list:
        """假设历史"""
        with self._lock:
            recent = list(reversed(self._hypotheses))
            if limit > 0:
                recent = recent[:limit]
            return [dict(h) for h in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._hypotheses)
            self._hypotheses.clear()
            return n


__all__ = [
    "HypothesisEngine",
    "HypothesisError",
]
