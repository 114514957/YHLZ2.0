"""
YHLZ Voice Identity System V2.3-Phase3 - API 层权限校验

职责:
    - 为 FastAPI 端点提供权限校验入口
    - 从请求头 X-Actor-ID 提取操作者 (缺省 system)
    - 复用 audit.VoicePermission 核心权限模型
    - 校验失败抛 HTTPException(403)

权限模型 (与 audit.py 对齐):
    - read:       任意 actor 可读
    - write:      owner 或 system (用于 clone/batch 创建 + 修改)
    - delete:     owner 或 system
    - synthesize: 任意 actor 可合成 (公共读语义)

接入端点 (V2.3-Phase3):
    - POST /voice/clone              → write  (创建, actor 默认成为 owner)
    - DELETE /voice/{voice_id}       → delete (须 owner/system)
    - POST /voice/clone/batch        → write  (批量创建)
    - POST /voice/quality/evaluate   → synthesize

设计原则:
    - 不引入新依赖, 复用 FastAPI Request/Header
    - 无认证系统时 actor_id 缺省 system (全权限), 通过 X-Actor-ID 头覆盖
    - 创建类操作 (clone/batch) 无既有 profile, 校验 actor 是否被允许创建
      (默认允许, 仅拒绝 "anonymous" / 空字符串)
    - 校验失败统一抛 403, 不泄露内部信息
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request

from backend.voice_identity.audit import VoicePermission
from backend.voice_identity.audit import (
    ACTION_READ,
    ACTION_WRITE,
    ACTION_DELETE,
    ACTION_SYNTHESIZE,
    ROLE_SYSTEM,
)

logger = logging.getLogger(__name__)

# 默认操作者 (无认证系统时)
DEFAULT_ACTOR = ROLE_SYSTEM

# 不允许创建声音的 actor (空/匿名)
_BLOCKED_ACTORS = {"", "anonymous", "guest"}


# ==================================================================
# Actor 提取
# ==================================================================

def get_actor_id(request: Optional[Request] = None, header_name: str = "X-Actor-ID") -> str:
    """从请求头提取 actor_id

    优先级:
        1. X-Actor-ID 请求头 (若存在且非空)
        2. DEFAULT_ACTOR ("system")

    参数:
        request:     FastAPI Request (可选, 测试可直接传 None)
        header_name: 头名称 (默认 X-Actor-ID)
    """
    if request is not None:
        try:
            val = request.headers.get(header_name)
            if val and val.strip():
                return val.strip()
        except Exception:
            pass
    return DEFAULT_ACTOR


# ==================================================================
# 权限校验
# ==================================================================

class PermissionChecker:
    """API 层权限校验器

    封装 VoicePermission + 403 异常抛出, 供端点调用。

    使用:
        checker = PermissionChecker()
        checker.check_create(actor_id)                    # clone/batch
        checker.check_voice_action(svc, voice_id, actor_id, "delete")
    """

    def __init__(self, perm: Optional[VoicePermission] = None):
        self._perm = perm or VoicePermission()

    # ------------------------------------------------------------------
    # 创建类 (clone / batch): 无既有 profile
    # ------------------------------------------------------------------

    def check_create(self, actor_id: str, action: str = ACTION_WRITE) -> str:
        """校验创建类操作 (clone / batch)

        规则:
            - actor 为 system → 允许
            - actor 非 system 但非空/非 anonymous → 允许 (成为新 owner)
            - actor 为空/anonymous → 403

        返回:
            actor_id (校验通过)

        异常:
            HTTPException(403): 权限不足
        """
        if actor_id in _BLOCKED_ACTORS:
            logger.warning(f"权限拒绝: actor={actor_id!r} 不允许创建声音")
            raise HTTPException(
                status_code=403,
                detail=f"permission denied: actor '{actor_id}' 不允许创建声音",
            )
        return actor_id

    # ------------------------------------------------------------------
    # 既有声音操作: 基于 profile 校验
    # ------------------------------------------------------------------

    def check_voice_action(
        self,
        svc,
        voice_id: str,
        actor_id: str,
        action: str,
    ) -> bool:
        """校验对既有声音的操作权限

        参数:
            svc:       VoiceIdentityService (用于查询 profile)
            voice_id:  目标声音
            actor_id:  操作者
            action:    read/write/delete/synthesize

        返回:
            True (校验通过)

        异常:
            HTTPException(403): 权限不足
            HTTPException(404): 声音不存在 (仅当 action != write 创建场景)
        """
        profile = svc.get_voice(voice_id)
        if profile is None:
            # 声音不存在: delete/synthesize/read → 404; 不在此处抛 403
            raise HTTPException(
                status_code=404,
                detail=f"voice_id 不存在: {voice_id}",
            )
        try:
            self._perm.check(profile, actor_id, action)
        except Exception as e:
            logger.warning(
                f"权限拒绝: actor={actor_id} action={action} voice_id={voice_id}: {e}"
            )
            raise HTTPException(
                status_code=403,
                detail=f"permission denied: actor '{actor_id}' 无权对 voice '{voice_id}' 执行 {action}",
            ) from e
        return True

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    def check_read(self, svc, voice_id: str, actor_id: str) -> bool:
        return self.check_voice_action(svc, voice_id, actor_id, ACTION_READ)

    def check_write(self, svc, voice_id: str, actor_id: str) -> bool:
        return self.check_voice_action(svc, voice_id, actor_id, ACTION_WRITE)

    def check_delete(self, svc, voice_id: str, actor_id: str) -> bool:
        return self.check_voice_action(svc, voice_id, actor_id, ACTION_DELETE)

    def check_synthesize(self, svc, voice_id: str, actor_id: str) -> bool:
        return self.check_voice_action(svc, voice_id, actor_id, ACTION_SYNTHESIZE)


# ==================================================================
# 模块级单例
# ==================================================================

_checker: Optional[PermissionChecker] = None


def get_permission_checker() -> PermissionChecker:
    """获取全局 PermissionChecker 单例"""
    global _checker
    if _checker is None:
        _checker = PermissionChecker()
    return _checker


def reset_permission_checker() -> None:
    """重置全局单例 (测试用)"""
    global _checker
    _checker = None
