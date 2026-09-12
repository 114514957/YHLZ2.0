"""
YHLZ Model Pool Router V10.1.3 - 模型池调度门面 (Model Pool Router)

职责:
    - 统一入口: 注册 / 分类 / 选择 / Token监控 / 切换 / 交接 / 调用记录
    - 模型评分数据库: 每次调用记录 (时间/模型/任务/Token/延迟/质量/评价)
    - Fallback Mode: 全部云端不可用 → 本地/缓存/Memory

流程:
    Task → Task Classifier → Model Selector → Token 检查 →
    (切换?) Handoff → Execute → Record → Memory Update

设计原则:
    - 模型不是主体, 只是能力模块 (模型变化, 元亨连续)
    - 规则可解释 (rule/reason)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from backend.model_pool.handoff import ModelHandoff
from backend.model_pool.registry import ModelEntry, ModelRegistry
from backend.model_pool.selector import ModelSelector
from backend.model_pool.task_classifier import TaskClassifier

logger = logging.getLogger(__name__)


class ModelPoolError(Exception):
    """模型池调度异常"""


class ModelPoolRouter:
    """模型池调度器 (V10.1.3)

    用法:
        pool = ModelPoolRouter()
        pool.register_model(ModelEntry(...))
        r = pool.route("帮我写个python函数")
        # r = {task_type, selected, reason, ...}
        r = pool.execute(model_id, fn, args)
    """

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        classifier: Optional[TaskClassifier] = None,
        selector: Optional[ModelSelector] = None,
        handoff: Optional[ModelHandoff] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._registry = registry or ModelRegistry()
        self._classifier = classifier or TaskClassifier()
        self._selector = selector or ModelSelector()
        self._handoff = handoff or ModelHandoff()
        self._call_records: List[Dict[str, Any]] = []
        self._max_records = 1000

    # ── 注册 ────────────────────────────────────────────────────
    def register_model(self, entry: ModelEntry) -> Dict[str, Any]:
        """注册模型"""
        with self._lock:
            return self._registry.register(entry)

    def register_defaults(self) -> Dict[str, Any]:
        """注册默认模型池 (百万 Token 额度)"""
        with self._lock:
            defaults = [
                ModelEntry(
                    model_id="qwen-turbo",
                    model_name="Qwen-Turbo",
                    provider="dashscope",
                    model_type="main",
                    capability=["chat", "reasoning", "summary",
                                "memory"],
                    token_limit=1_000_000,
                    remaining_token=1_000_000,
                    cost_per_1k=0.0003,
                    latency_ms=800.0,
                ),
                ModelEntry(
                    model_id="qwen-plus",
                    model_name="Qwen-Plus",
                    provider="dashscope",
                    model_type="specialist",
                    capability=["chat", "code", "reasoning",
                                "summary"],
                    token_limit=1_000_000,
                    remaining_token=1_000_000,
                    cost_per_1k=0.0008,
                    latency_ms=1000.0,
                ),
                ModelEntry(
                    model_id="qwen-vl-plus",
                    model_name="Qwen-VL-Plus",
                    provider="dashscope",
                    model_type="specialist",
                    capability=["vision", "chat", "reasoning"],
                    token_limit=1_000_000,
                    remaining_token=1_000_000,
                    cost_per_1k=0.0015,
                    latency_ms=1200.0,
                ),
                ModelEntry(
                    model_id="deepseek-chat",
                    model_name="DeepSeek-Chat",
                    provider="deepseek",
                    model_type="specialist",
                    capability=["chat", "code", "reasoning"],
                    token_limit=1_000_000,
                    remaining_token=1_000_000,
                    cost_per_1k=0.0014,
                    latency_ms=900.0,
                ),
                ModelEntry(
                    model_id="local-fallback",
                    model_name="Local Fallback",
                    provider="local",
                    model_type="local",
                    capability=["chat", "summary", "memory"],
                    token_limit=100_000,
                    remaining_token=100_000,
                    cost_per_1k=0.0,
                    latency_ms=50.0,
                ),
            ]
            for e in defaults:
                self._registry.register(e)
            return {"mode": "rule_based", "ok": True,
                    "registered": len(defaults)}

    # ── 路由 ────────────────────────────────────────────────────
    def route(self, text: str) -> Dict[str, Any]:
        """任务路由: 分类 → 选择模型"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "模型池调度器停用"}
            cls = self._classifier.classify(text)
            entries = self._registry.list()
            sel = self._selector.select(
                entries, cls.get("task_type", "CHAT"),
            )
            return {
                "mode": "rule_based",
                "ok": sel.get("ok", False),
                "task_type": cls.get("task_type"),
                "classification_reason": cls.get("reason"),
                "selected": sel.get("selected"),
                "candidates": sel.get("candidates"),
                "selection_reason": sel.get("reason"),
                "fallback_mode": sel.get("selected") is None,
            }

    # ── 执行 ────────────────────────────────────────────────────
    def execute(
        self,
        model_id: str,
        task_type: str,
        call_fn: Callable,
        args: Optional[Dict[str, Any]] = None,
        token_used: int = 0,
    ) -> Dict[str, Any]:
        """执行模型调用 (记录 Token/延迟)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "模型池调度器停用"}
        start = time.perf_counter()
        try:
            result = call_fn(**(args or {}))
            ok = True
            error = ""
        except Exception as e:  # noqa: BLE001 调用隔离
            result = None
            ok = False
            error = str(e)
            logger.error(f"[ModelPool] {model_id} 调用失败: {e}")
            self._registry.record_error(model_id)
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        if token_used > 0:
            self._registry.consume_token(model_id, token_used)
        record = {
            "timestamp": time.time(),
            "model_id": model_id,
            "task_type": task_type,
            "token_used": token_used,
            "latency_ms": latency_ms,
            "ok": ok,
            "error": error,
        }
        with self._lock:
            self._call_records.append(record)
            if len(self._call_records) > self._max_records:
                self._call_records = \
                    self._call_records[-self._max_records:]
        return {
            "mode": "rule_based", "ok": ok,
            "model_id": model_id,
            "task_type": task_type,
            "token_used": token_used,
            "latency_ms": latency_ms,
            "error": error,
            "result": result,
        }

    # ── 切换 ────────────────────────────────────────────────────
    def check_and_switch(
        self,
        model_id: str,
        task: str = "",
        user: str = "",
        project: str = "",
    ) -> Dict[str, Any]:
        """检查当前模型是否需要切换; 需要则走交接协议"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "模型池调度器停用"}
            entry = self._registry.get(model_id)
            if entry is None:
                return {"mode": "error_frame", "ok": False,
                        "reason": f"模型不存在: {model_id}"}
            check = self._selector.should_switch(entry)
            if not check["switch"]:
                return {
                    "mode": "rule_based", "ok": True,
                    "switch": False,
                    "model_id": model_id,
                    "reasons": [],
                }
            # 选择备用模型
            candidates = [
                e for e in self._registry.list()
                if e["model_id"] != model_id
                and e["status"] == "active"
                and e["remaining_token"] > 0
            ]
            if not candidates:
                return {
                    "mode": "rule_based", "ok": False,
                    "switch": True,
                    "fallback_mode": True,
                    "reason": "无备用模型, 进入 Fallback Mode",
                }
            candidates.sort(
                key=lambda e: (
                    e.get("type") != "local",
                    -e["remaining_token"],
                ),
            )
            backup = candidates[0]
            # 生成交接 (主体连续性保护)
            handoff = self._handoff.create(
                from_model=model_id,
                to_model=backup["model_id"],
                user=user, project=project, task=task,
                completed="", conclusion="", constraints="",
                next_step="继续当前任务",
            )
            return {
                "mode": "rule_based", "ok": True,
                "switch": True,
                "from_model": model_id,
                "to_model": backup["model_id"],
                "trigger_reasons": check["reasons"],
                "handoff": handoff,
            }

    # ── 查询 ────────────────────────────────────────────────────
    def model_status(self) -> Dict[str, Any]:
        """模型状态面板数据"""
        with self._lock:
            entries = self._registry.list()
        panels = []
        for e in entries:
            level = self._selector.token_level(
                e["remaining_token"], e["token_limit"],
            )
            panels.append({
                "model_id": e["model_id"],
                "model_name": e["model_name"],
                "type": e["type"],
                "status": e["status"],
                "remaining_token": e["remaining_token"],
                "token_level": level,
                "latency_ms": e["latency_ms"],
                "error_count": e["error_count"],
            })
        return {
            "mode": "rule_based",
            "enabled": self._enabled,
            "models": panels,
            "total_remaining_token": sum(
                p["remaining_token"] for p in panels
            ),
        }

    def call_history(
        self,
        model_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """调用记录 (模型评分数据库)"""
        with self._lock:
            records = list(self._call_records)
        out = []
        for r in reversed(records):
            if model_id and r["model_id"] != model_id:
                continue
            out.append(dict(r))
            if 0 < limit <= len(out):
                break
        return out

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "registry": self._registry.stats(),
                "classifier": self._classifier.stats(),
                "selector": self._selector.stats(),
                "handoff": self._handoff.stats(),
                "call_records": len(self._call_records),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._call_records)
            self._call_records.clear()
            n += self._registry.clear()
            n += self._handoff.clear()
            return n


__all__ = [
    "ModelPoolError",
    "ModelPoolRouter",
]
