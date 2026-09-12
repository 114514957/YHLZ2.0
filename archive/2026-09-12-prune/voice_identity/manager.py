"""
YHLZ Voice Identity System V1.4 - Voice Manager 生命周期管理

职责:
    - 统一管理 VoiceProfile / Registry / Cache
    - 编排完整生命周期: CREATED → PROCESSING → READY → ACTIVE → DISABLED → DELETED

API (对齐 V1.4 Prompt):
    create_voice()    创建 (CREATED→PROCESSING→READY)
    activate_voice()  激活 (READY→ACTIVE)
    disable_voice()   停用 (ACTIVE/READY→DISABLED)
    delete_voice()    删除 (→DELETED)
    get_voice()       查询

约束:
    - 可调用 Registry (发现/校验)
    - 可调用 Cache (V1.5, 可选; None 时跳过缓存操作)
    - 禁止直接调用 GPT-SoVITS / 任何 TTS 引擎 (仅经 Cache 间接)

Cache 协议 (V1.5 实现, 此处 duck-typed):
    cache.prepare(voice_id, reference_audio)  PROCESSING 阶段准备
    cache.load(voice_id)                      ACTIVE 阶段加载
    cache.unload(voice_id)                    DISABLE 阶段卸载
    cache.remove(voice_id)                    DELETE 阶段清理
    cache.exists(voice_id) -> bool            存在性
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.voice_identity.models import VoiceProfile
from backend.voice_identity.profile import VoiceProfileError, VoiceProfileStore
from backend.voice_identity.registry import VoiceRegistry

logger = logging.getLogger(__name__)


class VoiceManagerError(Exception):
    """Voice Manager 业务异常"""


class VoiceManager:
    """声音生命周期管理器 (顶层编排)

    生命周期:
        create_voice  : CREATED(creating) → PROCESSING(processing) → READY(ready)
        activate_voice: READY(ready) → ACTIVE(active)
        disable_voice : ACTIVE/READY → DISABLED(disabled)
        delete_voice  : * → DELETED(deleted, 终态)
    """

    def __init__(
        self,
        store: Optional[VoiceProfileStore] = None,
        registry: Optional[VoiceRegistry] = None,
        cache: Optional[Any] = None,
    ):
        self._store = store or VoiceProfileStore()
        self._registry = registry or VoiceRegistry(self._store)
        # cache: V1.5 CacheManager 实例 (可选); None 时跳过所有缓存操作
        self._cache = cache

    @property
    def store(self) -> VoiceProfileStore:
        return self._store

    @property
    def registry(self) -> VoiceRegistry:
        return self._registry

    @property
    def cache(self) -> Optional[Any]:
        return self._cache

    def set_cache(self, cache: Any) -> None:
        """注入 V1.5 CacheManager (允许延迟绑定)"""
        self._cache = cache
        logger.info("VoiceManager 已绑定 Cache")

    # ------------------------------------------------------------------
    # 缓存调用封装 (经 Cache 间接, 永不直接触引擎)
    # ------------------------------------------------------------------

    def _cache_prepare(self, voice_id: str, reference_audio: Optional[str]) -> None:
        if self._cache is None:
            logger.debug(f"无 Cache, 跳过 prepare: {voice_id}")
            return
        try:
            self._cache.prepare(voice_id, reference_audio)
        except Exception as e:
            logger.warning(f"Cache prepare 失败 {voice_id}: {e}")

    def _cache_load(self, voice_id: str) -> None:
        if self._cache is None:
            return
        try:
            self._cache.load(voice_id)
        except Exception as e:
            logger.warning(f"Cache load 失败 {voice_id}: {e}")

    def _cache_unload(self, voice_id: str) -> None:
        if self._cache is None:
            return
        try:
            self._cache.unload(voice_id)
        except Exception as e:
            logger.warning(f"Cache unload 失败 {voice_id}: {e}")

    def _cache_remove(self, voice_id: str) -> None:
        if self._cache is None:
            return
        try:
            self._cache.remove(voice_id)
        except Exception as e:
            logger.warning(f"Cache remove 失败 {voice_id}: {e}")

    # ------------------------------------------------------------------
    # 生命周期 API
    # ------------------------------------------------------------------

    def create_voice(
        self,
        name: str,
        type: str = "character",
        owner: str = "system",
        engine: str = "qwen3",
        voice_id: Optional[str] = None,
        reference_audio: Optional[str] = None,
        style: Optional[dict] = None,
        metadata: Optional[dict] = None,
        language: str = "zh",
    ) -> VoiceProfile:
        """创建声音: CREATED → PROCESSING → READY

        - 创建 Profile (creating)
        - 若有 Cache: 转 processing, 准备缓存
        - 转 ready (可发现)
        返回 ready 状态的 Profile。
        """
        # CREATED
        profile = self._store.create(
            name=name, type=type, owner=owner, engine=engine,
            voice_id=voice_id, reference_audio=reference_audio,
            style=style, metadata=metadata, language=language, status="creating",
        )
        vid = profile.voice_id
        logger.info(f"create_voice CREATED: {vid}")

        # PROCESSING (仅在有 cache 时进入; 否则直接 ready)
        if self._cache is not None:
            try:
                profile = self._store.mark_processing(vid)
                logger.info(f"create_voice PROCESSING: {vid}")
                self._cache_prepare(vid, reference_audio)
            except VoiceProfileError as e:
                logger.warning(f"进入 processing 失败 {vid}: {e}")

        # READY
        try:
            profile = self._store.mark_ready(vid)
        except VoiceProfileError as e:
            raise VoiceManagerError(f"无法就绪 {vid}: {e}") from e
        logger.info(f"create_voice READY: {vid}")
        return profile

    def activate_voice(self, voice_id: str) -> VoiceProfile:
        """激活声音: READY → ACTIVE

        - 必须可发现 (ready/active); ready→active
        - active 幂等
        - 加载缓存
        """
        profile = self._registry.get_voice(voice_id)
        if profile is None:
            raise VoiceManagerError(f"声音不可发现或不存在, 无法激活: {voice_id}")
        if profile.status == "active":
            self._cache_load(voice_id)
            return profile
        # ready → active
        try:
            profile = self._store.activate(voice_id)
        except VoiceProfileError as e:
            raise VoiceManagerError(f"激活失败 (状态非法 {profile.status}): {e}") from e
        self._cache_load(voice_id)
        logger.info(f"activate_voice ACTIVE: {voice_id}")
        return profile

    def disable_voice(self, voice_id: str) -> VoiceProfile:
        """停用声音: ACTIVE/READY → DISABLED

        - 卸载缓存
        - active→disabled 或 ready→disabled
        """
        profile = self._store.get(voice_id)
        if profile is None:
            raise VoiceManagerError(f"声音不存在: {voice_id}")
        if profile.status == "deleted":
            raise VoiceManagerError(f"已删除声音不可停用: {voice_id}")
        self._cache_unload(voice_id)
        try:
            profile = self._store.disable(voice_id)
        except VoiceProfileError as e:
            raise VoiceManagerError(f"停用失败 (状态非法 {profile.status}): {e}") from e
        logger.info(f"disable_voice DISABLED: {voice_id}")
        return profile

    def delete_voice(self, voice_id: str, soft: bool = True) -> bool:
        """删除声音: → DELETED

        - soft=True: 注销 + status=deleted (保留数据, 清缓存可选)
        - soft=False: 注销 + 清缓存 + 物理删除 (级联)
        """
        profile = self._store.get(voice_id)
        if profile is None:
            return False
        # 注销 (从发现层移除)
        try:
            self._registry.unregister_voice(voice_id)
        except Exception as e:
            logger.debug(f"注销时 {voice_id}: {e}")
        # 硬删清缓存; 软删保留缓存 (V1.5 约定: 删除清缓存, 禁用保留)
        if not soft:
            self._cache_remove(voice_id)
        ok = self._store.delete(voice_id, soft=soft)
        if ok:
            logger.info(f"delete_voice DELETED (soft={soft}): {voice_id}")
        return ok

    def get_voice(self, voice_id: str) -> Optional[VoiceProfile]:
        """查询声音 (任意状态, 不限可发现)"""
        return self._store.get(voice_id)

    # ------------------------------------------------------------------
    # 便捷查询 (经 Registry)
    # ------------------------------------------------------------------

    def list_voices(
        self,
        owner: Optional[str] = None,
        type: Optional[str] = None,
        discoverable_only: bool = True,
    ) -> List[VoiceProfile]:
        """列出声音 (默认仅可发现)"""
        return self._registry.list_voice(
            owner=owner, type=type, discoverable_only=discoverable_only
        )

    def get_active_voices(self) -> List[VoiceProfile]:
        """当前激活 (active) 的声音"""
        return self._registry.list_voice(status="active", discoverable_only=True)
