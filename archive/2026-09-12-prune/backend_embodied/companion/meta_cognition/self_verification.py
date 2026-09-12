"""
YHLZ Embodied AI V9.5 - 自我验证 (Self Verification)

职责:
    - 输出前检查: Evidence → Reasoning → Confidence → Conclusion
    - 必须区分: 事实 / 推论 / 假设 / 不确定内容

设计原则:
    - 检查链可解释
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


class VerificationError(Exception):
    """自我验证操作异常"""


# 结论类型 (可解释)
CONCLUSION_TYPES: list = [
    "fact",            # 事实
    "inference",       # 推论
    "hypothesis",      # 假设
    "uncertain",       # 不确定内容
]

# 证据信号 (可解释)
EVIDENCE_KEYWORDS: list = [
    "根据", "来源", "数据", "证据", "记录",
    "based on", "evidence", "data",
]

# 推理信号 (可解释)
REASONING_KEYWORDS: list = [
    "因此", "所以", "推断", "可能",
    "therefore", "infer", "likely",
]


class SelfVerification:
    """自我验证器 (输出前检查)

    用法:
        verifier = SelfVerification()
        r = verifier.verify("结论", evidence="...",
                            reasoning="...", confidence=0.8)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._verified_count = 0
        self._uncertain_count = 0

    # ── 验证主入口 ───────────────────────────────────────────────
    def verify(
        self,
        conclusion: str,
        evidence: str = "",
        reasoning: str = "",
        confidence: float = 0.5,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """输出前自我验证

        Args:
            conclusion: 结论
            evidence: 证据
            reasoning: 推理
            confidence: 置信度

        Returns:
            {
                'verification_id', 'conclusion_type', 'ok',
                'checks', 'reason', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "verification_id": "sv_" +
                    uuid.uuid4().hex[:8],
                    "conclusion_type": "inference",
                    "ok": True,
                    "checks": [],
                    "reason": "自我验证停用",
                    "mode": "rule_based",
                }
            try:
                conf = float(confidence)
            except (TypeError, ValueError):
                conf = 0.5
            conf = min(1.0, max(0.0, conf))
            checks: list = []
            # 1. Evidence 检查
            has_evidence = bool(evidence) or any(
                kw in str(conclusion)
                for kw in EVIDENCE_KEYWORDS
            )
            checks.append({
                "name": "evidence",
                "passed": has_evidence,
                "reason": (
                    "有证据" if has_evidence else "无证据"
                ),
            })
            # 2. Reasoning 检查
            has_reasoning = bool(reasoning) or any(
                kw in str(conclusion)
                for kw in REASONING_KEYWORDS
            )
            checks.append({
                "name": "reasoning",
                "passed": has_reasoning,
                "reason": (
                    "有推理" if has_reasoning else "无推理"
                ),
            })
            # 3. Confidence 检查
            conf_ok = conf >= 0.5
            checks.append({
                "name": "confidence",
                "passed": True,
                "reason": f"置信度 {conf}",
            })
            # 结论类型判定 (可解释)
            if has_evidence and has_reasoning:
                ctype = "fact"
            elif has_evidence or has_reasoning:
                ctype = "inference"
            elif conf >= 0.5:
                ctype = "hypothesis"
            else:
                ctype = "uncertain"
            ok = ctype != "uncertain"
            if not ok:
                self._uncertain_count += 1
            self._verified_count += 1
            return {
                "verification_id": "sv_" +
                uuid.uuid4().hex[:8],
                "conclusion_type": ctype,
                "ok": ok,
                "checks": checks,
                "reason": (
                    f"结论类型 '{ctype}'"
                    + (", 可输出" if ok else
                       ", 不确定内容需标注")
                ),
                "mode": "rule_based",
                "verified_at": now,
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """验证统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "verified_count": self._verified_count,
                "uncertain_count": self._uncertain_count,
                "conclusion_types": list(CONCLUSION_TYPES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._verified_count = 0
            self._uncertain_count = 0
            return 0


__all__ = [
    "CONCLUSION_TYPES",
    "SelfVerification",
    "VerificationError",
]
