"""
YHLZ Embodied AI V5.1 - 内部消息路由 (Internal Message Router)

职责:
    - 路由分析: 请求意图 → 专业 Agent (确定性规则)
    - 关键词映射: 意图关键词 → 能力域 (可解释)
    - 关键词权重打分: 多关键词加权 (确定性, 可解释分数)
    - Top-K 路由: 按得分取前 N 个能力域 (可配置)
    - 路由回退: 无法识别意图 → 默认委派 (可解释)

规则 (可解释, 确定性):
    - 意图关键词表 (v1) + 关键词权重:
      - 精确/复合词权重 3.0 (如 "长期目标" / "为什么失败" / "多目标")
      - 核心词权重 2.0 (如 "规划" / "整理" / "治理" / "扫描")
      - 普通词权重 1.0 (如 "历史" / "状态" / "审计")
    - 能力域得分 = 命中关键词权重之和
    - 多关键词命中 → 按得分降序取 Top-K (默认 3)
    - 无命中 → 默认回退: 返回感知 + 经验 (基础上下文)

设计原则:
    - 纯规则加权映射 (确定性, 可测试, 禁止黑盒)
    - 可解释: 每个命中输出 关键词 → 权重 → 能力域 → 得分
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

from backend.embodied.companion.specialist import (
    SPECIALIST_CAPABILITIES,
    SpecialistRegistry,
)

logger = logging.getLogger(__name__)


class RouterError(Exception):
    """内部消息路由操作异常"""


# 意图关键词 → 能力域 (可解释规则表 v1)
INTENT_KEYWORDS: Dict[str, List[str]] = {
    "perception": [
        "观察", "扫描", "环境", "场景", "状态", "感知", "查看环境",
        "observe", "scan", "scene", "state", "perception",
    ],
    "reasoning": [
        "为什么", "为啥", "原因", "预测", "因果", "分析", "推理",
        "解释", "怎么回事", "咋回事", "为什么失败",
        "why", "cause", "predict", "reason",
    ],
    "experience": [
        "策略", "经验", "建议", "教训", "历史", "回忆", "复用",
        "policy", "experience", "suggest", "lesson",
    ],
    "planning": [
        "规划", "预算", "调度", "协调", "多目标", "分组", "计划",
        "plan", "budget", "schedule", "coordinate",
    ],
    "long_horizon": [
        "长期", "任务", "里程碑", "进度", "整理", "学习", "项目",
        "长期目标", "分阶段",
        "long", "mission", "milestone", "progress", "organize",
    ],
    "governance": [
        "治理", "健康", "冗余", "冲突", "归档", "回收", "审计",
        "回滚", "同化", "分裂",
        "governance", "health", "redundant", "conflict", "audit",
    ],
    "execution": [
        "执行", "动作", "动手", "操作", "执行目标", "执行任务",
        "execute", "action", "run", "do",
    ],
}

# 关键词权重 (可解释: 复合/核心词更高分, 普通词低分)
KEYWORD_WEIGHTS: Dict[str, float] = {
    # 复合/精确词 (3.0)
    "长期目标": 3.0, "为什么失败": 3.0, "多目标": 3.0,
    "查看环境": 3.0, "分阶段": 3.0, "怎么回事": 3.0, "咋回事": 3.0,
    # 核心词 (2.0)
    "观察": 2.0, "扫描": 2.0, "感知": 2.0, "预测": 2.0, "推理": 2.0,
    "因果": 2.0, "策略": 2.0, "经验": 2.0, "建议": 2.0, "规划": 2.0,
    "预算": 2.0, "调度": 2.0, "协调": 2.0, "整理": 2.0, "学习": 2.0,
    "项目": 2.0, "里程碑": 2.0, "进度": 2.0, "治理": 2.0, "健康": 2.0,
    "冗余": 2.0, "冲突": 2.0, "归档": 2.0, "回滚": 2.0, "同化": 2.0,
    "observe": 2.0, "scan": 2.0, "predict": 2.0, "reason": 2.0,
    "policy": 2.0, "experience": 2.0, "plan": 2.0, "budget": 2.0,
    "organize": 2.0, "milestone": 2.0, "governance": 2.0, "health": 2.0,
    "redundant": 2.0, "conflict": 2.0,
    "执行": 2.0, "动作": 2.0, "execute": 2.0, "action": 2.0,
    "run": 2.0,
    # 普通词 (1.0, 默认)
}

# 默认关键词权重 (未在表内的词)
DEFAULT_KEYWORD_WEIGHT: float = 1.0

# 路由回退: 无法识别意图时的默认能力域 (可解释)
FALLBACK_CAPABILITIES: List[str] = ["perception", "experience"]

# 路由规则版本 (配置驱动)
ROUTE_RULE_VERSION = "v1"

# 默认 Top-K 路由数
DEFAULT_ROUTE_TOP_K: int = 3

# 路由规则版本 (配置驱动)
ROUTE_RULE_VERSION = "v1"


class CompanionRouter:
    """内部消息路由器 (意图 → 专业 Agent)

    用法:
        router = CompanionRouter(registry)
        route = router.route("帮我整理房间")
    """

    def __init__(
        self,
        registry: SpecialistRegistry,
        rule_version: str = ROUTE_RULE_VERSION,
        top_k: int = DEFAULT_ROUTE_TOP_K,
    ):
        if not isinstance(registry, SpecialistRegistry):
            raise RouterError("路由需要 SpecialistRegistry")
        if top_k <= 0:
            raise RouterError(f"top_k 必须 > 0, 当前: {top_k}")
        self._lock = threading.RLock()
        self._registry = registry
        self._rule_version = rule_version
        self._top_k = int(top_k)

    # ── 意图 → 能力域 (确定性加权打分) ────────────────────────────
    def detect_capabilities(self, text: str) -> List[Dict[str, Any]]:
        """意图关键词 → 能力域 (加权打分, 可解释命中列表)

        规则 (确定性):
            - 每个能力域收集全部命中关键词
            - 能力域得分 = 命中关键词权重之和 (KEYWORD_WEIGHTS)
            - 未在权重表的词按 DEFAULT_KEYWORD_WEIGHT (1.0)
        """
        with self._lock:
            text = (text or "").lower()
            scored: List[Dict[str, Any]] = []
            for capability in SPECIALIST_CAPABILITIES:
                matched: List[Dict[str, Any]] = []
                total = 0.0
                for kw in INTENT_KEYWORDS.get(capability, []):
                    if kw in text:
                        weight = KEYWORD_WEIGHTS.get(kw, DEFAULT_KEYWORD_WEIGHT)
                        total += weight
                        matched.append({
                            "keyword": kw, "weight": weight,
                        })
                if matched:
                    scored.append({
                        "capability": capability,
                        "score": round(total, 2),
                        "keywords": matched,
                        "reason": (
                            f"命中 {len(matched)} 个关键词 "
                            f"(权重和 {round(total, 2)}): "
                            + ", ".join(
                                f"'{m['keyword']}'={m['weight']}"
                                for m in matched
                            )
                        ),
                    })
            # 得分降序 (确定性排序, 同分按能力域顺序)
            scored.sort(key=lambda h: (-h["score"],
                                       SPECIALIST_CAPABILITIES.index(
                                           h["capability"]
                                       )))
            return scored

    # ── 路由 ──────────────────────────────────────────────────────
    def route(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """路由分析: 请求 → 专业 Agent 列表

        Args:
            request: 请求 dict (含 text / intent / query 等)

        Returns:
            {
                'request_text': ...,
                'rule_version': 'v1',
                'capabilities': [...],      # 命中的能力域 (Top-K)
                'scores': [...],            # 能力域得分 (可解释)
                'weighted_keywords': [...], # 加权关键词明细
                'assigned_agents': [...],   # 分派的专业 Agent 名
                'fallback': bool,
                'reason': ...,              # 可解释原因
            }
        """
        with self._lock:
            text = self._extract_text(request)
            hits = self.detect_capabilities(text)
            fallback = False
            if not hits:
                fallback = True
                # 回退: 默认能力域 (分数 1.0 标记)
                fallback_hits = [
                    {
                        "capability": cap, "score": 1.0,
                        "keywords": [{"keyword": "(回退)", "weight": 1.0}],
                        "reason": "无关键词命中, 回退默认委派",
                    }
                    for cap in FALLBACK_CAPABILITIES
                ]
                hits = fallback_hits
            # Top-K: 按得分取前 N 个能力域
            top_hits = hits[:self._top_k]
            capabilities = [h["capability"] for h in top_hits]
            # 分派: 每个能力域取已启用 Agent (可能多个)
            assigned: List[str] = []
            for cap in capabilities:
                for agent in self._registry.by_capability(cap):
                    assigned.append(agent.name)
            if not assigned:
                assigned = ["<无已启用专业 Agent>"]
            return {
                "request_text": text,
                "rule_version": self._rule_version,
                "capabilities": capabilities,
                "scores": [
                    {"capability": h["capability"], "score": h["score"]}
                    for h in top_hits
                ],
                "weighted_keywords": [
                    {"capability": h["capability"],
                     "keywords": h["keywords"]}
                    for h in top_hits
                ],
                "assigned_agents": assigned,
                "fallback": fallback,
                "reason": (
                    f"路由规则 {self._rule_version} (Top-{self._top_k}): "
                    + (
                        "; ".join(
                            f"{h['capability']} 得分 {h['score']}"
                            for h in top_hits
                        ) if top_hits else "无命中"
                    )
                    + (", 回退默认委派" if fallback else "")
                    + f", 分派 {len(assigned)} 个专业 Agent"
                ),
            }

    @staticmethod
    def _extract_text(request: Dict[str, Any]) -> str:
        """从请求提取意图文本"""
        if not isinstance(request, dict):
            return str(request or "")
        for key in ("text", "intent", "query", "request", "description"):
            if request.get(key):
                return str(request[key])
        return " ".join(str(v) for v in request.values())


__all__ = [
    "CompanionRouter",
    "DEFAULT_KEYWORD_WEIGHT",
    "DEFAULT_ROUTE_TOP_K",
    "FALLBACK_CAPABILITIES",
    "INTENT_KEYWORDS",
    "KEYWORD_WEIGHTS",
    "ROUTE_RULE_VERSION",
    "RouterError",
]
