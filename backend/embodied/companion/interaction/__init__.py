"""
YHLZ Embodied AI V10.1 - 交互协议引擎 (Interaction Protocol Engine)

职责:
    - YHLZ Interaction Protocol (伙伴交互协议): DEMO 吸收改造产物
    - 保留模块:
        1. Conversation State Manager (会话状态: 目标/阶段/未完成/上下文)
        2. Context Filter (上下文筛选: 不等同长期记忆)
        3. Tool Interaction Flow (工具流程: 可记录/审计/回溯)
        4. Partner Interaction State (伙伴状态: 协作目标/模式/关系)
    - 附加: Interaction Latency Tracker (对话链路延迟, 借鉴 DEMO)
    - 审计: 全流程可追踪

核心原则:
    - DEMO 定位 Interaction Layer, 不得进入 Identity / Constitution /
      Core Cognition Layer
    - 交互状态 ≠ 人格 (人格属于 Identity Layer)
    - 上下文必须筛选, 不能直接等同长期记忆
    - 不污染 Memory Layer / 不修改 Identity / 不绕过 Constitution

用法:
    protocol = InteractionProtocol(config=...)
    state = protocol.begin_session(goal="...")
    ctx = protocol.filter_context(text)
    trace = protocol.trace_flow(flow_id)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from backend.embodied.companion.interaction.context_filter import (
    InteractionContextFilter,
)
from backend.embodied.companion.interaction.conversation_state import (
    ConversationStateManager,
)
from backend.embodied.companion.interaction.interaction_audit import (
    INTERACTION_ACTIONS,
    InteractionAudit,
    InteractionAuditError,
)
from backend.embodied.companion.interaction.latency_tracker import (
    InteractionLatencyTracker,
)
from backend.embodied.companion.interaction.partner_state import (
    PartnerInteractionState,
)
from backend.embodied.companion.interaction.tool_flow import (
    ToolFlowRecorder,
)

logger = logging.getLogger(__name__)


class InteractionProtocolError(Exception):
    """交互协议引擎异常"""


class InteractionProtocol:
    """交互协议引擎 (V10.1, 统一入口)

    用法:
        protocol = InteractionProtocol(config=...)
        protocol.begin_session(goal="共同完成项目")
        protocol.set_context("当前处理任务A")
        flow = protocol.begin_tool_flow("查询状态")
        protocol.execute_tool(flow, "get_state", fn, {})
    """

    def __init__(
        self,
        conversation_state: Optional[ConversationStateManager] = None,
        context_filter: Optional[InteractionContextFilter] = None,
        tool_flow: Optional[ToolFlowRecorder] = None,
        partner_state: Optional[PartnerInteractionState] = None,
        latency_tracker: Optional[InteractionLatencyTracker] = None,
        audit: Optional[InteractionAudit] = None,
        config: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        cfg = dict(config or {})
        self._enabled = bool(enabled)
        self._config = cfg
        self._conversation = conversation_state or \
            ConversationStateManager(
                max_context_len=int(cfg.get(
                    "companion_interaction_max_context_len", 200,
                )),
                max_pending=int(cfg.get(
                    "companion_interaction_max_pending", 20,
                )),
                enabled=self._enabled,
            )
        self._context = context_filter or InteractionContextFilter(
            max_len=int(cfg.get(
                "companion_interaction_context_max_len", 200,
            )),
            enabled=self._enabled,
        )
        self._tool_flow = tool_flow or ToolFlowRecorder(
            max_flows=int(cfg.get(
                "companion_interaction_max_flows", 500,
            )),
            enabled=self._enabled,
        )
        self._partner = partner_state or PartnerInteractionState(
            enabled=self._enabled,
        )
        self._latency = latency_tracker or InteractionLatencyTracker(
            max_samples=int(cfg.get(
                "companion_interaction_latency_max_samples", 1000,
            )),
            enabled=self._enabled,
        )
        self._audit = audit or InteractionAudit(
            max_records=int(cfg.get(
                "companion_interaction_audit_max", 2000,
            )),
        )

    # ── 会话状态 (Conversation State Manager) ───────────────────
    def begin_session(
        self, goal: str = "", mode: str = "casual",
    ) -> Dict[str, Any]:
        """开始会话"""
        with self._lock:
            r = self._conversation.begin(goal, mode)
            if r.get("ok"):
                self._audit.record(
                    action="state_change", ref_id="session",
                    detail=f"begin goal={goal[:50]} mode={mode}",
                    result={"goal": goal, "mode": mode},
                )
            return r

    def update_stage(self, stage: str) -> Dict[str, Any]:
        """更新任务阶段"""
        with self._lock:
            r = self._conversation.update_stage(stage)
            if r.get("ok"):
                self._audit.record(
                    action="state_change", ref_id="session",
                    detail=f"stage {r['from']} → {r['to']}",
                )
            return r

    def set_context(self, context: str) -> Dict[str, Any]:
        """设置当前上下文 (经筛选)"""
        with self._lock:
            filtered = self._context.filter(context)
            r = self._conversation.set_context(
                filtered.get("summary", context),
            )
            if r.get("ok"):
                self._audit.record(
                    action="context_update", ref_id="session",
                    detail="上下文已筛选更新",
                    result={
                        "topic": filtered.get("topic"),
                        "clipped": filtered.get("clipped"),
                    },
                )
            return r

    def add_pending(self, item: str) -> Dict[str, Any]:
        """添加未完成事项"""
        with self._lock:
            return self._conversation.add_pending(item)

    def resolve_pending(self, item: str) -> bool:
        """移除已完成事项"""
        with self._lock:
            return self._conversation.resolve_pending(item)

    def conversation_snapshot(self) -> Dict[str, Any]:
        """会话状态快照"""
        with self._lock:
            return self._conversation.snapshot()

    # ── 上下文筛选 (Context Filter) ─────────────────────────────
    def filter_context(self, text: str) -> Dict[str, Any]:
        """上下文筛选 (不等同长期记忆)"""
        with self._lock:
            return self._context.filter(text)

    # ── 工具交互流程 (Tool Interaction Flow) ────────────────────
    def begin_tool_flow(self, intent: str) -> Dict[str, Any]:
        """开始工具交互流程"""
        with self._lock:
            r = self._tool_flow.begin(intent)
            if r.get("ok"):
                self._audit.record(
                    action="tool_call", ref_id=r["flow_id"],
                    detail=f"begin intent={intent[:50]}",
                )
            return r

    def advance_tool_flow(
        self, flow_id: str, stage: str, detail: str = "",
    ) -> Dict[str, Any]:
        """推进工具流程"""
        with self._lock:
            return self._tool_flow.advance(flow_id, stage, detail)

    def execute_tool(
        self,
        flow_id: str,
        tool_name: str,
        tool_fn: Callable,
        args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行工具调用 (记录延迟)"""
        with self._lock:
            if not callable(tool_fn):
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "工具回调不可用 (交互协议不执行工具)",
                }
            r = self._tool_flow.execute(
                flow_id, tool_name, tool_fn, args,
            )
            self._latency.mark("tool", r.get("latency_ms", 0.0))
            self._audit.record(
                action="tool_call", ref_id=flow_id,
                detail=f"execute {tool_name} ok={r.get('ok')}",
                result={
                    "tool": tool_name,
                    "latency_ms": r.get("latency_ms"),
                    "error": r.get("error"),
                },
            )
            return r

    def reflect_tool_flow(
        self, flow_id: str, reflection: str,
    ) -> Dict[str, Any]:
        """工具流程反思"""
        with self._lock:
            return self._tool_flow.reflect(flow_id, reflection)

    def finish_tool_flow(
        self, flow_id: str, response: str = "",
    ) -> Dict[str, Any]:
        """完成工具流程"""
        with self._lock:
            r = self._tool_flow.finish(flow_id, response)
            if r.get("ok"):
                self._latency.mark(
                    "response", r.get("elapsed_ms", 0.0),
                )
                self._audit.record(
                    action="tool_call", ref_id=flow_id,
                    detail="finish",
                    result={"elapsed_ms": r.get("elapsed_ms")},
                )
            return r

    def trace_tool_flow(self, flow_id: str) -> Dict[str, Any]:
        """回溯工具流程 (可审计)"""
        with self._lock:
            return self._tool_flow.trace(flow_id)

    # ── 伙伴交互状态 (Partner Interaction State) ───────────────
    def set_partner_goal(self, goal: str) -> Dict[str, Any]:
        """设置伙伴协作目标"""
        with self._lock:
            r = self._partner.set_goal(goal)
            if r.get("ok"):
                self._audit.record(
                    action="partner_state", ref_id="partner",
                    detail=f"goal={goal[:50]}",
                )
            return r

    def set_partner_relation(self, relation: str) -> Dict[str, Any]:
        """设置伙伴任务关系"""
        with self._lock:
            return self._partner.set_relation(relation)

    def set_partner_mode(self, mode: str) -> Dict[str, Any]:
        """设置伙伴交流模式"""
        with self._lock:
            return self._partner.set_mode(mode)

    def mark_partner_session(self) -> Dict[str, Any]:
        """标记一次伙伴交互"""
        with self._lock:
            return self._partner.mark_session()

    def partner_snapshot(self) -> Dict[str, Any]:
        """伙伴交互状态快照"""
        with self._lock:
            return self._partner.snapshot()

    # ── 延迟追踪 (Latency Tracker) ──────────────────────────────
    def mark_latency(
        self, stage: str, latency_ms: float,
    ) -> Dict[str, Any]:
        """记录链路延迟 (含审计)"""
        with self._lock:
            r = self._latency.mark(stage, latency_ms)
            if r.get("ok"):
                self._audit.record(
                    action="latency", ref_id=stage,
                    detail=f"latency={latency_ms}ms",
                    result={"latency_ms": latency_ms},
                )
            return r

    def latency_report(self) -> Dict[str, Any]:
        """延迟报告"""
        with self._lock:
            return self._latency.report()

    # ── 审计 / 统计 ─────────────────────────────────────────────
    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """交互审计报告"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "stats": self._audit.stats(),
                "recent": self._audit.query(limit=limit),
            }

    def stats(self) -> Dict[str, Any]:
        """交互协议统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "conversation": self._conversation.stats(),
                "context_filter": self._context.stats(),
                "tool_flow": self._tool_flow.stats(),
                "partner": self._partner.stats(),
                "latency": self._latency.stats(),
                "audit": self._audit.stats(),
            }

    def clear(self) -> int:
        """清空全部 (测试隔离)"""
        with self._lock:
            n = 0
            n += self._conversation.clear()
            n += self._context.clear()
            n += self._tool_flow.clear()
            n += self._partner.clear()
            n += self._latency.clear()
            n += self._audit.clear()
            return n


__all__ = [
    "INTERACTION_ACTIONS",
    "InteractionAudit",
    "InteractionAuditError",
    "InteractionProtocol",
    "InteractionProtocolError",
]
