"""
YHLZ Embodied AI V6.6 - 成长闭环 (Growth Cycle)

职责:
    - 自动触发成长分析流程 (反思 → 建议 → 评估 → 待审批)
    - 流程:
      Trigger → Collect Experience → Reflection → Generate Proposal
      → Evaluation → Approval Queue

触发器 (可解释):
    - 时间触发: 距上次运行 ≥ N 天 (companion_growth_cycle_days)
    - 事件触发: 经历数增长 ≥ M (companion_growth_cycle_min_experience_delta)
    - 用户触发: trigger="manual"

强制规则 (成长不是自我修改):
    - growth_auto_apply=false 硬保持: 闭环永不调用应用器
    - 任何成长必须进入待审批队列
    - 应用永远需人工 (经 GrowthApplier 审批流程)
    - 自动行为全部审计 (reuse GrowthAudit)

设计原则:
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class CycleError(Exception):
    """成长闭环操作异常"""


# 闭环状态 (可解释)
CYCLE_STATUS: List[str] = [
    "running",            # 运行中
    "completed",          # 完成
    "failed",             # 失败
]

# 触发器类型 (可解释)
CYCLE_TRIGGERS: List[str] = [
    "time",               # 时间触发 (距上次运行超天数)
    "event",              # 事件触发 (经历数增长超阈值)
    "manual",             # 用户触发
]

# 待审批决策 (可解释)
PENDING_DECISIONS: List[str] = [
    "approve",            # 批准 (仍需人工应用)
    "reject",             # 拒绝
]


class GrowthCycleEngine:
    """成长闭环引擎 (自动反思 → 建议 → 评估 → 待审批)

    用法:
        cycle = GrowthCycleEngine(
            reflection=engine, proposal=generator,
            evaluator=evaluator, audit=audit,
            records_fn=lambda: [...],
        )
        result = cycle.check(experience_count=10)
        result = cycle.run(trigger="manual")
        pending = cycle.pending()
    """

    def __init__(
        self,
        reflection=None,
        proposal=None,
        evaluator=None,
        audit=None,
        records_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        enabled: bool = True,
        cycle_days: int = 1,
        min_experience_delta: int = 5,
        max_pending: int = 50,
    ):
        if cycle_days <= 0:
            raise CycleError(
                f"cycle_days 必须 > 0, 当前: {cycle_days}"
            )
        if min_experience_delta <= 0:
            raise CycleError(
                f"min_experience_delta 必须 > 0, 当前: "
                f"{min_experience_delta}"
            )
        self._lock = threading.RLock()
        self._reflection = reflection
        self._proposal = proposal
        self._evaluator = evaluator
        self._audit = audit
        self._records_fn = records_fn
        self._enabled = bool(enabled)
        self._cycle_days = int(cycle_days)
        self._min_delta = int(min_experience_delta)
        self._max_pending = int(max_pending)
        self._cycles: List[Dict[str, Any]] = []
        self._pending: List[Dict[str, Any]] = []
        self._last_run: float = 0.0
        self._last_experience_count: int = 0
        self._run_count = 0
        self._trigger_reasons: Dict[str, int] = {}

    # ── 触发检查 (不运行) ───────────────────────────────────────
    def check(
        self,
        experience_count: int = 0,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """检查是否满足触发条件

        Args:
            experience_count: 当前经历数
            now: 当前时间

        Returns:
            {
                'triggered', 'reasons': [...], 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {"triggered": False,
                        "reasons": ["成长闭环停用"],
                        "mode": "rule_based"}
            reasons: List[str] = []
            # 1. 时间触发
            if self._last_run > 0 and \
                    (now - self._last_run) >= self._cycle_days * 86400:
                reasons.append(
                    f"距上次运行 ≥ {self._cycle_days} 天 (时间触发)"
                )
            # 2. 事件触发
            delta = experience_count - self._last_experience_count
            if delta >= self._min_delta:
                reasons.append(
                    f"经历数增长 {delta} ≥ {self._min_delta} "
                    f"(事件触发)"
                )
            return {
                "triggered": bool(reasons),
                "reasons": reasons,
                "mode": "rule_based",
            }

    # ── 运行闭环 ─────────────────────────────────────────────────
    def run(
        self,
        trigger: str = "auto",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """运行完整成长闭环

        Args:
            trigger: 触发类型 (auto/manual; auto 内部判定
                time/event)

        Returns:
            {
                'cycle': {...}, 'reflection': {...},
                'proposals': [...], 'evaluations': [...],
                'pending_count', 'audit', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {"cycle": None,
                        "reason": "成长闭环停用",
                        "mode": "rule_based"}
            # 触发类型归一
            trigger_type = "manual"
            if trigger == "auto":
                check = self.check(
                    self._experience_count(), now=now,
                )
                trigger_type = "time" if any(
                    "时间" in r for r in check["reasons"]
                ) else ("event" if check["triggered"]
                        else "none")
                if trigger_type == "none":
                    return {
                        "cycle": None,
                        "reason": "无触发条件",
                        "mode": "rule_based",
                    }
            elif trigger not in CYCLE_TRIGGERS:
                raise CycleError(
                    f"非法触发类型: {trigger} "
                    f"(可选: {CYCLE_TRIGGERS})"
                )
            cycle = self._begin_cycle(trigger_type, now)
            try:
                # 1. 收集经历 (None/异常 → 空列表, 容错)
                records = []
                if self._records_fn is not None:
                    try:
                        records = self._records_fn() or []
                        if not isinstance(records, list):
                            records = []
                    except Exception as e:
                        logger.warning(
                            f"[GrowthCycle] 经历采集失败: {e}",
                        )
                        records = []
                # 2. 反思
                reflection = {}
                if self._reflection is not None:
                    try:
                        identity = self._identity_hook()
                        reflection = self._reflection.analyze(
                            records, identity,
                        )
                    except Exception as e:
                        logger.warning(
                            f"[GrowthCycle] 反思失败: {e}",
                        )
                        reflection = {"error": str(e)}
                # 3. 建议
                proposals: List[Dict[str, Any]] = []
                if self._proposal is not None:
                    try:
                        proposals = self._proposal.generate(
                            reflection,
                        )
                    except Exception as e:
                        logger.warning(
                            f"[GrowthCycle] 建议生成失败: {e}"
                        )
                # 4. 评估 + 待审批队列
                evaluations: List[Dict[str, Any]] = []
                pending_added = 0
                for p in proposals:
                    ev = self._evaluate(p)
                    evaluations.append(ev)
                    if pending_added >= self._max_pending:
                        break
                    self._pending.append({
                        "pending_id": "pc_" +
                        uuid.uuid4().hex[:8],
                        "proposal": p,
                        "evaluation": ev,
                        "decision": "pending",
                        "cycle_id": cycle["id"],
                        "created_at": now,
                    })
                    pending_added += 1
                # 5. 完成闭环
                self._finish_cycle(
                    cycle, "completed",
                    experience_count=len(records),
                    proposal_count=len(proposals),
                )
                # 6. 审计 (自动行为全部记录)
                if self._audit is not None:
                    try:
                        self._audit.record(
                            proposal_id=cycle["id"],
                            before={"trigger": trigger_type},
                            decision="cycle_completed",
                            after={
                                "reflection_count":
                                    int(bool(reflection)),
                                "proposal_count": len(proposals),
                                "evaluation_count": len(evaluations),
                                "pending_count": pending_added,
                            },
                        )
                    except Exception as e:
                        logger.warning(
                            f"[GrowthCycle] 审计记录失败: {e}"
                        )
                return {
                    "mode": "rule_based",
                    "cycle": dict(cycle),
                    "reflection": reflection,
                    "proposals": [dict(p) for p in proposals],
                    "evaluations": [
                        dict(e) for e in evaluations
                    ],
                    "pending_count": pending_added,
                    "audited": True,
                }
            except Exception as e:
                self._finish_cycle(cycle, "failed",
                                   reason=str(e))
                logger.error(f"[GrowthCycle] 闭环失败: {e}")
                return {
                    "mode": "rule_based",
                    "cycle": dict(cycle),
                    "error": str(e),
                }

    def _evaluate(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """评估建议 (身份/安全/价值)"""
        if self._evaluator is None:
            return {"approved": False,
                    "reason": "无评估器",
                    "mode": "rule_based"}
        try:
            return self._evaluator.evaluate(
                proposal, self._identity_hook(),
            )
        except Exception as e:
            logger.warning(f"[GrowthCycle] 评估失败: {e}")
            return {"approved": False,
                    "reason": f"评估失败: {e}",
                    "mode": "rule_based"}

    def _identity_hook(self) -> Dict[str, Any]:
        """身份状态钩子 (子类/注入可覆盖)"""
        return {}

    def _experience_count(self) -> int:
        """当前经历数 (记录提供者)"""
        if self._records_fn is None:
            return 0
        try:
            return len(self._records_fn())
        except Exception as e:
            logger.warning(
                f"[GrowthCycle] 读取经历数失败: {e}",
            )
            return 0

    # ── 闭环记录 ─────────────────────────────────────────────────
    def _begin_cycle(self, trigger_type: str,
                     now: float) -> Dict[str, Any]:
        cycle = {
            "id": "gc_" + uuid.uuid4().hex[:8],
            "start_time": now,
            "trigger": trigger_type,
            "experience_count": 0,
            "proposal_count": 0,
            "status": "running",
        }
        self._cycles.append(cycle)
        return cycle

    def _finish_cycle(self, cycle: Dict[str, Any], status: str,
                      experience_count: int = 0,
                      proposal_count: int = 0,
                      reason: str = "") -> None:
        cycle["status"] = status
        cycle["experience_count"] = int(experience_count)
        cycle["proposal_count"] = int(proposal_count)
        if reason:
            cycle["reason"] = reason
        self._last_run = cycle["start_time"]
        self._last_experience_count = int(experience_count)
        self._run_count += 1
        self._trigger_reasons[cycle["trigger"]] = \
            self._trigger_reasons.get(cycle["trigger"], 0) + 1

    # ── 待审批队列 ───────────────────────────────────────────────
    def pending(self, limit: int = 50) -> Dict[str, Any]:
        """待审批列表 (应用永远需人工)"""
        with self._lock:
            items = list(self._pending)
        if limit > 0:
            items = items[:limit]
        return {
            "mode": "rule_based",
            "pending_count": len(items),
            "items": [
                {
                    "pending_id": i["pending_id"],
                    "proposal": dict(i["proposal"]),
                    "evaluation": dict(i["evaluation"]),
                    "decision": i["decision"],
                    "cycle_id": i["cycle_id"],
                    "created_at": i["created_at"],
                }
                for i in items
            ],
        }

    def decide(
        self, pending_id: str, decision: str,
        reason: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """待审批决策 (批准不等于应用, 应用仍走人工)

        Args:
            pending_id: 待审批项 id
            decision: approve/reject
            reason: 决策原因

        Returns:
            {
                'pending_id', 'decision', 'applied',
                'reason', 'mode',
            }
        """
        if decision not in PENDING_DECISIONS:
            raise CycleError(
                f"非法决策: {decision} (可选: {PENDING_DECISIONS})"
            )
        with self._lock:
            now = now if now is not None else time.time()
            for i in self._pending:
                if i["pending_id"] == pending_id:
                    i["decision"] = decision
                    i["decided_at"] = now
                    i["decide_reason"] = reason
                    if self._audit is not None:
                        try:
                            self._audit.record(
                                proposal_id=i["proposal"].get(
                                    "id", "",
                                ),
                                before={
                                    "decision": "pending",
                                },
                                decision=f"cycle_{decision}",
                                after={
                                    "reason": reason,
                                    "applied": False,
                                },
                            )
                        except Exception as e:
                            logger.warning(
                                f"[GrowthCycle] 审计失败: {e}"
                            )
                    return {
                        "mode": "rule_based",
                        "pending_id": pending_id,
                        "decision": decision,
                        "applied": False,
                        "reason": (
                            "批准仅标记, 应用仍经人工审批"
                            if decision == "approve"
                            else "已拒绝"
                        ) if not reason else reason,
                    }
            raise CycleError(f"待审批项不存在: {pending_id}")

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """闭环统计"""
        with self._lock:
            cycles = list(self._cycles)
            pending = list(self._pending)
        by_status: Dict[str, int] = {}
        for c in cycles:
            by_status[c["status"]] = by_status.get(
                c["status"], 0,
            ) + 1
        return {
            "mode": "rule_based",
            "enabled": self._enabled,
            "cycle_count": len(cycles),
            "run_count": self._run_count,
            "by_status": by_status,
            "pending_count": len(pending),
            "pending_decisions": {
                "approve": sum(
                    1 for i in pending
                    if i["decision"] == "approve"
                ),
                "reject": sum(
                    1 for i in pending
                    if i["decision"] == "reject"
                ),
            },
            "trigger_reasons": dict(self._trigger_reasons),
            "thresholds": {
                "cycle_days": self._cycle_days,
                "min_experience_delta": self._min_delta,
                "max_pending": self._max_pending,
            },
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._cycles) + len(self._pending)
            self._cycles.clear()
            self._pending.clear()
            self._last_run = 0.0
            self._last_experience_count = 0
            self._run_count = 0
            self._trigger_reasons = {}
            return n


__all__ = [
    "CYCLE_STATUS",
    "CYCLE_TRIGGERS",
    "CycleError",
    "GrowthCycleEngine",
    "PENDING_DECISIONS",
]
