"""
YHLZ Embodied AI V6.6 - 反思情绪集成 (Reflection Emotion Integration)

职责:
    - 反思结果经 Meaning → Growth Value → 情绪状态调整建议
    - 流程:
      Reflection Report → Meaning Extraction → Emotion Analysis
      → Growth Value Score → Emotion Adjustment (经 EmotionEngine)

原则 (反思 ≠ 意识, 情绪不直接修改身份):
    - 反思是计算过程, 不是真实体验
    - 禁止 Reflection 直接修改人格
    - 禁止 Emotion 模块改变 Core Value
    - 情绪调整必须经 EmotionEngine (不直接写状态)

情绪调整规则 (可解释):
    - 正面反思 (有效策略确认) → 温和积极 (success)
    - 负面反思 (问题模式识别) → 有限调整 (failure, 有限幅)
    - 无模式 → 中性 (idle, 不调整情绪)

设计原则:
    - 纯规则 (无黑盒)
    - 每次调整可解释 (meaning/reason)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReflectionEmotionError(Exception):
    """反思情绪集成操作异常"""


# 允许的反思情绪上下文 (可解释, 白名单)
REFLECTION_EMOTION_CONTEXTS: List[str] = [
    "success",            # 有效策略确认 → 温和积极
    "failure",            # 问题模式识别 → 有限调整
    "idle",               # 无模式 → 不调整
]

# 情绪状态 (可解释)
EMOTION_STATES: List[str] = [
    "positive",           # 积极 (有效策略)
    "cautious",           # 谨慎 (问题模式/矛盾)
    "neutral",            # 中性 (无显著信号)
]

# 风险等级 (可解释)
RISK_LEVELS: List[str] = [
    "low",                # 无矛盾
    "medium",             # 知识矛盾
    "high",               # 身份/价值矛盾
]

# 模式 → 意义映射 (可解释)
MEANING_BY_PATTERN: Dict[str, Dict[str, Any]] = {
    "success_strategy": {
        "meaning": "有效策略确认: 连续成功形成可复用策略",
        "growth_value": 0.85,
        "emotion_context": "success",
        "emotion_state": "positive",
    },
    "problem_pattern": {
        "meaning": "问题模式识别: 连续失败暴露待改进环节",
        "growth_value": 0.35,
        "emotion_context": "failure",
        "emotion_state": "cautious",
    },
    "repetition": {
        "meaning": "重复行为确认: 行为模式重复出现",
        "growth_value": 0.5,
        "emotion_context": "idle",
        "emotion_state": "neutral",
    },
}

# 矛盾类型 → 风险提升 (可解释)
CONTRADICTION_RISK: Dict[str, str] = {
    "identity_conflict": "high",
    "knowledge_conflict": "medium",
    "value_conflict": "high",
}


class ReflectionEmotionIntegrator:
    """反思情绪集成器 (反思 → 意义 → 成长值 → 情绪调整建议)

    用法:
        integrator = ReflectionEmotionIntegrator(emotion=engine)
        result = integrator.adjust(reflection_report)
    """

    def __init__(
        self,
        emotion=None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._emotion = emotion
        self._enabled = bool(enabled)
        self._results: List[Dict[str, Any]] = []
        self._adjustment_count = 0
        self._skip_count = 0
        self._context_distribution: Dict[str, int] = {}

    # ── 主入口: 分析 ─────────────────────────────────────────────
    def analyze(
        self,
        reflection_report: Dict[str, Any],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """反思 → 意义提取 → 情绪分析 → 成长值

        Args:
            reflection_report: 认知反思报告 (CognitiveReflectionEngine
                analyze 输出: patterns/contradictions/confidence)

        Returns:
            {
                'result_id', 'report_id', 'meaning',
                'emotion_analysis': {state, confidence},
                'growth_value', 'risk_level', 'emotion_context',
                'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not isinstance(reflection_report, dict):
                reflection_report = {}
            # 输入规范化 (异常输入容错)
            patterns = [
                p for p in (reflection_report.get("patterns") or [])
                if isinstance(p, dict)
            ]
            contradictions = [
                c for c in (
                    reflection_report.get("contradictions") or []
                )
                if isinstance(c, dict)
            ]
            reflection_report = dict(reflection_report)
            reflection_report["patterns"] = patterns
            reflection_report["contradictions"] = contradictions
            if not self._enabled:
                return self._build_result(
                    reflection_report, now,
                    meaning="反思情绪集成停用",
                    growth_value=0.0,
                    risk_level="low",
                    emotion_context="idle",
                    emotion_state="neutral",
                    confidence=0.0,
                )
            # 1. Meaning Extraction (模式 → 意义)
            patterns = reflection_report.get("patterns", []) or []
            meaning, growth_value, emotion_context, emotion_state = \
                self._extract_meaning(patterns)
            # 2. Emotion Analysis (状态 + 置信度)
            state, confidence = self._emotion_analysis(
                reflection_report, growth_value,
            )
            # 3. Risk Level (矛盾)
            risk_level = self._risk_level(
                reflection_report.get("contradictions", []) or [],
            )
            # 风险 → 谨慎 + 成长值降幅 (有限)
            if risk_level in ("medium", "high"):
                growth_value = round(
                    max(0.0, growth_value - 0.15), 4,
                )
                if state == "neutral":
                    state = "cautious"
            result = self._build_result(
                reflection_report, now, meaning,
                growth_value, risk_level,
                emotion_context, state, confidence,
            )
            self._results.append(result)
            return dict(result)

    # ── 主入口: 调整 (经 EmotionEngine) ──────────────────────────
    def adjust(
        self,
        reflection_report: Dict[str, Any],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """反思 → 情绪调整 (经 EmotionEngine, 不直接写状态)

        Args:
            reflection_report: 认知反思报告

        Returns:
            analyze 结果 + adjustment 段:
                'adjustment': {
                    applied, context, before, after, reason,
                }
        """
        with self._lock:
            result = self.analyze(reflection_report, now=now)
            adjustment = {
                "applied": False,
                "context": result["emotion_context"],
                "before": {},
                "after": {},
                "reason": "无情绪引擎或上下文为 idle, 跳过调整",
            }
            context = result["emotion_context"]
            if self._emotion is not None and context != "idle":
                try:
                    before = self._emotion.get_state()
                    after = self._emotion.update(context)
                    adjustment = {
                        "applied": True,
                        "context": context,
                        "before": before,
                        "after": after,
                        "reason": result["meaning"],
                    }
                    self._adjustment_count += 1
                    self._context_distribution[context] = \
                        self._context_distribution.get(context, 0) + 1
                except Exception as e:
                    logger.warning(
                        f"[ReflectionEmotion] 情绪调整失败: {e}",
                    )
                    adjustment["reason"] = f"情绪调整失败: {e}"
            else:
                self._skip_count += 1
            result["adjustment"] = adjustment
            return result

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _extract_meaning(
        patterns: List[Dict[str, Any]],
    ) -> tuple:
        """模式 → 意义 + 成长值 + 情绪上下文 (最高置信模式优先)"""
        if not patterns:
            return ("暂无明显模式, 无成长信号", 0.6, "idle", "neutral")
        ordered = sorted(
            patterns,
            key=lambda p: float(p.get("confidence", 0.0)),
            reverse=True,
        )
        ptype = str(ordered[0].get("type", ""))
        rule = MEANING_BY_PATTERN.get(ptype)
        if rule is None:
            return ("经验模式待分类, 暂不调整情绪", 0.5,
                    "idle", "neutral")
        return (rule["meaning"], rule["growth_value"],
                rule["emotion_context"], rule["emotion_state"])

    @staticmethod
    def _emotion_analysis(
        reflection_report: Dict[str, Any],
        growth_value: float,
    ) -> tuple:
        """情绪状态 + 置信度"""
        try:
            report_conf = float(
                reflection_report.get("confidence", 0.0),
            )
        except (TypeError, ValueError):
            report_conf = 0.0
        state = "positive" if growth_value >= 0.7 else (
            "cautious" if growth_value < 0.5 else "neutral"
        )
        return state, round(min(1.0, report_conf), 4)

    @staticmethod
    def _risk_level(
        contradictions: List[Dict[str, Any]],
    ) -> str:
        """矛盾 → 风险等级 (最高风险优先)"""
        level = "low"
        for c in contradictions:
            ctype = c.get("conflict_type", "")
            level = CONTRADICTION_RISK.get(ctype, "low")
            if level == "high":
                break
        return level

    def _build_result(self, report, now, meaning,
                      growth_value, risk_level, emotion_context,
                      emotion_state, confidence) -> Dict[str, Any]:
        return {
            "result_id": "re_" + uuid.uuid4().hex[:8],
            "report_id": report.get("report_id", ""),
            "meaning": meaning,
            "emotion_analysis": {
                "state": emotion_state,
                "confidence": confidence,
            },
            "growth_value": round(float(growth_value), 4),
            "risk_level": risk_level,
            "emotion_context": emotion_context,
            "mode": "rule_based",
            "generated_at": now,
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def latest(self) -> Optional[Dict[str, Any]]:
        """最新集成结果"""
        with self._lock:
            if not self._results:
                return None
            return dict(self._results[-1])

    def stats(self) -> Dict[str, Any]:
        """集成统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "analysis_count": len(self._results),
                "adjustment_count": self._adjustment_count,
                "skip_count": self._skip_count,
                "context_distribution": dict(
                    self._context_distribution,
                ),
                "emotion_contexts": list(
                    REFLECTION_EMOTION_CONTEXTS,
                ),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            self._adjustment_count = 0
            self._skip_count = 0
            self._context_distribution = {}
            return n


__all__ = [
    "CONTRADICTION_RISK",
    "EMOTION_STATES",
    "MEANING_BY_PATTERN",
    "REFLECTION_EMOTION_CONTEXTS",
    "RISK_LEVELS",
    "ReflectionEmotionError",
    "ReflectionEmotionIntegrator",
]
