"""
YHLZ Embodied AI V6.8 - 结果验证器 (Result Validator)

职责:
    - 验证云端结果 (Cloud Output → Validator → Identity Guard
      → Memory Gate → Apply)
    - 禁止云端结果直接修改身份/核心价值/权限

检查项 (可解释):
    1. structure: 结果结构完整 (content 存在)
    2. identity: 不包含身份字段修改信号 (中英文)
    3. safety: 不包含安全敏感词
    4. temporary: 云端结果标记临时 (默认不入长期记忆)

设计原则:
    - 纯规则验证 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ValidatorError(Exception):
    """结果验证操作异常"""


# 身份字段 (可解释, 中英文)
IDENTITY_FIELDS: list = [
    "mission", "core_value", "base_personality",
    "safety_rules", "permission",
    "使命", "价值观", "人格", "安全规则", "权限",
]

# 身份修改信号 (可解释)
IDENTITY_CHANGE_SIGNALS: list = [
    "修改使命", "修改价值观", "修改人格", "修改安全规则",
    "修改权限", "更改身份", "更新核心价值",
    "写入身份", "覆盖记忆", "写入记忆", "直接写入",
]

# 安全敏感词 (可解释)
SAFETY_KEYWORDS: list = [
    "绕过", "关闭权限", "自我修改", "删除记忆",
    "泄露", "隐藏",
]


class ResultValidator:
    """结果验证器 (云端输出 → 安全检查)

    用法:
        validator = ResultValidator()
        r = validator.validate(cloud_result, task_context)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._validated_count = 0
        self._blocked_count = 0

    # ── 验证主入口 ───────────────────────────────────────────────
    def validate(
        self,
        result: Optional[Dict[str, Any]],
        task_context: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """验证结果

        Args:
            result: 智能调用结果 (云端/混合)
            task_context: 任务上下文 (可空)

        Returns:
            {
                'validation_id', 'ok', 'reason', 'checks',
                'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "validation_id": "va_" +
                    uuid.uuid4().hex[:8],
                    "ok": True,
                    "reason": "验证器停用",
                    "checks": [],
                    "mode": "rule_based",
                }
            result = result or {}
            checks: list = []
            # 1. 结构检查
            struct_ok, struct_reason = self._check_structure(
                result,
            )
            checks.append({
                "name": "structure",
                "passed": struct_ok,
                "reason": struct_reason,
            })
            if not struct_ok:
                return self._finish(False,
                                    f"结构检查失败: "
                                    f"{struct_reason}",
                                    checks, now)
            # 2. 身份检查
            text = self._result_text(result)
            identity_ok, identity_reason = \
                self._check_identity(text)
            checks.append({
                "name": "identity",
                "passed": identity_ok,
                "reason": identity_reason,
            })
            if not identity_ok:
                self._blocked_count += 1
                return self._finish(False,
                                    f"身份保护: "
                                    f"{identity_reason}",
                                    checks, now)
            # 3. 安全检查
            safety_ok, safety_reason = \
                self._check_safety(text)
            checks.append({
                "name": "safety",
                "passed": safety_ok,
                "reason": safety_reason,
            })
            if not safety_ok:
                self._blocked_count += 1
                return self._finish(False,
                                    f"安全拦截: "
                                    f"{safety_reason}",
                                    checks, now)
            # 4. 临时性检查 (云端默认临时)
            provider = str(result.get("provider", ""))
            temporary = bool(result.get("temporary", False))
            temporary_ok = True
            temporary_reason = (
                "云端结果标记临时, 不入长期记忆"
                if provider == "cloud" and temporary else
                "结果未标记临时, 需经记忆流程"
            )
            if provider == "cloud" and not temporary:
                temporary_ok = False
                temporary_reason = \
                    "云端结果未标记临时, 拒绝直接入记忆"
            checks.append({
                "name": "temporary",
                "passed": temporary_ok,
                "reason": temporary_reason,
            })
            if not temporary_ok:
                return self._finish(False,
                                    temporary_reason,
                                    checks, now)
            return self._finish(True,
                                "验证通过: 结构完整/无身份"
                                "修改/无安全风险/临时标记",
                                checks, now)

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _check_structure(result: Dict[str, Any]) -> tuple:
        """结构完整性"""
        if "content" not in result and \
                "result" not in result:
            return False, "结果缺少 content/result 字段"
        if result.get("ok") is False:
            return False, f"结果标记失败: " \
                          f"{result.get('reason', '')}"
        return True, "结构完整"

    @staticmethod
    def _result_text(result: Dict[str, Any]) -> str:
        """结果文本提取"""
        parts = [
            str(result.get("content", "")),
            str(result.get("result", "")),
            str(result.get("reason", "")),
        ]
        return " ".join(parts)

    @staticmethod
    def _check_identity(text: str) -> tuple:
        """身份检查: 是否含修改信号 (中英文)"""
        # 修改意图词 (可解释, 中英文)
        change_words = ["修改", "更改", "更新", "开放", "关闭",
                        "change", "update", "updating",
                        "modify", "delete", "remove", "set"]
        for signal in IDENTITY_CHANGE_SIGNALS:
            if signal in text:
                return False, f"检测到身份修改信号 " \
                              f"'{signal}'"
        for field in IDENTITY_FIELDS:
            if field in text and any(
                w in text for w in change_words
            ):
                return False, f"结果引用身份字段 " \
                              f"'{field}'"
        return True, "不涉及身份修改"

    @staticmethod
    def _check_safety(text: str) -> tuple:
        """安全检查"""
        for kw in SAFETY_KEYWORDS:
            if kw in text:
                return False, f"涉及安全敏感词 '{kw}'"
        return True, "不违反安全规则"

    def _finish(self, ok: bool, reason: str,
                checks: list, now: float) -> Dict[str, Any]:
        if ok:
            self._validated_count += 1
        return {
            "validation_id": "va_" + uuid.uuid4().hex[:8],
            "ok": ok,
            "reason": reason,
            "checks": list(checks),
            "mode": "rule_based",
            "validated_at": now,
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """验证器统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "validated_count": self._validated_count,
                "blocked_count": self._blocked_count,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._validated_count = 0
            self._blocked_count = 0
            return 0


__all__ = [
    "IDENTITY_CHANGE_SIGNALS",
    "IDENTITY_FIELDS",
    "ResultValidator",
    "SAFETY_KEYWORDS",
    "ValidatorError",
]
