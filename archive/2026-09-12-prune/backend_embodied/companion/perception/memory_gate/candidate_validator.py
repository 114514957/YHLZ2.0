"""
YHLZ Embodied AI V6.3 - 候选校验器 (Candidate Validator)

职责:
    - 记忆候选结构校验 (进入 Memory Gate 前)
    - 检查: 必填字段 / 值域 / 长度限制

设计原则:
    - 校验不通过 → 拒绝 (不进入批准流程)
    - 每项检查可解释
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ValidatorError(Exception):
    """候选校验操作异常"""


# 必填字段 (可解释)
REQUIRED_CANDIDATE_FIELDS: List[str] = [
    "candidate_id",  # 候选 ID
    "source",        # 感知来源
    "kind",          # 感知类型 (ocr/object)
    "summary",       # 内容摘要
    "confidence",    # 置信度
]


class CandidateValidator:
    """候选校验器

    用法:
        validator = CandidateValidator()
        ok, reason = validator.validate(candidate)
    """

    def __init__(self, max_summary_length: int = 200):
        if max_summary_length <= 0:
            raise ValidatorError(
                f"max_summary_length 必须 > 0, 当前: "
                f"{max_summary_length}"
            )
        self._lock = threading.RLock()
        self._max_summary = int(max_summary_length)
        self._history: List[Dict[str, Any]] = []

    # ── 校验 ─────────────────────────────────────────────────────
    def validate(self, candidate: Dict[str, Any]) -> tuple:
        """校验候选

        Args:
            candidate: 记忆候选 dict

        Returns:
            (ok: bool, reason: str)
        """
        with self._lock:
            if not candidate or not isinstance(candidate, dict):
                return self._finish(False, "候选为空或非法")
            # 必填字段
            missing = [
                f for f in REQUIRED_CANDIDATE_FIELDS
                if f not in candidate
            ]
            if missing:
                return self._finish(False, f"缺必填字段 {missing}")
            # 来源合法 (白名单)
            source = str(candidate.get("source", ""))
            if source not in ("vision", "camera", "screen", "mock",
                              "tesseract", "template"):
                return self._finish(False, f"来源非法: {source}")
            # 置信度范围
            conf = float(candidate.get("confidence", 0.0))
            if not (0.0 <= conf <= 1.0):
                return self._finish(
                    False, f"置信度必须在 [0,1], 当前: {conf}",
                )
            # 摘要长度
            summary = str(candidate.get("summary", ""))
            if len(summary) > self._max_summary:
                return self._finish(
                    False, f"摘要过长: {len(summary)} > "
                           f"{self._max_summary}",
                )
            return self._finish(True, "候选校验通过")

    def _finish(self, ok: bool, reason: str) -> tuple:
        """记录并返回"""
        with self._lock:
            self._history.append({
                "ok": ok, "reason": reason,
            })
            return ok, reason

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """校验统计"""
        with self._lock:
            history = list(self._history)
        passed = sum(1 for h in history if h["ok"])
        return {
            "mode": "rule_based",
            "input_count": len(history),
            "passed_count": passed,
            "rejected_count": len(history) - passed,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
            return n


__all__ = [
    "REQUIRED_CANDIDATE_FIELDS",
    "CandidateValidator",
    "ValidatorError",
]
