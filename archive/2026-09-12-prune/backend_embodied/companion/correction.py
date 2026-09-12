"""
YHLZ Embodied AI V5.4 - 自我修正器 (Companion Self-Correction)

职责:
    - 自我修正: 执行失败 → 规则驱动调整 (换目标/换参数/换场景) → 再执行 (上限内)
    - 修正策略表: 失败原因 → 修正动作映射 (可配置, 可解释)
    - 修正审计: 每次修正记录 (原因/调整/结果)

数据模型:
    CorrectionRecord:
    {
        attempt, reason, adjustment, result,
    }

修正策略表 (可解释规则):
    - position_mismatch → 调整: 先移动靠近目标再执行
    - boundary_limit    → 调整: 缩短移动距离
    - object_missing    → 调整: 先扫描再执行
    - object_not_held   → 调整: 先拾取再放置
    - permission_denied → 调整: 无法修正 (权限问题)
    - unknown           → 调整: 重试 (原样)

设计原则:
    - 纯规则修正 (确定性, 禁止黑盒优化)
    - 只调整执行参数/顺序, 不修改策略内容
    - 修正必须经 Permission (执行仍走 run_goal)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CorrectionError(Exception):
    """自我修正操作异常"""


# 失败原因 → 修正动作 (可解释规则表)
CORRECTION_RULES: Dict[str, Dict[str, Any]] = {
    "position_mismatch": {
        "adjustment": "move_first",
        "reason": "位置不匹配: 先移动靠近目标再执行",
    },
    "boundary_limit": {
        "adjustment": "shorter_move",
        "reason": "边界限制: 缩短移动距离",
    },
    "object_missing": {
        "adjustment": "scan_first",
        "reason": "对象缺失: 先扫描环境再执行",
    },
    "object_not_held": {
        "adjustment": "pick_first",
        "reason": "对象未持有: 先拾取再放置",
    },
    "invalid_parameter": {
        "adjustment": "fix_parameters",
        "reason": "参数不合法: 修正参数后重试",
    },
    "permission_denied": {
        "adjustment": "no_correction",
        "reason": "权限拒绝: 无法自动修正 (需人工开启权限)",
    },
}

# 默认修正 (未知原因)
DEFAULT_CORRECTION: Dict[str, Any] = {
    "adjustment": "retry",
    "reason": "未知原因: 原样重试",
}


class SelfCorrector:
    """自我修正器 (失败 → 规则调整 → 再执行)

    用法:
        corrector = SelfCorrector(svc, max_attempts=3)
        result = corrector.correct(request)
    """

    def __init__(
        self,
        svc,
        max_attempts: int = 3,
        strict: bool = False,
        learner=None,
    ):
        if max_attempts <= 0:
            raise CorrectionError(
                f"max_attempts 必须 > 0, 当前: {max_attempts}"
            )
        self._lock = threading.RLock()
        self._svc = svc
        self._max_attempts = int(max_attempts)
        self._strict = bool(strict)
        self._learner = learner
        self._records: List[Dict[str, Any]] = []

    # ── 修正策略查询 ──────────────────────────────────────────────
    @classmethod
    def rule_for(cls, cause: str) -> Dict[str, Any]:
        """失败原因 → 修正规则 (可解释)"""
        return CORRECTION_RULES.get(cause or "unknown",
                                    DEFAULT_CORRECTION)

    # ── 修正执行 ──────────────────────────────────────────────────
    def correct(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """自我修正入口: 执行失败 → 规则调整 → 再执行 (上限内)

        Args:
            request: 请求 dict (description/intent/target/scene 等)

        Returns:
            {
                'correction_id', 'success', 'attempts', 'max_attempts',
                'records': [CorrectionRecord...],
                'final_status', 'explainable_reason', 'mode': 'rule_based',
            }
        """
        with self._lock:
            if not isinstance(request, dict) or not request:
                raise CorrectionError("修正请求不能为空")
            records: List[Dict[str, Any]] = []
            current = dict(request)
            for attempt in range(1, self._max_attempts + 1):
                rec = self._execute(current)
                records.append(rec)
                if rec["result"].get("success"):
                    if self._learner is not None:
                        self._learner.record_success(
                            action=current.get("intent", ""),
                            scene=current.get("scene", ""),
                        )
                    return self._build_result(True, records, attempt,
                                              rec["result"].get("status"))
                # 失败 → 规则修正
                cause = rec["result"].get("error") or "unknown"
                cause = self._extract_cause(cause)
                if cause == "permission_denied" or "权限" in str(
                    rec["result"].get("error", "")
                ):
                    # 权限拒绝不可修正
                    if self._learner is not None:
                        self._learner.record_failure(
                            cause="permission_denied",
                            action=current.get("intent", ""),
                        )
                    return self._build_result(False, records, attempt,
                                              "denied")
                rule = self.rule_for(cause)
                if self._learner is not None:
                    self._learner.record_failure(
                        cause=cause,
                        action=current.get("intent", ""),
                        scene=current.get("scene", ""),
                    )
                if rule["adjustment"] == "no_correction":
                    return self._build_result(False, records, attempt,
                                              rec["result"].get("status"))
                # 应用修正
                adjusted = self._apply_adjustment(
                    current, rule["adjustment"],
                )
                records[-1]["adjustment"] = rule["adjustment"]
                records[-1]["reason"] = rule["reason"]
                current = adjusted
            return self._build_result(
                False, records, self._max_attempts,
                records[-1]["result"].get("status"),
            )

    # ── 执行单次 ──────────────────────────────────────────────────
    def _execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """单次执行 (经 run_goal)"""
        from backend.embodied.schema import EmbodiedGoal
        goal = EmbodiedGoal.create(
            description=request.get("description", request.get("text", "")),
            intent=request.get("intent", ""),
            target=request.get("target", ""),
            scene=request.get("scene", ""),
            constraints=dict(request.get("constraints", {}) or {}),
            priority=request.get("priority", "medium"),
        )
        try:
            result = self._svc.run_goal(goal)
            return {
                "attempt": 0,  # 由 correct 填充
                "reason": "",
                "adjustment": "",
                "result": {
                    "success": bool(result.success),
                    "status": result.status,
                    "error": result.error,
                },
            }
        except Exception as e:
            return {
                "attempt": 0,
                "reason": "",
                "adjustment": "",
                "result": {"success": False, "status": "error",
                           "error": str(e)},
            }

    # ── 修正应用 ──────────────────────────────────────────────────
    @staticmethod
    def _apply_adjustment(request: Dict[str, Any],
                          adjustment: str) -> Dict[str, Any]:
        """修正动作应用 (只调执行参数, 可解释)"""
        adjusted = dict(request)
        if adjustment == "move_first":
            adjusted["description"] = (
                f"先移动到{request.get('target', '目标')}附近, "
                f"然后{request.get('description', '')}"
            )
            adjusted["intent"] = "move " + request.get("intent", "")
        elif adjustment == "shorter_move":
            constraints = dict(request.get("constraints", {}) or {})
            constraints["shorter_move"] = True
            adjusted["constraints"] = constraints
        elif adjustment == "scan_first":
            adjusted["description"] = (
                f"先扫描环境, 然后{request.get('description', '')}"
            )
            adjusted["intent"] = "scan " + request.get("intent", "")
        elif adjustment == "pick_first":
            adjusted["description"] = (
                f"先拾取{request.get('target', '对象')}, 然后"
                f"{request.get('description', '')}"
            )
            adjusted["intent"] = "pick " + request.get("intent", "")
        elif adjustment == "fix_parameters":
            constraints = dict(request.get("constraints", {}) or {})
            constraints["retry_fixed"] = True
            adjusted["constraints"] = constraints
        return adjusted

    @staticmethod
    def _extract_cause(error: str) -> str:
        """从错误提取原因 (规则匹配)"""
        text = str(error or "").lower()
        # 权限拒绝 (中文/配置/英文)
        if ("权限" in text or "embodied_enabled" in text
                or "denied" in text or "permission" in text):
            return "permission_denied"
        for cause, rule in CORRECTION_RULES.items():
            if cause.replace("_", " ") in text or cause in text:
                return cause
        return "unknown"

    # ── 结果构造 ──────────────────────────────────────────────────
    def _build_result(self, success: bool, records: List[Dict[str, Any]],
                      attempts: int, final_status: str) -> Dict[str, Any]:
        # 填充 attempt 序号
        for i, rec in enumerate(records, 1):
            rec["attempt"] = i
        reason_lines = [
            f"自我修正: {attempts} 次尝试, "
            f"{'成功' if success else '未成功'} (最终状态 {final_status})",
        ]
        for rec in records:
            adj = rec.get("adjustment") or "无"
            reason_lines.append(
                f"  尝试{rec['attempt']}: {rec['result'].get('status')} "
                f"修正: {adj}"
            )
        result = {
            "correction_id": "corr_" + uuid.uuid4().hex[:8],
            "success": success,
            "attempts": attempts,
            "max_attempts": self._max_attempts,
            "records": records,
            "final_status": final_status,
            "explainable_reason": "\n".join(reason_lines),
            "mode": "rule_based",
        }
        self.record_audit(result)
        return result

    # ── 修正审计 ──────────────────────────────────────────────────
    def audit(self, limit: int = 50) -> Dict[str, Any]:
        """修正审计 (最近修正记录)"""
        with self._lock:
            records = list(self._records)
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": len(records),
            "recent": recent,
        }

    def record_audit(self, result: Dict[str, Any]) -> None:
        """记录修正结果 (供审计)"""
        with self._lock:
            self._records.append({
                "correction_id": result.get("correction_id"),
                "success": result.get("success"),
                "attempts": result.get("attempts"),
                "final_status": result.get("final_status"),
                "timestamp": time.time(),
            })

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "max_attempts": self._max_attempts,
                "strict": self._strict,
            }


__all__ = [
    "CORRECTION_RULES",
    "CorrectionError",
    "SelfCorrector",
]
