"""
YHLZ Embodied AI V9.5 - 认知反思循环 (Reflection Loop)

职责:
    - 流程: Experience → Analysis → Reflection → Adjustment
      Proposal → Validation → Update
    - 所有调整必须经过 Constitution Check

原则:
    - 元认知可以优化方法, 不能修改最高原则
    - 调整建议永不直接应用 (需验证)

设计原则:
    - 纯规则反思 (可解释)
    - 调整建议经 Constitution 检查
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ReflectionError(Exception):
    """认知反思操作异常"""


class ReflectionLoop:
    """认知反思循环 (经验 → 调整建议 → 验证)

    用法:
        loop = ReflectionLoop(constitution=...)
        r = loop.reflect("经验", "分析", "调整建议")
    """

    def __init__(self, constitution=None,
                 enabled: bool = True,
                 max_records: int = 1000):
        if max_records <= 0:
            raise ReflectionError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._constitution = constitution
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._records: list = []

    # ── 反思主入口 ───────────────────────────────────────────────
    def reflect(
        self,
        experience: str,
        analysis: str = "",
        adjustment: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """认知反思

        Args:
            experience: 经验/事件
            analysis: 分析
            adjustment: 调整建议

        Returns:
            {
                'reflection_id', 'reflection', 'proposal',
                'constitution_ok', 'validation', 'update',
                'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "认知反思停用",
                }
            # 1. 反思总结 (可解释)
            reflection = (
                f"经验 '{str(experience)[:20]}' "
                f"分析: {str(analysis)[:30]}"
            )
            # 2. 调整建议
            proposal = {
                "proposal_id": "rp_" + uuid.uuid4().hex[:8],
                "adjustment": str(adjustment),
                "method_level": True,
                "principle_level": False,
            }
            # 3. Constitution Check (调整必须经过)
            constitution_ok = True
            constitution_reason = "无宪法约束引擎"
            if self._constitution is not None:
                try:
                    cr = self._constitution.review({
                        "module": "meta_cognition",
                        "action_text": str(adjustment),
                        "change": {},
                    })
                    constitution_ok = (
                        cr["decision"] == "allow"
                    )
                    reasons = cr.get("reasons") or []
                    constitution_reason = "; ".join(
                        reasons,
                    ) if reasons else cr.get(
                        "reason", "",
                    )
                except Exception as e:
                    logger.warning(
                        f"[MetaCognition] 宪法检查失败: {e}",
                    )
            # 4. 验证 (调整建议需验证后应用)
            validation = {
                "ok": constitution_ok and bool(adjustment),
                "reason": (
                    "宪法通过且建议非空"
                    if constitution_ok and adjustment else
                    ("宪法拦截" if not constitution_ok else
                     "调整建议为空")
                ),
            }
            # 5. Update (仅验证通过才更新)
            update = validation["ok"]
            record = {
                "reflection_id": "rf_" +
                uuid.uuid4().hex[:8],
                "experience": str(experience),
                "analysis": str(analysis),
                "reflection": reflection,
                "proposal": dict(proposal),
                "constitution_ok": constitution_ok,
                "constitution_reason": constitution_reason,
                "validation": validation,
                "update": update,
                "mode": "rule_based",
                "created_at": now,
            }
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return dict(record)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """反思统计"""
        with self._lock:
            updates = sum(
                1 for r in self._records if r["update"]
            )
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "reflection_count": len(self._records),
                "update_count": updates,
            }

    def history(self, limit: int = 50) -> list:
        """反思历史"""
        with self._lock:
            recent = list(reversed(self._records))
            if limit > 0:
                recent = recent[:limit]
            return [dict(r) for r in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "ReflectionError",
    "ReflectionLoop",
]
