"""
YHLZ Embodied AI V10.1 - 交互延迟追踪 (Interaction Latency Tracker)

职责:
    - 对话链路延迟追踪 (借鉴 DEMO LatencyTracker):
      user_input / understand / context / tool / response / tts / play
    - 全链路阶段 mark + report (热机健康指标对话链路版)
    - 只存统计数字, 不存内容

设计原则:
    - 各阶段 mark(latency_ms) → 累计统计
    - 窗口统计 (平均值 / 最大 / 计数)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LatencyTrackerError(Exception):
    """延迟追踪异常"""


# 对话链路阶段 (可解释)
LATENCY_STAGES: List[str] = [
    "user_input",   # 用户输入
    "understand",   # 意图理解
    "context",      # 上下文检索
    "tool",         # 工具调用
    "response",     # 响应生成
    "tts",          # 语音合成
    "play",         # 播放
]


class InteractionLatencyTracker:
    """交互延迟追踪器 (V10.1)

    用法:
        t = InteractionLatencyTracker()
        t.mark("user_input", 12.5)
        t.mark("response", 300.2)
        report = t.report()
    """

    def __init__(self, max_samples: int = 1000,
                 enabled: bool = True):
        if max_samples <= 0:
            raise LatencyTrackerError(
                f"max_samples 必须 > 0, 当前: {max_samples}"
            )
        self._lock = threading.RLock()
        self._max_samples = int(max_samples)
        self._enabled = bool(enabled)
        self._samples: Dict[str, List[float]] = {
            s: [] for s in LATENCY_STAGES
        }

    def mark(self, stage: str, latency_ms: float) -> Dict[str, Any]:
        """记录某阶段延迟 (毫秒)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "延迟追踪停用"}
            if stage not in LATENCY_STAGES:
                raise LatencyTrackerError(
                    f"非法阶段: {stage} (可选: {LATENCY_STAGES})"
                )
            if latency_ms < 0:
                raise LatencyTrackerError(
                    f"延迟不能为负: {latency_ms}"
                )
            samples = self._samples[stage]
            samples.append(float(latency_ms))
            if len(samples) > self._max_samples:
                self._samples[stage] = samples[-self._max_samples:]
            return {
                "mode": "rule_based", "ok": True,
                "stage": stage, "latency_ms": latency_ms,
            }

    def report(self) -> Dict[str, Any]:
        """延迟报告 (按阶段统计)"""
        with self._lock:
            out: Dict[str, Any] = {}
            for stage in LATENCY_STAGES:
                samples = self._samples[stage]
                if samples:
                    out[stage] = {
                        "count": len(samples),
                        "avg_ms": round(
                            sum(samples) / len(samples), 2,
                        ),
                        "max_ms": round(max(samples), 2),
                        "min_ms": round(min(samples), 2),
                    }
                else:
                    out[stage] = {
                        "count": 0, "avg_ms": 0.0,
                        "max_ms": 0.0, "min_ms": 0.0,
                    }
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "stages": out,
                "total_samples": sum(
                    len(v) for v in self._samples.values()
                ),
            }

    def stats(self) -> Dict[str, Any]:
        """统计"""
        return self.report()

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = sum(len(v) for v in self._samples.values())
            for k in self._samples:
                self._samples[k] = []
            return n


__all__ = [
    "InteractionLatencyTracker",
    "LATENCY_STAGES",
    "LatencyTrackerError",
]
