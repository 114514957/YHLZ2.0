"""
YHLZ Embodied AI V10.1 - 工具交互流程 (Tool Interaction Flow)

职责:
    - 工具调用标准流程: Understand → Plan → Tool → Result →
      Reflection → Response
    - 全流程可记录 / 可审计 / 可回溯
    - 不执行工具本身, 只编排与记录 (执行经外部回调)

设计原则:
    - 工具调用全程审计 (可回溯)
    - 流程状态机: understand → plan → tool → result → reflect → response
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolFlowError(Exception):
    """工具交互流程异常"""


# 流程阶段 (可解释)
FLOW_STAGES: List[str] = [
    "understand",  # 理解
    "plan",        # 规划
    "tool",        # 工具调用
    "result",      # 结果
    "reflect",     # 反思
    "response",    # 响应
]


class ToolFlowRecorder:
    """工具交互流程记录器 (V10.1)

    用法:
        tfr = ToolFlowRecorder()
        flow_id = tfr.begin("查询天气")
        tfr.advance(flow_id, "plan", "选择天气工具")
        r = tfr.execute(flow_id, "weather_tool", fn, args)
        tfr.advance(flow_id, "response", "已回复")
        trace = tfr.trace(flow_id)
    """

    def __init__(self, max_flows: int = 500, enabled: bool = True):
        if max_flows <= 0:
            raise ToolFlowError(
                f"max_flows 必须 > 0, 当前: {max_flows}"
            )
        self._lock = threading.RLock()
        self._max_flows = int(max_flows)
        self._enabled = bool(enabled)
        self._flows: Dict[str, Dict[str, Any]] = {}

    def begin(self, intent: str) -> Dict[str, Any]:
        """开始一次工具交互 (Understand 阶段)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "工具交互流程停用"}
            flow_id = "tf_" + uuid.uuid4().hex[:10]
            self._flows[flow_id] = {
                "flow_id": flow_id,
                "intent": str(intent),
                "stage": "understand",
                "started_at": time.time(),
                "steps": [{
                    "stage": "understand",
                    "detail": str(intent),
                    "timestamp": time.time(),
                }],
                "tool": "",
                "result": None,
                "reflection": "",
            }
            if len(self._flows) > self._max_flows:
                # 淘汰最旧流程
                oldest = min(
                    self._flows,
                    key=lambda k: self._flows[k]["started_at"],
                )
                self._flows.pop(oldest, None)
            return {"mode": "rule_based", "ok": True,
                    "flow_id": flow_id}

    def advance(
        self,
        flow_id: str,
        stage: str,
        detail: str = "",
    ) -> Dict[str, Any]:
        """推进流程阶段"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "工具交互流程停用"}
            flow = self._flows.get(flow_id)
            if flow is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"流程不存在: {flow_id}"}
            if stage not in FLOW_STAGES:
                raise ToolFlowError(
                    f"非法流程阶段: {stage} (可选: {FLOW_STAGES})"
                )
            flow["stage"] = stage
            flow["steps"].append({
                "stage": stage,
                "detail": str(detail),
                "timestamp": time.time(),
            })
            return {"mode": "rule_based", "ok": True,
                    "flow_id": flow_id, "stage": stage}

    def execute(
        self,
        flow_id: str,
        tool_name: str,
        tool_fn: Callable,
        args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行工具调用 (Tool → Result)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "工具交互流程停用"}
            flow = self._flows.get(flow_id)
            if flow is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"流程不存在: {flow_id}"}
        start = time.time()
        try:
            result = tool_fn(**(args or {}))
            ok = True
            error = ""
        except Exception as e:  # noqa: BLE001 工具回调异常捕获
            result = None
            ok = False
            error = str(e)
            logger.error(f"[Interaction] 工具 {tool_name} 执行失败: {e}")
        latency_ms = round((time.time() - start) * 1000.0, 2)
        with self._lock:
            flow["tool"] = tool_name
            flow["result"] = {
                "ok": ok,
                "result": result,
                "error": error,
                "latency_ms": latency_ms,
            }
            flow["stage"] = "result"
            flow["steps"].append({
                "stage": "tool",
                "detail": f"调用 {tool_name}",
                "timestamp": time.time(),
            })
            flow["steps"].append({
                "stage": "result",
                "detail": f"ok={ok} latency={latency_ms}ms",
                "timestamp": time.time(),
            })
            return {
                "mode": "rule_based", "ok": ok,
                "flow_id": flow_id, "tool": tool_name,
                "latency_ms": latency_ms, "error": error,
            }

    def reflect(
        self,
        flow_id: str,
        reflection: str,
    ) -> Dict[str, Any]:
        """记录反思 (Reflection 阶段)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "工具交互流程停用"}
            flow = self._flows.get(flow_id)
            if flow is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"流程不存在: {flow_id}"}
            flow["reflection"] = str(reflection)
            flow["stage"] = "reflect"
            flow["steps"].append({
                "stage": "reflect",
                "detail": str(reflection),
                "timestamp": time.time(),
            })
            return {"mode": "rule_based", "ok": True,
                    "flow_id": flow_id}

    def finish(
        self,
        flow_id: str,
        response: str = "",
    ) -> Dict[str, Any]:
        """完成流程 (Response 阶段, 记录响应摘要)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "工具交互流程停用"}
            flow = self._flows.get(flow_id)
            if flow is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"流程不存在: {flow_id}"}
            flow["stage"] = "response"
            flow["response"] = str(response)[:200]
            flow["steps"].append({
                "stage": "response",
                "detail": str(response)[:200],
                "timestamp": time.time(),
            })
            return {"mode": "rule_based", "ok": True,
                    "flow_id": flow_id,
                    "elapsed_ms": round(
                        (time.time() - flow["started_at"]) * 1000.0, 2,
                    )}

    def trace(self, flow_id: str) -> Dict[str, Any]:
        """回溯完整流程 (可审计)"""
        with self._lock:
            flow = self._flows.get(flow_id)
            if flow is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"流程不存在: {flow_id}"}
            return {"mode": "rule_based", "ok": True,
                    "flow": dict(flow)}

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            total = len(self._flows)
            done = sum(1 for f in self._flows.values()
                       if f["stage"] == "response")
            tool_calls = sum(
                1 for f in self._flows.values() if f["tool"]
            )
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "max_flows": self._max_flows,
                "total_flows": total,
                "completed_flows": done,
                "tool_call_flows": tool_calls,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._flows)
            self._flows.clear()
            return n


__all__ = [
    "FLOW_STAGES",
    "ToolFlowError",
    "ToolFlowRecorder",
]
