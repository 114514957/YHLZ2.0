"""
YHLZ Embodied AI V4.2 - 语义环境分析器 (Semantic Environment Analyzer)

职责:
    - 将环境事件时间线 → 事件理解 → 语义摘要 (一句话/多句话, 供 LLM 上下文)
    - 结合因果分析输出"发生了什么 → 为什么 → 结果如何"的语义描述
    - 生成环境事件解释 (explain) 与语义上下文 (semantic_context)

设计原则:
    - 规则驱动文本生成 (确定性, 禁止 AI 幻觉)
    - 只理解不执行: 分析结果仅进入 Agent 推理上下文
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.schema import (
    CausalAnalysis,
    EnvironmentEvent,
    EnvironmentState,
    EventType,
)

logger = logging.getLogger(__name__)


class SemanticError(Exception):
    """语义分析异常"""


class SemanticAnalyzer:
    """语义环境分析器 (规则驱动)

    用法:
        sem = SemanticAnalyzer()
        ctx = sem.semantic_context(state, events, causal_list)
        text = sem.explain(events)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._summarized_count = 0

    # ── 事件理解 ──────────────────────────────────────────────────
    def understand(self, event: EnvironmentEvent) -> str:
        """单事件理解: 事件 → 一句话语义"""
        if event is None:
            return ""
        if event.summary:
            base = event.summary
        else:
            base = f"{event.event_type} 事件 (action={event.action_type} result={event.result or '无'})"
        if event.cause:
            base += f", 原因: {event.cause}"
        return base

    def explain(
        self,
        events: List[EnvironmentEvent],
        limit: int = 10,
    ) -> str:
        """事件时间线解释: 过去发生了什么 → 为什么 → 结果

        输出为按时间顺序 (旧 → 新) 的文本列表。
        """
        if not events:
            return "环境事件: 暂无记录"
        lines = [self.understand(e) for e in events[-limit:]]
        return "环境事件: " + "; ".join(lines)

    # ── 语义上下文 ────────────────────────────────────────────────
    def semantic_context(
        self,
        state: Optional[EnvironmentState],
        events: Optional[List[EnvironmentEvent]] = None,
        causal: Optional[List[CausalAnalysis]] = None,
        event_limit: int = 10,
    ) -> Dict[str, Any]:
        """构建语义环境上下文 (供 Agent 推理)

        内容:
            - understanding: 环境理解摘要 (当前状态一句话)
            - event_summary: 事件摘要 (发生了什么)
            - causal_summary: 因果摘要 (为什么失败 / 补救)
            - context:       组合语义描述
        """
        with self._lock:
            self._summarized_count += 1

        understanding = self._describe_state(state)
        event_summary = self.explain(events or [], limit=event_limit)
        causal_summary = self._describe_causal(causal or [])
        context = f"{understanding} | {event_summary}"
        if causal_summary:
            context += f" | {causal_summary}"
        return {
            "understanding": understanding,
            "event_summary": event_summary,
            "causal_summary": causal_summary,
            "context": context,
        }

    @staticmethod
    def _describe_state(state: Optional[EnvironmentState]) -> str:
        """当前状态 → 一句话理解"""
        if state is None:
            return "环境理解: 当前无状态快照"
        objects = [
            f"{o.name}={o.state or 'unknown'}" for o in state.objects
        ]
        obj_text = ", ".join(objects) if objects else "无对象"
        loc = state.location or {}

        def fmt(v: Any) -> Any:
            if isinstance(v, float) and v.is_integer():
                return int(v)
            return v

        return (
            f"环境理解: {len(state.objects)} 个对象 ({obj_text}), "
            f"主体位置 ({fmt(loc.get('x', 0))}, {fmt(loc.get('y', 0))})"
        )

    @staticmethod
    def _describe_causal(causal: List[CausalAnalysis]) -> str:
        """因果列表 → 一句话摘要"""
        if not causal:
            return ""
        parts = []
        for c in causal[-5:]:
            if not c.cause:
                continue
            parts.append(f"{c.action_id[:8]}: {c.cause} (补救: {c.remedy or '无'})")
        if not parts:
            return ""
        return "因果分析: " + "; ".join(parts)

    # ── 状态 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "summarized_count": self._summarized_count,
                "mode": "rule_based",
            }

    def reset(self) -> None:
        with self._lock:
            self._summarized_count = 0


__all__ = ["SemanticAnalyzer", "SemanticError"]
