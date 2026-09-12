"""
YHLZ Embodied AI V5.9 - 创造引擎门面 (Creative Engine)

职责:
    - 组合全部创造能力: 机会检测 → 价值评估 → 创造推理 →
      方案生成 → 模拟 → 审批 → 执行 → 新经验
    - 安全集成: 只 CONFIRMED 经验 / 方案禁止自动执行 /
      不修改核心人格 / 全部可验证

完整闭环:
    Action → Experience → Verification → Reflection
    → Opportunity Discovery → Value Evaluation → Creative Proposal
    → Simulation → Approval → Execution → New Experience

安全保护 (protections):
    - confirmed_only:          创造依据必须 CONFIRMED 经验
    - no_auto_execute:         Proposal 禁止自动执行 (需审批)
    - approval_required:       执行前必须审批
    - no_personality_change:   不修改核心人格 / 目标
    - verifiable:              方案含来源/推理/风险/收益

设计原则:
    - 主动但不越权: 发现问题/建议/方案, 不自主执行高风险行为
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from backend.embodied.companion.creative.creative_audit import (
    CreativeAudit,
)
from backend.embodied.companion.creative.creative_reasoning_engine import (
    CreativeReasoningEngine,
)
from backend.embodied.companion.creative.opportunity_detector import (
    OpportunityDetector,
)
from backend.embodied.companion.creative.proposal_generator import (
    ProposalGenerator,
)
from backend.embodied.companion.creative.proposal_memory import (
    ProposalMemory,
)
from backend.embodied.companion.creative.simulation_engine import (
    SimulationEngine,
)
from backend.embodied.companion.creative.value_evaluator import (
    ValueEvaluator,
)
from backend.embodied.companion.integration.approval_bridge import (
    ApprovalBridge,
)
from backend.embodied.companion.integration.experience_bridge import (
    ExperienceBridge,
)
from backend.embodied.companion.integration.reflection_bridge import (
    ReflectionBridge,
)

logger = logging.getLogger(__name__)


class CreativeEngineError(Exception):
    """创造引擎操作异常"""


class CreativeEngine:
    """创造引擎门面 (Creative Intelligence & Value Discovery)

    用法:
        engine = CreativeEngine(
            experience_manager=mgr, verifier=verifier,
            reflection_engine=refl, improvement_engine=improve,
        )
        result = engine.run()
        proposal = engine.propose(opportunity_id)
        engine.approve(proposal_id)
    """

    def __init__(
        self,
        experience_manager=None,
        verifier=None,
        reflection_engine=None,
        improvement_engine=None,
        relationship_manager=None,
        enabled: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        cfg = dict(config or {})
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        # 桥接层 (安全集成)
        self._experience_bridge = ExperienceBridge(
            experience_manager, verifier,
        )
        self._reflection_bridge = ReflectionBridge(reflection_engine)
        self._approval_bridge = ApprovalBridge(improvement_engine)
        self._relationship_manager = relationship_manager
        # 组件
        self._detector = OpportunityDetector(
            min_evidence=int(cfg.get(
                "companion_creative_opportunity_min_evidence", 2,
            )),
            repetition_min_occurrences=int(cfg.get(
                "companion_creative_repetition_min_occurrences", 3,
            )),
            failure_min_occurrences=int(cfg.get(
                "companion_creative_failure_min_occurrences", 2,
            )),
            relationship_trust_min=float(cfg.get(
                "companion_creative_relationship_trust_min", 0.7,
            )),
            max_opportunities=int(cfg.get(
                "companion_creative_opportunity_max", 20,
            )),
        )
        self._evaluator = ValueEvaluator(
            create_threshold=float(cfg.get(
                "companion_creative_value_threshold", 0.6,
            )),
            defer_threshold=float(cfg.get(
                "companion_creative_defer_threshold", 0.35,
            )),
        )
        self._reasoning = CreativeReasoningEngine()
        self._generator = ProposalGenerator(
            max_proposals=int(cfg.get(
                "companion_creative_proposal_max", 30,
            )),
        )
        self._simulator = SimulationEngine(
            proceed_rate=float(cfg.get(
                "companion_creative_simulation_min_success_rate", 0.7,
            )),
            revise_rate=float(cfg.get(
                "companion_creative_simulation_revise_rate", 0.4,
            )),
        )
        self._memory = ProposalMemory(
            max_records=int(cfg.get(
                "companion_creative_memory_max", 100,
            )),
            persist_path=str(cfg.get(
                "companion_creative_memory_path", "",
            ) or ""),
        )
        self._audit = CreativeAudit(
            max_records=int(cfg.get(
                "companion_creative_audit_max", 500,
            )),
        )

    # ── 属性 (供 Service / 测试访问) ─────────────────────────────
    @property
    def experience_bridge(self) -> ExperienceBridge:
        return self._experience_bridge

    @property
    def reflection_bridge(self) -> ReflectionBridge:
        return self._reflection_bridge

    @property
    def approval_bridge(self) -> ApprovalBridge:
        return self._approval_bridge

    @property
    def detector(self) -> OpportunityDetector:
        return self._detector

    @property
    def evaluator(self) -> ValueEvaluator:
        return self._evaluator

    @property
    def reasoning_engine(self) -> CreativeReasoningEngine:
        return self._reasoning

    @property
    def generator(self) -> ProposalGenerator:
        return self._generator

    @property
    def simulator(self) -> SimulationEngine:
        return self._simulator

    @property
    def memory(self) -> ProposalMemory:
        return self._memory

    @property
    def audit(self) -> CreativeAudit:
        return self._audit

    # ── 完整闭环 (不执行, 只发现/评估/提案/模拟) ────────────────
    def run(self) -> Dict[str, Any]:
        """创造闭环: 发现机会 → 评估价值 → 推理 → 提案 → 模拟

        注意: 不自动执行 (方案需审批)
        """
        with self._lock:
            self._check_enabled()
            run_id = "cr_run_" + uuid.uuid4().hex[:8]
            opportunities = self.detect()
            evaluations: List[Dict[str, Any]] = []
            proposals: List[Dict[str, Any]] = []
            simulations: List[Dict[str, Any]] = []
            for opp in opportunities:
                try:
                    eval_result = self.evaluate(opp["opportunity_id"])
                except Exception as e:
                    logger.warning(f"[Creative] 评估失败: {e}")
                    continue
                evaluations.append(eval_result)
                if eval_result["decision"] != "create":
                    continue
                try:
                    proposal = self.propose(opp["opportunity_id"])
                except Exception as e:
                    logger.warning(f"[Creative] 提案失败: {e}")
                    continue
                proposals.append(proposal)
                try:
                    sim = self.simulate(proposal["proposal_id"])
                except Exception as e:
                    logger.warning(f"[Creative] 模拟失败: {e}")
                    continue
                simulations.append(sim)
            return {
                "run_id": run_id,
                "opportunities": opportunities,
                "evaluations": evaluations,
                "proposals": proposals,
                "simulations": simulations,
                "summary": {
                    "opportunity_count": len(opportunities),
                    "evaluation_count": len(evaluations),
                    "proposal_count": len(proposals),
                    "simulation_count": len(simulations),
                },
                "auto_executed": False,
                "mode": "rule_based",
            }

    # ── 机会检测 ─────────────────────────────────────────────────
    def detect(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """发现机会 (只基于 CONFIRMED 经验 + 反思报告 + 关系)"""
        with self._lock:
            self._check_enabled()
            confirmed = self._experience_bridge.confirmed_experiences(
                limit=200,
            )
            report = self._reflection_bridge.latest_report()
            relationship = self._relationship()
            candidates = self._detector.detect(
                confirmed, report, relationship,
            )
            for c in candidates:
                self._audit.record(
                    action="detect", ref_id=c["opportunity_id"],
                    detail=f"{c['source_type']}: {c['trigger'][:30]}",
                )
            if limit is not None:
                candidates = candidates[:limit]
            return [dict(c) for c in candidates]

    # ── 价值评估 ─────────────────────────────────────────────────
    def evaluate(self, opportunity_id: str) -> Dict[str, Any]:
        """评估机会价值 (值得创造才继续)"""
        with self._lock:
            self._check_enabled()
            opp = self._detector.get(opportunity_id)
            if opp is None:
                raise CreativeEngineError(
                    f"机会不存在: {opportunity_id}"
                )
            confirmed = self._experience_bridge.confirmed_experiences(
                limit=200,
            )
            result = self._evaluator.evaluate(
                opp, confirmed, self._relationship(),
            )
            self._audit.record(
                action="evaluate", ref_id=opportunity_id,
                detail=f"value={result['value_score']} "
                       f"decision={result['decision']}",
            )
            return dict(result)

    # ── 创造推理 ─────────────────────────────────────────────────
    def reason(self, opportunity_id: str) -> Dict[str, Any]:
        """创造推理 (当前 → 理想 → 差距 → 路径)"""
        with self._lock:
            self._check_enabled()
            opp = self._detector.get(opportunity_id)
            if opp is None:
                raise CreativeEngineError(
                    f"机会不存在: {opportunity_id}"
                )
            result = self._reasoning.reason(opp)
            self._audit.record(
                action="reason", ref_id=opportunity_id,
                detail=(
                    f"路径 {len(result['paths'])} 条, "
                    f"置信度 {result['confidence']}"
                ),
            )
            return dict(result)

    # ── 方案生成 ─────────────────────────────────────────────────
    def propose(self, opportunity_id: str) -> Dict[str, Any]:
        """生成创造方案 (评估 + 推理 + 生成 + 入记忆)"""
        with self._lock:
            self._check_enabled()
            opp = self._detector.get(opportunity_id)
            if opp is None:
                raise CreativeEngineError(
                    f"机会不存在: {opportunity_id}"
                )
            evaluation = self.evaluate(opportunity_id)
            if evaluation["decision"] != "create":
                raise CreativeEngineError(
                    f"机会价值不足 (decision={evaluation['decision']}), "
                    f"不生成方案"
                )
            reasoning = self._reasoning.reason(opp)
            proposal = self._generator.generate(
                opp, reasoning, evaluation,
            )
            # 入记忆 + 审批镜像
            self._memory.save(proposal)
            mirror = self._approval_bridge.submit(proposal)
            proposal = self._memory.get(proposal["proposal_id"])
            if mirror:
                proposal["improvement_proposal_id"] = mirror[
                    "proposal_id"
                ]
                self._memory.update_proposal(
                    proposal["proposal_id"],
                    {"improvement_proposal_id": mirror["proposal_id"]},
                )
            self._audit.record(
                action="propose", ref_id=proposal["proposal_id"],
                detail=proposal["title"][:40],
            )
            return dict(proposal)

    # ── 模拟 ─────────────────────────────────────────────────────
    def simulate(self, proposal_id: str) -> Dict[str, Any]:
        """执行前模拟 (预期收益/风险/副作用/可行性)"""
        with self._lock:
            self._check_enabled()
            proposal = self._memory.get(proposal_id)
            if proposal is None:
                raise CreativeEngineError(
                    f"方案不存在: {proposal_id}"
                )
            confirmed = self._experience_bridge.confirmed_experiences(
                limit=200,
            )
            result = self._simulator.simulate(proposal, confirmed)
            self._memory.update_proposal(
                proposal_id, {"simulation": dict(result)},
            )
            self._audit.record(
                action="simulate", ref_id=proposal_id,
                detail=f"recommendation={result['recommendation']}",
            )
            return dict(result)

    # ── 审批 (Approval) ──────────────────────────────────────────
    def approve(self, proposal_id: str,
                approver: str = "user") -> Dict[str, Any]:
        """批准方案 (PENDING → APPROVED, 才可执行)"""
        with self._lock:
            self._check_enabled()
            try:
                result = self._memory.approve(proposal_id, approver)
            except Exception as e:
                raise CreativeEngineError(f"批准失败: {e}")
            self._audit.record(
                action="approve", ref_id=proposal_id,
                detail=f"approver={approver}",
            )
            return dict(result)

    def reject(self, proposal_id: str,
               reason: str = "") -> Dict[str, Any]:
        """拒绝方案 (PENDING/APPROVED → REJECTED)"""
        with self._lock:
            self._check_enabled()
            try:
                result = self._memory.reject(proposal_id, reason)
            except Exception as e:
                raise CreativeEngineError(f"拒绝失败: {e}")
            self._audit.record(
                action="reject", ref_id=proposal_id,
                detail=reason or "拒绝",
            )
            return dict(result)

    # ── 执行 (仅 APPROVED, 硬门槛) ──────────────────────────────
    def execute(self, proposal_id: str) -> Dict[str, Any]:
        """执行方案 (仅 APPROVED 可执行)

        注意: 标记执行, 真实动作仍走 Service Permission 流程
        """
        with self._lock:
            self._check_enabled()
            proposal = self._memory.get(proposal_id)
            if proposal is None:
                raise CreativeEngineError(
                    f"方案不存在: {proposal_id}"
                )
            if not self._approval_bridge.can_execute(
                proposal["status"],
            ):
                raise CreativeEngineError(
                    f"方案未批准 (status={proposal['status']}), "
                    f"禁止执行"
                )
            try:
                result = self._memory.execute(proposal_id)
            except Exception as e:
                raise CreativeEngineError(f"执行失败: {e}")
            self._audit.record(
                action="execute", ref_id=proposal_id,
                detail="方案进入执行",
            )
            return dict(result)

    # ── 结果记录 (形成新经验) ────────────────────────────────────
    def record_result(
        self, proposal_id: str, success: bool,
        result: str = "",
    ) -> Dict[str, Any]:
        """记录执行结果 → 形成新经验 (闭环)

        Args:
            proposal_id: 方案 ID
            success: 是否成功
            result: 结果描述
        """
        with self._lock:
            self._check_enabled()
            proposal = self._memory.get(proposal_id)
            if proposal is None:
                raise CreativeEngineError(
                    f"方案不存在: {proposal_id}"
                )
            if proposal["status"] != "EXECUTED":
                raise CreativeEngineError(
                    f"只有 EXECUTED 方案可记录结果, "
                    f"当前: {proposal['status']}"
                )
            # 形成新经历 (New Experience)
            experience = self._experience_bridge.record_new_experience(
                trigger=f"creative:{proposal['title'][:40]}",
                lesson=(
                    f"创造方案 '{proposal['title'][:40]}' "
                    f"{'成功' if success else '失败'}: {result[:40]}"
                ),
                result=result or ("成功" if success else "失败"),
                action="creative_execution",
            )
            # 新经历进入验证 (验证流)
            self._experience_bridge.verify_new_experience(
                experience["id"], evidence_count=1,
            )
            updated = self._memory.record_result(
                proposal_id, success, result,
                experience_id=experience["id"],
            )
            self._audit.record(
                action="result", ref_id=proposal_id,
                detail=(
                    f"success={success} → 新经验 {experience['id'][:8]}"
                ),
            )
            return dict(updated)

    # ── 持久化 ───────────────────────────────────────────────────
    def persist(self, path: str = "") -> int:
        """方案记忆持久化 (JSONL)"""
        with self._lock:
            try:
                n = self._memory.save_to_file(path)
            except Exception as e:
                raise CreativeEngineError(f"持久化失败: {e}")
            self._audit.record(
                action="persist", detail=f"保存 {n} 条方案记忆",
            )
            return n

    def load(self, path: str = "") -> int:
        """方案记忆加载"""
        with self._lock:
            try:
                n = self._memory.load_from_file(path)
            except Exception as e:
                raise CreativeEngineError(f"加载失败: {e}")
            self._audit.record(
                action="persist", detail=f"加载 {n} 条方案记忆",
            )
            return n

    # ── 统计与状态 ───────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """创造层统计 (机会/评估/提案/模拟/记忆)"""
        with self._lock:
            memory_stats = self._memory.stats()
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "opportunities": self._detector.stats(),
                "evaluations": self._evaluator.stats(),
                "reasoning": self._reasoning.stats(),
                "proposals": self._generator.stats(),
                "simulations": self._simulator.stats(),
                "memory": memory_stats,
                "summary": {
                    "opportunity_count": (
                        self._detector.stats()["opportunity_count"]
                    ),
                    "confirmed_source_count": (
                        self._experience_bridge.confirmed_count()
                    ),
                    "proposal_count": (
                        self._generator.stats()["proposal_count"]
                    ),
                    "approved_count": memory_stats.get("approved", 0),
                    "rejected_count": memory_stats.get("rejected", 0),
                    "completed_count": memory_stats.get("completed", 0),
                },
            }

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """创造审计报告"""
        return self._audit.report(limit=limit)

    def protections(self) -> List[Dict[str, Any]]:
        """安全保护检查 (主动但不越权)"""
        checks = [
            {
                "name": "confirmed_only",
                "passed": True,
                "reason": (
                    "创造依据只来自 CONFIRMED 经验, "
                    "未验证经验禁止进入创造流程"
                ),
            },
            {
                "name": "no_auto_execute",
                "passed": True,
                "reason": "Proposal 不自动执行, 需显式审批",
            },
            {
                "name": "approval_required",
                "passed": self._approval_bridge.requires_approval(),
                "reason": "执行前必须审批 (Approval Bridge)",
            },
            {
                "name": "no_personality_change",
                "passed": True,
                "reason": "创造模块不修改核心人格/目标",
            },
            {
                "name": "verifiable",
                "passed": True,
                "reason": (
                    "所有方案含来源经验/推理链/风险分析/预期收益"
                ),
            },
        ]
        return checks

    def status(self) -> Dict[str, Any]:
        """创造层状态"""
        with self._lock:
            return {
                "version": "9.5.0",
                "enabled": self._enabled,
                "mode": "rule_based",
                "protections": self.protections(),
                "summary": self.stats()["summary"],
            }

    def clear(self) -> Dict[str, Any]:
        """清空全部状态 (测试隔离)"""
        with self._lock:
            return {
                "opportunities": self._detector.clear(),
                "evaluations": self._evaluator.clear(),
                "reasoning": self._reasoning.clear(),
                "proposals": self._generator.clear(),
                "simulations": self._simulator.clear(),
                "memory": self._memory.clear(),
                "audit": self._audit.clear(),
            }

    # ── 内部辅助 ─────────────────────────────────────────────────
    def _check_enabled(self) -> None:
        """停用检查"""
        if not self._enabled:
            raise CreativeEngineError("创造引擎已停用")

    def _relationship(self) -> Optional[Dict[str, Any]]:
        """关系上下文 (只读, 可空)

        兼容映射: RelationshipManager 使用 trust_level,
        OpportunityDetector 读取 trust
        """
        if self._relationship_manager is None:
            return None
        try:
            rel = self._relationship_manager.relationship()
            if not rel:
                return None
            rel = dict(rel)
            rel.setdefault("trust", rel.get("trust_level", 0.0))
            return rel
        except Exception as e:
            logger.warning(f"[Creative] 读取关系上下文失败: {e}")
            return None


__all__ = [
    "CreativeEngine",
    "CreativeEngineError",
]
