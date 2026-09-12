"""
YHLZ Embodied AI V5.9 - 创造推理引擎 (Creative Reasoning Engine)

职责:
    - 不是生成器, 是创造推理系统
    - 寻找: 当前状态 → 理想状态 → 差距 → 可能路径
    - 输出推理链:
      {current_state, desired_state, gap, paths[], confidence}

路径类型 (可解释):
    - automation:           自动化 (重复需求 → 自动化工具/流程)
    - optimization:         优化 (反复失败 → 方案优化)
    - new_capability:       新能力 (缺失能力 → 新增能力)
    - personalization:      个性化 (关系偏好 → 个性化服务)
    - process_improvement:  流程改进 (兜底路径)

设计原则:
    - 推理必须基于机会证据 (可回溯)
    - 纯规则推理 (禁止黑盒)
    - 每条路径含证据与置信度
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReasoningError(Exception):
    """创造推理操作异常"""


# 路径类型白名单 (可解释)
PATH_TYPES: List[str] = [
    "automation",            # 自动化
    "optimization",          # 优化
    "new_capability",        # 新能力
    "personalization",       # 个性化
    "process_improvement",   # 流程改进
]

# 关键词 → 路径类型 (可解释)
PATH_KEYWORDS: Dict[str, List[str]] = {
    "automation": ["重复", "每次", "总是", "一直", "手工", "手动",
                   "模板", "自动"],
    "optimization": ["失败", "出错", "错误", "失败率", "重试",
                     "规避", "无效"],
    "new_capability": ["新", "需要", "想要", "缺少", "没有",
                       "缺少能力"],
    "personalization": ["喜欢", "偏好", "信任", "习惯", "常做",
                        "个性化"],
}


class CreativeReasoningEngine:
    """创造推理引擎 (当前状态 → 差距 → 可能路径)

    用法:
        engine = CreativeReasoningEngine()
        result = engine.reason(opportunity)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._results: List[Dict[str, Any]] = []

    # ── 推理主入口 ────────────────────────────────────────────────
    def reason(
        self,
        opportunity: Dict[str, Any],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """创造推理 (规则驱动, 可解释)

        Args:
            opportunity: Opportunity Candidate

        Returns:
            {
                'reasoning_id', 'opportunity_id',
                'current_state', 'desired_state', 'gap',
                'paths': [...], 'confidence', 'mode',
                'reasoned_at',
            }
        """
        with self._lock:
            if not opportunity or not opportunity.get("opportunity_id"):
                raise ReasoningError("机会候选无效: 缺 opportunity_id")
            now = now if now is not None else time.time()
            paths = self._infer_paths(opportunity)
            confidence = self._reasoning_confidence(
                opportunity, paths,
            )
            result = {
                "reasoning_id": "rsn_" + uuid.uuid4().hex[:8],
                "opportunity_id": opportunity["opportunity_id"],
                "current_state": opportunity.get("current_state", ""),
                "desired_state": opportunity.get("desired_state", ""),
                "gap": opportunity.get("gap", ""),
                "paths": paths,
                "confidence": round(confidence, 4),
                "mode": "rule_based",
                "reasoned_at": now,
            }
            self._results.append(result)
            return dict(result)

    # ── 路径推理 (可解释) ────────────────────────────────────────
    def _infer_paths(
        self, opportunity: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """推断可能路径: 来源类型 + 关键词匹配"""
        source = opportunity.get("source_type", "")
        text = " ".join([
            str(opportunity.get("trigger", "")),
            str(opportunity.get("problem", "")),
            str(opportunity.get("gap", "")),
        ])
        evidence = opportunity.get("evidence", []) or []
        paths: List[Dict[str, Any]] = []
        # 来源类型直接映射
        source_paths = {
            "repetition": "automation",
            "failure": "optimization",
            "pattern": "process_improvement",
            "relationship": "personalization",
            "improvement": "process_improvement",
        }
        primary = source_paths.get(source, "process_improvement")
        paths.append(self._build_path(
            path_type=primary,
            trigger=opportunity.get("trigger", ""),
            evidence=evidence,
            confidence=self._path_confidence(
                primary, opportunity,
            ),
        ))
        # 关键词补充路径 (不重复)
        for path_type, keywords in PATH_KEYWORDS.items():
            if path_type == primary:
                continue
            if any(k in text for k in keywords):
                paths.append(self._build_path(
                    path_type=path_type,
                    trigger=opportunity.get("trigger", ""),
                    evidence=evidence,
                    confidence=self._path_confidence(
                        path_type, opportunity,
                    ) - 0.1,
                ))
        # 兜底: 至少一条主路径
        return paths[:3]

    @staticmethod
    def _build_path(
        path_type: str, trigger: str, evidence: List[str],
        confidence: float,
    ) -> Dict[str, Any]:
        """构建路径描述"""
        descriptions = {
            "automation": (
                f"将 '{trigger}' 封装为可复用自动化流程/工具"
            ),
            "optimization": (
                f"针对 '{trigger}' 失败点优化执行方案"
            ),
            "new_capability": (
                f"为 '{trigger}' 新增能力模块"
            ),
            "personalization": (
                f"按用户偏好定制 '{trigger}' 的个性化响应"
            ),
            "process_improvement": (
                f"改进 '{trigger}' 相关流程与步骤"
            ),
        }
        return {
            "path_id": "path_" + uuid.uuid4().hex[:6],
            "type": path_type,
            "description": descriptions.get(
                path_type, f"改进 '{trigger}'",
            ),
            "evidence": list(evidence),
            "confidence": round(max(0.05, confidence), 4),
        }

    @staticmethod
    def _path_confidence(
        path_type: str, opportunity: Dict[str, Any],
    ) -> float:
        """路径置信度: 主路径较高 + 证据加成"""
        base = 0.5 if path_type == "process_improvement" else 0.55
        n = len(opportunity.get("evidence", []) or [])
        return min(0.95, base + 0.1 * n)

    @staticmethod
    def _reasoning_confidence(
        opportunity: Dict[str, Any], paths: List[Dict[str, Any]],
    ) -> float:
        """推理置信度: 机会置信度 + 路径覆盖"""
        opp_conf = float(opportunity.get("confidence", 0.0))
        path_score = min(1.0, len(paths) / 2.0) * 0.2
        return min(0.98, opp_conf * 0.8 + path_score)

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, reasoning_id: str) -> Optional[Dict[str, Any]]:
        """查询推理结果"""
        with self._lock:
            for r in self._results:
                if r["reasoning_id"] == reasoning_id:
                    return dict(r)
            return None

    def by_opportunity(
        self, opportunity_id: str,
    ) -> List[Dict[str, Any]]:
        """按机会查询推理"""
        with self._lock:
            return [
                dict(r) for r in self._results
                if r["opportunity_id"] == opportunity_id
            ]

    def stats(self) -> Dict[str, Any]:
        """推理统计"""
        with self._lock:
            results = list(self._results)
        path_types: Dict[str, int] = {}
        for r in results:
            for p in r["paths"]:
                path_types[p["type"]] = path_types.get(
                    p["type"], 0,
                ) + 1
        return {
            "mode": "rule_based",
            "reasoning_count": len(results),
            "avg_paths": round(
                sum(len(r["paths"]) for r in results) / len(results)
                if results else 0.0, 2,
            ),
            "by_path_type": path_types,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "PATH_KEYWORDS",
    "PATH_TYPES",
    "CreativeReasoningEngine",
    "ReasoningError",
]
