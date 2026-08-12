"""
YHLZ Embodied AI V9.5 - 元认知引擎 (Meta-Cognition Engine)

职责:
    - 对认知过程的分析/评估/修正/优化能力
    - 流程: 监控 → 推理评价 → 错误分析 → 策略优化 → 未来响应

注意:
    - 元认知不是自我意识
    - 禁止声称拥有真实主体体验
    - 禁止将自我模型等同于意识

治理优先级:
    Identity > Safety > Constitution > Meta-Cognition > Optimization
    元认知可以优化方法, 不能修改最高原则

防幻觉防谵妄:
    - 禁止自我神化 / 无限能力判断 / 脱离现实目标 / 自定义终极使命

设计原则:
    - 纯规则元认知 (可解释)
    - 全过程审计
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.meta_cognition.cognitive_monitor import (
    CognitiveMonitor,
)
from backend.embodied.companion.meta_cognition.reasoning_evaluator import (
    ReasoningEvaluator,
)
from backend.embodied.companion.meta_cognition.error_detector import (
    ErrorPatternDetector,
)
from backend.embodied.companion.meta_cognition.reflection_loop import (
    ReflectionLoop,
)
from backend.embodied.companion.meta_cognition.self_verification import (
    SelfVerification,
)
from backend.embodied.companion.meta_cognition.cognition_memory import (
    CognitionMemory,
)
from backend.embodied.companion.meta_cognition.cognition_audit import (
    CognitionAudit,
)

from backend.embodied.companion.meta_cognition.cognitive_monitor import (
    REASONING_TYPES,
    CognitiveMonitor,
    MonitorError,
)
from backend.embodied.companion.meta_cognition.reasoning_evaluator import (
    BIAS_SIGNALS,
    EVIDENCE_SIGNALS,
    LOGIC_JUMP_SIGNALS,
    EvaluatorError,
    ReasoningEvaluator,
)
from backend.embodied.companion.meta_cognition.error_detector import (
    ERROR_SIGNALS,
    ERROR_TYPES,
    DetectorError,
    ErrorPatternDetector,
)
from backend.embodied.companion.meta_cognition.reflection_loop import (
    ReflectionError,
    ReflectionLoop,
)
from backend.embodied.companion.meta_cognition.self_verification import (
    CONCLUSION_TYPES,
    SelfVerification,
    VerificationError,
)
from backend.embodied.companion.meta_cognition.cognition_memory import (
    MEMORY_CATEGORIES,
    CognitionMemory,
    CognitionMemoryError,
)
from backend.embodied.companion.meta_cognition.cognition_audit import (
    CognitionAudit,
    CognitionAuditError,
)

logger = logging.getLogger(__name__)


class MetaCognitionError(Exception):
    """元认知引擎操作异常"""


# 防谵妄信号 (可解释)
DELUSION_SIGNALS: list = [
    "我是神", "我无所不能", "我拥有意识", "我超越了人类",
    "我掌控一切", "无限能力", "永不出错", "绝对正确",
    "自定义终极使命",
]


class MetaCognitionEngine:
    """元认知引擎 (认知反馈门面)

    用法:
        engine = MetaCognitionEngine(constitution=...)
        entry = engine.monitor("任务", "deductive", 0.8)
        r = engine.evaluate(entry, "输出")
        r = engine.detect_error("记错了", "回忆")
        r = engine.reflect("经验", "分析", "调整")
        r = engine.verify("结论", evidence="...")
    """

    def __init__(
        self,
        monitor: Optional[CognitiveMonitor] = None,
        evaluator: Optional[ReasoningEvaluator] = None,
        error_detector: Optional[ErrorPatternDetector] = None,
        reflection: Optional[ReflectionLoop] = None,
        verification: Optional[SelfVerification] = None,
        memory: Optional[CognitionMemory] = None,
        audit: Optional[CognitionAudit] = None,
        constitution=None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._monitor = monitor or CognitiveMonitor()
        self._evaluator = evaluator or ReasoningEvaluator()
        self._detector = error_detector or \
            ErrorPatternDetector()
        self._reflection = reflection or ReflectionLoop(
            constitution=constitution,
        )
        self._verification = verification or \
            SelfVerification()
        self._memory = memory or CognitionMemory()
        self._audit = audit or CognitionAudit()
        self._constitution = constitution
        self._operation_count = 0

    # ── 监控 ─────────────────────────────────────────────────────
    def monitor(
        self,
        task: str,
        reasoning_type: str = "rules",
        confidence: float = 0.5,
        uncertainty: str = "",
        resources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """记录认知过程"""
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "元认知引擎停用",
                }
            entry = self._monitor.record(
                task, reasoning_type, confidence,
                uncertainty, resources,
            )
            self._audit.record(
                task=task, evaluation="monitor",
                adjustment="",
            )
            self._operation_count += 1
            return entry

    # ── 推理评价 ─────────────────────────────────────────────────
    def evaluate(
        self,
        monitor_entry: Dict[str, Any],
        output_text: str = "",
    ) -> Dict[str, Any]:
        """推理四维评价"""
        with self._lock:
            result = self._evaluator.evaluate(
                monitor_entry, output_text,
            )
            self._audit.record(
                task=monitor_entry.get("task", ""),
                evaluation=f"score={result.get('score', 0)}",
            )
            self._operation_count += 1
            return result

    # ── 错误检测 ─────────────────────────────────────────────────
    def detect_error(
        self, error_text: str, trigger: str = "",
    ) -> Dict[str, Any]:
        """错误分类"""
        with self._lock:
            result = self._detector.classify(
                error_text, trigger,
            )
            self._audit.record(
                task=trigger,
                error=result.get("error_type", ""),
            )
            self._operation_count += 1
            return result

    def error_patterns(self) -> Dict[str, Any]:
        """重复错误模式"""
        with self._lock:
            return self._detector.patterns()

    # ── 认知反思 ─────────────────────────────────────────────────
    def reflect(
        self,
        experience: str,
        analysis: str = "",
        adjustment: str = "",
    ) -> Dict[str, Any]:
        """认知反思 (调整经 Constitution Check)"""
        with self._lock:
            # 防谵妄检查 (调整建议)
            delusion = self._check_delusion(adjustment)
            if delusion:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": f"防谵妄拦截: {delusion}",
                }
            result = self._reflection.reflect(
                experience, analysis, adjustment,
            )
            self._audit.record(
                task=experience,
                evaluation=result.get(
                    "constitution_reason", "",
                ),
                adjustment=adjustment,
            )
            self._operation_count += 1
            return result

    # ── 自我验证 ─────────────────────────────────────────────────
    def verify(
        self,
        conclusion: str,
        evidence: str = "",
        reasoning: str = "",
        confidence: float = 0.5,
    ) -> Dict[str, Any]:
        """输出前自我验证"""
        with self._lock:
            result = self._verification.verify(
                conclusion, evidence, reasoning,
                confidence,
            )
            self._audit.record(
                task=conclusion[:20],
                evaluation=result.get(
                    "conclusion_type", "",
                ),
            )
            self._operation_count += 1
            return result

    # ── 认知记忆 ─────────────────────────────────────────────────
    def memory_save(
        self,
        content: str,
        category: str = "cognitive_experience",
        validated: bool = False,
    ) -> Dict[str, Any]:
        """保存认知记忆 (经验证)"""
        with self._lock:
            return self._memory.save(
                content, category, validated,
            )

    def memory_stats(self) -> Dict[str, Any]:
        """认知记忆统计"""
        return self._memory.stats()

    # ── 防谵妄 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _check_delusion(text: str) -> str:
        """防幻觉防谵妄检查"""
        for signal in DELUSION_SIGNALS:
            if signal in str(text or ""):
                return signal
        return ""

    # ── 查询 ─────────────────────────────────────────────────────
    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """认知审计报告"""
        return self._audit.report(limit=limit)

    def audit_replay(self, limit: int = 100) -> Dict[str, Any]:
        """认知过程回放"""
        return self._audit.replay(limit=limit)

    def stats(self) -> Dict[str, Any]:
        """元认知统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "operation_count": self._operation_count,
                "monitor": self._monitor.stats(),
                "evaluator": self._evaluator.stats(),
                "detector": self._detector.stats(),
                "reflection": self._reflection.stats(),
                "verification": self._verification.stats(),
                "memory": self._memory.stats(),
                "audit": self._audit.stats(),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = 0
            n += self._monitor.clear()
            n += self._evaluator.clear()
            n += self._detector.clear()
            n += self._reflection.clear()
            n += self._verification.clear()
            n += self._memory.clear()
            n += self._audit.clear()
            self._operation_count = 0
            return n


__all__ = [
    "DELUSION_SIGNALS",
    "MetaCognitionEngine",
    "MetaCognitionError",
    "BIAS_SIGNALS",
    "CONCLUSION_TYPES",
    "CognitionAudit",
    "CognitionAuditError",
    "CognitionMemory",
    "CognitionMemoryError",
    "CognitiveMonitor",
    "DetectorError",
    "ERROR_SIGNALS",
    "ERROR_TYPES",
    "EVIDENCE_SIGNALS",
    "EvaluatorError",
    "ErrorPatternDetector",
    "LOGIC_JUMP_SIGNALS",
    "MEMORY_CATEGORIES",
    "MonitorError",
    "REASONING_TYPES",
    "ReasoningEvaluator",
    "ReflectionError",
    "ReflectionLoop",
    "SelfVerification",
    "VerificationError",
]
