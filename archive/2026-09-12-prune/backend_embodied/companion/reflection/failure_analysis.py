"""
YHLZ Embodied AI V5.8 - 失败分析 (Failure Analysis)

职责:
    - 从失败中学习: Failure Event → Possible Cause → Evidence →
      Correction Proposal
    - 失败原因分类 (可解释): 执行/策略/权限/环境/未知

数据结构:
    {
        failure, possible_reason, evidence[], confidence,
    }

设计原则:
    - 纯规则分析 (禁止黑盒)
    - 每分析含证据与置信度
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FailureError(Exception):
    """失败分析操作异常"""


# 失败原因分类 (可解释)
FAILURE_REASONS: List[str] = [
    "execution",    # 执行失败 (动作执行错误)
    "strategy",     # 策略失败 (策略选择不当)
    "permission",   # 权限失败 (未授权)
    "environment",  # 环境失败 (状态/对象不满足)
    "unknown",      # 未知
]

# 失败信号 → 原因 (规则匹配)
FAILURE_SIGNALS: Dict[str, str] = {
    "权限": "permission",
    "denied": "permission",
    "embodied_enabled": "permission",
    "位置": "execution",
    "对象": "environment",
    "missing": "environment",
    "boundary": "execution",
    "策略": "strategy",
    "policy": "strategy",
}


class FailureAnalysisEngine:
    """失败分析器

    用法:
        engine = FailureAnalysisEngine()
        result = engine.analyze(failure="拾取失败", error="位置不匹配")
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._analyses: List[Dict[str, Any]] = []

    # ── 原因推断 (规则) ───────────────────────────────────────────
    @staticmethod
    def infer_reason(error: str, action: str = "") -> str:
        """从错误/动作推断原因 (可解释)"""
        text = (str(error or "") + " " + str(action or "")).lower()
        for signal, reason in FAILURE_SIGNALS.items():
            if signal in text:
                return reason
        return "unknown"

    # ── 分析 ──────────────────────────────────────────────────────
    def analyze(
        self,
        failure: str,
        error: str = "",
        action: str = "",
        evidence: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """失败分析: 原因 + 证据 + 置信度 + 修正建议

        Returns:
            {
                'analysis_id', 'failure', 'possible_reason',
                'evidence': [...], 'confidence', 'correction_proposal',
                'timestamp', 'mode': 'rule_based',
            }
        """
        with self._lock:
            reason = self.infer_reason(error, action)
            ev = list(evidence or [])
            if error and not ev:
                ev.append(f"错误信息: {error[:80]}")
            if action:
                ev.append(f"动作: {action}")
            # 置信度: 有错误信息+动作 → 0.8; 只有其一 → 0.6; 无 → 0.4
            confidence = 0.4
            if error and action:
                confidence = 0.8
            elif error or action:
                confidence = 0.6
            proposal = self._correction_proposal(reason)
            result = {
                "analysis_id": "fa_" + uuid.uuid4().hex[:8],
                "failure": failure,
                "possible_reason": reason,
                "evidence": ev,
                "confidence": confidence,
                "correction_proposal": proposal,
                "timestamp": time.time(),
                "mode": "rule_based",
            }
            self._analyses.append(result)
            return result

    @staticmethod
    def _correction_proposal(reason: str) -> str:
        """修正建议 (按原因, 可解释)"""
        proposals = {
            "execution": "检查执行参数与状态后重试",
            "strategy": "更换策略 (参考经验库) 后重试",
            "permission": "检查权限配置 (embodied_enabled) 后重试",
            "environment": "先观察环境补充信息后重试",
            "unknown": "记录更多证据后重试",
        }
        return proposals.get(reason, "记录更多证据后重试")

    # ── 统计 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """分析统计 (原因分布)"""
        with self._lock:
            analyses = list(self._analyses)
        by_reason: Dict[str, int] = {}
        for a in analyses:
            by_reason[a["possible_reason"]] = \
                by_reason.get(a["possible_reason"], 0) + 1
        return {
            "mode": "rule_based",
            "total": len(analyses),
            "by_reason": by_reason,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._analyses)
            self._analyses.clear()
            return n


__all__ = [
    "FAILURE_REASONS",
    "FAILURE_SIGNALS",
    "FailureAnalysisEngine",
    "FailureError",
]
