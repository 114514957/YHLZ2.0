"""
YHLZ Embodied AI V5.3 - 执行协调器 (Execution Coordinator)

职责:
    - 执行集成: 规划结果 → EmbodiedGoal → run_goal (经 Permission)
    - 反馈闭环: 执行结果 → 反馈分析 → 更新经验 (成功/失败统计)
    - 闭环循环: 感知-策略-规划-执行-反馈 (循环上限可配)
    - 执行审计: 每次执行记录 (目标/动作/结果/耗时)

数据模型:
    ExecutionRecord:
    {
        goal, actions, result, latency_ms, status,
    }

闭环流程 (可解释):
    感知 → 策略 → 规划 → 执行 → 反馈 → (失败时) 调整 → 重试
    循环上限: companion_loop_max_iterations (默认 3)

安全约束:
    - 执行必须经 Permission Layer (run_goal 内部校验)
    - 不写 Agent Memory (经验更新走 Embodied 既有规则)
    - 不控制真实设备 (只操作 Mock 环境)
    - 纯规则 + 确定性: 禁止黑盒优化
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.schema import EmbodiedGoal

logger = logging.getLogger(__name__)


class ExecutorError(Exception):
    """执行协调器操作异常"""


class ExecutionCoordinator:
    """执行协调器 (规划 → 执行 → 反馈 → 调整)

    用法:
        executor = ExecutionCoordinator(svc, max_iterations=3)
        record = executor.execute({"title": "拿起台灯", "intent": "pick"})
        loop = executor.close_loop(request)
    """

    def __init__(
        self,
        svc,
        max_iterations: int = 3,
        feedback_enabled: bool = True,
        confirm: bool = False,
    ):
        if max_iterations <= 0:
            raise ExecutorError(
                f"max_iterations 必须 > 0, 当前: {max_iterations}"
            )
        self._lock = threading.RLock()
        self._svc = svc
        self._max_iterations = int(max_iterations)
        self._feedback_enabled = bool(feedback_enabled)
        self._confirm = bool(confirm)
        self._records: List[Dict[str, Any]] = []

    # ── 目标构造 ──────────────────────────────────────────────────
    @staticmethod
    def _make_goal(request: Dict[str, Any]) -> EmbodiedGoal:
        """从请求构造 EmbodiedGoal (可解释)"""
        return EmbodiedGoal.create(
            description=request.get("description", request.get("text", "")),
            intent=request.get("intent", ""),
            target=request.get("target", ""),
            scene=request.get("scene", ""),
            constraints=dict(request.get("constraints", {}) or {}),
            priority=request.get("priority", "medium"),
        )

    # ── 执行 ──────────────────────────────────────────────────────
    def execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """执行入口: 请求 → EmbodiedGoal → run_goal → 执行记录

        Args:
            request: 请求 dict (description/intent/target/scene 等)

        Returns:
            ExecutionRecord:
            {
                'execution_id', 'goal': {...}, 'status', 'success',
                'actions': [...], 'latency_ms', 'feedback': {...},
                'error', 'permission_required': True,
            }
        """
        started = time.perf_counter()
        with self._lock:
            if not isinstance(request, dict) or not request:
                raise ExecutorError("执行请求不能为空")
            goal = self._make_goal(request)
            try:
                result = self._svc.run_goal(goal, confirmed=self._confirm)
            except Exception as e:
                logger.error(f"[Executor] run_goal 异常: {e}")
                record = {
                    "execution_id": "exec_" + uuid.uuid4().hex[:8],
                    "goal": goal.to_dict(),
                    "status": "error",
                    "success": False,
                    "actions": [],
                    "latency_ms": round(
                        (time.perf_counter() - started) * 1000.0, 2,
                    ),
                    "feedback": None,
                    "error": str(e),
                    "permission_required": True,
                }
                self._records.append(record)
                return record
            latency = (time.perf_counter() - started) * 1000.0
            record = {
                "execution_id": "exec_" + uuid.uuid4().hex[:8],
                "goal": goal.to_dict(),
                "status": result.status,
                "success": bool(result.success),
                "actions": (
                    result.to_dict().get("suggestions", [])
                    if hasattr(result, "to_dict") else []
                ),
                "latency_ms": round(latency, 2),
                "feedback": (
                    result.feedback.to_dict()
                    if result.feedback is not None else None
                ),
                "error": result.error,
                "permission_required": True,
            }
            self._records.append(record)
            logger.info(
                f"[Executor] 执行完成: {goal.description[:20]} "
                f"status={result.status} latency={round(latency, 2)}ms"
            )
            return record

    # ── 反馈闭环 ──────────────────────────────────────────────────
    def feedback_loop(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """反馈闭环: 执行结果 → 反馈分析 → 经验更新建议

        Returns:
            {
                'enabled': bool, 'success': bool,
                'experience_update': 'recorded' | 'skipped' | 'no_change',
                'suggestions': [...],   # 调整建议 (可解释)
            }
        """
        with self._lock:
            if not self._feedback_enabled:
                return {
                    "enabled": False, "success": bool(record.get("success")),
                    "experience_update": "skipped",
                    "suggestions": ["反馈闭环已停用"],
                }
            success = bool(record.get("success"))
            # 经验更新: Embodied 既有规则已记录 (run_goal 内)
            # 此处只做闭环统计与调整建议
            suggestions: List[str] = []
            if success:
                suggestions.append("执行成功, 经验已按规则记录")
            else:
                status = record.get("status")
                if status == "denied":
                    suggestions.append(
                        "权限拒绝: 检查 embodied_enabled / 权限配置"
                    )
                else:
                    suggestions.append(
                        "执行失败: 建议重新感知环境后调整目标再试"
                    )
            return {
                "enabled": True,
                "success": success,
                "experience_update": "recorded",
                "suggestions": suggestions,
            }

    # ── 闭环循环 ──────────────────────────────────────────────────
    def close_loop(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """闭环循环: 感知-策略-规划-执行-反馈 (循环上限可配)

        流程 (可解释):
            - 迭代 1..max_iterations:
              执行目标 → 反馈分析 → 成功或达到上限停止
            - 失败时: 记录调整建议 (不自动修改目标内容)

        Returns:
            {
                'loop_id', 'iterations', 'max_iterations',
                'success', 'executions': [...], 'feedbacks': [...],
                'final_status', 'explainable_reason', 'mode': 'rule_based',
            }
        """
        with self._lock:
            executions: List[Dict[str, Any]] = []
            feedbacks: List[Dict[str, Any]] = []
            success = False
            final_status = "pending"
            for i in range(1, self._max_iterations + 1):
                record = self.execute(request)
                executions.append(record)
                fb = self.feedback_loop(record)
                feedbacks.append(fb)
                if record["success"]:
                    success = True
                    final_status = record["status"]
                    break
                final_status = record["status"]
                # 权限拒绝不可重试
                if record["status"] == "denied":
                    break
            reason_lines = [
                f"闭环执行: {len(executions)}/{self._max_iterations} 轮, "
                f"{'成功' if success else '未成功'} (最终状态 {final_status})",
            ]
            for i, (rec, fb) in enumerate(zip(executions, feedbacks), 1):
                reason_lines.append(
                    f"  轮次{i}: {rec['status']} "
                    f"({rec.get('latency_ms', 0)}ms) "
                    f"- {fb['suggestions'][0] if fb['suggestions'] else ''}"
                )
            return {
                "loop_id": "loop_" + uuid.uuid4().hex[:8],
                "iterations": len(executions),
                "max_iterations": self._max_iterations,
                "success": success,
                "executions": executions,
                "feedbacks": feedbacks,
                "final_status": final_status,
                "explainable_reason": "\n".join(reason_lines),
                "mode": "rule_based",
            }

    # ── 执行审计 ──────────────────────────────────────────────────
    def audit(self, limit: int = 50) -> Dict[str, Any]:
        """执行审计: 全部执行记录统计

        Args:
            limit: 近期记录条数 (0=全部)
        """
        with self._lock:
            records = list(self._records)
        total = len(records)
        ok = sum(1 for r in records if r["success"])
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": total,
            "success_count": ok,
            "fail_count": total - ok,
            "success_rate": round(ok / total, 4) if total else 0.0,
            "recent": recent,
        }

    def clear(self) -> int:
        """清空执行记录 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "max_iterations": self._max_iterations,
                "feedback_enabled": self._feedback_enabled,
                "confirm": self._confirm,
            }


__all__ = [
    "ExecutorError",
    "ExecutionCoordinator",
]
