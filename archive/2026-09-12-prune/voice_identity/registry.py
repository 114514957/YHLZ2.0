"""
YHLZ Voice Identity System V1.3 - Voice Registry 注册中心

职责:
    - 声音发现 / 声音注册 / 声音索引
    - 在 VoiceProfileStore 之上提供"可发现"语义层

API (对齐 V1.3 Prompt):
    register_voice(voice_id)      注册 (使声音可被发现)
    unregister_voice(voice_id)    注销 (从发现层隐藏, 不删数据)
    get_voice(voice_id)           发现查询 (仅返回可发现声音)
    list_voice(owner/type/status) 索引查询

设计原则:
    - 只管理身份, 不直接调用 TTS, 不处理模型加载
    - 无独立索引存储: 以 profile.status 作为"可发现"信号, DB 即索引
      (ready/active = 可发现; creating/disabled/deleted = 不可发现)
    - register/unregister 通过 ProfileStore 状态机转移, 不绕过校验
    - 支持三类声音: character(角色) / user(用户) / system(系统)
"""
from __future__ import annotations

import logging
from typing import List, Optional

from backend.voice_identity.profile import VoiceProfileError, VoiceProfileStore
from backend.voice_identity.models import VoiceProfile

logger = logging.getLogger(__name__)

# 可发现状态: register 后落入这些状态之一即被 Registry 视为已注册/可发现
DISCOVERABLE_STATUS = ("ready", "active")


class VoiceRegistryError(Exception):
    """Voice Registry 业务异常"""


class VoiceRegistry:
    """声音注册中心 (发现层)

    线程安全由底层 VoiceProfileStore / VoiceIdentityDB 保证。
    """

    def __init__(self, store: Optional[VoiceProfileStore] = None):
        self._store = store or VoiceProfileStore()

    @property
    def store(self) -> VoiceProfileStore:
        return self._store

    # ------------------------------------------------------------------
    # 注册 / 注销
    # ------------------------------------------------------------------

    def register_voice(self, voice_id: str) -> VoiceProfile:
        """注册声音: 使其可被发现

        - 不存在 → VoiceRegistryError
        - deleted → 不可注册 (需先恢复)
        - creating/disabled → 自动转移到 ready
        - ready/active → 幂等返回

        返回注册后的 Profile。
        """
        profile = self._store.get(voice_id)
        if profile is None:
            raise VoiceRegistryError(f"声音不存在, 无法注册: {voice_id}")
        if profile.status == "deleted":
            raise VoiceRegistryError(f"已删除声音不可注册: {voice_id}")

        if profile.status not in DISCOVERABLE_STATUS:
            # creating/disabled → ready (经状态机校验)
            try:
                profile = self._store.mark_ready(voice_id)
            except VoiceProfileError as e:
                raise VoiceRegistryError(f"注册失败, 状态转移非法: {e}") from e

        logger.info(f"声音已注册: voice_id={voice_id} status={profile.status}")
        return profile

    def unregister_voice(self, voice_id: str) -> bool:
        """注销声音: 从发现层隐藏 (不删除数据)

        - ready/active → disabled (隐藏)
        - 其他状态 → 幂等返回 True (本就不可发现)
        - 不存在 → False
        """
        profile = self._store.get(voice_id)
        if profile is None:
            return False
        if profile.status in DISCOVERABLE_STATUS:
            try:
                self._store.disable(voice_id)
            except VoiceProfileError as e:
                raise VoiceRegistryError(f"注销失败, 状态转移非法: {e}") from e
        logger.info(f"声音已注销: voice_id={voice_id}")
        return True

    # ------------------------------------------------------------------
    # 发现 / 索引查询
    # ------------------------------------------------------------------

    def get_voice(self, voice_id: str) -> Optional[VoiceProfile]:
        """发现查询: 仅返回可发现 (ready/active) 的声音, 否则 None"""
        profile = self._store.get(voice_id)
        if profile is None or profile.status not in DISCOVERABLE_STATUS:
            return None
        return profile

    def list_voice(
        self,
        owner: Optional[str] = None,
        type: Optional[str] = None,
        status: Optional[str] = None,
        engine: Optional[str] = None,
        discoverable_only: bool = True,
    ) -> List[VoiceProfile]:
        """索引查询

        优先级:
        - status 显式给定 → 按 status 精确筛选 (可查任意状态)
        - status=None + discoverable_only=True → 仅 ready/active (可发现视图)
        - status=None + discoverable_only=False → 全部
        - owner/type/engine 可叠加筛选
        - 支持三类: type=character/user/system
        """
        if status is not None:
            return self._store.list(owner=owner, type=type, status=status, engine=engine)
        if discoverable_only:
            ready = self._store.list(owner=owner, type=type, status="ready", engine=engine)
            active = self._store.list(owner=owner, type=type, status="active", engine=engine)
            # 去重 (按 voice_id), 保持顺序
            seen = set()
            result: List[VoiceProfile] = []
            for p in ready + active:
                if p.voice_id not in seen:
                    seen.add(p.voice_id)
                    result.append(p)
            return result
        return self._store.list(owner=owner, type=type, status=status, engine=engine)

    # ------------------------------------------------------------------
    # 便捷: 按类型发现
    # ------------------------------------------------------------------

    def list_character_voices(self, owner: Optional[str] = None) -> List[VoiceProfile]:
        """角色声音"""
        return self.list_voice(owner=owner, type="character")

    def list_user_voices(self, owner: Optional[str] = None) -> List[VoiceProfile]:
        """用户声音"""
        return self.list_voice(owner=owner, type="user")

    def list_system_voices(self) -> List[VoiceProfile]:
        """系统声音"""
        return self.list_voice(type="system")

    def is_registered(self, voice_id: str) -> bool:
        """是否已注册 (可发现)"""
        return self.get_voice(voice_id) is not None
