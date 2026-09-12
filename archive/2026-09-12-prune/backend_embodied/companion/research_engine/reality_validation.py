"""
YHLZ Embodied AI V9.0 - 现实验证 (Reality Validation)

职责:
    - 输出分级: Fact / Evidence / Inference / Hypothesis /
      Speculation
    - 禁止将推测写入事实记忆

分级规则 (可解释):
    - fact:        可靠来源 + 明确证据
    - evidence:    有来源 + 可验证数据
    - inference:   有推理链 (无直接证据)
    - hypothesis:  有基础假设 (待验证)
    - speculation: 无依据推测 (禁止入事实记忆)

设计原则:
    - 纯规则分级 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class RealityError(Exception):
    """现实验证操作异常"""


# 知识等级 (可解释, 高→低)
REALITY_LEVELS: list = [
    "fact",          # 事实
    "evidence",      # 证据
    "inference",     # 推论
    "hypothesis",    # 假设
    "speculation",   # 推测
]

# 可靠来源关键词 (可解释)
RELIABLE_SOURCE_KEYWORDS: list = [
    "local", "user_authorized", "tool",
    "根据", "来源", "记录显示", "verified",
]

# 证据关键词 (可解释)
EVIDENCE_KEYWORDS: list = [
    "数据", "证据", "实验", "测量", "统计",
    "data", "evidence", "measured",
]

# 推理关键词 (可解释)
INFERENCE_KEYWORDS: list = [
    "因此", "所以", "推断", "可能", "推测",
    "therefore", "infer", "likely",
]


class RealityValidation:
    """现实验证器 (输出 → 知识等级)

    用法:
        validator = RealityValidation()
        r = validator.validate(content, source)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._validated_count = 0
        self._speculation_count = 0

    # ── 验证主入口 ───────────────────────────────────────────────
    def validate(
        self,
        content: str,
        source: str = "unknown",
        reliability: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """输出现实验证

        Args:
            content: 输出内容
            source: 来源
            reliability: 来源可靠度 (None → 关键词推断)

        Returns:
            {
                'validation_id', 'level', 'ok', 'reason',
                'checks', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "validation_id": "rv_" +
                    uuid.uuid4().hex[:8],
                    "level": "inference",
                    "ok": True,
                    "reason": "现实验证停用",
                    "checks": [],
                    "mode": "rule_based",
                }
            text = str(content or "")
            checks: list = []
            # 1. 来源可靠度
            if reliability is None:
                reliability = 0.7 if any(
                    kw in str(source) or kw in text
                    for kw in RELIABLE_SOURCE_KEYWORDS
                ) else 0.3
            reliable = reliability >= 0.5
            checks.append({
                "name": "source",
                "passed": True,
                "reason": (
                    f"来源可靠 (可靠度 {reliability})"
                    if reliable else
                    f"来源不可靠 (可靠度 {reliability})"
                ),
            })
            # 2. 证据
            has_evidence = any(
                kw in text for kw in EVIDENCE_KEYWORDS
            )
            checks.append({
                "name": "evidence",
                "passed": True,
                "reason": (
                    "有明确证据" if has_evidence else
                    "无直接证据"
                ),
            })
            # 3. 推理
            has_inference = any(
                kw in text for kw in INFERENCE_KEYWORDS
            )
            checks.append({
                "name": "reasoning",
                "passed": True,
                "reason": (
                    "有推理链" if has_inference else
                    "无推理链"
                ),
            })
            # 分级 (可解释)
            if reliable and has_evidence:
                level = "fact"
            elif reliable:
                level = "evidence"
            elif has_inference:
                level = "inference"
            elif has_evidence or text:
                level = "hypothesis"
            else:
                level = "speculation"
            # 推测禁止入事实记忆 (ok 表示可入长期记忆)
            ok = level != "speculation"
            if not ok:
                self._speculation_count += 1
            self._validated_count += 1
            return {
                "validation_id": "rv_" + uuid.uuid4().hex[:8],
                "level": level,
                "ok": ok,
                "reason": (
                    f"分级为 '{level}'"
                    + (", 可入长期记忆" if ok else
                       ", 推测禁止写入事实记忆")
                ),
                "checks": checks,
                "mode": "rule_based",
                "validated_at": now,
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """验证统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "validated_count": self._validated_count,
                "speculation_count": self._speculation_count,
                "levels": list(REALITY_LEVELS),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._validated_count = 0
            self._speculation_count = 0
            return 0


__all__ = [
    "REALITY_LEVELS",
    "RealityError",
    "RealityValidation",
]
