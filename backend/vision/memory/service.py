"""
YHLZ Vision Memory V1.0 - 视觉记忆 Service

职责:
    - 统一对外 API (Interface 层)
    - 组合 Manager + Permission + Logger
    - 流程: 权限校验 → 存储操作 → 日志记录 → 返回 MemoryOperationResult
    - 保存 UnderstandingResult (只记忆结构化结果, 不保存原始图像)
    - 提供 recent_visual_context (给 Agent 使用的视觉上下文)

架构位置:
    Interface (FastAPI / 外部调用 / Agent Tool)
        ↓
    Service (本模块)
        ↓
    Manager → Store (Adapter / Storage)

设计原则:
    - 单一入口: 所有记忆操作经 Service
    - 权限优先: 操作前先校验权限 (vision_memory_enabled)
    - 日志完整: 记录开始/成功/失败/耗时/异常
    - 配置驱动: 从 config 加载权限与参数
    - 可测试: 提供完整 Mock 注入接口
    - Service 不允许直接操作数据库 (只经 Manager → Store)
"""
from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.vision.memory.logger import MemoryLogger
from backend.vision.memory.manager import (
    MemoryManager,
    get_manager,
    reset_manager,
)
from backend.vision.memory.permission import (
    MemoryPermission,
    PermissionChecker,
)
from backend.vision.memory.schema import (
    MemoryQuery,
    MemoryStatus,
    VisualMemoryRecord,
)

logger = logging.getLogger(__name__)


class MemoryServiceError(Exception):
    """Memory Service 操作异常"""


@dataclass
class MemoryOperationResult:
    """记忆操作统一结果

    Attributes:
        success:   是否成功
        status:    操作状态 (ok / denied / error / not_found / no_store)
        error:     失败原因 (None=成功)
        memory_id: 关联记录 id
        record:    单条记录 (retrieve 结果)
        records:   记录列表 (query 结果)
        count:     影响记录数
        latency_ms:耗时 (毫秒)
    """
    success: bool = False
    status: str = MemoryStatus.OK.value
    error: Optional[str] = None
    memory_id: Optional[str] = None
    record: Optional[VisualMemoryRecord] = None
    records: List[VisualMemoryRecord] = field(default_factory=list)
    count: int = 0
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "error": self.error,
            "memory_id": self.memory_id,
            "record": self.record.to_dict() if self.record else None,
            "records": [r.to_dict() for r in self.records],
            "count": self.count,
            "latency_ms": round(self.latency_ms, 2),
        }


class MemoryService:
    """视觉记忆统一服务

    用法:
        svc = MemoryService()
        svc.load_config(config_dict)
        result = svc.save_understanding_result(understand_result)

    流程:
        1. 权限校验 (PermissionChecker)
        2. 调用 Manager 路由到 Store
        3. 日志记录 (save / query / delete / fail)
        4. 返回 MemoryOperationResult
    """

    def __init__(
        self,
        manager: Optional[MemoryManager] = None,
        permission: Optional[PermissionChecker] = None,
        mlog: Optional[MemoryLogger] = None,
    ):
        self._lock = threading.RLock()
        self._manager: MemoryManager = manager or MemoryManager()
        self._permission: PermissionChecker = permission or PermissionChecker()
        self._mlog: MemoryLogger = mlog or MemoryLogger()
        self._initialized = False

    # ── 依赖注入 ──────────────────────────────────────────────────
    def set_manager(self, manager: MemoryManager) -> None:
        with self._lock:
            self._manager = manager

    def set_permission(self, permission: PermissionChecker) -> None:
        with self._lock:
            self._permission = permission

    def set_logger(self, mlog: MemoryLogger) -> None:
        with self._lock:
            self._mlog = mlog

    @property
    def manager(self) -> MemoryManager:
        return self._manager

    @property
    def permission(self) -> PermissionChecker:
        return self._permission

    @property
    def mlog(self) -> MemoryLogger:
        return self._mlog

    # ── 配置 ──────────────────────────────────────────────────────
    def load_config(self, config: Dict[str, Any]) -> None:
        """从 dict 加载配置 (权限 + 默认注册)"""
        with self._lock:
            perm = MemoryPermission.from_dict(config)
            self._permission.load_from_permission(perm)
            self._manager.register_defaults(
                include_memory=True,
                db_path=config.get("db_path"),
            )
            self._initialized = True
        logger.info(f"MemoryService 配置已加载: {perm.to_dict()}")

    def load_permission(self, permission: MemoryPermission) -> None:
        self._permission.load_from_permission(permission)

    def update_permission(self, **kwargs) -> MemoryPermission:
        return self._permission.update(**kwargs)

    def get_permission(self) -> Dict[str, Any]:
        return self._permission.to_dict()

    def reset_permission(self) -> None:
        self._permission.reset()

    # ── 保存 ──────────────────────────────────────────────────────
    def save(self, record: VisualMemoryRecord) -> MemoryOperationResult:
        """保存记忆记录 (需权限)

        流程:
            1. 权限校验 (check_save: 总开关 + 禁止原始图像)
            2. 调用 Manager → Store
            3. 日志记录
        """
        start = _time.perf_counter()

        # 1. 权限校验
        allowed, reason = self._permission.check_save(record)
        if not allowed:
            latency = (_time.perf_counter() - start) * 1000
            self._mlog.log_fail(
                store=self._store_name(),
                action="save",
                status=MemoryStatus.PERMISSION_DENIED.value,
                error=reason,
                latency_ms=latency,
            )
            return MemoryOperationResult(
                success=False,
                status=MemoryStatus.PERMISSION_DENIED.value,
                error=reason,
                latency_ms=latency,
            )

        # 2. 存储操作
        try:
            memory_id = self._manager.save(record)
        except Exception as e:
            latency = (_time.perf_counter() - start) * 1000
            logger.error(f"[VisionMemory] 保存异常: {e}", exc_info=True)
            self._mlog.log_fail(
                store=self._store_name(),
                action="save",
                status=MemoryStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}",
                latency_ms=latency,
            )
            return MemoryOperationResult(
                success=False,
                status=MemoryStatus.ERROR.value,
                error=f"保存失败: {e}",
                latency_ms=latency,
            )

        latency = (_time.perf_counter() - start) * 1000
        self._mlog.log_save(
            store=self._store_name(),
            memory_id=memory_id,
            latency_ms=latency,
            metadata={"memory_type": record.memory_type, "scene_type": record.scene_type},
        )
        return MemoryOperationResult(
            success=True,
            status=MemoryStatus.OK.value,
            memory_id=memory_id,
            record=record,
            count=1,
            latency_ms=latency,
        )

    def save_understanding_result(
        self,
        result: Any,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
        memory_type: Optional[str] = None,
    ) -> MemoryOperationResult:
        """保存 UnderstandingResult 到视觉记忆 (只取结构化字段)

        Args:
            result: UnderstandingResult 实例 (仅成功结果可保存)
            tags: 自定义标签 (None=自动从主体名生成)
            importance: 重要程度 (None=配置默认)
            memory_type: 记忆类型 (None=自动推断)

        Returns:
            MemoryOperationResult
        """
        # 校验输入
        if result is None:
            return MemoryOperationResult(
                success=False,
                status=MemoryStatus.EMPTY_INPUT.value,
                error="输入为空 (result=None)",
            )
        is_ok = getattr(result, "is_ok", False)
        if not is_ok:
            return MemoryOperationResult(
                success=False,
                status=MemoryStatus.ERROR.value,
                error="只保存成功结果 (result.is_ok=False)",
            )

        effective_importance = importance or self._permission.permission.default_importance
        record = VisualMemoryRecord.from_understanding_result(
            result,
            tags=tags,
            importance=effective_importance,
            memory_type=memory_type,
        )
        return self.save(record)

    # ── 查询 ──────────────────────────────────────────────────────
    def retrieve(self, memory_id: str) -> MemoryOperationResult:
        """按 id 获取记录 (需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("retrieve", reason, start)
        try:
            record = self._manager.get_default_store().retrieve(memory_id)
        except Exception as e:
            logger.error(f"[VisionMemory] 获取异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            self._mlog.log_fail(
                store=self._store_name(), action="retrieve",
                status=MemoryStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}", latency_ms=latency,
            )
            return MemoryOperationResult(
                success=False, status=MemoryStatus.ERROR.value,
                error=f"获取失败: {e}", latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        if record is None:
            self._mlog.log_fail(
                store=self._store_name(), action="retrieve",
                status=MemoryStatus.NOT_FOUND.value,
                error=f"记录不存在: {memory_id}", latency_ms=latency,
            )
            return MemoryOperationResult(
                success=False, status=MemoryStatus.NOT_FOUND.value,
                error=f"记录不存在: {memory_id}", memory_id=memory_id,
                latency_ms=latency,
            )
        return MemoryOperationResult(
            success=True, status=MemoryStatus.OK.value,
            record=record, memory_id=memory_id, count=1, latency_ms=latency,
        )

    def query(self, query: MemoryQuery) -> MemoryOperationResult:
        """按条件检索记忆 (需权限)

        Args:
            query: 检索条件 (MemoryQuery)

        Returns:
            MemoryOperationResult (records 为结果列表, 最新在前)
        """
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("query", reason, start)
        # 查询上限保护
        max_limit = self._permission.permission.max_query_limit
        if query.limit > max_limit:
            query.limit = max_limit
        try:
            records = self._manager.get_default_store().query(query)
        except Exception as e:
            logger.error(f"[VisionMemory] 检索异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            self._mlog.log_fail(
                store=self._store_name(), action="query",
                status=MemoryStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}", latency_ms=latency,
            )
            return MemoryOperationResult(
                success=False, status=MemoryStatus.ERROR.value,
                error=f"检索失败: {e}", latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        self._mlog.log_query(
            store=self._store_name(), latency_ms=latency,
            hit_count=len(records), metadata=query.to_dict(),
        )
        return MemoryOperationResult(
            success=True, status=MemoryStatus.OK.value,
            records=records, count=len(records), latency_ms=latency,
        )

    def update(self, memory_id: str, **fields) -> MemoryOperationResult:
        """更新记录字段 (白名单, 需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("update", reason, start)
        try:
            ok = self._manager.get_default_store().update(memory_id, **fields)
        except Exception as e:
            logger.error(f"[VisionMemory] 更新异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            self._mlog.log_fail(
                store=self._store_name(), action="update",
                status=MemoryStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}", latency_ms=latency,
            )
            return MemoryOperationResult(
                success=False, status=MemoryStatus.ERROR.value,
                error=f"更新失败: {e}", memory_id=memory_id, latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        if not ok:
            return MemoryOperationResult(
                success=False, status=MemoryStatus.NOT_FOUND.value,
                error=f"记录不存在: {memory_id}", memory_id=memory_id,
                latency_ms=latency,
            )
        self._mlog.log_delete(
            store=self._store_name(), action="update", memory_id=memory_id,
            latency_ms=latency, status=MemoryStatus.OK.value, count=1,
        )
        return MemoryOperationResult(
            success=True, status=MemoryStatus.OK.value,
            memory_id=memory_id, count=1, latency_ms=latency,
        )

    def delete(self, memory_id: str) -> MemoryOperationResult:
        """删除记录 (需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("delete", reason, start)
        try:
            ok = self._manager.get_default_store().delete(memory_id)
        except Exception as e:
            logger.error(f"[VisionMemory] 删除异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            self._mlog.log_fail(
                store=self._store_name(), action="delete",
                status=MemoryStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}", latency_ms=latency,
            )
            return MemoryOperationResult(
                success=False, status=MemoryStatus.ERROR.value,
                error=f"删除失败: {e}", memory_id=memory_id, latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        if not ok:
            return MemoryOperationResult(
                success=False, status=MemoryStatus.NOT_FOUND.value,
                error=f"记录不存在: {memory_id}", memory_id=memory_id,
                latency_ms=latency,
            )
        self._mlog.log_delete(
            store=self._store_name(), action="delete", memory_id=memory_id,
            latency_ms=latency, status=MemoryStatus.OK.value, count=1,
        )
        return MemoryOperationResult(
            success=True, status=MemoryStatus.OK.value,
            memory_id=memory_id, count=1, latency_ms=latency,
        )

    def clear(self) -> MemoryOperationResult:
        """清空所有记忆 (需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("clear", reason, start)
        try:
            n = self._manager.get_default_store().clear()
        except Exception as e:
            logger.error(f"[VisionMemory] 清空异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            self._mlog.log_fail(
                store=self._store_name(), action="clear",
                status=MemoryStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}", latency_ms=latency,
            )
            return MemoryOperationResult(
                success=False, status=MemoryStatus.ERROR.value,
                error=f"清空失败: {e}", latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        self._mlog.log_delete(
            store=self._store_name(), action="clear", memory_id="",
            latency_ms=latency, status=MemoryStatus.OK.value, count=n,
        )
        return MemoryOperationResult(
            success=True, status=MemoryStatus.OK.value, count=n, latency_ms=latency,
        )

    def count(self) -> int:
        """当前记忆总数 (不校验权限, 用于状态展示)"""
        try:
            store = self._manager.get_default_store()
            return store.count() if store is not None else 0
        except Exception as e:
            logger.warning(f"[VisionMemory] 计数失败: {e}")
            return 0

    # ── 视觉上下文 (P1: Agent 使用) ──────────────────────────────
    def recent_visual_context(self, limit: int = 5) -> str:
        """生成最近视觉记忆上下文文本 (给 Agent 使用)

        格式:
            [1] (场景类型, 记忆类型, 重要程度) 描述
            ...
        """
        import datetime as _dt

        if limit <= 0:
            return ""
        result = self.query(MemoryQuery(limit=limit))
        if not result.success or not result.records:
            return ""
        lines = []
        for i, r in enumerate(result.records, start=1):
            ts = _dt.datetime.fromtimestamp(r.timestamp).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(
                f"[{i}] ({r.scene_type}, {r.memory_type}, {r.importance}) "
                f"{ts} | {r.description}"
            )
        return "\n".join(lines)

    # ── 内部工具 ──────────────────────────────────────────────────
    def _store_name(self) -> str:
        store = self._manager.get_default_store()
        return store.name if store is not None else "none"

    def _denied(self, action: str, reason: str, start: float) -> MemoryOperationResult:
        latency = (_time.perf_counter() - start) * 1000
        self._mlog.log_fail(
            store=self._store_name(), action=action,
            status=MemoryStatus.PERMISSION_DENIED.value,
            error=reason, latency_ms=latency,
        )
        return MemoryOperationResult(
            success=False,
            status=MemoryStatus.PERMISSION_DENIED.value,
            error=reason,
            latency_ms=latency,
        )

    # ── Store 管理 ────────────────────────────────────────────────
    def list_stores(self) -> List[Dict[str, Any]]:
        return self._manager.list_stores()

    # ── 日志查询 ──────────────────────────────────────────────────
    def get_logs(
        self,
        event: Optional[str] = None,
        action: Optional[str] = None,
        store: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        entries = self._mlog.query(
            event=event, action=action, store=store, status=status, limit=limit
        )
        return [e.to_dict() for e in entries]

    def get_log_stats(self) -> Dict[str, Any]:
        return self._mlog.stats()

    def clear_logs(self) -> int:
        return self._mlog.clear()

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "initialized": self._initialized,
            "permission": self._permission.to_dict(),
            "manager": self._manager.status(),
            "memory_count": self.count(),
            "log_stats": self._mlog.stats(),
        }


# ── 全局单例 ─────────────────────────────────────────────────────
_global_service: Optional[MemoryService] = None
_service_lock = threading.Lock()


def get_service(db_path: Optional[str] = None) -> MemoryService:
    """获取全局 MemoryService 单例

    Args:
        db_path: 首次创建时指定 SQLite 数据库路径 (None=默认)
    """
    global _global_service
    with _service_lock:
        if _global_service is None:
            mgr = get_manager(db_path=db_path)
            _global_service = MemoryService(manager=mgr)
        return _global_service


def reset_service() -> None:
    """重置全局 Service (测试用)"""
    global _global_service
    with _service_lock:
        _global_service = None
    reset_manager()


__all__ = [
    "MemoryService",
    "MemoryServiceError",
    "MemoryOperationResult",
    "get_service",
    "reset_service",
]
