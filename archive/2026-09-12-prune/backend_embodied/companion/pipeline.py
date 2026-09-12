"""
YHLZ Embodied AI V5.3 - Agent 数据管道 (Agent Data Pipeline)

职责:
    - 管道定义: 前序 Agent 输出 → 后序 Agent 输入 (顺序依赖)
    - 管道分析: 依赖顺序 / 阶段明细 (可解释)
    - 感知-策略闭环: perception → experience → planning (V5.2)
    - 执行闭环管道: + execution → feedback (V5.3)

数据模型:
    PipelineStage:
    {
        stage, source (前序 Agent 名), target (后序 Agent 名),
        input_from (前序输出字段), output_to (后序输入字段),
        reason (可解释),
    }

管道规则 (可解释, 确定性):
    - 感知-策略闭环管道 (DEFAULT_PIPELINE):
      Stage 1: perception → experience (环境状态 → 策略建议输入)
      Stage 2: experience → planning (策略建议 → 规划输入)
    - 执行闭环管道 (LOOP_PIPELINE):
      Stage 3: planning → execution (规划结果 → 执行输入)
    - 管道启用: companion_pipeline_enabled (默认 True)
    - 严格模式: companion_pipeline_strict (默认 False,
      输入缺失 → 报错; False 时缺失输入 → 后序 Agent 用空输入)

设计原则:
    - 纯规则管道 (确定性, 禁止自由协商)
    - 可解释: 每阶段输出 source/target/input_from/output_to/reason
    - 管道只传数据 (不执行动作, 不写 Agent Memory)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Agent 数据管道操作异常"""


# 默认感知-策略闭环管道 (可解释)
DEFAULT_PIPELINE: List[Dict[str, Any]] = [
    {
        "stage": 1,
        "source": "perception_agent",
        "target": "experience_agent",
        "input_from": "data",
        "output_to": "env_state",
        "reason": "感知环境状态 → 供经验 Agent 生成策略建议",
    },
    {
        "stage": 2,
        "source": "experience_agent",
        "target": "planning_agent",
        "input_from": "data",
        "output_to": "strategy_suggestions",
        "reason": "策略建议 → 供规划 Agent 作为规划输入",
    },
]

# V5.3 闭环管道 (感知-策略-规划-执行-反馈)
LOOP_PIPELINE: List[Dict[str, Any]] = [
    {
        "stage": 1,
        "source": "perception_agent",
        "target": "experience_agent",
        "input_from": "data",
        "output_to": "env_state",
        "reason": "感知环境状态 → 供经验 Agent 生成策略建议",
    },
    {
        "stage": 2,
        "source": "experience_agent",
        "target": "planning_agent",
        "input_from": "data",
        "output_to": "strategy_suggestions",
        "reason": "策略建议 → 供规划 Agent 作为规划输入",
    },
    {
        "stage": 3,
        "source": "planning_agent",
        "target": "execution_agent",
        "input_from": "data",
        "output_to": "plan_result",
        "reason": "规划结果 → 供执行 Agent 执行目标 (经 Permission)",
    },
]

# V5.3 闭环管道 (感知-策略-规划-执行-反馈)
LOOP_PIPELINE: List[Dict[str, Any]] = [
    {
        "stage": 1,
        "source": "perception_agent",
        "target": "experience_agent",
        "input_from": "data",
        "output_to": "env_state",
        "reason": "感知环境状态 → 供经验 Agent 生成策略建议",
    },
    {
        "stage": 2,
        "source": "experience_agent",
        "target": "planning_agent",
        "input_from": "data",
        "output_to": "strategy_suggestions",
        "reason": "策略建议 → 供规划 Agent 作为规划输入",
    },
    {
        "stage": 3,
        "source": "planning_agent",
        "target": "execution_agent",
        "input_from": "data",
        "output_to": "plan_result",
        "reason": "规划结果 → 供执行 Agent 执行目标 (经 Permission)",
    },
]


class AgentPipeline:
    """Agent 数据管道 (前序输出 → 后序输入)

    用法:
        pipeline = AgentPipeline()
        stages = pipeline.pipeline_stages()
        analysis = pipeline.analyze()
        enriched = pipeline.apply(request, results)
    """

    def __init__(
        self,
        stages: Optional[List[Dict[str, Any]]] = None,
        enabled: bool = True,
        strict: bool = False,
    ):
        self._lock = threading.RLock()
        self._stages = list(stages or DEFAULT_PIPELINE)
        self._enabled = bool(enabled)
        self._strict = bool(strict)

    # ── 管道状态 ──────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def strict(self) -> bool:
        with self._lock:
            return self._strict

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)

    def set_strict(self, strict: bool) -> None:
        with self._lock:
            self._strict = bool(strict)

    # ── 管道分析 ──────────────────────────────────────────────────
    def pipeline_stages(self) -> List[Dict[str, Any]]:
        """管道阶段明细 (按执行顺序)"""
        with self._lock:
            return [dict(s) for s in self._stages]

    def analyze(self) -> Dict[str, Any]:
        """管道分析: 依赖顺序 / 阶段明细 / 可解释

        Returns:
            {
                'enabled': bool, 'strict': bool,
                'stages': [...],            # PipelineStage 明细
                'execution_order': [...],   # 去重后按依赖排序的 Agent 名
                'dependencies': [...],      # (target, source) 依赖对
                'reason': ...,              # 可解释
            }
        """
        with self._lock:
            order: List[str] = []
            seen: set = set()
            deps: List[Dict[str, str]] = []
            for s in self._stages:
                src, tgt = s.get("source", ""), s.get("target", "")
                if src and src not in seen:
                    order.append(src)
                    seen.add(src)
                if tgt and tgt not in seen:
                    order.append(tgt)
                    seen.add(tgt)
                if src and tgt:
                    deps.append({"target": tgt, "source": src})
            return {
                "enabled": self._enabled,
                "strict": self._strict,
                "stages": [dict(s) for s in self._stages],
                "execution_order": order,
                "dependencies": deps,
                "reason": (
                    f"管道 {'启用' if self._enabled else '停用'} "
                    f"({'严格' if self._strict else '宽松'}模式): "
                    f"{len(self._stages)} 个阶段, "
                    f"执行顺序 {', '.join(order)}"
                ),
            }

    # ── 数据传递 ──────────────────────────────────────────────────
    def apply(
        self,
        request: Dict[str, Any],
        results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """将前序 Agent 结果注入请求 (供后序 Agent 使用)

        Args:
            request: 原始请求 (不修改, 返回新 dict)
            results: {agent_name: agent_result}

        Returns:
            增强后的请求 (含管道注入字段)

        Raises:
            PipelineError: 严格模式下已执行的前序结果缺失/无数据
                (未执行的前序不报错, 由执行方保证顺序)
        """
        with self._lock:
            enriched = dict(request)
            for s in self._stages:
                src, tgt = s.get("source", ""), s.get("target", "")
                input_from = s.get("input_from", "data")
                output_to = s.get("output_to", "pipeline_input")
                src_result = results.get(src)
                if src_result is None:
                    # 前序尚未执行: 跳过 (由执行方按阶段顺序调用)
                    continue
                if not src_result.get("ok"):
                    if self._strict:
                        raise PipelineError(
                            f"严格模式: 前序 Agent {src} 执行失败, "
                            f"无法向 {tgt} 传递 ({output_to})"
                        )
                    enriched[output_to] = None
                    continue
                payload = (src_result.get("result") or {}).get(input_from)
                if payload is None:
                    if self._strict:
                        raise PipelineError(
                            f"严格模式: {src} 输出缺少字段 {input_from}, "
                            f"无法向 {tgt} 传递"
                        )
                    enriched[output_to] = None
                    continue
                enriched[output_to] = payload
                # 后序 Agent 可通过该字段读取前序结果
            return enriched

    # ── 管道参与判定 ──────────────────────────────────────────────
    def involved_agents(self) -> List[str]:
        """管道涉及的 Agent 名 (去重, 按依赖顺序)"""
        with self._lock:
            return self.analyze()["execution_order"]

    def has_stage(self, source: str, target: str) -> bool:
        """是否存在指定阶段"""
        with self._lock:
            return any(
                s.get("source") == source and s.get("target") == target
                for s in self._stages
            )


__all__ = [
    "AgentPipeline",
    "DEFAULT_PIPELINE",
    "LOOP_PIPELINE",
    "PipelineError",
]
