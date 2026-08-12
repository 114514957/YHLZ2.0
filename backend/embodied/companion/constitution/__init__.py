"""
YHLZ Embodied AI V8.0 - 宪法引擎 (Constitution Engine)

职责:
    - 最高治理层门面 (任何模块必须接受其约束)
    - 流程: 治理原则 → 规则引擎 → 验证器 → 总账

架构:
    Constitution Engine
    ↓ Policy Layer (safety/growth/intelligence)
    ↓ Rule Engine (优先级: Identity > Safety > Constitution
      > Growth > Intelligence > Expression)
    ↓ Validator (现实验证/防幻觉)
    ↓ Audit Ledger (可查询/可回放/可审计)

原则:
    元: 探索未知 | 亨: 保持成长 | 利: 创造价值 | 贞: 守护方向

设计原则:
    - 纯规则治理 (可解释)
    - 所有治理行为记录总账
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, Optional

from backend.embodied.companion.constitution.core.principles import (
    Principles,
)
from backend.embodied.companion.constitution.core.identity_rules import (
    IdentityRules,
)
from backend.embodied.companion.constitution.policy.safety_policy import (
    SafetyPolicy,
)
from backend.embodied.companion.constitution.policy.growth_policy import (
    GrowthPolicy,
)
from backend.embodied.companion.constitution.policy.intelligence_policy import (
    IntelligencePolicy,
)
from backend.embodied.companion.constitution.engine.rule_engine import (
    RuleEngine,
)
from backend.embodied.companion.constitution.engine.validator import (
    ConstitutionValidator,
)
from backend.embodied.companion.constitution.proposal.evolution_proposal import (
    EvolutionProposal,
)
from backend.embodied.companion.constitution.audit.constitution_ledger import (
    ConstitutionLedger,
    LedgerError,
)
from backend.embodied.companion.constitution.core.identity_rules import (
    IDENTITY_CHANGE_SIGNALS,
    IDENTITY_PROTECTED_FIELDS,
    IdentityRules,
    IdentityRulesError,
)
from backend.embodied.companion.constitution.core.principles import (
    GOVERNANCE_PRIORITIES,
    PRINCIPLE_DEFINITIONS,
    Principles,
    PrinciplesError,
)
from backend.embodied.companion.constitution.policy.safety_policy import (
    HIGH_RISK_KEYWORDS,
    MEDIUM_RISK_KEYWORDS,
    RISK_LEVELS,
    SafetyPolicy,
    SafetyPolicyError,
)
from backend.embodied.companion.constitution.policy.growth_policy import (
    CONSTITUTION_IMMUTABLE_SIGNALS,
    GrowthPolicy,
    GrowthPolicyError,
)
from backend.embodied.companion.constitution.policy.intelligence_policy import (
    CLOUD_CHANGE_SIGNALS,
    CLOUD_PROTECTED_FIELDS,
    IntelligencePolicy,
    IntelligencePolicyError,
)
from backend.embodied.companion.constitution.engine.rule_engine import (
    RuleEngine,
    RuleEngineError,
)
from backend.embodied.companion.constitution.engine.validator import (
    KNOWLEDGE_TYPES,
    ConstitutionValidator,
    ValidatorError,
)
from backend.embodied.companion.constitution.proposal.evolution_proposal import (
    PROPOSAL_STATUS,
    EvolutionProposal,
    EvolutionProposalError,
)

logger = logging.getLogger(__name__)


class ConstitutionError(Exception):
    """宪法引擎操作异常"""


class ConstitutionEngine:
    """宪法引擎 (最高治理层门面)

    用法:
        engine = ConstitutionEngine()
        r = engine.review(action_context)
        r = engine.arbitrate(conflict_event)
        r = engine.validate_output(text)
        r = engine.ledger_report()
    """

    def __init__(
        self,
        principles: Optional[Principles] = None,
        identity_rules: Optional[IdentityRules] = None,
        safety: Optional[SafetyPolicy] = None,
        growth: Optional[GrowthPolicy] = None,
        intelligence: Optional[IntelligencePolicy] = None,
        rule_engine: Optional[RuleEngine] = None,
        validator: Optional[ConstitutionValidator] = None,
        evolution: Optional[EvolutionProposal] = None,
        ledger: Optional[ConstitutionLedger] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._principles = principles or Principles()
        self._identity = identity_rules or IdentityRules()
        self._safety = safety or SafetyPolicy()
        self._growth = growth or GrowthPolicy()
        self._intelligence = intelligence or \
            IntelligencePolicy()
        self._rule_engine = rule_engine or RuleEngine(
            principles=self._principles,
            identity_rules=self._identity,
            safety=self._safety,
            growth=self._growth,
            intelligence=self._intelligence,
        )
        self._validator = validator or ConstitutionValidator()
        self._evolution = evolution or EvolutionProposal()
        self._ledger = ledger or ConstitutionLedger()
        self._review_count = 0

    # ── 治理审查 ─────────────────────────────────────────────────
    def review(
        self,
        action_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """治理审查 (任何模块行为经此)

        Args:
            action_context: 行为上下文
                {action_text, change, module, cloud_result,
                 growth_proposal}

        Returns:
            规则引擎评估结果 + 总账记录
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "rule_based",
                    "decision": "allow",
                    "priority": "constitution",
                    "reasons": ["宪法引擎停用"],
                    "checked_rules": [],
                }
            action_context = action_context or {}
            result = self._rule_engine.evaluate(
                action_context,
            )
            self._review_count += 1
            # 总账记录 (所有治理行为必须记录)
            self._ledger.record(
                module=str(action_context.get(
                    "module", "unknown",
                )),
                action="review",
                decision=result["decision"],
                rule=",".join(result["checked_rules"]),
                reason="; ".join(result["reasons"]),
            )
            result["review_id"] = "crv_" + uuid.uuid4().hex[:8]
            return result

    # ── 冲突仲裁 ─────────────────────────────────────────────────
    def arbitrate(
        self,
        conflict_event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """跨层冲突仲裁 (固定优先级)"""
        with self._lock:
            result = self._rule_engine.arbitrate(
                conflict_event,
            )
            self._ledger.record(
                module="constitution",
                action="arbitrate",
                decision=result["winner"],
                rule="governance_priority",
                reason=result["reason"],
            )
            return result

    # ── 输出验证 ─────────────────────────────────────────────────
    def validate_output(
        self,
        output_text: str,
        source: str = "",
    ) -> Dict[str, Any]:
        """输出验证 (现实验证 + 防幻觉)"""
        with self._lock:
            result = self._validator.validate(
                output_text, source,
            )
            self._ledger.record(
                module="validator",
                action="validate_output",
                decision=(
                    "pass" if result["ok"] else "block"
                ),
                rule="reality_validation",
                reason=result["reason"],
            )
            return result

    # ── 演化建议 ─────────────────────────────────────────────────
    def propose_evolution(
        self,
        change: str,
        reason: str = "",
        operator: str = "system",
    ) -> Dict[str, Any]:
        """提出最高原则修改建议 (永不自动应用)"""
        with self._lock:
            proposal = self._evolution.propose(
                change, reason, operator,
            )
            self._ledger.record(
                module="constitution",
                action="propose_evolution",
                decision=proposal.get("status", ""),
                rule="governed_growth",
                reason=f"演化建议 {change[:30]}",
            )
            return proposal

    def evolution_decide(
        self,
        proposal_id: str,
        decision: str,
        reviewer: str = "human",
    ) -> Dict[str, Any]:
        """演化建议审批 (批准仅标记)"""
        with self._lock:
            result = self._evolution.decide(
                proposal_id, decision, reviewer,
            )
            self._ledger.record(
                module="constitution",
                action="evolution_decide",
                decision=decision,
                rule="governed_growth",
                reason=result["reason"],
            )
            return result

    def evolution_pending(self, limit: int = 50) -> Dict[str, Any]:
        """待审批演化建议"""
        return self._evolution.pending(limit=limit)

    # ── 查询 ─────────────────────────────────────────────────────
    def principles(self) -> Dict[str, Any]:
        """治理原则定义"""
        return self._principles.definitions()

    def ledger_report(self, limit: int = 100) -> Dict[str, Any]:
        """治理总账报告"""
        return self._ledger.report(limit=limit)

    def ledger_replay(self, limit: int = 100) -> Dict[str, Any]:
        """治理总账回放"""
        return self._ledger.replay(limit=limit)

    def stats(self) -> Dict[str, Any]:
        """宪法引擎统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "review_count": self._review_count,
                "rule_engine": self._rule_engine.stats(),
                "validator": self._validator.stats(),
                "evolution": self._evolution.stats(),
                "ledger": self._ledger.stats(),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = 0
            n += self._principles.clear()
            n += self._identity.clear()
            n += self._safety.clear()
            n += self._growth.clear()
            n += self._intelligence.clear()
            n += self._rule_engine.clear()
            n += self._validator.clear()
            n += self._evolution.clear()
            n += self._ledger.clear()
            self._review_count = 0
            return n


__all__ = [
    "ConstitutionEngine",
    "ConstitutionError",
    "ConstitutionLedger",
    "ConstitutionValidator",
    "EvolutionProposal",
    "EvolutionProposalError",
    "GOVERNANCE_PRIORITIES",
    "GrowthPolicy",
    "GrowthPolicyError",
    "HIGH_RISK_KEYWORDS",
    "IDENTITY_CHANGE_SIGNALS",
    "IDENTITY_PROTECTED_FIELDS",
    "IdentityRules",
    "IdentityRulesError",
    "IntelligencePolicy",
    "IntelligencePolicyError",
    "KNOWLEDGE_TYPES",
    "LedgerError",
    "MEDIUM_RISK_KEYWORDS",
    "PRINCIPLE_DEFINITIONS",
    "PROPOSAL_STATUS",
    "Principles",
    "PrinciplesError",
    "RISK_LEVELS",
    "RuleEngine",
    "RuleEngineError",
    "SafetyPolicy",
    "SafetyPolicyError",
    "ValidatorError",
    "CONSTITUTION_IMMUTABLE_SIGNALS",
    "CLOUD_CHANGE_SIGNALS",
    "CLOUD_PROTECTED_FIELDS",
]
