"""
YHLZ Model Pool Router V10.1.3 - 模型注册表 (Model Registry)

职责:
    - 登记模型池: model_id / model_name / provider / type /
      capability / token_limit / remaining_token / cost / latency / status
    - 模型类型: 主模型 / 专业模型 / 快速模型 / 本地模型
    - 能力域: chat / code / reasoning / vision / summary / memory

设计原则:
    - 模型不是元亨主体, 只是被调用的能力模块
    - 注册可替换 (热机冻结: 新增 API 独立命名)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ModelRegistryError(Exception):
    """模型注册表异常"""


# 模型类型 (可解释)
MODEL_TYPES: List[str] = [
    "main",       # 主模型: 长期协作/项目理解/复杂分析/核心决策
    "specialist", # 专业模型: 代码/数学/推理/特定任务
    "fast",       # 快速模型: 简单问答/格式处理/总结/分类
    "local",      # 本地模型: 离线/隐私/简单处理/Token节省
]

# 能力域 (可解释)
CAPABILITIES: List[str] = [
    "chat",       # 对话
    "code",       # 代码
    "reasoning",  # 推理
    "vision",     # 视觉
    "summary",    # 总结
    "memory",     # 记忆处理
]

# 状态 (可解释)
MODEL_STATUS: List[str] = [
    "active",   # 可用
    "degraded", # 降级 (延迟/错误率升高)
    "disabled", # 停用
]


class ModelEntry:
    """模型登记条目"""

    def __init__(
        self,
        model_id: str,
        model_name: str,
        provider: str,
        model_type: str = "fast",
        capability: Optional[List[str]] = None,
        token_limit: int = 1_000_000,
        remaining_token: int = 1_000_000,
        cost_per_1k: float = 0.0,
        latency_ms: float = 0.0,
        status: str = "active",
    ):
        if model_type not in MODEL_TYPES:
            raise ModelRegistryError(
                f"非法模型类型: {model_type} (可选: {MODEL_TYPES})"
            )
        if status not in MODEL_STATUS:
            raise ModelRegistryError(
                f"非法状态: {status} (可选: {MODEL_STATUS})"
            )
        self.model_id = model_id
        self.model_name = model_name
        self.provider = provider
        self.model_type = model_type
        self.capability = list(capability or ["chat"])
        self.token_limit = int(token_limit)
        self.remaining_token = int(remaining_token)
        self.cost_per_1k = float(cost_per_1k)
        self.latency_ms = float(latency_ms)
        self.status = status
        self.last_used = 0.0
        self.error_count = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "provider": self.provider,
            "type": self.model_type,
            "capability": list(self.capability),
            "token_limit": self.token_limit,
            "remaining_token": self.remaining_token,
            "used_token": self.token_limit - self.remaining_token,
            "cost_per_1k": self.cost_per_1k,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "last_used": self.last_used,
            "error_count": self.error_count,
        }


class ModelRegistry:
    """模型注册表 (V10.1.3)

    用法:
        reg = ModelRegistry()
        reg.register(ModelEntry("qwen-turbo", "Qwen-Turbo",
                                "dashscope", "main",
                                ["chat", "reasoning"],
                                token_limit=1_000_000))
        entry = reg.get("qwen-turbo")
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._entries: Dict[str, ModelEntry] = {}

    def register(self, entry: ModelEntry) -> Dict[str, Any]:
        """登记/更新模型"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "模型注册表停用"}
            self._entries[entry.model_id] = entry
            logger.info(
                f"[ModelPool] 注册模型 {entry.model_id} "
                f"({entry.model_name}, {entry.model_type})"
            )
            return {"mode": "rule_based", "ok": True,
                    "model_id": entry.model_id}

    def unregister(self, model_id: str) -> bool:
        """注销模型"""
        with self._lock:
            return self._entries.pop(model_id, None) is not None

    def get(self, model_id: str) -> Optional[Dict[str, Any]]:
        """查询模型"""
        with self._lock:
            entry = self._entries.get(model_id)
            return entry.to_dict() if entry else None

    def list(
        self,
        model_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出模型 (可按类型/状态过滤)"""
        with self._lock:
            entries = list(self._entries.values())
        out = []
        for e in entries:
            if model_type and e.model_type != model_type:
                continue
            if status and e.status != status:
                continue
            out.append(e.to_dict())
        return out

    def count(self) -> int:
        """模型数"""
        with self._lock:
            return len(self._entries)

    def update_status(
        self, model_id: str, status: str,
    ) -> Dict[str, Any]:
        """更新模型状态"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "模型注册表停用"}
            if status not in MODEL_STATUS:
                raise ModelRegistryError(
                    f"非法状态: {status} (可选: {MODEL_STATUS})"
                )
            entry = self._entries.get(model_id)
            if entry is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"模型不存在: {model_id}"}
            entry.status = status
            return {"mode": "rule_based", "ok": True,
                    "model_id": model_id, "status": status}

    def consume_token(
        self, model_id: str, tokens: int,
    ) -> Dict[str, Any]:
        """消耗 Token"""
        with self._lock:
            entry = self._entries.get(model_id)
            if entry is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"模型不存在: {model_id}"}
            entry.remaining_token = max(
                0, entry.remaining_token - int(tokens),
            )
            entry.last_used = time.time()
            return {
                "mode": "rule_based", "ok": True,
                "model_id": model_id,
                "remaining_token": entry.remaining_token,
            }

    def record_error(self, model_id: str) -> Dict[str, Any]:
        """记录模型错误 (达到阈值自动降级)"""
        with self._lock:
            entry = self._entries.get(model_id)
            if entry is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"模型不存在: {model_id}"}
            entry.error_count += 1
            return {
                "mode": "rule_based", "ok": True,
                "model_id": model_id,
                "error_count": entry.error_count,
            }

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            entries = list(self._entries.values())
        by_type: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        total_remaining = 0
        for e in entries:
            by_type[e.model_type] = by_type.get(e.model_type, 0) + 1
            by_status[e.status] = by_status.get(e.status, 0) + 1
            total_remaining += e.remaining_token
        return {
            "mode": "rule_based",
            "enabled": self._enabled,
            "total": len(entries),
            "by_type": by_type,
            "by_status": by_status,
            "total_remaining_token": total_remaining,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n


__all__ = [
    "CAPABILITIES",
    "MODEL_STATUS",
    "MODEL_TYPES",
    "ModelEntry",
    "ModelRegistry",
    "ModelRegistryError",
]
