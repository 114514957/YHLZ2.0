"""
YHLZ Embodied AI V5.9 - 反思桥接 (Reflection Bridge)

职责:
    - 接入 Reflection Layer (V5.8)
    - 读取: Reflection Report (模式 / 失败 / 建议)
    - 转换: Reflection 结果 → 机会检测输入

设计原则:
    - 反思报告只读 (不修改反思层状态)
    - 无反思报告时返回空输入 (机会检测不阻塞)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReflectionBridgeError(Exception):
    """反思桥接操作异常"""


class ReflectionBridge:
    """反思桥接 (Reflection Report → 创造输入)

    用法:
        bridge = ReflectionBridge(reflection_engine)
        report = bridge.latest_report()
    """

    def __init__(self, reflection_engine=None):
        self._lock = threading.RLock()
        self._engine = reflection_engine

    # ── 反思报告供给 ─────────────────────────────────────────────
    def latest_report(self) -> Dict[str, Any]:
        """最近一次 Reflection Report (只读)"""
        with self._lock:
            if self._engine is None:
                return self.empty_report()
            try:
                reports = self._engine._reports
                if reports:
                    return dict(reports[-1])
            except Exception as e:
                logger.warning(f"[ReflectionBridge] 读取反思报告失败: {e}")
            return self.empty_report()

    def latest_validated_report(self) -> Dict[str, Any]:
        """最近一次带验证反思报告 (只 CONFIRMED)"""
        with self._lock:
            if self._engine is None:
                return self.empty_report()
            try:
                reports = self._engine._reports
                if reports:
                    for r in reversed(reports):
                        if r.get("mode") == "rule_based":
                            return dict(r)
            except Exception as e:
                logger.warning(f"[ReflectionBridge] 读取反思报告失败: {e}")
            return self.empty_report()

    @staticmethod
    def empty_report() -> Dict[str, Any]:
        """空报告 (无反思结果时)"""
        return {
            "patterns": [],
            "failure_analyses": [],
            "suggestion": "",
            "risk": "low",
        }

    def patterns(self) -> List[Dict[str, Any]]:
        """有效模式列表"""
        return self.latest_report().get("patterns", []) or []

    def suggestion(self) -> str:
        """反思建议"""
        return str(self.latest_report().get("suggestion", "") or "")

    def failure_analyses(self) -> List[Dict[str, Any]]:
        """失败分析列表"""
        return (
            self.latest_report().get("failure_analyses", []) or []
        )

    def input_payload(self) -> Dict[str, Any]:
        """转换为机会检测输入"""
        report = self.latest_report()
        return {
            "patterns": report.get("patterns", []) or [],
            "failure_analyses": (
                report.get("failure_analyses", []) or []
            ),
            "suggestion": report.get("suggestion", ""),
            "risk": report.get("risk", "low"),
        }

    def stats(self) -> Dict[str, Any]:
        """桥接统计"""
        return {
            "mode": "rule_based",
            "reflection_connected": self._engine is not None,
            "report_available": bool(
                self.latest_report().get("report_id")
            ),
            "pattern_count": len(self.patterns()),
        }


__all__ = [
    "ReflectionBridge",
    "ReflectionBridgeError",
]
