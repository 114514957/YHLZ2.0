"""
YHLZ Embodied AI V6.8 - 任务分类器 (Task Classifier)

职责:
    - 规范化任务上下文 (Task Context)
    - 判定任务类型 (身份/记忆/权限/视觉/推理/创造/分析...)
    - 为路由引擎提供可解释特征

输入:
    {
        "type": "",
        "complexity": 0.0,
        "privacy_level": "",
        "latency_requirement": "",
        "creativity_requirement": 0.0,
    }

输出:
    {
        "type": "",
        "complexity": 0.0,
        "privacy_level": "",
        "latency_requirement": "",
        "creativity_requirement": 0.0,
        "reason": "",
    }

设计原则:
    - 纯规则分类 (无黑盒)
    - 类型映射可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ClassifierError(Exception):
    """任务分类操作异常"""


# 任务类型 (可解释)
TASK_TYPES: list = [
    "identity_query",          # 身份查询 (本地铁律)
    "memory_retrieval",        # 记忆检索 (本地优先)
    "permission_check",        # 权限检查 (本地铁律)
    "vision_detection",        # 视觉检测 (本地实时)
    "basic_reasoning",         # 基础推理 (本地)
    "deep_reasoning",          # 深度推理 (云端)
    "creative_exploration",    # 创造探索 (云端增强)
    "analysis",                # 专业分析 (云端)
    "research",                # 研究分析 (云端)
    "architecture_design",     # 架构设计 (云端)
    "document_understanding",  # 大文档理解 (云端)
]

# 隐私等级 (可解释)
PRIVACY_LEVELS: list = ["high", "medium", "low"]

# 实时性要求 (可解释)
LATENCY_LEVELS: list = ["realtime", "normal", "async"]

# 任务类型 → 默认特征 (可解释)
TASK_PROFILES: Dict[str, Dict[str, Any]] = {
    "identity_query": {
        "complexity": 0.2, "privacy_level": "high",
        "latency_requirement": "realtime",
        "creativity_requirement": 0.0,
    },
    "memory_retrieval": {
        "complexity": 0.3, "privacy_level": "high",
        "latency_requirement": "realtime",
        "creativity_requirement": 0.0,
    },
    "permission_check": {
        "complexity": 0.1, "privacy_level": "high",
        "latency_requirement": "realtime",
        "creativity_requirement": 0.0,
    },
    "vision_detection": {
        "complexity": 0.4, "privacy_level": "medium",
        "latency_requirement": "realtime",
        "creativity_requirement": 0.1,
    },
    "basic_reasoning": {
        "complexity": 0.4, "privacy_level": "low",
        "latency_requirement": "normal",
        "creativity_requirement": 0.2,
    },
    "deep_reasoning": {
        "complexity": 0.8, "privacy_level": "medium",
        "latency_requirement": "async",
        "creativity_requirement": 0.5,
    },
    "creative_exploration": {
        "complexity": 0.6, "privacy_level": "low",
        "latency_requirement": "async",
        "creativity_requirement": 0.9,
    },
    "analysis": {
        "complexity": 0.7, "privacy_level": "medium",
        "latency_requirement": "async",
        "creativity_requirement": 0.4,
    },
    "research": {
        "complexity": 0.8, "privacy_level": "medium",
        "latency_requirement": "async",
        "creativity_requirement": 0.6,
    },
    "architecture_design": {
        "complexity": 0.9, "privacy_level": "low",
        "latency_requirement": "async",
        "creativity_requirement": 0.7,
    },
    "document_understanding": {
        "complexity": 0.8, "privacy_level": "medium",
        "latency_requirement": "async",
        "creativity_requirement": 0.3,
    },
}

# 类型关键词映射 (可解释, 中文友好)
TYPE_KEYWORDS: Dict[str, list] = {
    "identity_query": ["身份", "使命", "我是谁", "identity"],
    "memory_retrieval": ["记忆", "回忆", "记住", "memory"],
    "permission_check": ["权限", "允许", "可以吗", "permission"],
    "vision_detection": ["视觉", "摄像头", "识别", "看", "vision"],
    "creative_exploration": ["创造", "创意", "方案", "灵感",
                             "creative"],
    "research": ["研究", "调研", "资料", "research"],
    "architecture_design": ["架构", "设计系统", "architecture"],
    "document_understanding": ["文档", "长文", "理解文档"],
    "analysis": ["分析", "评估", "报告", "analysis"],
    "deep_reasoning": ["推理", "复杂", "推理题", "reason"],
    "basic_reasoning": ["判断", "简单", "basic"],
}


class TaskClassifier:
    """任务分类器 (上下文 → 规范化特征 + 类型)

    用法:
        classifier = TaskClassifier()
        ctx = classifier.classify(task_context)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._classified_count = 0
        self._type_distribution: Dict[str, int] = {}

    # ── 分类主入口 ───────────────────────────────────────────────
    def classify(
        self,
        task_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """规范化任务上下文

        Args:
            task_context: 原始任务描述 (可空)

        Returns:
            规范化上下文 (含 reason)
        """
        with self._lock:
            raw = task_context or {}
            # 类型判定: 显式 type 或关键词推断
            ttype = str(raw.get("type", "")).strip()
            if ttype and ttype not in TASK_TYPES:
                raise ClassifierError(
                    f"非法任务类型: {ttype} (可选: {TASK_TYPES})"
                )
            if not ttype:
                ttype, kw = self._infer_type(
                    str(raw.get("text", "")),
                )
            else:
                kw = "显式指定"
            profile = TASK_PROFILES.get(
                ttype, TASK_PROFILES["basic_reasoning"],
            )
            complexity = self._clamp_float(
                raw.get("complexity"),
                profile["complexity"],
            )
            privacy = self._pick_level(
                raw.get("privacy_level"),
                profile["privacy_level"],
                PRIVACY_LEVELS,
            )
            latency = self._pick_level(
                raw.get("latency_requirement"),
                profile["latency_requirement"],
                LATENCY_LEVELS,
            )
            creativity = self._clamp_float(
                raw.get("creativity_requirement"),
                profile["creativity_requirement"],
            )
            self._classified_count += 1
            self._type_distribution[ttype] = \
                self._type_distribution.get(ttype, 0) + 1
            return {
                "mode": "rule_based",
                "type": ttype,
                "complexity": complexity,
                "privacy_level": privacy,
                "latency_requirement": latency,
                "creativity_requirement": creativity,
                "type_reason": kw,
            }

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _infer_type(text: str) -> tuple:
        """关键词推断任务类型"""
        for ttype, keywords in TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw and kw in text:
                    return ttype, f"关键词 '{kw}'"
        return "basic_reasoning", "无关键词匹配, 默认基础推理"

    @staticmethod
    def _clamp_float(value, default: float) -> float:
        """数值钳制 (非法/越界 → 默认)"""
        if value is None:
            return round(float(default), 4)
        try:
            v = float(value)
        except (TypeError, ValueError):
            return round(float(default), 4)
        return round(min(1.0, max(0.0, v)), 4)

    @staticmethod
    def _pick_level(value, default: str,
                    levels: list) -> str:
        """等级选择 (非法 → 默认)"""
        if value in levels:
            return str(value)
        return str(default)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """分类统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "classified_count": self._classified_count,
                "type_distribution": dict(
                    self._type_distribution,
                ),
                "task_types": list(TASK_TYPES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._classified_count = 0
            self._type_distribution = {}
            return 0


__all__ = [
    "ClassifierError",
    "LATENCY_LEVELS",
    "PRIVACY_LEVELS",
    "TASK_PROFILES",
    "TASK_TYPES",
    "TYPE_KEYWORDS",
    "TaskClassifier",
]
