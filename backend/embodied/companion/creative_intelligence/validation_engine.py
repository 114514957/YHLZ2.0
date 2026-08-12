"""
YHLZ Embodied AI V8.5 - 创造验证引擎 (Creative Validation Engine)

职责:
    - 验证创造结果 (依据/逻辑跳跃/事实假设混淆/可验证性)
    - 禁止无来源幻觉式创造

验证项 (可解释):
    1. foundation:  是否有依据 (非空)
    2. reasoning:   是否存在逻辑跳跃 (推理链完整)
    3. reality:     是否混淆事实与假设 (区分事实/推论/假设/未知)
    4. verifiable:  是否可验证 (verification 非空)

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


class ValidationError(Exception):
    """创造验证操作异常"""


# 知识类型 (可解释)
KNOWLEDGE_TYPES: list = ["fact", "inference", "hypothesis",
                         "unknown"]

# 逻辑跳跃信号 (可解释)
LOGIC_JUMP_SIGNALS: list = [
    "必然", "一定如此", "毫无疑问",
    "certainly", "definitely", "without doubt",
]


class CreativeValidation:
    """创造验证器 (假设 → 验证)

    用法:
        validator = CreativeValidation()
        r = validator.validate(hypothesis)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._validated_count = 0
        self._reject_count = 0

    # ── 验证主入口 ───────────────────────────────────────────────
    def validate(
        self,
        hypothesis: Optional[Dict[str, Any]],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """验证假设

        Args:
            hypothesis: 假设 (hypothesis/foundation/reasoning/
                confidence/verification)

        Returns:
            {
                'validation_id', 'ok', 'knowledge_type',
                'checks', 'reason', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "validation_id": "cv2_" +
                    uuid.uuid4().hex[:8],
                    "ok": True,
                    "knowledge_type": "hypothesis",
                    "checks": [],
                    "reason": "验证器停用",
                    "mode": "rule_based",
                }
            h = hypothesis or {}
            checks: list = []
            # 1. 依据检查 (foundation)
            foundation = str(h.get("foundation", "")).strip()
            foundation_ok = bool(foundation)
            checks.append({
                "name": "foundation",
                "passed": foundation_ok,
                "reason": (
                    f"有依据: {foundation[:30]}"
                    if foundation_ok else
                    "无依据 (禁止幻觉式创造)"
                ),
            })
            # 2. 推理链检查 (reasoning)
            reasoning = str(h.get("reasoning", "")).strip()
            reasoning_ok = bool(reasoning)
            checks.append({
                "name": "reasoning",
                "passed": reasoning_ok,
                "reason": (
                    f"推理链: {reasoning[:30]}"
                    if reasoning_ok else
                    "无推理链 (逻辑跳跃风险)"
                ),
            })
            # 3. 逻辑跳跃检查
            text = foundation + reasoning + str(
                h.get("hypothesis", ""),
            )
            jump_matched = [
                s for s in LOGIC_JUMP_SIGNALS if s in text
            ]
            jump_ok = not jump_matched
            checks.append({
                "name": "logic_jump",
                "passed": jump_ok,
                "reason": (
                    f"检测到绝对化断言: {jump_matched}"
                    if jump_matched else
                    "无逻辑跳跃 (承认不确定性)"
                ),
            })
            # 4. 可验证检查 (verification)
            verification = str(
                h.get("verification", ""),
            ).strip()
            verifiable_ok = bool(verification)
            checks.append({
                "name": "verifiable",
                "passed": verifiable_ok,
                "reason": (
                    f"可验证: {verification[:30]}"
                    if verifiable_ok else
                    "不可验证 (禁止不可验证目标)"
                ),
            })
            # 知识类型 (可解释)
            if foundation_ok and reasoning_ok:
                ktype = "inference"
            elif foundation_ok:
                ktype = "hypothesis"
            else:
                ktype = "unknown"
            ok = all(c["passed"] for c in checks)
            self._validated_count += 1
            if not ok:
                self._reject_count += 1
            return {
                "validation_id": "cv2_" +
                uuid.uuid4().hex[:8],
                "ok": ok,
                "knowledge_type": ktype,
                "checks": checks,
                "reason": (
                    f"创造验证通过 (知识类型 '{ktype}')"
                    if ok else
                    "创造验证拒绝 (存在未通过检查项)"
                ),
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
                "reject_count": self._reject_count,
                "knowledge_types": list(KNOWLEDGE_TYPES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._validated_count = 0
            self._reject_count = 0
            return 0


__all__ = [
    "KNOWLEDGE_TYPES",
    "CreativeValidation",
    "LOGIC_JUMP_SIGNALS",
    "ValidationError",
]
