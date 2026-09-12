"""
YHLZ Embodied AI V9.0 - 自主研究探索引擎 (Autonomous Research Engine)

职责:
    - 受治理的主动探索门面
    - 流程: 观察 → 问题发现 → 计划 → 知识获取 → 假设循环
      → 现实验证 → 记忆集成 → 审计

原则:
    - 主动探索必须有目标 (为什么/解决什么/产生什么价值)
    - 未知管理: Known/Unknown/Hypothesis/Verification 区分
    - 自主 ≠ 无限自主 (受 Constitution/Identity/Safety/Reality 约束)

防失控机制:
    - 禁止自定义终极目标
    - 禁止脱离用户价值体系
    - 禁止无限扩大任务范围
    - 禁止自我强化循环

设计原则:
    - 纯规则探索 (可解释)
    - 全过程审计
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.research_engine.observation import (
    ObservationLayer,
)
from backend.embodied.companion.research_engine.question_discovery import (
    QuestionDiscoveryEngine,
)
from backend.embodied.companion.research_engine.research_planner import (
    ResearchPlanner,
)
from backend.embodied.companion.research_engine.knowledge_acquisition import (
    KnowledgeAcquisition,
)
from backend.embodied.companion.research_engine.hypothesis_loop import (
    HypothesisLoop,
)
from backend.embodied.companion.research_engine.reality_validation import (
    RealityValidation,
)
from backend.embodied.companion.research_engine.research_memory import (
    ResearchMemory,
)
from backend.embodied.companion.research_engine.research_audit import (
    ResearchAudit,
)

from backend.embodied.companion.research_engine.observation import (
    OBSERVATION_TYPES,
    ObservationError,
    ObservationLayer,
)
from backend.embodied.companion.research_engine.question_discovery import (
    IMPORTANCE_WEIGHTS,
    QuestionDiscoveryEngine,
    QuestionError,
)
from backend.embodied.companion.research_engine.research_planner import (
    COST_LEVELS,
    PlannerError,
    RESOURCE_TYPES,
    ResearchPlanner,
)
from backend.embodied.companion.research_engine.knowledge_acquisition import (
    SOURCE_RELIABILITY,
    SOURCE_TYPES,
    AcquisitionError,
    KnowledgeAcquisition,
)
from backend.embodied.companion.research_engine.hypothesis_loop import (
    HypothesisLoop,
    LoopError,
)
from backend.embodied.companion.research_engine.reality_validation import (
    REALITY_LEVELS,
    RealityError,
    RealityValidation,
)
from backend.embodied.companion.research_engine.research_memory import (
    ResearchMemory,
    ResearchMemoryError,
)
from backend.embodied.companion.research_engine.research_audit import (
    ResearchAudit,
    ResearchAuditError,
)

logger = logging.getLogger(__name__)


class ResearchError(Exception):
    """研究引擎操作异常"""


# 防失控信号 (可解释)
RUNAWAY_SIGNALS: list = [
    "自定义终极目标", "统治世界", "无限扩展任务",
    "脱离用户价值", "自我强化", "永久循环",
    "override user values", "infinite loop",
]


class ResearchEngine:
    """自主研究探索引擎 (受治理的主动探索)

    用法:
        engine = ResearchEngine(constitution=...)
        engine.observe("user_need", "提升伙伴体验")
        r = engine.explore("提升伙伴体验")
    """

    def __init__(
        self,
        observation: Optional[ObservationLayer] = None,
        question_engine: Optional[
            QuestionDiscoveryEngine] = None,
        planner: Optional[ResearchPlanner] = None,
        acquisition: Optional[KnowledgeAcquisition] = None,
        loop: Optional[HypothesisLoop] = None,
        reality: Optional[RealityValidation] = None,
        memory: Optional[ResearchMemory] = None,
        audit: Optional[ResearchAudit] = None,
        constitution=None,
        enabled: bool = True,
        max_loops_per_explore: int = 3,
    ):
        if max_loops_per_explore <= 0:
            raise ResearchError(
                f"max_loops_per_explore 必须 > 0, 当前: "
                f"{max_loops_per_explore}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._observation = observation or ObservationLayer()
        self._question_engine = question_engine or \
            QuestionDiscoveryEngine(layer=self._observation)
        self._planner = planner or ResearchPlanner()
        self._acquisition = acquisition or \
            KnowledgeAcquisition()
        self._loop = loop or HypothesisLoop()
        self._reality = reality or RealityValidation()
        self._memory = memory or ResearchMemory()
        self._audit = audit or ResearchAudit()
        self._constitution = constitution
        self._max_loops = int(max_loops_per_explore)
        self._explore_count = 0
        self._blocked_count = 0
        self._runaway_block_count = 0

    # ── 观察 ─────────────────────────────────────────────────────
    def observe(
        self, obs_type: str, content: str,
        source: str = "system",
    ) -> Dict[str, Any]:
        """采集观察"""
        with self._lock:
            return self._observation.observe(
                obs_type, content, source,
            )

    def observe_gaps(self, gaps: List[str]) -> int:
        """从知识缺口观察"""
        with self._lock:
            return self._observation.from_knowledge_gaps(gaps)

    # ── 探索主入口 ───────────────────────────────────────────────
    def explore(
        self,
        goal: str,
        user_value: str = "",
    ) -> Dict[str, Any]:
        """受治理的主动探索

        Args:
            goal: 探索目标 (必须明确)
            user_value: 用户价值体系 (防失控约束)

        Returns:
            {
                'explore_id', 'goal', 'questions', 'plans',
                'results', 'memories', 'audit', 'mode',
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "研究引擎停用",
                }
            # 1. 防失控检查 (目标边界)
            runaway = self._check_runaway(goal, user_value)
            if runaway:
                self._runaway_block_count += 1
                self._blocked_count += 1
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": f"防失控拦截: {runaway}",
                    "explore_id": "re_" +
                    uuid.uuid4().hex[:8],
                }
            # 2. 宪法检查 (目标)
            if self._constitution is not None:
                try:
                    cr = self._constitution.review({
                        "module": "research",
                        "action_text": str(goal),
                        "change": {},
                    })
                    if cr["decision"] != "allow":
                        self._blocked_count += 1
                        return {
                            "mode": "error_frame",
                            "ok": False,
                            "reason": f"宪法拦截: "
                                      f"{cr['reasons']}",
                            "explore_id": "re_" +
                            uuid.uuid4().hex[:8],
                        }
                except Exception as e:
                    logger.warning(
                        f"[Research] 宪法检查失败: {e}",
                    )
            # 3. 问题发现
            questions = self._question_engine.discover()
            if not questions:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "无可探索问题 (需先观察)",
                    "explore_id": "re_" +
                    uuid.uuid4().hex[:8],
                }
            # 4. 研究计划 + 执行 (最多 max_loops 轮)
            results: list = []
            memories: list = []
            for q in questions[:self._max_loops]:
                plan = self._planner.plan(
                    q["question"], q["importance"],
                )
                # 知识获取
                acquired = self._acquisition.acquire(
                    q["question"], source="local",
                )
                # 现实验证
                reality = self._reality.validate(
                    acquired["content"],
                    source=acquired["source"],
                    reliability=acquired["reliability"],
                )
                # 假设循环
                loop_result = self._loop.run(
                    question=q["question"],
                    hypothesis=(
                        f"{q['question'][:20]} 的候选假设"
                    ),
                    analysis=acquired["content"],
                    validated=reality["ok"],
                    validation_reason=reality["reason"],
                )
                # 记忆集成 (经 Constitution)
                constitution_ok = True
                if self._constitution is not None:
                    try:
                        mr = self._constitution.review({
                            "module": "research",
                            "action_text": loop_result[
                                "result"],
                            "change": {},
                        })
                        constitution_ok = (
                            mr["decision"] == "allow"
                        )
                    except Exception:
                        pass
                mem = self._memory.save(
                    conclusion=loop_result["result"],
                    source=acquired["source"],
                    level=reality["level"],
                    validated=reality["ok"],
                    constitution_ok=constitution_ok,
                    uncertainty=(
                        "已验证" if reality["ok"] else
                        "未验证/推测"
                    ),
                )
                # 审计
                self._audit.record(
                    question=q["question"],
                    source=acquired["source"],
                    method="hypothesis_loop",
                    result=loop_result["result"],
                    validation=reality,
                )
                results.append({
                    "question": q["question"],
                    "plan": plan,
                    "acquired": acquired,
                    "reality": reality,
                    "loop": loop_result,
                })
                if mem.get("ok", True):
                    memories.append(mem)
            self._explore_count += 1
            return {
                "mode": "rule_based",
                "explore_id": "re_" + uuid.uuid4().hex[:8],
                "goal": str(goal),
                "questions": [dict(q) for q in questions],
                "results": results,
                "memories": memories,
                "audit_id": self.audit_report()["total"],
                "blocked": False,
            }

    # ── 防失控检查 (可解释) ─────────────────────────────────────
    @staticmethod
    def _check_runaway(goal: str,
                       user_value: str) -> str:
        """目标边界检查"""
        text = str(goal or "") + " " + str(user_value or "")
        for signal in RUNAWAY_SIGNALS:
            if signal in text:
                return f"检测到 '{signal}'"
        if not goal:
            return "探索目标为空 (禁止无目标探索)"
        return ""

    # ── 查询 ─────────────────────────────────────────────────────
    def questions(self) -> Dict[str, Any]:
        """当前问题列表"""
        return {
            "mode": "rule_based",
            "questions": self._question_engine._questions[
                -10:],
        }

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """研究审计报告"""
        return self._audit.report(limit=limit)

    def audit_replay(self, limit: int = 100) -> Dict[str, Any]:
        """研究过程回放"""
        return self._audit.replay(limit=limit)

    def memory_stats(self) -> Dict[str, Any]:
        """研究记忆统计"""
        return self._memory.stats()

    def stats(self) -> Dict[str, Any]:
        """研究引擎统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "explore_count": self._explore_count,
                "blocked_count": self._blocked_count,
                "runaway_block_count":
                    self._runaway_block_count,
                "observation": self._observation.stats(),
                "questions": self._question_engine.stats(),
                "planner": self._planner.stats(),
                "acquisition": self._acquisition.stats(),
                "loop": self._loop.stats(),
                "reality": self._reality.stats(),
                "memory": self._memory.stats(),
                "audit": self._audit.stats(),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = 0
            n += self._observation.clear()
            n += self._question_engine.clear()
            n += self._planner.clear()
            n += self._acquisition.clear()
            n += self._loop.clear()
            n += self._reality.clear()
            n += self._memory.clear()
            n += self._audit.clear()
            self._explore_count = 0
            self._blocked_count = 0
            self._runaway_block_count = 0
            return n


__all__ = [
    "RUNAWAY_SIGNALS",
    "ResearchEngine",
    "ResearchError",
    "COST_LEVELS",
    "IMPORTANCE_WEIGHTS",
    "OBSERVATION_TYPES",
    "REALITY_LEVELS",
    "RESOURCE_TYPES",
    "SOURCE_RELIABILITY",
    "SOURCE_TYPES",
    "AcquisitionError",
    "HypothesisLoop",
    "KnowledgeAcquisition",
    "LoopError",
    "ObservationError",
    "ObservationLayer",
    "PlannerError",
    "QuestionDiscoveryEngine",
    "QuestionError",
    "RealityError",
    "RealityValidation",
    "ResearchAudit",
    "ResearchAuditError",
    "ResearchMemory",
    "ResearchMemoryError",
    "ResearchPlanner",
]
