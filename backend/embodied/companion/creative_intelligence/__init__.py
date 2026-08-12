"""
YHLZ Embodied AI V8.5 - 元创造力引擎 (Meta Creative Engine)

职责:
    - 创造流程门面: 知识图 → 思维火花 → 概念重组 → 假设
      → 验证 → 输出 + 记忆
    - Constitution 约束: 创造必须经治理检查
    - HIL 连接: 复杂创造云端增强

流程:
    Memory → Knowledge Graph → Idea Spark → Concept Fusion
    → Hypothesis → Validation → Creative Output

原则:
    创造不是随机生成, 是基于已有认知/经验/记忆/约束产生
    新的可验证组合
    Evidence Based Creation / Falsifiability

设计原则:
    - 纯规则创造 (无黑盒)
    - 创造结果可验证可证伪
    - 无依据不创造 (防幻觉)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.creative_intelligence.knowledge_graph import (
    KnowledgeGraph,
)
from backend.embodied.companion.creative_intelligence.idea_spark import (
    IdeaSparkGenerator,
)
from backend.embodied.companion.creative_intelligence.concept_fusion import (
    ConceptFusion,
)
from backend.embodied.companion.creative_intelligence.boundary_detector import (
    ThoughtBoundaryDetector,
)
from backend.embodied.companion.creative_intelligence.hypothesis_engine import (
    HypothesisEngine,
)
from backend.embodied.companion.creative_intelligence.validation_engine import (
    CreativeValidation,
)
from backend.embodied.companion.creative_intelligence.creative_memory import (
    CreativeMemory,
)
from backend.embodied.companion.creative_intelligence.collaborative import (
    CollaborativeCreation,
)

from backend.embodied.companion.creative_intelligence.collaborative import (
    CollaborativeCreation,
    CollaborativeError,
)
from backend.embodied.companion.creative_intelligence.creative_memory import (
    CreativeMemory,
    CreativeMemoryError,
    MEMORY_STATUS,
)
from backend.embodied.companion.creative_intelligence.hypothesis_engine import (
    HypothesisEngine,
    HypothesisError,
)
from backend.embodied.companion.creative_intelligence.validation_engine import (
    CreativeValidation,
    KNOWLEDGE_TYPES,
    LOGIC_JUMP_SIGNALS,
    ValidationError,
)
from backend.embodied.companion.creative_intelligence.knowledge_graph import (
    KnowledgeGraph,
    KnowledgeGraphError,
)
from backend.embodied.companion.creative_intelligence.idea_spark import (
    IdeaSparkGenerator,
    SparkError,
)
from backend.embodied.companion.creative_intelligence.concept_fusion import (
    ConceptFusion,
    FUSION_LOGIC_TYPES,
    FusionError,
)
from backend.embodied.companion.creative_intelligence.boundary_detector import (
    BoundaryError,
    ThoughtBoundaryDetector,
)

logger = logging.getLogger(__name__)


class MetaCreativeError(Exception):
    """元创造力引擎操作异常"""


class MetaCreativeEngine:
    """元创造力引擎 (受治理的创造门面)

    用法:
        engine = MetaCreativeEngine()
        engine.load_experience(records)
        r = engine.create("如何提升伙伴体验")
    """

    def __init__(
        self,
        graph: Optional[KnowledgeGraph] = None,
        spark_generator: Optional[IdeaSparkGenerator] = None,
        fusion: Optional[ConceptFusion] = None,
        boundary: Optional[ThoughtBoundaryDetector] = None,
        hypothesis: Optional[HypothesisEngine] = None,
        validation: Optional[CreativeValidation] = None,
        memory: Optional[CreativeMemory] = None,
        collaborative: Optional[CollaborativeCreation] = None,
        constitution=None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._graph = graph or KnowledgeGraph()
        self._spark = spark_generator or IdeaSparkGenerator(
            graph=self._graph,
        )
        self._fusion = fusion or ConceptFusion()
        self._boundary = boundary or \
            ThoughtBoundaryDetector(graph=self._graph)
        self._hypothesis = hypothesis or HypothesisEngine()
        self._validation = validation or CreativeValidation()
        self._memory = memory or CreativeMemory()
        self._collaborative = collaborative or \
            CollaborativeCreation()
        self._constitution = constitution
        # 统一绑定知识图 (注入的生成器/边界检测器共享图)
        self._spark._graph = self._graph
        self._boundary._graph = self._graph
        self._create_count = 0
        self._blocked_count = 0

    # ── 经验加载 (Continuity) ───────────────────────────────────
    def load_experience(
        self, records: List[Dict[str, Any]],
    ) -> int:
        """加载经历 → 知识图 (创造来源于长期记忆)"""
        with self._lock:
            return self._graph.load_records(records)

    # ── 创建主入口 ───────────────────────────────────────────────
    def create(
        self,
        problem: str,
        context: Optional[Dict[str, Any]] = None,
        human_input: Optional[str] = None,
    ) -> Dict[str, Any]:
        """完整创造流程

        Args:
            problem: 当前问题
            context: 上下文
            human_input: 人类输入 (人机协同, 可空)

        Returns:
            {
                'create_id', 'problem', 'sparks',
                'boundary', 'hypothesis', 'validation',
                'output', 'mode',
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "元创造力引擎停用",
                }
            # 1. 思维火花
            sparks = self._spark.generate(problem, context)
            # 2. 思维断口
            boundary = self._boundary.detect(problem)
            # 3. 概念重组 (取最强火花)
            fusion_result = None
            if sparks:
                new_ctx = ""
                if isinstance(context, dict):
                    new_ctx = str(
                        context.get("goal", ""),
                    )
                fusion_result = self._fusion.fuse(
                    sparks[0]["related_concepts"][0]
                    if sparks[0]["related_concepts"] else
                    problem[:10],
                    sparks[0]["related_concepts"][-1]
                    if sparks[0]["related_concepts"] else
                    "新维度",
                    new_context=new_ctx,
                    logic="merge",
                )
            # 4. 假设 (无基础 → 容错错误帧)
            try:
                hypothesis = self._hypothesis.build(
                    sparks[0] if sparks else None,
                    fusion_result,
                )
            except Exception as e:
                logger.warning(
                    f"[MetaCreative] 假设构建失败: {e}",
                )
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": f"创造失败: 无基础 (需先加载"
                              f"经历到知识图)",
                    "create_id": "mc_" + uuid.uuid4().hex[:8],
                }
            # 5. 验证 (经 Constitution 检查)
            validation = self._validation.validate(hypothesis)
            constitution_ok = True
            if self._constitution is not None:
                try:
                    cr = self._constitution.review({
                        "module": "meta_creative",
                        "action_text": str(
                            hypothesis.get("hypothesis", ""),
                        ),
                        "change": {},
                    })
                    constitution_ok = cr["decision"] == "allow"
                except Exception as e:
                    logger.warning(
                        f"[MetaCreative] 宪法检查失败: {e}",
                    )
            # 6. 输出 + 记忆 (经 Memory Filter)
            ok = validation["ok"] and constitution_ok
            output = {
                "create_id": "mc_" + uuid.uuid4().hex[:8],
                "problem": str(problem),
                "sparks": [dict(s) for s in sparks],
                "boundary": dict(boundary),
                "fusion": dict(fusion_result)
                if fusion_result else None,
                "hypothesis": dict(hypothesis),
                "validation": dict(validation),
                "constitution_ok": constitution_ok,
                "output": (
                    hypothesis.get("hypothesis", "")
                    if ok else "创造被验证拒绝"
                ),
                "mode": "rule_based",
            }
            if ok:
                self._memory.save(
                    hypothesis.get("hypothesis", ""),
                    status="incomplete",
                    validated=True,
                    validation_reason=validation["reason"],
                )
            else:
                self._blocked_count += 1
            self._create_count += 1
            return output

    # ── 人机协同 ─────────────────────────────────────────────────
    def collaborate(
        self,
        human_input: str,
        ai_analysis: str,
        goal: str = "",
    ) -> Dict[str, Any]:
        """人机协同创造"""
        with self._lock:
            return self._collaborative.create(
                human_input, ai_analysis, goal,
            )

    # ── 记忆 ─────────────────────────────────────────────────────
    def memory_save(
        self,
        content: str,
        status: str = "incomplete",
        validated: bool = True,
        validation_reason: str = "",
    ) -> Dict[str, Any]:
        """保存创造记忆 (经过滤)"""
        with self._lock:
            return self._memory.save(
                content, status, validated,
                validation_reason,
            )

    def memory_stats(self) -> Dict[str, Any]:
        """创造记忆统计"""
        return self._memory.stats()

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """创造引擎统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "create_count": self._create_count,
                "blocked_count": self._blocked_count,
                "graph": self._graph.stats(),
                "spark": self._spark.stats(),
                "fusion": self._fusion.stats(),
                "boundary": self._boundary.stats(),
                "hypothesis": self._hypothesis.stats(),
                "validation": self._validation.stats(),
                "memory": self._memory.stats(),
                "collaborative": self._collaborative.stats(),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = 0
            n += self._graph.clear()
            n += self._spark.clear()
            n += self._fusion.clear()
            n += self._boundary.clear()
            n += self._hypothesis.clear()
            n += self._validation.clear()
            n += self._memory.clear()
            n += self._collaborative.clear()
            self._create_count = 0
            self._blocked_count = 0
            return n


__all__ = [
    "MetaCreativeEngine",
    "MetaCreativeError",
    "BoundaryError",
    "CollaborativeCreation",
    "CollaborativeError",
    "ConceptFusion",
    "CreativeMemory",
    "CreativeMemoryError",
    "CreativeValidation",
    "FUSION_LOGIC_TYPES",
    "FusionError",
    "HypothesisEngine",
    "HypothesisError",
    "IdeaSparkGenerator",
    "KNOWLEDGE_TYPES",
    "KnowledgeGraph",
    "KnowledgeGraphError",
    "LOGIC_JUMP_SIGNALS",
    "MEMORY_STATUS",
    "SparkError",
    "ThoughtBoundaryDetector",
    "ValidationError",
]
