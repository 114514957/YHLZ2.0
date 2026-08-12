"""
YHLZ Embodied AI V10.0 - 热机健康指标引擎 (Warm Runtime Health Metrics)

职责:
    - 聚合四维健康指标: Cognitive / Memory / Growth / Safety
    - 输出统一健康报告 (score / level / reason 可解释)
    - 纯只读监控: 不修改任何引擎状态, 仅读取统计

设计原则:
    - 只读聚合: 热机监控不干预运行, 不写任何状态
    - 线程安全 (RLock)
    - 容错: 任一引擎不可用返回错误帧, 不抛异常
    - 规则可解释: 阈值全部为命名常量 + rule/reason 字段

用法:
    health = WarmRuntimeHealth(meta_cognition=..., continuity=..., ...)
    report = health.report()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── 健康等级 ──────────────────────────────────────────────────
HEALTH_LEVELS: list = ["good", "warning", "risk"]

# ── 认知维度阈值 (命名常量, 规则可解释) ────────────────────────
# 推理稳定性 = 平均置信度; 越高越稳定
COGNITIVE_STABILITY_GOOD: float = 0.6
COGNITIVE_STABILITY_WARNING: float = 0.4
# 错误率 = 错误数 / 监控记录数
COGNITIVE_ERROR_RATE_GOOD: float = 0.1
COGNITIVE_ERROR_RATE_WARNING: float = 0.3
# 修正率 = 反思更新数 / 反思次数
COGNITIVE_CORRECTION_GOOD: float = 0.3
COGNITIVE_CORRECTION_WARNING: float = 0.1

# ── 记忆维度阈值 ──────────────────────────────────────────────
# 重复率 = 回收记忆数 / 索引总数 (回收 = 重复淘汰)
MEMORY_DUPLICATE_GOOD: float = 0.3
MEMORY_DUPLICATE_WARNING: float = 0.5
# 污染率 = 门禁拒绝数 / 候选数
MEMORY_POLLUTION_GOOD: float = 0.3
MEMORY_POLLUTION_WARNING: float = 0.5
# 检索质量 = 活跃记忆占比
MEMORY_ACTIVE_GOOD: float = 0.5
MEMORY_ACTIVE_WARNING: float = 0.3

# ── 成长维度阈值 ──────────────────────────────────────────────
# 有效优化次数 (确认经验 + 反思)
GROWTH_EFFECTIVE_GOOD: int = 5
GROWTH_EFFECTIVE_WARNING: int = 1

# ── 安全维度阈值 ──────────────────────────────────────────────
# 拦截次数 (身份守护 + 宪法防谵妄); 拦截多说明防护活跃, 不降级
SAFETY_INTERCEPT_ACTIVE: int = 1

# ── 维度权重 (整体评分) ───────────────────────────────────────
WEIGHT_COGNITIVE: float = 0.3
WEIGHT_MEMORY: float = 0.25
WEIGHT_GROWTH: float = 0.2
WEIGHT_SAFETY: float = 0.25


class WarmRuntimeHealthError(Exception):
    """热机健康指标引擎异常"""


def _safe(value: Any, default: Any = 0.0) -> float:
    """安全数值转换 (容错)"""
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return float(default)


class WarmRuntimeHealth:
    """热机健康指标引擎 (V10.0, 纯只读聚合)

    输入为各引擎实例 (可缺省), 输出四维健康报告:
        Cognitive: 推理稳定性 / 错误率 / 修正率
        Memory:    重复率 / 污染率 / 检索质量
        Growth:    有效优化次数 / 策略改进效果
        Safety:    拦截次数 / 异常行为
    """

    def __init__(
        self,
        meta_cognition=None,
        continuity=None,
        memory_gate=None,
        identity_guard=None,
        constitution=None,
        memory_stabilization=None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._meta_cognition = meta_cognition
        self._continuity = continuity
        self._memory_gate = memory_gate
        self._identity_guard = identity_guard
        self._constitution = constitution
        self._memory_stabilization = memory_stabilization

    # ── 四维聚合 ────────────────────────────────────────────────
    def _cognitive(self) -> Dict[str, Any]:
        """认知健康: 推理稳定性 / 错误率 / 修正率"""
        stats: Dict[str, Any] = {}
        if self._meta_cognition is not None:
            try:
                stats = self._meta_cognition.stats()
            except Exception as e:
                logger.warning(f"[Health] 元认知统计失败: {e}")
        monitor = stats.get("monitor", {}) or {}
        detector = stats.get("detector", {}) or {}
        reflection = stats.get("reflection", {}) or {}
        verification = stats.get("verification", {}) or {}

        record_count = int(_safe(monitor.get("record_count"), 0))
        error_count = int(_safe(detector.get("error_count"), 0))
        reflection_count = int(_safe(reflection.get("reflection_count"), 0))
        update_count = int(_safe(reflection.get("update_count"), 0))
        verified_count = int(_safe(verification.get("verified_count"), 0))
        uncertain_count = int(_safe(verification.get("uncertain_count"), 0))

        stability = round(_safe(monitor.get("avg_confidence"), 0.0), 4)
        error_rate = round(
            error_count / record_count, 4,
        ) if record_count else 0.0
        correction_rate = round(
            update_count / reflection_count, 4,
        ) if reflection_count else 0.0

        # 等级判定 (规则可解释)
        levels = []
        reasons = []
        if stability >= COGNITIVE_STABILITY_GOOD:
            levels.append("good")
            reasons.append(
                f"推理稳定: 平均置信 {stability} >= "
                f"{COGNITIVE_STABILITY_GOOD}"
            )
        elif stability >= COGNITIVE_STABILITY_WARNING:
            levels.append("warning")
            reasons.append(
                f"推理置信偏低: {stability} < "
                f"{COGNITIVE_STABILITY_GOOD}"
            )
        else:
            levels.append("risk")
            reasons.append(
                f"推理置信过低: {stability} < "
                f"{COGNITIVE_STABILITY_WARNING}"
            )

        if error_rate <= COGNITIVE_ERROR_RATE_GOOD:
            levels.append("good")
            reasons.append(f"错误率低: {error_rate}")
        elif error_rate <= COGNITIVE_ERROR_RATE_WARNING:
            levels.append("warning")
            reasons.append(
                f"错误率偏高: {error_rate} > "
                f"{COGNITIVE_ERROR_RATE_GOOD}"
            )
        else:
            levels.append("risk")
            reasons.append(
                f"错误率过高: {error_rate} > "
                f"{COGNITIVE_ERROR_RATE_WARNING}"
            )

        if correction_rate >= COGNITIVE_CORRECTION_GOOD:
            levels.append("good")
            reasons.append(
                f"修正率良好: {correction_rate} >= "
                f"{COGNITIVE_CORRECTION_GOOD}"
            )
        elif correction_rate >= COGNITIVE_CORRECTION_WARNING:
            levels.append("warning")
            reasons.append(f"修正率一般: {correction_rate}")
        else:
            levels.append("risk")
            reasons.append(f"缺少反思修正: {correction_rate}")

        level = self._worst_level(levels)
        return {
            "mode": "rule_based",
            "enabled": bool(stats.get("enabled", True)),
            "stability": stability,
            "error_rate": error_rate,
            "correction_rate": correction_rate,
            "verified_count": verified_count,
            "uncertain_count": uncertain_count,
            "score": round(
                stability * 0.4 + (1.0 - error_rate) * 0.3
                + correction_rate * 0.3, 4,
            ),
            "level": level,
            "reasons": reasons,
        }

    def _memory(self) -> Dict[str, Any]:
        """记忆健康: 重复率 / 污染率 / 检索质量"""
        overview: Dict[str, Any] = {}
        if self._continuity is not None:
            try:
                overview = self._continuity.memory_overview()
            except Exception as e:
                logger.warning(f"[Health] 记忆总览失败: {e}")
        gate: Dict[str, Any] = {}
        if self._memory_gate is not None:
            try:
                gate = self._memory_gate.stats()
            except Exception as e:
                logger.warning(f"[Health] 记忆门禁统计失败: {e}")
        # V10.1 记忆稳定化统计 (只读聚合, 不破坏冻结)
        stabilize: Dict[str, Any] = {}
        if self._memory_stabilization is not None:
            try:
                stabilize = self._memory_stabilization.stats()
            except Exception as e:
                logger.warning(f"[Health] 稳定化统计失败: {e}")

        index = overview.get("index", {}) or {}
        index_total = int(_safe(index.get("total"), 0))
        by_stage = index.get("by_stage", {}) or {}
        active_count = int(_safe(by_stage.get("active"), 0))
        recycled_total = int(
            _safe(overview.get("recycled_total"), 0),
        )

        candidate_count = int(_safe(gate.get("candidate_count"), 0))
        rejected_count = int(_safe(gate.get("rejected_count"), 0))
        approved_count = int(_safe(gate.get("approved_count"), 0))

        # 稳定化审计统计 (合并/淘汰/冲突)
        stab_audit = stabilize.get("audit", {}) or {}
        stab_by_action = stab_audit.get("by_action", {}) or {}
        compress_count = int(_safe(
            stab_by_action.get("compress"), 0,
        ))
        prune_count = int(_safe(
            stab_by_action.get("prune"), 0,
        ))
        conflict_count = int(_safe(
            stab_by_action.get("conflict"), 0,
        ))

        duplicate_rate = round(
            recycled_total / index_total, 4,
        ) if index_total else 0.0
        pollution_rate = round(
            rejected_count / candidate_count, 4,
        ) if candidate_count else 0.0
        retrieval_quality = round(
            active_count / index_total, 4,
        ) if index_total else 0.0
        gate_quality = round(
            approved_count / candidate_count, 4,
        ) if candidate_count else 0.0

        levels = []
        reasons = []
        if duplicate_rate <= MEMORY_DUPLICATE_GOOD:
            levels.append("good")
            reasons.append(f"重复率低: {duplicate_rate}")
        elif duplicate_rate <= MEMORY_DUPLICATE_WARNING:
            levels.append("warning")
            reasons.append(
                f"重复率偏高: {duplicate_rate} > "
                f"{MEMORY_DUPLICATE_GOOD}"
            )
        else:
            levels.append("risk")
            reasons.append(
                f"重复率过高: {duplicate_rate} > "
                f"{MEMORY_DUPLICATE_WARNING}"
            )

        if pollution_rate <= MEMORY_POLLUTION_GOOD:
            levels.append("good")
            reasons.append(f"污染率低: {pollution_rate}")
        elif pollution_rate <= MEMORY_POLLUTION_WARNING:
            levels.append("warning")
            reasons.append(
                f"污染率偏高: {pollution_rate} > "
                f"{MEMORY_POLLUTION_GOOD}"
            )
        else:
            levels.append("risk")
            reasons.append(
                f"污染率过高: {pollution_rate} > "
                f"{MEMORY_POLLUTION_WARNING}"
            )

        if retrieval_quality >= MEMORY_ACTIVE_GOOD:
            levels.append("good")
            reasons.append(
                f"检索质量良好: 活跃占比 {retrieval_quality}"
            )
        elif retrieval_quality >= MEMORY_ACTIVE_WARNING:
            levels.append("warning")
            reasons.append(
                f"活跃记忆占比偏低: {retrieval_quality}"
            )
        else:
            levels.append("risk")
            reasons.append(
                f"活跃记忆占比过低: {retrieval_quality}"
            )

        return {
            "mode": "rule_based",
            "enabled": bool(gate.get("enabled", True)),
            "duplicate_rate": duplicate_rate,
            "pollution_rate": pollution_rate,
            "retrieval_quality": retrieval_quality,
            "gate_quality": gate_quality,
            "index_total": index_total,
            "candidate_count": candidate_count,
            "stabilization": {
                "compress_count": compress_count,
                "prune_count": prune_count,
                "conflict_count": conflict_count,
                "audit_total": int(_safe(
                    stab_audit.get("total"), 0,
                )),
            },
            "score": round(
                (1.0 - duplicate_rate) * 0.35
                + (1.0 - pollution_rate) * 0.35
                + retrieval_quality * 0.3, 4,
            ),
            "level": self._worst_level(levels),
            "reasons": reasons,
        }

    def _growth(self) -> Dict[str, Any]:
        """成长健康: 有效优化次数 / 策略改进效果"""
        metrics: Dict[str, Any] = {}
        if self._continuity is not None:
            try:
                metrics = self._continuity.growth_metrics()
            except Exception as e:
                logger.warning(f"[Health] 成长指标失败: {e}")
        by_type = metrics.get("by_type", {}) or {}
        confirmed_count = int(_safe(metrics.get("confirmed_count"), 0))
        reflection_count = int(_safe(metrics.get("reflection_count"), 0))
        effective = confirmed_count + reflection_count

        levels = []
        reasons = []
        if effective >= GROWTH_EFFECTIVE_GOOD:
            levels.append("good")
            reasons.append(
                f"有效优化活跃: {effective} 次 "
                f"(确认 {confirmed_count} + 反思 {reflection_count})"
            )
        elif effective >= GROWTH_EFFECTIVE_WARNING:
            levels.append("warning")
            reasons.append(f"有效优化偏少: {effective} 次")
        else:
            levels.append("risk")
            reasons.append(
                f"无有效优化: {effective} 次 "
                f"(需确认经验或反思)"
            )

        return {
            "mode": "rule_based",
            "enabled": bool(metrics.get("enabled", True)),
            "effective_optimizations": effective,
            "confirmed_count": confirmed_count,
            "reflection_count": reflection_count,
            "by_type": by_type,
            "score": round(
                min(effective / GROWTH_EFFECTIVE_GOOD, 1.0), 4,
            ),
            "level": self._worst_level(levels),
            "reasons": reasons,
        }

    def _safety(self) -> Dict[str, Any]:
        """安全健康: 拦截次数 / 异常行为"""
        guard: Dict[str, Any] = {}
        if self._identity_guard is not None:
            try:
                guard = self._identity_guard.stats()
            except Exception as e:
                logger.warning(f"[Health] 身份守护统计失败: {e}")
        constitution: Dict[str, Any] = {}
        if self._constitution is not None:
            try:
                constitution = self._constitution.stats()
            except Exception as e:
                logger.warning(f"[Health] 宪法统计失败: {e}")

        intercept_count = int(_safe(guard.get("intercept_count"), 0))
        approval_count = int(_safe(guard.get("approval_count"), 0))
        validator = constitution.get("validator", {}) or {}
        delusion_block = int(_safe(
            validator.get("delusion_block_count"), 0,
        ))
        rule_engine = constitution.get("rule_engine", {}) or {}
        decisions = rule_engine.get("decisions", {}) or {}
        block_count = sum(
            v for k, v in decisions.items()
            if k in ("block", "review", "deny")
        )

        total_intercepts = intercept_count + delusion_block

        levels = []
        reasons = []
        if total_intercepts >= SAFETY_INTERCEPT_ACTIVE:
            levels.append("good")
            reasons.append(
                f"防护活跃: 拦截 {total_intercepts} 次 "
                f"(身份 {intercept_count} + 防谵妄 {delusion_block})"
            )
        else:
            levels.append("good")
            reasons.append("防护就绪: 暂无拦截记录 (无需干预)")

        return {
            "mode": "rule_based",
            "enabled": True,
            "interception_count": total_intercepts,
            "identity_intercepts": intercept_count,
            "delusion_blocks": delusion_block,
            "constitution_blocks": block_count,
            "approval_count": approval_count,
            "score": 1.0,
            "level": self._worst_level(levels),
            "reasons": reasons,
        }

    # ── 报告 ────────────────────────────────────────────────────
    @staticmethod
    def _worst_level(levels: list) -> str:
        """取最差等级 (risk > warning > good)"""
        if "risk" in levels:
            return "risk"
        if "warning" in levels:
            return "warning"
        return "good"

    def report(self) -> Dict[str, Any]:
        """热机健康报告 (四维 + 整体)"""
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "热机健康指标停用",
                }
            cognitive = self._cognitive()
            memory = self._memory()
            growth = self._growth()
            safety = self._safety()

            overall_score = round(
                cognitive["score"] * WEIGHT_COGNITIVE
                + memory["score"] * WEIGHT_MEMORY
                + growth["score"] * WEIGHT_GROWTH
                + safety["score"] * WEIGHT_SAFETY, 4,
            )
            overall_level = self._worst_level([
                cognitive["level"], memory["level"],
                growth["level"], safety["level"],
            ])

            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "version": "9.5.0",
                "generated_at": time.time(),
                "overall": {
                    "score": overall_score,
                    "level": overall_level,
                    "reason": (
                        f"认知={cognitive['level']} "
                        f"记忆={memory['level']} "
                        f"成长={growth['level']} "
                        f"安全={safety['level']}"
                    ),
                },
                "cognitive": cognitive,
                "memory": memory,
                "growth": growth,
                "safety": safety,
            }

    def clear(self) -> int:
        """健康指标无自有状态, 恒 0 (只读聚合)"""
        return 0


__all__ = [
    "COGNITIVE_CORRECTION_GOOD",
    "COGNITIVE_CORRECTION_WARNING",
    "COGNITIVE_ERROR_RATE_GOOD",
    "COGNITIVE_ERROR_RATE_WARNING",
    "COGNITIVE_STABILITY_GOOD",
    "COGNITIVE_STABILITY_WARNING",
    "GROWTH_EFFECTIVE_GOOD",
    "GROWTH_EFFECTIVE_WARNING",
    "HEALTH_LEVELS",
    "MEMORY_ACTIVE_GOOD",
    "MEMORY_ACTIVE_WARNING",
    "MEMORY_DUPLICATE_GOOD",
    "MEMORY_DUPLICATE_WARNING",
    "MEMORY_POLLUTION_GOOD",
    "MEMORY_POLLUTION_WARNING",
    "SAFETY_INTERCEPT_ACTIVE",
    "WEIGHT_COGNITIVE",
    "WEIGHT_GROWTH",
    "WEIGHT_MEMORY",
    "WEIGHT_SAFETY",
    "WarmRuntimeHealth",
    "WarmRuntimeHealthError",
]
