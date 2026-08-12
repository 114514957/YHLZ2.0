"""
YHLZ Embodied AI V9.5 - 错误模式检测器 (Error Pattern Detector)

职责:
    - 错误分类: Fact / Logic / Memory / Assumption / Decision
    - 发现重复错误模式

设计原则:
    - 分类可解释 (规则/信号)
    - 重复模式统计驱动 (≥2 次同类错误)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DetectorError(Exception):
    """错误检测操作异常"""


# 错误类型 (可解释)
ERROR_TYPES: list = [
    "fact_error",        # 事实错误
    "logic_error",       # 逻辑错误
    "memory_error",      # 记忆错误
    "assumption_error",  # 假设错误
    "decision_error",    # 决策错误
]

# 各错误类型信号 (可解释)
ERROR_SIGNALS: Dict[str, List[str]] = {
    "fact_error": [
        "与事实不符", "错误事实", "数据错误",
        "wrong fact", "incorrect data",
    ],
    "logic_error": [
        "逻辑矛盾", "推理错误", "因果倒置",
        "logic contradiction", "wrong inference",
    ],
    "memory_error": [
        "记错了", "记忆混淆", "来源不明",
        "wrong memory", "unclear source",
    ],
    "assumption_error": [
        "假设当作事实", "未经验证的假设",
        "assumption as fact", "unverified assumption",
    ],
    "decision_error": [
        "错误决策", "选择失误", "判断错误",
        "wrong decision", "bad choice",
    ],
}


class ErrorPatternDetector:
    """错误模式检测器 (分类 + 重复模式)

    用法:
        detector = ErrorPatternDetector()
        r = detector.classify("记错了日期", trigger="回忆")
        patterns = detector.patterns()
    """

    def __init__(self, enabled: bool = True,
                 min_pattern: int = 2):
        if min_pattern < 2:
            raise DetectorError(
                f"min_pattern 必须 >= 2, 当前: {min_pattern}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._min_pattern = int(min_pattern)
        self._errors: list = []
        self._pattern_count: Dict[str, int] = {}

    # ── 分类主入口 ───────────────────────────────────────────────
    def classify(
        self,
        error_text: str,
        trigger: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """错误分类

        Args:
            error_text: 错误描述
            trigger: 触发情境

        Returns:
            {
                'error_id', 'error_type', 'reason',
                'matched_signal', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "错误检测停用",
                }
            text = str(error_text or "")
            matched = None
            matched_signal = ""
            for etype, signals in ERROR_SIGNALS.items():
                for signal in signals:
                    if signal in text:
                        matched = etype
                        matched_signal = signal
                        break
                if matched:
                    break
            if matched is None:
                return {
                    "mode": "rule_based",
                    "error_id": "ed_" + uuid.uuid4().hex[:8],
                    "error_type": "none",
                    "reason": "未匹配到已知错误类型",
                    "matched_signal": "",
                }
            entry = {
                "error_id": "ed_" + uuid.uuid4().hex[:8],
                "error_type": matched,
                "trigger": str(trigger),
                "reason": f"匹配信号 '{matched_signal}'",
                "matched_signal": matched_signal,
                "mode": "rule_based",
                "timestamp": now,
            }
            self._errors.append(entry)
            # 重复模式计数 (按 trigger+type)
            key = f"{trigger}:{matched}"
            self._pattern_count[key] = \
                self._pattern_count.get(key, 0) + 1
            return dict(entry)

    # ── 重复模式 ─────────────────────────────────────────────────
    def patterns(self) -> Dict[str, Any]:
        """重复错误模式 (≥min_pattern)"""
        with self._lock:
            patterns = []
            for key, count in self._pattern_count.items():
                if count >= self._min_pattern:
                    trigger, etype = key.split(":", 1)
                    patterns.append({
                        "trigger": trigger,
                        "error_type": etype,
                        "occurrences": count,
                    })
            patterns.sort(
                key=lambda p: p["occurrences"],
                reverse=True,
            )
            return {
                "mode": "rule_based",
                "patterns": patterns,
                "pattern_count": len(patterns),
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """检测统计"""
        with self._lock:
            by_type: Dict[str, int] = {}
            for e in self._errors:
                by_type[e["error_type"]] = by_type.get(
                    e["error_type"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "error_count": len(self._errors),
                "by_type": by_type,
                "min_pattern": self._min_pattern,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._errors)
            self._errors.clear()
            self._pattern_count = {}
            return n


__all__ = [
    "ERROR_SIGNALS",
    "ERROR_TYPES",
    "DetectorError",
    "ErrorPatternDetector",
]
