"""
YHLZ Embodied AI V5.2 - 任务委派与结果汇总 (Task Delegation & Aggregation)

职责:
    - 委派: 按路由结果将请求分派给专业 Agent (确定性)
    - 并发委派: 无依赖专业 Agent 线程池并行处理 (可配置 workers)
    - 超时控制: 单 Agent 超时 → 标记 timeout 错误 (不阻塞整体)
    - 耗时统计: 总耗时 / 每 Agent 耗时 (可解释)
    - 结果汇总: 聚合各 Agent 输出为完整响应 (CompanionResponse)
    - 管道感知委派: 前序 Agent 结果 → 后序 Agent 输入 (V5.2)
    - 异常隔离: 单个 Agent 失败不影响整体 (错误捕获 + 标记)

数据模型:
    CompanionResponse:
    {
        request_id, intent, assigned_agents, results,
        aggregated, explainable_reason, mode: "rule_based",
        dispatched_parallel: bool, total_latency_ms: float,
        per_agent_latency_ms: [...],
        pipeline: {...}, pipeline_stages: [...],   # V5.2 管道明细
    }

设计原则:
    - 并发委派 (线程池) 但结果按路由顺序稳定输出
    - 管道依赖: 前序 Agent 完成后才执行后序 Agent (顺序保证)
    - 每个 Agent 结果保留独立 (results), 汇总结构统一 (aggregated)
    - 可解释: 委派顺序 + 管道阶段 + 每个结果摘要 + 耗时
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from backend.embodied.companion.pipeline import AgentPipeline, PipelineError
from backend.embodied.companion.router import CompanionRouter
from backend.embodied.companion.specialist import SpecialistRegistry

logger = logging.getLogger(__name__)


class DelegateError(Exception):
    """任务委派操作异常"""


class TaskDelegator:
    """任务委派器 (路由 → 管道感知委派 → 汇总)

    用法:
        delegator = TaskDelegator(router, workers=4, timeout=10.0)
        response = delegator.delegate(request)
    """

    def __init__(
        self,
        router: CompanionRouter,
        timeout: float = 10.0,
        workers: int = 4,
        pipeline: Optional[AgentPipeline] = None,
    ):
        if not isinstance(router, CompanionRouter):
            raise DelegateError("委派需要 CompanionRouter")
        if workers <= 0:
            raise DelegateError(f"workers 必须 > 0, 当前: {workers}")
        if timeout <= 0:
            raise DelegateError(f"timeout 必须 > 0, 当前: {timeout}")
        self._lock = threading.RLock()
        self._router = router
        self._timeout = float(timeout)
        self._workers = int(workers)
        self._pipeline = pipeline or AgentPipeline()
        self._executor = ThreadPoolExecutor(
            max_workers=self._workers,
            thread_name_prefix="companion",
        )

    # ── 单 Agent 执行 (带超时) ────────────────────────────────────
    def _invoke_one(
        self,
        agent_name: str,
        request: Dict[str, Any],
        timeout: float,
    ) -> Dict[str, Any]:
        """单 Agent 调用 (超时控制, 不抛异常)"""
        registry = self._router._registry
        agent = registry.get(agent_name)
        if agent is None:
            return {
                "agent": agent_name, "capability": "",
                "ok": False, "error": "专业 Agent 未注册",
                "result": None, "latency_ms": 0.0,
            }
        if not agent.enabled:
            return {
                "agent": agent_name, "capability": agent.capability,
                "ok": False, "error": "专业 Agent 已停用",
                "result": None, "latency_ms": 0.0,
            }
        started = time.perf_counter()
        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="companion_one",
        ) as one:
            future: Future = one.submit(agent.invoke, request)
            try:
                result = future.result(timeout=timeout)
            except Exception as e:
                latency = (time.perf_counter() - started) * 1000.0
                return {
                    "agent": agent_name, "capability": agent.capability,
                    "ok": False, "error": f"超时/异常: {e}",
                    "result": None, "latency_ms": round(latency, 2),
                }
        latency = (time.perf_counter() - started) * 1000.0
        ok = "error" not in result
        return {
            "agent": agent_name, "capability": agent.capability,
            "ok": ok, "error": result.get("error"),
            "result": result, "latency_ms": round(latency, 2),
        }

    # ── 委派 ──────────────────────────────────────────────────────
    def delegate(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """委派请求 → 专业 Agent (并发 + 管道) → 汇总响应

        Args:
            request: 请求 dict (text/intent/query + 附加参数)

        Returns:
            CompanionResponse:
            {
                'request_id', 'intent', 'assigned_agents',
                'results': [...], 'aggregated': {...},
                'dispatched_parallel': bool, 'total_latency_ms': float,
                'per_agent_latency_ms': [...],
                'pipeline': {...}, 'pipeline_stages': [...],
                'explainable_reason', 'mode',
            }
        """
        started = time.perf_counter()
        with self._lock:
            route = self._router.route(request)
            assigned = route["assigned_agents"]
            pipeline_on = self._pipeline.enabled
            parallel = len(assigned) > 1
            # 管道阶段执行 (V5.2): 感知-策略-规划按依赖顺序
            stage_exec: List[Dict[str, Any]] = []
            if pipeline_on and self._pipeline.has_stage(
                "perception_agent", "experience_agent",
            ):
                stage_exec = self._run_pipeline_stages(
                    request, assigned,
                )
            if stage_exec:
                # 管道执行后: results 已按顺序填好 (含管道注入)
                results = stage_exec
                pipeline_used = self._pipeline.analyze()
            else:
                # 常规委派 (无管道/管道未命中): 并发或顺序
                results = self._dispatch(request, assigned, parallel)
                pipeline_used = None
            # 补充未执行 Agent (管道未覆盖的路由 Agent)
            executed_names = {r["agent"] for r in results}
            for name in assigned:
                if name not in executed_names:
                    results.append(self._invoke_one(
                        name, request, self._timeout,
                    ))
            # 汇总
            total_latency = (time.perf_counter() - started) * 1000.0
            aggregated = self._aggregate(results)
            mode_desc = "管道" if pipeline_used else ("并行" if parallel else "顺序")
            reason_lines = [
                f"委派顺序: {', '.join(r['agent'] for r in results)} "
                f"({mode_desc}, 总耗时 {round(total_latency, 2)}ms)",
            ]
            for r in results:
                status = "成功" if r["ok"] else f"失败 ({r.get('error')})"
                reason_lines.append(
                    f"  [{r['agent']}] {r['capability']}: {status} "
                    f"({r.get('latency_ms', 0)}ms)"
                )
            if pipeline_used:
                for s in pipeline_used["stages"]:
                    reason_lines.append(
                        f"  [管道] 阶段{s['stage']}: "
                        f"{s['source']} → {s['target']} ({s['reason']})"
                    )
            return {
                "request_id": "req_" + uuid.uuid4().hex[:8],
                "intent": route["request_text"],
                "assigned_agents": assigned,
                "results": results,
                "aggregated": aggregated,
                "dispatched_parallel": parallel,
                "total_latency_ms": round(total_latency, 2),
                "per_agent_latency_ms": [
                    {"agent": r["agent"],
                     "latency_ms": r.get("latency_ms", 0.0)}
                    for r in results
                ],
                "pipeline": pipeline_used,
                "pipeline_stages": (
                    pipeline_used["stages"] if pipeline_used else []
                ),
                "explainable_reason": "\n".join(reason_lines),
                "mode": "rule_based",
            }

    # ── 常规委派 (并发/顺序) ──────────────────────────────────────
    def _dispatch(
        self,
        request: Dict[str, Any],
        assigned: List[str],
        parallel: bool,
    ) -> List[Dict[str, Any]]:
        """常规委派: 并发或顺序执行全部 Agent"""
        results: List[Dict[str, Any]] = [None] * len(assigned)

        def run(idx: int, agent_name: str) -> None:
            results[idx] = self._invoke_one(
                agent_name, request, self._timeout,
            )

        if parallel and len(assigned) > 1:
            futures: List[Future] = []
            for i, name in enumerate(assigned):
                futures.append(self._executor.submit(run, i, name))
            for f in futures:
                try:
                    f.result(timeout=self._timeout + 1.0)
                except Exception as e:
                    logger.warning(f"[Delegate] 委派异常: {e}")
            for i, name in enumerate(assigned):
                if results[i] is None:
                    results[i] = {
                        "agent": name, "capability": "",
                        "ok": False, "error": "委派执行失败",
                        "result": None, "latency_ms": 0.0,
                    }
        else:
            for i, name in enumerate(assigned):
                results[i] = self._invoke_one(name, request, self._timeout)
        return results

    # ── 管道阶段执行 (V5.2) ───────────────────────────────────────
    def _run_pipeline_stages(
        self,
        request: Dict[str, Any],
        assigned: List[str],
    ) -> List[Dict[str, Any]]:
        """管道阶段执行: 前序 Agent 结果 → 后序 Agent 输入

        规则 (可解释):
            - 按管道阶段顺序执行
            - 阶段内: 前序结果注入请求 → 后序 Agent 执行
            - 严格模式: 前序无结果 → PipelineError; 宽松: 传 None
        """
        stages = self._pipeline.pipeline_stages()
        order = self._pipeline.involved_agents()
        # 只执行管道涉及且被路由分派的 Agent
        targets = [s["target"] for s in stages]
        targets += [s["source"] for s in stages]
        involved = [a for a in order if a in assigned]
        results_map: Dict[str, Dict[str, Any]] = {}
        results: List[Dict[str, Any]] = []
        current_request = dict(request)
        try:
            for s in stages:
                src, tgt = s.get("source", ""), s.get("target", "")
                # 执行前序 (若尚未执行且被分派)
                if src in assigned and src not in results_map:
                    r = self._invoke_one(src, current_request, self._timeout)
                    results_map[src] = r
                    results.append(r)
                # 注入前序结果 → 后序输入
                current_request = self._pipeline.apply(
                    current_request, results_map,
                )
                # 执行后序 (若被分派)
                if tgt in assigned and tgt not in results_map:
                    r = self._invoke_one(tgt, current_request, self._timeout)
                    results_map[tgt] = r
                    results.append(r)
        except PipelineError as e:
            logger.warning(f"[Pipeline] 管道异常: {e}")
            # 宽松模式兜底: 未执行的后序 Agent 标记错误
            for a in involved:
                if a not in results_map:
                    results.append({
                        "agent": a, "capability": "",
                        "ok": False, "error": f"管道异常: {e}",
                        "result": None, "latency_ms": 0.0,
                    })
        return results

    # ── 汇总 ──────────────────────────────────────────────────────
    @staticmethod
    def _aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """结果汇总 (统一结构, 可解释)"""
        ok_count = sum(1 for r in results if r["ok"])
        fail_count = len(results) - ok_count
        payloads: List[Dict[str, Any]] = []
        for r in results:
            if r["ok"] and r.get("result"):
                payloads.append({
                    "agent": r["agent"],
                    "capability": r["capability"],
                    "result": r["result"],
                })
        return {
            "total": len(results),
            "ok_count": ok_count,
            "fail_count": fail_count,
            "all_ok": fail_count == 0 and len(results) > 0,
            "payloads": payloads,
        }

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "timeout": self._timeout,
                "workers": self._workers,
                "rule_version": self._router._rule_version,
                "pipeline_enabled": self._pipeline.enabled,
                "pipeline_strict": self._pipeline.strict,
            }

    @property
    def pipeline(self) -> AgentPipeline:
        with self._lock:
            return self._pipeline

    def shutdown(self) -> None:
        """关闭线程池 (测试清理)"""
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass


__all__ = [
    "DelegateError",
    "TaskDelegator",
]
