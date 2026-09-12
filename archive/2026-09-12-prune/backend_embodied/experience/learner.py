"""
YHLZ Embodied AI V4.4 - 经验学习器 (Experience Learner, Rule-based)

职责:
    - 编排: Experience → Analysis → Pattern Extraction → Policy Table → Future Suggestion
    - 失败经验沉淀: 同类失败达到阈值 → 生成失败策略 (可解释)
    - 成功经验沉淀: 成功目标 → 生成成功配方 (Action Sequence + Preconditions, 参数归一化)
    - V4.4 策略自适应调度: trigger → scene → goal_type → candidates → 质量排序 → best
    - V4.4 Dry Run 预演: suggest_for_goal(dry_run=True) 只模拟不写统计/不改计划
    - V4.4 策略生命周期: 归档/恢复/老化 (stale) / 降级恢复评估
    - 策略应用到规划: suggest_for_goal → 警告 (失败策略) / 初始计划模板 (成功配方)
    - 经验质量指标: 建议/采纳/成功/命中率 + 低质量策略自动降级

安全约束 (必须保持):
    - 禁止神经网络训练 / 梯度更新 / 黑盒学习 (纯规则 + 模板匹配)
    - 经验学习不修改 Agent Brain / Vision / Memory 接口
    - 策略建议不绕过 Permission Layer (动作仍经权限判定)
    - 不生成自我目标 (只对已有 Goal 提供建议)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.experience.patterns import PatternExtractor
from backend.embodied.experience.policy import (
    ExperiencePolicy,
    PolicyTable,
)
from backend.embodied.schema import FeedbackResult
from backend.embodied.strategy.ranker import PolicyRanker
from backend.embodied.strategy.trends import infer_goal_type

logger = logging.getLogger(__name__)


class ExperienceLearnerError(Exception):
    """经验学习器操作异常"""


class ExperienceLearner:
    """经验学习器 (规则驱动, V4.4 自适应策略调度)

    用法:
        learner = ExperienceLearner()
        learner.on_action_result(action, feedback, analysis)  # 失败 → 模式计数
        learner.on_goal_complete(goal, trace, success, ...)   # 成功 → 配方 + 质量统计
        suggestions = learner.suggest_for_goal(goal, plan)    # 规划前置查询
        preview = learner.suggest_for_goal(goal, plan, dry_run=True)  # 只模拟
    """

    def __init__(
        self,
        table: Optional[PolicyTable] = None,
        pattern_extractor: Optional[PatternExtractor] = None,
        ranker: Optional[PolicyRanker] = None,
        failure_threshold: int = 2,
        min_suggestions: int = 3,
        min_hit_rate: float = 0.5,
        planning_use_recipe: bool = True,
        enabled: bool = True,
        max_age_days: float = 30.0,
        recovery_threshold: int = 3,
        scene_enabled: bool = True,
        goal_type_enabled: bool = True,
    ):
        if failure_threshold <= 0:
            raise ExperienceLearnerError(
                f"failure_threshold 必须 > 0, 当前: {failure_threshold}"
            )
        self._lock = threading.RLock()
        self._table: PolicyTable = table or PolicyTable()
        self._patterns: PatternExtractor = pattern_extractor or PatternExtractor()
        self._ranker: PolicyRanker = ranker or PolicyRanker()
        self._failure_threshold = failure_threshold
        self._min_suggestions = min_suggestions
        self._min_hit_rate = min_hit_rate
        self._planning_use_recipe = planning_use_recipe
        self._enabled = enabled
        self._max_age_days = max_age_days
        self._recovery_threshold = recovery_threshold
        self._scene_enabled = scene_enabled
        self._goal_type_enabled = goal_type_enabled
        self._failure_counts: Dict[str, int] = {}  # trigger → 累计失败次数

    # ── 属性 ──────────────────────────────────────────────────────
    @property
    def table(self) -> PolicyTable:
        return self._table

    @property
    def ranker(self) -> PolicyRanker:
        """策略排序器 (V4.4)"""
        return self._ranker

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def planning_use_recipe(self) -> bool:
        with self._lock:
            return self._planning_use_recipe

    def set_ranker(self, ranker: PolicyRanker) -> None:
        """注入排序器 (V4.4, 测试 / 配置用)"""
        if ranker is None:
            raise ExperienceLearnerError("ranker 不能为 None")
        with self._lock:
            self._ranker = ranker

    def configure(
        self,
        failure_threshold: Optional[int] = None,
        min_suggestions: Optional[int] = None,
        min_hit_rate: Optional[float] = None,
        planning_use_recipe: Optional[bool] = None,
        enabled: Optional[bool] = None,
        max_age_days: Optional[float] = None,
        recovery_threshold: Optional[int] = None,
        scene_enabled: Optional[bool] = None,
        goal_type_enabled: Optional[bool] = None,
    ) -> None:
        """配置更新 (None 忽略)"""
        with self._lock:
            if failure_threshold is not None:
                if failure_threshold <= 0:
                    raise ExperienceLearnerError(
                        f"failure_threshold 必须 > 0, 当前: {failure_threshold}"
                    )
                self._failure_threshold = int(failure_threshold)
            if min_suggestions is not None:
                self._min_suggestions = int(min_suggestions)
            if min_hit_rate is not None:
                self._min_hit_rate = float(min_hit_rate)
            if planning_use_recipe is not None:
                self._planning_use_recipe = bool(planning_use_recipe)
            if enabled is not None:
                self._enabled = bool(enabled)
            if max_age_days is not None:
                if max_age_days <= 0:
                    raise ExperienceLearnerError(
                        f"max_age_days 必须 > 0, 当前: {max_age_days}"
                    )
                self._max_age_days = float(max_age_days)
            if recovery_threshold is not None:
                if recovery_threshold <= 0:
                    raise ExperienceLearnerError(
                        f"recovery_threshold 必须 > 0, 当前: {recovery_threshold}"
                    )
                self._recovery_threshold = int(recovery_threshold)
            if scene_enabled is not None:
                self._scene_enabled = bool(scene_enabled)
            if goal_type_enabled is not None:
                self._goal_type_enabled = bool(goal_type_enabled)

    # ── 失败经验沉淀 ──────────────────────────────────────────────
    def on_action_result(self, action, feedback, analysis=None) -> Optional[ExperiencePolicy]:
        """处理单次行动结果: 失败 → 模式计数 → 达到阈值生成失败策略

        Returns:
            新生成/合并的策略 (未达阈值或非失败 → None)
        """
        if action is None or feedback is None:
            return None
        if feedback.result != FeedbackResult.FAILURE.value:
            return None
        if not self._enabled:
            return None
        pattern = self._patterns.extract_failure_policy(action, feedback, analysis)
        if pattern is None:
            return None
        trigger = pattern["trigger"]
        with self._lock:
            count = self._failure_counts.get(trigger, 0) + 1
            self._failure_counts[trigger] = count
            threshold = self._failure_threshold
        if count < threshold:
            return None
        logger.info(
            f"[Experience] 失败模式重复 {count} 次, 生成策略: "
            f"{trigger} → {pattern['strategy']}"
        )
        return self._table.upsert(
            trigger=trigger,
            strategy=pattern["strategy"],
            kind="failure",
            detail=pattern["detail"],
            action_type=pattern["action_type"],
            cause=pattern["cause"],
            required_action=pattern["required_action"],
        )

    # ── 成功经验沉淀 + 质量统计 (V4.4: scene/goal_type 维度) ───────
    def on_goal_complete(
        self,
        goal,
        trace,
        success: bool,
        applied_policies: Optional[List[str]] = None,
        suggestions: Optional[List[Dict[str, Any]]] = None,
        executed_actions: Optional[List[Dict[str, Any]]] = None,
        scene: str = "",
        goal_type: str = "",
    ) -> Optional[ExperiencePolicy]:
        """目标完成回调: 采纳统计 + 成功配方 + 降级/恢复/老化评估

        Args:
            goal:             目标
            trace:            目标轨迹 (携带 goal_id)
            success:          最终是否成功
            applied_policies: 本目标实际采用的经验策略 trigger 列表
            suggestions:      本目标收到的建议列表 (用于采纳统计)
            executed_actions: 实际执行序列 (用于失败策略采纳判定)
            scene:            目标所在场景 (V4.4 调度维度, 空=未指定)
            goal_type:        目标类型 (V4.4 调度维度, 空=自动推断)

        Returns:
            生成的配方 (成功时) / None
        """
        goal_id = goal.goal_id if goal is not None else (getattr(trace, "goal_id", "") if trace else "")
        if not goal_type:
            goal_type = infer_goal_type(
                goal.to_dict() if goal is not None else (getattr(trace, "goal", None) or {}),
                executed_actions,
            )

        # 1. 失败策略采纳统计: 建议中出现 + 执行序列包含核心动作 → 采纳
        if suggestions and executed_actions:
            executed_types = [e.get("action_type") for e in executed_actions]
            for s in suggestions:
                if s.get("kind") != "failure":
                    continue
                trigger = s.get("trigger", "")
                policy = self._table.get(trigger)
                if policy is None:
                    continue
                required = policy.required_action
                if not required or required in executed_types:
                    self._table.record_accepted(trigger, success)

        # 2. 成功配方采纳统计 (实际采用了模板 → 直接采纳)
        if applied_policies:
            for trigger in applied_policies:
                self._table.record_accepted(trigger, success)

        # 3. 成功 → 生成成功配方 (V4.4: 内容变化 → 版本升级)
        recipe: Optional[ExperiencePolicy] = None
        if success:
            recipe = self._patterns.extract_success_recipe(goal, executed=executed_actions)
            if recipe is not None:
                recipe["source_goal_id"] = goal_id
                recipe["preconditions"] = recipe.get("preconditions", [])
                recipe["scene"] = scene
                recipe["goal_type"] = goal_type
                existing = self._table.get(recipe["trigger"])
                if existing is not None and existing.kind == "success" and \
                        existing.action_sequence != recipe["action_sequence"]:
                    # V4.4 策略进化: 新配方内容 → 新版本 (旧版本入历史)
                    self._table.upsert_version(
                        trigger=recipe["trigger"],
                        strategy=recipe["strategy"],
                        kind="success",
                        detail=recipe["detail"],
                        action_sequence=recipe["action_sequence"],
                        preconditions=recipe["preconditions"],
                        source_goal_id=goal_id,
                        scene=scene,
                        goal_type=goal_type,
                    )
                else:
                    self._table.upsert(
                        trigger=recipe["trigger"],
                        strategy=recipe["strategy"],
                        kind="success",
                        detail=recipe["detail"],
                        action_sequence=recipe["action_sequence"],
                        preconditions=recipe["preconditions"],
                        source_goal_id=goal_id,
                        scene=scene,
                        goal_type=goal_type,
                    )
                recipe = self._table.get(recipe["trigger"])

        # 4. 自动降级评估 (V4.3) + V4.4 恢复评估 + 老化评估
        self._table.evaluate_degradation(
            min_suggestions=self._min_suggestions,
            min_hit_rate=self._min_hit_rate,
        )
        self._table.evaluate_recovery(recovery_threshold=self._recovery_threshold)
        self._table.evaluate_aging(max_age_days=self._max_age_days)
        return recipe

    # ── 策略应用到规划 (V4.4: 场景/目标类型调度 + 质量排序 + Dry Run) ─
    def suggest_for_goal(
        self,
        goal,
        plan: List[Any],
        scene: str = "",
        goal_type: str = "",
        dry_run: bool = False,
    ) -> List[Dict[str, Any]]:
        """规划前置查询: 候选筛选 → 质量排序 → 最佳策略 (可解释)

        Args:
            goal:      目标
            plan:      初始计划
            scene:     目标场景 (V4.4 调度维度)
            goal_type: 目标类型 (V4.4 调度维度, 空=自动推断)
            dry_run:   True=只模拟 (不写统计, 建议携带 dry_run 标记)

        Returns:
            List[Dict]:
                {
                    'type': 'template' | 'warning',
                    'trigger': ...,
                    'strategy': ...,
                    'kind': 'success' | 'failure',
                    'detail': ...,
                    'hit_rate': ...,
                    'degraded': False,
                    'version': ...,
                    'scene': ...,
                    'goal_type': ...,
                    'rank': 1,
                    'candidates': 2,
                    'reason': '为什么选择该策略 (可解释)',
                    'dry_run': bool,
                }
            规则:
                - 成功配方 → template (候选排序最佳, 初始计划模板)
                - 失败策略 → warning (每个动作类型取排序最佳)
                - 已降级 / stale / archived 策略不参与候选
                - dry_run=True 不写任何统计, 不改计划
        """
        if not self._enabled:
            return []
        if not goal_type:
            goal_type = infer_goal_type(
                goal.to_dict() if goal is not None else {}, plan
            )
        dim_scene = scene if self._scene_enabled else ""
        dim_goal_type = goal_type if self._goal_type_enabled else ""
        suggestions: List[Dict[str, Any]] = []

        # 1. 成功配方 → 初始计划模板 (候选排序, 最佳策略)
        recipe_trigger = self._patterns.recipe_trigger_for_plan(plan)
        if self._planning_use_recipe and recipe_trigger:
            recipe_candidates = [
                p for p in self._table.candidates(
                    kind="success", scene=dim_scene, goal_type=dim_goal_type,
                )
                if p.trigger == recipe_trigger
            ]
            best = self._ranker.select_best(recipe_candidates)
            if best is not None:
                best_policy = best["policy"][0]
                suggestions.append({
                    "type": "template",
                    "trigger": best_policy.trigger,
                    "strategy": best_policy.strategy,
                    "kind": "success",
                    "detail": best_policy.detail,
                    "hit_rate": best_policy.hit_rate,
                    "degraded": False,
                    "version": best_policy.version,
                    "scene": best_policy.scene,
                    "goal_type": best_policy.goal_type,
                    "rank": best["best"]["rank"],
                    "candidates": len(best["ranked"]),
                    "reason": best["reason"],
                    "dry_run": dry_run,
                })
                if not dry_run:
                    self._table.record_suggested(best_policy.trigger)

        # 2. 失败策略 → warning (按计划动作类型候选 + 排序最佳)
        seen: set = set()
        for act in plan:
            action_type = (
                act.action_type if hasattr(act, "action_type") else act.get("action_type")
            )
            if not action_type:
                continue
            candidates = self._table.candidates(
                action_type=action_type, kind="failure",
                scene=dim_scene, goal_type=dim_goal_type,
            )
            ranked = self._ranker.rank(candidates)
            if not ranked:
                continue
            best_entry = ranked[0]
            best_policy = self._table.get(best_entry["trigger"])
            if best_policy is None or best_policy.trigger in seen:
                continue
            seen.add(best_policy.trigger)
            suggestions.append({
                "type": "warning",
                "trigger": best_policy.trigger,
                "strategy": best_policy.strategy,
                "kind": "failure",
                "detail": best_policy.detail,
                "hit_rate": best_policy.hit_rate,
                "degraded": False,
                "version": best_policy.version,
                "scene": best_policy.scene,
                "goal_type": best_policy.goal_type,
                "rank": best_entry["rank"],
                "candidates": len(ranked),
                "reason": best_entry["reason"],
                "dry_run": dry_run,
            })
            if not dry_run:
                self._table.record_suggested(best_policy.trigger)
        return suggestions

    def get_policy(self, trigger: str) -> Optional[ExperiencePolicy]:
        """按 trigger 查询策略 (供模板应用)"""
        return self._table.get(trigger)

    # ── V4.4 策略生命周期 (供 Service 接入) ───────────────────────
    def archive_policy(self, trigger: str) -> Optional[ExperiencePolicy]:
        """归档策略 (不是删除, 可恢复)"""
        return self._table.archive_policy(trigger)

    def restore_policy(self, trigger: str) -> Optional[ExperiencePolicy]:
        """恢复策略 (archived → active)"""
        return self._table.restore_policy(trigger)

    def policy_history(self, trigger: str) -> List[Dict[str, Any]]:
        """策略版本历史 (最旧 → 最新)"""
        return self._table.policy_history(trigger)

    def evaluate_lifecycle(self) -> Dict[str, Any]:
        """生命周期评估 (V4.4): 老化 + 恢复 + 降级, 返回本次变更"""
        return {
            "aged_to_stale": self._table.evaluate_aging(
                max_age_days=self._max_age_days
            ),
            "recovered": self._table.evaluate_recovery(
                recovery_threshold=self._recovery_threshold
            ),
            "degraded": self._table.evaluate_degradation(
                min_suggestions=self._min_suggestions,
                min_hit_rate=self._min_hit_rate,
            ),
        }

    # ── 状态 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            counts = dict(self._failure_counts)
        return {
            "enabled": self._enabled,
            "failure_threshold": self._failure_threshold,
            "min_suggestions": self._min_suggestions,
            "min_hit_rate": self._min_hit_rate,
            "planning_use_recipe": self._planning_use_recipe,
            "max_age_days": self._max_age_days,
            "recovery_threshold": self._recovery_threshold,
            "scene_enabled": self._scene_enabled,
            "goal_type_enabled": self._goal_type_enabled,
            "failure_pattern_counts": counts,
            "patterns": self._patterns.stats(),
            "table": self._table.stats(),
            "ranker": self._ranker.weights(),
            "mode": "rule_based",
        }

    def report_dict(self) -> Dict[str, Any]:
        """报告: 策略统计 + 策略列表 (供 Embodied Report)"""
        return {
            "stats": self._table.stats(),
            "policies": [p.to_dict() for p in self._table.all(limit=20)],
        }

    def save_policy(self, path: str) -> int:
        """持久化策略表 (embodied_policy.jsonl)"""
        return self._table.save_to_file(path)

    def load_policy(self, path: str) -> int:
        """加载策略表"""
        return self._table.load_from_file(path)

    def reset(self) -> None:
        with self._lock:
            self._failure_counts.clear()
        self._table.clear()
        self._patterns.reset()


__all__ = ["ExperienceLearner", "ExperienceLearnerError"]
