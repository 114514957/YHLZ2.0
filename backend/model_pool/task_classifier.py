"""
YHLZ Model Pool Router V10.1.3 - 任务分类器 (Task Classifier)

职责:
    - 请求分类: CHAT / KNOWLEDGE / CODING / ENGINEERING /
      REASONING / VISION / MEMORY / SUMMARY
    - 分类依据: 关键词规则 (可解释)

设计原则:
    - 规则可解释 (rule/reason)
    - 分类结果供模型选择算法使用
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskClassifierError(Exception):
    """任务分类器异常"""


# 任务类型 (可解释)
TASK_TYPES: List[str] = [
    "CHAT",        # 对话
    "KNOWLEDGE",   # 知识问答
    "CODING",      # 代码
    "ENGINEERING", # 工程
    "REASONING",   # 推理
    "VISION",      # 视觉
    "MEMORY",      # 记忆
    "SUMMARY",     # 总结
]

# 分类关键词 (可解释)
TASK_KEYWORDS: Dict[str, List[str]] = {
    "CODING": ["代码", "编写", "函数", "bug", "报错", "debug",
               "python", "实现", "算法", "重构", "写一个"],
    "ENGINEERING": ["架构", "设计", "方案", "系统", "部署",
                    "工程", "模块", "接口", "架构设计"],
    "REASONING": ["为什么", "推理", "证明", "逻辑",
                  "判断", "比较", "推导", "分析原因"],
    "VISION": ["图片", "图像", "截图", "屏幕", "摄像头",
               "视觉", "识别", "ocr", "分析这张图",
               "看这张图"],
    "MEMORY": ["记住", "记忆", "回忆", "忘了", "之前说过",
               "上次"],
    "SUMMARY": ["总结", "概括", "摘要", "提炼", "归纳"],
    "KNOWLEDGE": ["是什么", "什么是", "定义", "介绍", "解释",
                  "原理", "区别", "知识", "学习什么"],
}


class TaskClassifier:
    """任务分类器 (V10.1.3)

    用法:
        tc = TaskClassifier()
        result = tc.classify("帮我写一个python函数")
        # result = {task_type: "CODING", reason: "..."}
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._classify_count = 0

    def classify(self, text: str) -> Dict[str, Any]:
        """分类任务"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "任务分类器停用"}
            content = str(text or "")
            scores: Dict[str, int] = {}
            hits: Dict[str, List[str]] = {}
            for task_type, keywords in TASK_KEYWORDS.items():
                matched = [k for k in keywords if k in content]
                if matched:
                    scores[task_type] = len(matched)
                    hits[task_type] = matched
            self._classify_count += 1
            if not scores:
                return {
                    "mode": "rule_based", "ok": True,
                    "task_type": "CHAT",
                    "confidence": 0.5,
                    "reason": "无特定关键词, 默认对话",
                    "matched": [],
                }
            best = max(scores, key=scores.get)
            confidence = round(
                min(0.5 + scores[best] * 0.1, 1.0), 2,
            )
            return {
                "mode": "rule_based", "ok": True,
                "task_type": best,
                "confidence": confidence,
                "reason": (
                    f"命中关键词 {scores[best]} 个: {hits[best]}"
                ),
                "matched": hits[best],
                "scores": scores,
            }

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "classify_count": self._classify_count,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = self._classify_count
            self._classify_count = 0
            return n


__all__ = [
    "TASK_KEYWORDS",
    "TASK_TYPES",
    "TaskClassifier",
    "TaskClassifierError",
]
