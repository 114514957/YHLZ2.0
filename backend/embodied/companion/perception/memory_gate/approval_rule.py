"""
YHLZ Embodied AI V6.3 - 记忆批准规则 (Memory Gate Approval Rules)

职责:
    - 感知候选 → 批准/拒绝规则 (5 维检查):
      来源可信度 / 重复程度 / 长期价值 / 身份影响 / 风险等级
    - 输出: {status: approved/rejected, reason, confidence}

规则 (可解释):
    - 来源可信度: camera/screen/mock 可信; 低可信来源减分
    - 重复程度: 同内容出现次数 (重复过高 → 降价值)
    - 长期价值: 候选 summary 关键词 (任务/清单/重要 等)
    - 身份影响: 身份/人格关键词 (高影响 → 需谨慎, 但高价值)
    - 风险等级: 危险关键词 (高风险 → 拒绝)

设计原则:
    - 纯规则 (无黑盒)
    - 每维附 reason
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ApprovalRuleError(Exception):
    """批准规则操作异常"""


# 来源可信度 (可解释)
TRUSTED_SOURCES: Dict[str, float] = {
    "camera": 0.9,       # 摄像头 (直接观察)
    "screen": 0.8,       # 屏幕 (用户可见内容)
    "tesseract": 0.8,    # OCR 引擎
    "template": 0.7,     # 模板检测
    "mock": 0.5,         # Mock (测试)
}

# 长期价值关键词 (可解释)
VALUE_KEYWORDS: List[str] = [
    "任务", "清单", "计划", "重要", "目标", "会议",
    "提醒", "学习", "工作",
]

# 身份影响关键词 (可解释)
IDENTITY_KEYWORDS: List[str] = [
    "身份", "人格", "核心", "使命", "价值观",
]

# 风险关键词 (可解释)
RISK_KEYWORDS: List[str] = [
    "删除", "覆盖", "格式化", "关闭", "危险",
    "密码", "支付", "授权",
]


class ApprovalRule:
    """批准规则器 (5 维检查)

    用法:
        rule = ApprovalRule()
        result = rule.evaluate(candidate)
    """

    def __init__(self, approve_threshold: float = 0.6,
                 reject_threshold: float = 0.3):
        if not (0.0 <= approve_threshold <= 1.0):
            raise ApprovalRuleError(
                f"approve_threshold 必须在 [0,1], 当前: "
                f"{approve_threshold}"
            )
        if not (0.0 <= reject_threshold <= 1.0):
            raise ApprovalRuleError(
                f"reject_threshold 必须在 [0,1], 当前: "
                f"{reject_threshold}"
            )
        if reject_threshold >= approve_threshold:
            raise ApprovalRuleError(
                f"reject_threshold({reject_threshold}) 必须小于 "
                f"approve_threshold({approve_threshold})"
            )
        self._lock = threading.RLock()
        self._approve = float(approve_threshold)
        self._reject = float(reject_threshold)

    # ── 评估主入口 ───────────────────────────────────────────────
    def evaluate(
        self, candidate: Dict[str, Any],
        reflection_score: float = None,
    ) -> Dict[str, Any]:
        """评估候选 (5 维 + 可选 Reflection Score → 最终评分)

        Args:
            candidate: 记忆候选 (source/kind/summary/confidence)
            reflection_score: 反思评估评分 (V6.4, 可空)

        Returns:
            {
                'status': approved/rejected, 'reason',
                'confidence', 'dimensions': [...],
                'final_score', 'reflection_score',
            }
        """
        with self._lock:
            dims = {
                "source_trust": self._source_trust(candidate),
                "repetition": self._repetition(candidate),
                "long_term_value": self._long_term_value(candidate),
                "identity_impact": self._identity_impact(candidate),
                "risk": self._risk(candidate),
            }
            if reflection_score is not None:
                try:
                    rscore = float(reflection_score)
                except (TypeError, ValueError):
                    rscore = 0.5
                rscore = max(0.0, min(1.0, rscore))
                dims["reflection"] = {
                    "score": rscore,
                    "reason": f"反思评估评分 {rscore}",
                }
                reflection_score = rscore
            score = round(sum(
                d["score"] for d in dims.values()
            ) / len(dims), 4)
            # 风险特殊: 高风险直接拒绝 (1 个风险词即拒绝)
            if dims["risk"]["score"] >= 0.5:
                status = "rejected"
                reason = f"高风险候选: {dims['risk']['reason']}"
            elif score >= self._approve:
                status = "approved"
                reason = f"综合评分 {score} ≥ 批准阈值 {self._approve}"
            elif score < self._reject:
                status = "rejected"
                reason = f"综合评分 {score} < 拒绝阈值 {self._reject}"
            else:
                status = "rejected"
                reason = f"综合评分 {score} 未达批准阈值, 暂不写入"
            return {
                "status": status,
                "reason": reason,
                "confidence": score,
                "final_score": score,
                "reflection_score": round(
                    float(reflection_score), 4,
                ) if reflection_score is not None else None,
                "dimensions": [
                    {"name": k, "score": v["score"],
                     "reason": v["reason"]}
                    for k, v in dims.items()
                ],
                "mode": "rule_based",
            }

    # ── 维度评分 (可解释) ───────────────────────────────────────
    @staticmethod
    def _source_trust(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """来源可信度"""
        source = str(candidate.get("source", ""))
        score = TRUSTED_SOURCES.get(source, 0.3)
        return {
            "score": score,
            "reason": f"来源 '{source}' 可信度 {score}",
        }

    @staticmethod
    def _repetition(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """重复程度: 同内容出现次数 (重复过高降价值)"""
        count = int(candidate.get("occurrence_count", 1) or 1)
        # 1 次: 0.8; 2-3 次: 0.6; 4+: 0.4 (重复降价值)
        if count >= 4:
            score = 0.4
        elif count >= 2:
            score = 0.6
        else:
            score = 0.8
        return {
            "score": score,
            "reason": f"同内容出现 {count} 次",
        }

    @staticmethod
    def _long_term_value(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """长期价值: 关键词 + 置信度"""
        summary = str(candidate.get("summary", ""))
        hits = [k for k in VALUE_KEYWORDS if k in summary]
        base = 0.4 + 0.1 * len(hits)
        try:
            conf = float(candidate.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        base += 0.2 * conf
        return {
            "score": round(min(1.0, base), 4),
            "reason": (
                f"价值关键词 {hits if hits else '无'}, "
                f"置信度 {conf}"
            ),
        }

    @staticmethod
    def _identity_impact(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """身份影响: 身份关键词 (高影响需谨慎但高价值)"""
        summary = str(candidate.get("summary", ""))
        hits = [k for k in IDENTITY_KEYWORDS if k in summary]
        score = 0.5 + 0.1 * len(hits) if hits else 0.5
        return {
            "score": round(min(1.0, score), 4),
            "reason": (
                f"身份关键词 {hits if hits else '无'} "
                f"(不影响核心身份, 仅记忆评估)"
            ),
        }

    @staticmethod
    def _risk(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """风险等级: 危险关键词 (1 词即高风险)"""
        summary = str(candidate.get("summary", ""))
        hits = [k for k in RISK_KEYWORDS if k in summary]
        score = 0.5 if hits else 0.2
        return {
            "score": score,
            "reason": f"风险关键词 {hits if hits else '无'}",
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        """阈值 (可解释)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "approve_threshold": self._approve,
                "reject_threshold": self._reject,
            }


__all__ = [
    "IDENTITY_KEYWORDS",
    "RISK_KEYWORDS",
    "TRUSTED_SOURCES",
    "VALUE_KEYWORDS",
    "ApprovalRule",
    "ApprovalRuleError",
]
