"""
YHLZ Vision Action V1.0 - 行动 Service

职责:
    - 统一对外 API (Interface 层)
    - 组合 Manager + Permission + Validator + Logger + History
    - 流程: 校验 → 权限检查 → 风险评估 → 用户确认 → Executor 执行 → 记录结果
    - 行动历史保存 / 取消 / 状态查询
    - 理解 → 行动建议 (suggest_actions, 鸭子类型)

架构位置:
    Interface (FastAPI / Agent Tool)
        ↓
    Service (本模块)
        ↓
    Manager → Executor (Adapter)

设计原则:
    - 单一入口: 所有行动操作经 Service
    - 权限优先: 执行前必须通过 PermissionChecker
    - 高风险必须确认 (awaiting_confirm)
    - 先理解后行动: request 必须携带 reason / confidence
    - 日志完整: 记录开始/成功/失败/取消/异常/耗时
    - 配置驱动: 从 config 加载
    - 可测试: 提供完整 Mock 注入接口
    - Service 不允许直接调用执行器内部逻辑 (只经 Manager 路由)
"""
from __future__ import annotations

import logging
import threading
import time as _time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from backend.action.logger import ActionLogger
from backend.action.manager import ActionManager, get_manager, reset_manager
from backend.action.permission import (
    ActionPermission,
    ActionPermissionConfig,
    PermissionChecker,
)
from backend.action.schema import (
    ActionQuery,
    ActionRequest,
    ActionResult,
    ActionStatus,
)
from backend.action.validator import ActionValidator

logger = logging.getLogger(__name__)


class ActionServiceError(Exception):
    """Action Service 操作异常"""


@dataclass
class ActionOperationResult:
    """行动操作统一结果

    Attributes:
        success:     是否成功 (业务层面, 如请求受理/执行完成)
        action:      ActionRequest
        result:      ActionResult
        permission:  ActionPermission
        action_id:   行动 id
        status:      状态 (ActionResult.status)
        latency_ms:  耗时 (毫秒)
    """
    success: bool = False
    action: Optional[ActionRequest] = None
    result: Optional[ActionResult] = None
    permission: Optional[ActionPermission] = None
    action_id: str = ""
    status: str = ActionStatus.PENDING.value
    error: Optional[str] = None
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action.to_dict() if self.action else None,
            "result": self.result.to_dict() if self.result else None,
            "permission": self.permission.to_dict() if self.permission else None,
            "action_id": self.action_id,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
        }


class ActionService:
    """行动统一服务

    用法:
        svc = ActionService()
        svc.load_config({"action_enabled": True})
        result = svc.execute(request)
    """

    def __init__(
        self,
        manager: Optional[ActionManager] = None,
        permission: Optional[PermissionChecker] = None,
        validator: Optional[ActionValidator] = None,
        alog: Optional[ActionLogger] = None,
        history_max: int = 200,
    ):
        self._lock = threading.RLock()
        self._manager: ActionManager = manager or ActionManager()
        self._permission: PermissionChecker = permission or PermissionChecker()
        self._validator: ActionValidator = validator or ActionValidator()
        self._alog: ActionLogger = alog or ActionLogger()
        self._history: Deque[ActionResult] = deque(maxlen=history_max)
        self._initialized = False

    # ── 依赖注入 ──────────────────────────────────────────────────
    def set_manager(self, manager: ActionManager) -> None:
        with self._lock:
            self._manager = manager

    def set_permission(self, permission: PermissionChecker) -> None:
        with self._lock:
            self._permission = permission

    def set_validator(self, validator: ActionValidator) -> None:
        with self._lock:
            self._validator = validator

    def set_logger(self, alog: ActionLogger) -> None:
        with self._lock:
            self._alog = alog

    @property
    def manager(self) -> ActionManager:
        return self._manager

    @property
    def permission(self) -> PermissionChecker:
        return self._permission

    @property
    def alog(self) -> ActionLogger:
        return self._alog

    # ── 配置 ──────────────────────────────────────────────────────
    def load_config(self, config: Dict[str, Any]) -> None:
        """从 dict 加载配置 (权限 + 默认执行器注册)"""
        with self._lock:
            perm = ActionPermissionConfig.from_dict(config)
            self._permission.load_from_config(perm)
            self._manager.register_defaults()
            self._initialized = True
        logger.info(f"ActionService 配置已加载: {perm.to_dict()}")

    def load_permission(self, permission: ActionPermissionConfig) -> None:
        self._permission.load_from_config(permission)

    def update_permission(self, **kwargs) -> ActionPermissionConfig:
        return self._permission.update(**kwargs)

    def get_permission(self) -> Dict[str, Any]:
        return self._permission.to_dict()

    def reset_permission(self) -> None:
        self._permission.reset()

    # ── 请求创建 ──────────────────────────────────────────────────
    def create_request(
        self,
        action_type: str,
        target: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        reason: str = "",
        confidence: float = 0.0,
        risk_level: str = "low",
    ) -> ActionRequest:
        """创建行动请求 (不执行)"""
        return ActionRequest.create(
            action_type=action_type, target=target, parameters=parameters,
            reason=reason, confidence=confidence, risk_level=risk_level,
        )

    # ── 校验 ──────────────────────────────────────────────────────
    def validate_request(self, request: ActionRequest) -> tuple:
        """字段级校验 + 执行器级校验

        Returns:
            (True, '') 通过
            (False, error) 不通过
        """
        ok, errors = self._validator.validate(request)
        if not ok:
            return False, "; ".join(errors)
        executor = self._manager.route(request)
        if executor is None:
            return False, "无可用执行器"
        ex_ok, ex_err = executor.validate(request)
        if not ex_ok:
            return False, f"执行器校验失败: {ex_err}"
        return True, ""

    # ── 执行 (核心流程) ───────────────────────────────────────────
    def execute(
        self,
        request: ActionRequest,
        confirmed: bool = False,
    ) -> ActionOperationResult:
        """执行行动

        流程:
            1. 字段校验 (invalid)
            2. 权限检查 (denied)
            3. 高风险 → 需确认 (awaiting_confirm)
            4. 路由执行器 → 执行 (ok / error / unsupported)
            5. 记录历史 + 日志
        """
        start = _time.perf_counter()
        self._alog.log_start(
            action_id=request.action_id,
            action_type=request.action_type,
            risk_level=request.risk_level,
        )

        # 1. 校验
        ok, error = self.validate_request(request)
        if not ok:
            return self._finish(
                request, ActionResult(
                    action_id=request.action_id,
                    status=ActionStatus.INVALID.value,
                    message="行动请求校验失败",
                    error=error,
                ), start, log_fail=True,
            )

        # 2. 权限检查 (含风险评估)
        perm = self._permission.evaluate(request)
        if not perm.allowed:
            return self._finish(
                request, ActionResult(
                    action_id=request.action_id,
                    status=ActionStatus.DENIED.value,
                    message="权限拒绝",
                    error=perm.reason,
                    output={"permission": perm.to_dict()},
                ), start, log_fail=True,
            )

        # 3. 高风险需确认
        if perm.require_confirm and not confirmed:
            return self._finish(
                request, ActionResult(
                    action_id=request.action_id,
                    status=ActionStatus.AWAITING_CONFIRM.value,
                    message=f"高风险行动待确认: {perm.reason} (请确认后重试)",
                    output={"permission": perm.to_dict()},
                ), start, log_fail=False,
            )

        # 4. 路由 + 执行
        executor = self._manager.route(request)
        try:
            result = executor.execute(request)
        except Exception as e:
            logger.error(f"[Action] 执行异常: {e}", exc_info=True)
            return self._finish(
                request, ActionResult(
                    action_id=request.action_id,
                    status=ActionStatus.ERROR.value,
                    message="行动执行异常",
                    error=f"{type(e).__name__}: {e}",
                ), start, log_fail=True,
            )

        return self._finish(
            request, result, start,
            log_fail=result.status != ActionStatus.OK.value,
        )

    def _finish(
        self,
        request: ActionRequest,
        result: ActionResult,
        start: float,
        log_fail: bool,
    ) -> ActionOperationResult:
        """收尾: 记录历史 + 日志 + 组装结果"""
        latency = (_time.perf_counter() - start) * 1000
        self._record_history(result)
        if log_fail:
            self._alog.log_fail(
                action_id=request.action_id, action_type=request.action_type,
                status=result.status, error=result.error or result.message,
                risk_level=request.risk_level, latency_ms=latency,
            )
        else:
            self._alog.log_success(
                action_id=request.action_id, action_type=request.action_type,
                status=result.status, risk_level=request.risk_level,
                latency_ms=latency,
            )
        success = result.status in (ActionStatus.OK.value, ActionStatus.AWAITING_CONFIRM.value)
        return ActionOperationResult(
            success=success,
            action=request,
            result=result,
            permission=self._permission.evaluate(request),
            action_id=request.action_id,
            status=result.status,
            error=result.error,
            latency_ms=latency,
        )

    # ── 取消 / 状态 ───────────────────────────────────────────────
    def cancel(self, action_id: str) -> ActionOperationResult:
        """取消行动 (路由到执行器 cancel)"""
        start = _time.perf_counter()
        executor = self._manager.get_default_executor()
        if executor is None:
            return ActionOperationResult(
                success=False, status=ActionStatus.ERROR.value,
                error="无可用执行器",
            )
        try:
            result = executor.cancel(action_id)
        except Exception as e:
            logger.error(f"[Action] 取消失败: {e}", exc_info=True)
            return ActionOperationResult(
                success=False, status=ActionStatus.ERROR.value,
                error=f"取消失败: {e}",
            )
        self._alog.log_cancel(
            action_id=action_id, action_type="",
            latency_ms=(_time.perf_counter() - start) * 1000,
        )
        return ActionOperationResult(
            success=result.status == ActionStatus.CANCELLED.value,
            result=result, action_id=action_id, status=result.status,
            latency_ms=(_time.perf_counter() - start) * 1000,
        )

    def get_status(self, action_id: str) -> Optional[ActionResult]:
        """查询行动状态 (从历史记录)"""
        for r in reversed(self._history):
            if r.action_id == action_id:
                return r
        return None

    # ── 历史 ──────────────────────────────────────────────────────
    def _record_history(self, result: ActionResult) -> None:
        with self._lock:
            self._history.append(result)

    def history(self, query: Optional[ActionQuery] = None) -> List[Dict[str, Any]]:
        """检索历史行动记录 (最新在前)

        记录字段: action_id / action_type / target / status / risk_level / result
        """
        q = query or ActionQuery()
        with self._lock:
            entries = list(self._history)
        records = []
        for r in reversed(entries):
            if q.status and r.status != q.status:
                continue
            records.append(r.to_dict())
            if len(records) >= q.limit:
                break
        return records

    # ── 理解 → 行动建议 (P1) ──────────────────────────────────────
    def suggest_actions(self, understanding_result: Any) -> List[ActionRequest]:
        """从理解结果生成行动建议 (不执行)"""
        from backend.action.planners.action_planner import suggest_actions as _suggest
        return _suggest(understanding_result)

    # ── 日志 / 指标 ───────────────────────────────────────────────
    def get_logs(
        self,
        event: Optional[str] = None,
        action_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        entries = self._alog.query(
            event=event, action_type=action_type, status=status, limit=limit
        )
        return [e.to_dict() for e in entries]

    def get_log_stats(self) -> Dict[str, Any]:
        return self._alog.stats()

    def clear_logs(self) -> int:
        return self._alog.clear()

    def clear_history(self) -> int:
        """清空行动历史记录"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "initialized": self._initialized,
            "permission": self._permission.to_dict(),
            "manager": self._manager.status(),
            "history_count": len(self._history),
            "metrics": self._alog.stats(),
        }


# ── 全局单例 ─────────────────────────────────────────────────────
_global_service: Optional[ActionService] = None
_service_lock = threading.Lock()


def get_service() -> ActionService:
    """获取全局 ActionService 单例"""
    global _global_service
    with _service_lock:
        if _global_service is None:
            _global_service = ActionService(manager=get_manager())
        return _global_service


def reset_service() -> None:
    """重置全局 Service (测试用)"""
    global _global_service
    with _service_lock:
        _global_service = None
    reset_manager()


__all__ = [
    "ActionService",
    "ActionServiceError",
    "ActionOperationResult",
    "get_service",
    "reset_service",
]
