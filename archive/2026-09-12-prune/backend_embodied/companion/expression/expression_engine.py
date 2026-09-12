"""
YHLZ Embodied AI V6.2 - 表达引擎 (Expression Engine)

职责:
    - 根据 Emotion / Relationship / Task / Conversation 生成表达建议
    - 输出: {style, tone, reason, confidence, timestamp}

安全协议 (表达 ≠ 人格修改):
    - 只能影响: 回复风格 / 互动方式 / 表达策略
    - 不能修改: Personality / Core Value / Mission / Identity

设计原则:
    - 规则驱动 (禁止黑盒情绪生成)
    - 表达建议 = 建议, 不强制输出 (由上层决定)
    - 每次生成审计 (可回溯)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

from backend.embodied.companion.expression.expression_audit import (
    ExpressionAudit,
)
from backend.embodied.companion.expression.expression_context import (
    ExpressionContext,
)
from backend.embodied.companion.expression.expression_rules import (
    EXPRESSION_STYLES,
    EXPRESSION_TONES,
    ExpressionRules,
)

logger = logging.getLogger(__name__)


class ExpressionEngineError(Exception):
    """表达引擎操作异常"""


class ExpressionEngine:
    """表达引擎 (状态 → 表达建议)

    用法:
        engine = ExpressionEngine()
        suggestion = engine.generate(emotion=..., relationship=...)
    """

    def __init__(
        self,
        enabled: bool = True,
        threshold: float = 0.7,
        rules: Optional[ExpressionRules] = None,
        context: Optional[ExpressionContext] = None,
        audit: Optional[ExpressionAudit] = None,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._rules = rules or ExpressionRules(threshold=threshold)
        self._context = context or ExpressionContext()
        self._audit = audit or ExpressionAudit()
        self._generate_count = 0
        self._style_distribution: Dict[str, int] = {}
        self._rule_hits: Dict[str, int] = {}

    # ── 生成表达建议 ─────────────────────────────────────────────
    def generate(
        self,
        emotion: Optional[Dict[str, Any]] = None,
        relationship: Optional[Dict[str, Any]] = None,
        task: Optional[Dict[str, Any]] = None,
        conversation: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """生成表达建议 (规则驱动, 可解释)

        Args:
            emotion: 情绪状态 (positivity/energy/warmth)
            relationship: 关系状态 (trust)
            task: 任务上下文 (result)
            conversation: 对话上下文

        Returns:
            {
                'suggestion_id', 'style', 'tone', 'reason',
                'confidence', 'rules': [...], 'mode', 'timestamp',
            }
        """
        with self._lock:
            if not self._enabled:
                raise ExpressionEngineError("表达引擎已停用")
            now = now if now is not None else time.time()
            context = self._context.build(
                emotion=emotion, relationship=relationship,
                task=task, conversation=conversation,
            )
            hits = self._rules.match(context)
            style, tone, reason = self._compose(hits)
            confidence = self._confidence(hits, context)
            suggestion = {
                "suggestion_id": "expr_" + uuid.uuid4().hex[:8],
                "style": style,
                "tone": tone,
                "reason": reason,
                "confidence": round(confidence, 4),
                "rules": [h["rule"] for h in hits],
                "mode": "rule_based",
                "timestamp": now,
            }
            # 审计 + 统计
            self._audit.record(
                action="generate", detail=style,
                ref_id=suggestion["suggestion_id"],
            )
            self._generate_count += 1
            self._style_distribution[style] = \
                self._style_distribution.get(style, 0) + 1
            for h in hits:
                self._rule_hits[h["rule"]] = \
                    self._rule_hits.get(h["rule"], 0) + 1
            return suggestion

    # ── 组合 (可解释) ────────────────────────────────────────────
    @staticmethod
    def _compose(hits: List[Dict[str, Any]]) -> tuple:
        """组合命中规则 → (style, tone, reason)"""
        if not hits:
            return ("neutral", "neutral",
                    "无规则命中, 使用中性表达")
        # 优先级: 第一条为主风格, 语气取温暖度最高
        primary = hits[0]
        style = primary["style"]
        tones = [h["tone"] for h in hits]
        tone = "warm" if "warm" in tones else tones[0]
        reasons = "; ".join(h["reason"] for h in hits[:3])
        return (style, tone, reasons)

    @staticmethod
    def _confidence(hits: List[Dict[str, Any]],
                    context: Dict[str, Any]) -> float:
        """置信度: 命中数 + 输入完整度"""
        if not hits:
            return 0.3
        base = 0.5 + 0.1 * (len(hits) - 1)
        emotion = context.get("emotion", {})
        complete = sum(
            1 for k in ("positivity", "energy", "warmth")
            if k in emotion
        )
        base += 0.05 * complete
        return min(0.95, base)

    # ── 查询 ─────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        """表达引擎状态"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "threshold": self._rules.threshold(),
                "generate_count": self._generate_count,
                "style_distribution": dict(self._style_distribution),
                "rule_hits": dict(self._rule_hits),
                "styles": list(EXPRESSION_STYLES),
                "tones": list(EXPRESSION_TONES),
            }

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """表达审计"""
        return self._audit.report(limit=limit)

    def clear(self) -> Dict[str, Any]:
        """清空 (测试隔离)"""
        with self._lock:
            n_audit = self._audit.clear()
            n_ctx = self._context.clear()
            self._generate_count = 0
            self._style_distribution = {}
            self._rule_hits = {}
            return {"audit": n_audit, "context": n_ctx}


__all__ = [
    "ExpressionEngine",
    "ExpressionEngineError",
]
