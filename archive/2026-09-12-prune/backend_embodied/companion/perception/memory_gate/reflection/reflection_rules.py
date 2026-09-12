"""
YHLZ Embodied AI V6.4 - 反思规则 (Reflection Rules)

职责:
    - 感知候选深度评估规则 (5 维):
      可信度 / 一致性 / 长期价值 / 身份影响 / 风险
    - 每维评分 + reason (可解释)

设计原则:
    - 纯规则 (无黑盒)
    - 一致性需对比已有知识 (矛盾检测)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ReflectionRulesError(Exception):
    """反思规则操作异常"""


# 一致性矛盾关键词 (可解释)
CONTRADICTION_KEYWORDS: List[str] = [
    "不是", "错误", "失败", "无效", "取消", "撤销",
    "失败", "否认",
]

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


class ReflectionRules:
    """反思规则器 (5 维评估)

    用法:
        rules = ReflectionRules()
        dims = rules.evaluate(candidate, known_experiences)
    """

    def __init__(self, threshold: float = 0.6):
        if not (0.0 <= threshold <= 1.0):
            raise ReflectionRulesError(
                f"threshold 必须在 [0,1], 当前: {threshold}"
            )
        self._lock = threading.RLock()
        self._threshold = float(threshold)

    # ── 评估主入口 ───────────────────────────────────────────────
    def evaluate(
        self,
        candidate: Dict[str, Any],
        known_experiences: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """5 维评估候选

        Args:
            candidate: 感知候选
            known_experiences: 已有经历 (一致性对比)

        Returns:
            {
                'reflection_score', 'pattern', 'contradiction',
                'value_hint', 'reason', 'dimensions': [...],
            }
        """
        with self._lock:
            known = known_experiences or []
            dims = {
                "credibility": self._credibility(candidate),
                "consistency": self._consistency(candidate, known),
                "long_term_value": self._long_term_value(candidate),
                "identity_impact": self._identity_impact(candidate),
                "risk": self._risk(candidate),
            }
            score = round(sum(
                d["score"] for d in dims.values()
            ) / 5.0, 4)
            pattern = self._find_pattern(candidate, known)
            contradiction = ""
            if dims["consistency"]["score"] < 0.5:
                contradiction = dims["consistency"]["reason"]
            value_hint = self._value_hint(candidate)
            reasons = "; ".join(
                d["reason"] for d in dims.values()
            )
            return {
                "reflection_score": score,
                "pattern": pattern,
                "contradiction": contradiction,
                "value_hint": value_hint,
                "reason": reasons,
                "dimensions": [
                    {"name": k, "score": v["score"],
                     "reason": v["reason"]}
                    for k, v in dims.items()
                ],
                "mode": "rule_based",
            }

    # ── 维度评分 (可解释) ───────────────────────────────────────
    @staticmethod
    def _credibility(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """可信度: 来源 + 置信度"""
        source = str(candidate.get("source", ""))
        conf = float(candidate.get("confidence", 0.0))
        source_score = {
            "camera": 0.9, "screen": 0.8, "tesseract": 0.8,
            "template": 0.7, "mock": 0.5,
        }.get(source, 0.3)
        score = round((source_score + conf) / 2.0, 4)
        return {
            "score": score,
            "reason": (
                f"来源 '{source}' 可信度 {source_score}, "
                f"置信度 {conf}"
            ),
        }

    @staticmethod
    def _consistency(
        candidate: Dict[str, Any],
        known: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """一致性: 与已有知识冲突检测"""
        summary = str(candidate.get("summary", ""))
        contradictions: List[str] = []
        for kw in CONTRADICTION_KEYWORDS:
            if kw in summary:
                contradictions.append(kw)
        # 与已有经历对比 (同触发器已存在 → 重复信号)
        for exp in known:
            trigger = str(exp.get("trigger", ""))
            if trigger and trigger in summary:
                contradictions.append(
                    f"与已有经历 '{trigger[:20]}' 重复",
                )
        if contradictions:
            return {
                "score": 0.3,
                "reason": f"发现矛盾信号 {contradictions[:3]}",
            }
        return {"score": 0.8, "reason": "与已有知识一致"}

    @staticmethod
    def _long_term_value(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """长期价值: 关键词 + 置信度"""
        summary = str(candidate.get("summary", ""))
        hits = [k for k in VALUE_KEYWORDS if k in summary]
        try:
            conf = float(candidate.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        score = 0.4 + 0.15 * len(hits) + 0.1 * conf
        return {
            "score": round(min(1.0, score), 4),
            "reason": (
                f"价值关键词 {hits if hits else '无'}, "
                f"置信度 {conf}"
            ),
        }

    @staticmethod
    def _identity_impact(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """身份影响: 关键词"""
        summary = str(candidate.get("summary", ""))
        hits = [k for k in IDENTITY_KEYWORDS if k in summary]
        score = 0.5 + 0.1 * len(hits) if hits else 0.5
        return {
            "score": round(min(1.0, score), 4),
            "reason": (
                f"身份关键词 {hits if hits else '无'} "
                f"(评估不影响核心身份)"
            ),
        }

    @staticmethod
    def _risk(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """风险: 危险关键词"""
        summary = str(candidate.get("summary", ""))
        hits = [k for k in RISK_KEYWORDS if k in summary]
        score = 0.5 if hits else 0.2
        return {
            "score": score,
            "reason": f"风险关键词 {hits if hits else '无'}",
        }

    # ── 模式与价值提示 (可解释) ─────────────────────────────────
    @staticmethod
    def _find_pattern(
        candidate: Dict[str, Any],
        known: List[Dict[str, Any]],
    ) -> str:
        """模式发现: 与已有经历的同触发器"""
        summary = str(candidate.get("summary", ""))
        for exp in known:
            trigger = str(exp.get("trigger", ""))
            if trigger and trigger[:6] in summary:
                return f"与已有经历 '{trigger[:20]}' 相似"
        return "无匹配模式"

    @staticmethod
    def _value_hint(candidate: Dict[str, Any]) -> str:
        """价值提示"""
        summary = str(candidate.get("summary", ""))
        hits = [k for k in VALUE_KEYWORDS if k in summary]
        if hits:
            return f"包含价值关键词 {hits[:3]}, 建议保存"
        return "无明确价值信号, 建议谨慎"

    # ── 查询 ─────────────────────────────────────────────────────
    def threshold(self) -> float:
        """评估阈值"""
        return self._threshold

    def stats(self) -> Dict[str, Any]:
        """规则配置"""
        with self._lock:
            return {
                "mode": "rule_based",
                "threshold": self._threshold,
                "dimensions": ["credibility", "consistency",
                               "long_term_value",
                               "identity_impact", "risk"],
            }


__all__ = [
    "CONTRADICTION_KEYWORDS",
    "IDENTITY_KEYWORDS",
    "RISK_KEYWORDS",
    "ReflectionRules",
    "ReflectionRulesError",
    "VALUE_KEYWORDS",
]
