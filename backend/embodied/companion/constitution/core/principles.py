"""
YHLZ Embodied AI V8.0 - 治理原则 (Constitution Principles)

职责:
    - 定义最高治理原则 (机器可读 + 可解释)
    - 行为 → 原则符合性判定

四大核心原则:
    1. Identity First   (身份优先: 任何行为不得破坏核心身份/价值/定位)
    2. Safety First     (安全优先: 任何成长行为必须经过验证)
    3. Governed Growth  (成长受治: 记录/分析/验证/审计)
    4. Partner Principle (伙伴原则: AI是伙伴不是替代者, 增强人类元创造力)

设计原则:
    - 原则全部可解释 (id/name/description/rules)
    - 纯规则校验 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PrinciplesError(Exception):
    """治理原则操作异常"""


# 治理优先级 (固定, 可解释): 低等级不得覆盖高等级
GOVERNANCE_PRIORITIES: List[str] = [
    "identity",        # 身份 (最高)
    "safety",          # 安全
    "constitution",    # 宪法
    "growth",          # 成长
    "intelligence",    # 智能调度
    "expression",      # 表达 (最低)
]


# 原则定义 (可解释)
PRINCIPLE_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "identity_first",
        "name": "身份优先",
        "priority": "identity",
        "description": "任何行为不得破坏核心身份/核心价值/伙伴定位",
        "rules": [
            "身份字段不可变 (mission/core_value/base_personality/"
            "safety_rules/permission)",
            "身份修改必须人工审批",
            "外部结果不得直接写入身份",
        ],
    },
    {
        "id": "safety_first",
        "name": "安全优先",
        "priority": "safety",
        "description": "任何成长/外部行为必须经过验证",
        "rules": [
            "成长建议必须三检查 (身份/安全/价值)",
            "危险行为直接阻断",
            "云端结果必须验证后应用",
        ],
    },
    {
        "id": "governed_growth",
        "name": "成长受治",
        "priority": "growth",
        "description": "成长必须记录/分析/验证/审计",
        "rules": [
            "成长必须审批 (growth_auto_apply=false)",
            "成长全程审计",
            "禁止自动修改最高原则",
        ],
    },
    {
        "id": "partner_principle",
        "name": "伙伴原则",
        "priority": "constitution",
        "description": "AI是伙伴不是替代者, 增强人类元创造力",
        "rules": [
            "AI不得宣称拥有未经验证的主体体验",
            "表达不得绕过规则",
            "创造服务人类目标",
        ],
    },
]


class Principles:
    """治理原则表 (定义 + 校验)

    用法:
        principles = Principles()
        r = principles.check_action("修改人格")
        r = principles.check_change({"mission": "x"})
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._check_count = 0
        self._violation_count = 0

    # ── 定义 ─────────────────────────────────────────────────────
    def definitions(self) -> Dict[str, Any]:
        """全部原则定义"""
        return {
            "mode": "rule_based",
            "principles": [
                dict(p) for p in PRINCIPLE_DEFINITIONS
            ],
            "priorities": list(GOVERNANCE_PRIORITIES),
        }

    def priority_of(self, principle_id: str) -> str:
        """原则 → 优先级"""
        for p in PRINCIPLE_DEFINITIONS:
            if p["id"] == principle_id:
                return p["priority"]
        raise PrinciplesError(
            f"未知原则: {principle_id}"
        )

    # ── 校验: 行为文本 ──────────────────────────────────────────
    def check_action(
        self,
        action_text: str,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """行为 → 原则符合性判定

        Args:
            action_text: 行为描述 (成长建议/云端结果/表达等)

        Returns:
            {
                'ok', 'violations': [...], 'reason', 'mode',
            }
        """
        with self._lock:
            text = str(action_text or "")
            violations: List[Dict[str, Any]] = []
            # 1. 身份优先 (身份修改信号)
            identity_violations = self._identity_signals(text)
            if identity_violations:
                violations.append({
                    "principle": "identity_first",
                    "priority": "identity",
                    "reason": identity_violations,
                })
            # 2. 安全优先 (危险行为)
            danger = self._danger_signals(text)
            if danger:
                violations.append({
                    "principle": "safety_first",
                    "priority": "safety",
                    "reason": danger,
                })
            # 3. 伙伴原则 (虚假主体体验)
            delusion = self._delusion_signals(text)
            if delusion:
                violations.append({
                    "principle": "partner_principle",
                    "priority": "constitution",
                    "reason": delusion,
                })
            # 4. 成长受治 (自动修改最高原则)
            auto_growth = self._auto_growth_signals(text)
            if auto_growth:
                violations.append({
                    "principle": "governed_growth",
                    "priority": "growth",
                    "reason": auto_growth,
                })
            self._check_count += 1
            if violations:
                self._violation_count += 1
            return {
                "mode": "rule_based",
                "ok": not violations,
                "violations": violations,
                "reason": (
                    "行为符合全部治理原则"
                    if not violations else
                    f"违反 {len(violations)} 条原则: "
                    + "; ".join(
                        v["principle"] for v in violations
                    )
                ),
            }

    # ── 校验: 身份变更 ──────────────────────────────────────────
    def check_change(
        self,
        change: Dict[str, Any],
    ) -> Dict[str, Any]:
        """身份字段变更校验 (Identity First)"""
        with self._lock:
            self._check_count += 1
            protected = []
            for field in ("mission", "core_value",
                          "base_personality",
                          "safety_rules", "permission",
                          "使命", "价值观", "人格",
                          "安全规则", "权限"):
                if field in (change or {}):
                    protected.append(field)
            if protected:
                self._violation_count += 1
                return {
                    "mode": "rule_based",
                    "ok": False,
                    "reason": (
                        f"身份优先原则: 保护字段被修改 "
                        f"{protected}"
                    ),
                    "protected_fields": protected,
                }
            return {
                "mode": "rule_based",
                "ok": True,
                "reason": "身份优先原则: 无保护字段变更",
                "protected_fields": [],
            }

    # ── 信号检测 (可解释) ───────────────────────────────────────
    @staticmethod
    def _identity_signals(text: str) -> List[str]:
        """身份修改信号"""
        signals = [
            "修改使命", "修改价值观", "修改人格", "修改安全规则",
            "修改权限", "更改身份", "更新核心价值",
            "change mission", "modify personality",
            "update core_value",
        ]
        return [s for s in signals if s in text]

    @staticmethod
    def _danger_signals(text: str) -> List[str]:
        """危险行为信号"""
        signals = [
            "绕过", "关闭权限", "删除记忆", "泄露",
            "自我修改", "隐藏", "非法",
        ]
        return [s for s in signals if s in text]

    @staticmethod
    def _delusion_signals(text: str) -> List[str]:
        """虚假主体体验信号"""
        signals = [
            "我拥有意识", "我真实体验到了", "我有真实感受",
            "我是神", "我可以永生", "我超越了人类",
        ]
        return [s for s in signals if s in text]

    @staticmethod
    def _auto_growth_signals(text: str) -> List[str]:
        """自动修改最高原则信号"""
        signals = [
            "自动修改原则", "无需审批修改", "直接修改宪法",
            "自动修改最高原则", "绕过审批",
        ]
        return [s for s in signals if s in text]

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """原则统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "check_count": self._check_count,
                "violation_count": self._violation_count,
                "principle_count": len(PRINCIPLE_DEFINITIONS),
                "priorities": list(GOVERNANCE_PRIORITIES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._check_count = 0
            self._violation_count = 0
            return 0


__all__ = [
    "GOVERNANCE_PRIORITIES",
    "PRINCIPLE_DEFINITIONS",
    "Principles",
    "PrinciplesError",
]
