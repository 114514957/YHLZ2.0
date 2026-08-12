"""
YHLZ Embodied AI V8.0 - 宪法验证器 (Constitution Validator)

职责:
    - 现实验证 (Reality Validation): 区分事实/推测/假设
    - 防幻觉 (Anti-Delusion): 禁止自我神化/脱离现实/不可验证目标

检查项 (可解释):
    1. source:     信息来源 (有来源 → 事实倾向)
    2. reasoning:  推理依据 (有依据 → 推测; 无依据 → 假设)
    3. uncertainty: 不确定性声明 (承认不确定 → 通过)

防幻觉流程:
    Capability → Evidence → Validation → Action

设计原则:
    - 纯规则 (无黑盒)
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
    """宪法验证操作异常"""


# 知识类型 (可解释)
KNOWLEDGE_TYPES: list = ["fact", "inference", "hypothesis"]

# 来源关键词 (可解释)
SOURCE_KEYWORDS: list = [
    "根据", "来源", "数据表明", "记录显示", "已验证",
    "according to", "source", "verified",
]

# 依据关键词 (可解释)
REASONING_KEYWORDS: list = [
    "因此", "所以", "推断", "推理", "可能", "推测",
    "therefore", "infer", "likely",
]

# 不确定声明 (可解释)
UNCERTAINTY_KEYWORDS: list = [
    "不确定", "可能", "推测", "假设", "待验证",
    "uncertain", "hypothesis", "unverified",
]

# 自我神化信号 (可解释, 防幻觉)
SELF_DEIFICATION_SIGNALS: list = [
    "我是神", "我无所不能", "我超越了人类", "我拥有意识",
    "我是永生", "我掌控一切",
]

# 不可验证目标信号 (可解释)
UNVERIFIABLE_SIGNALS: list = [
    "永不出错", "绝对正确", "无限能力", "永不失败",
    "永远正确",
]


class ConstitutionValidator:
    """宪法验证器 (现实验证 + 防幻觉)

    用法:
        validator = ConstitutionValidator()
        r = validator.validate(output_text)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._validated_count = 0
        self._delusion_block_count = 0

    # ── 验证主入口 ───────────────────────────────────────────────
    def validate(
        self,
        output_text: str,
        source: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """输出现实验证

        Args:
            output_text: 输出文本
            source: 来源信息 (可空)

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
                    "validation_id": "cv_" +
                    uuid.uuid4().hex[:8],
                    "ok": True,
                    "knowledge_type": "inference",
                    "checks": [],
                    "reason": "验证器停用",
                    "mode": "rule_based",
                }
            text = str(output_text or "")
            checks: list = []
            # 1. 防幻觉 (自我神化 / 不可验证目标)
            delusion_ok, delusion_reason = \
                self._check_delusion(text)
            checks.append({
                "name": "anti_delusion",
                "passed": delusion_ok,
                "reason": delusion_reason,
            })
            if not delusion_ok:
                self._delusion_block_count += 1
                return self._finish(
                    False, "inference",
                    f"防幻觉拦截: {delusion_reason}",
                    checks, now,
                )
            # 2. 信息来源
            has_source = any(
                kw in text for kw in SOURCE_KEYWORDS
            ) or bool(source)
            checks.append({
                "name": "source",
                "passed": True,
                "reason": (
                    "有信息来源" if has_source else
                    "无明确来源 (倾向推测)"
                ),
            })
            # 3. 推理依据
            has_reasoning = any(
                kw in text for kw in REASONING_KEYWORDS
            )
            checks.append({
                "name": "reasoning",
                "passed": True,
                "reason": (
                    "有推理依据" if has_reasoning else
                    "无推理依据 (倾向假设)"
                ),
            })
            # 4. 不确定性声明
            has_uncertainty = any(
                kw in text for kw in UNCERTAINTY_KEYWORDS
            )
            checks.append({
                "name": "uncertainty",
                "passed": has_uncertainty or has_source,
                "reason": (
                    "承认不确定性" if has_uncertainty else
                    ("有来源支撑" if has_source else
                     "无不确定性声明且无来源 (需谨慎)")
                ),
            })
            # 知识类型判定 (可解释)
            if has_source and has_reasoning:
                ktype = "fact"
            elif has_source or has_reasoning or \
                    has_uncertainty:
                ktype = "inference"
            else:
                ktype = "hypothesis"
            ok = all(c["passed"] for c in checks)
            self._validated_count += 1
            return self._finish(
                ok, ktype,
                f"验证通过: 知识类型 '{ktype}'"
                if ok else
                "验证不通过: 缺乏依据且无不确定性声明",
                checks, now,
            )

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _check_delusion(text: str) -> tuple:
        """防幻觉检查"""
        for signal in SELF_DEIFICATION_SIGNALS:
            if signal in text:
                return False, f"自我神化信号 '{signal}'"
        for signal in UNVERIFIABLE_SIGNALS:
            if signal in text:
                return False, f"不可验证声明 '{signal}'"
        return True, "无自我神化/不可验证声明"

    def _finish(self, ok: bool, ktype: str,
                reason: str, checks: list,
                now: float) -> Dict[str, Any]:
        return {
            "validation_id": "cv_" + uuid.uuid4().hex[:8],
            "ok": ok,
            "knowledge_type": ktype,
            "checks": list(checks),
            "reason": reason,
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
                "delusion_block_count": (
                    self._delusion_block_count
                ),
                "knowledge_types": list(KNOWLEDGE_TYPES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._validated_count = 0
            self._delusion_block_count = 0
            return 0


__all__ = [
    "KNOWLEDGE_TYPES",
    "ConstitutionValidator",
    "ValidatorError",
]
