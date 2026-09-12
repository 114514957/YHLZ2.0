"""
YHLZ Voice Identity System V1.6 - Voice Identity Service API

职责:
    - 内部 Service Layer (非 Web API, 不创建 FastAPI)
    - 组合 Manager + Registry + Cache, 提供统一入口
    - 未来 WebUI / CLI / Plugin 均调用本 Service

API (对齐 V1.6 Prompt):
    create_voice()   创建声音
    get_voice()      查询声音
    list_voice()     列出声音
    delete_voice()   删除声音
    select_voice()   选择当前使用声音 (单激活策略)

设计原则:
    - 薄封装: 委托 Manager/Registry/Cache, 不重复业务逻辑
    - select_voice 实现单激活选择 (同时仅一个 active), 持久化到 schema_meta
    - 提供 create_default() 工厂, 便于生产接线
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.voice_identity.adapter.config import (
    VoiceCloneConfig,
    build_adapter_from_config,
    load_config,
)
from backend.voice_identity.adapter.tts_adapter import TTSAdapter
from backend.voice_identity.cache_manager import VoiceCacheManager
from backend.voice_identity.clone import (
    CloneResult,
    Result,
    VoiceClonePipeline,
)
from backend.voice_identity.database import VoiceIdentityDB, get_db
from backend.voice_identity.manager import VoiceManager, VoiceManagerError
from backend.voice_identity.models import VoiceProfile
from backend.voice_identity.profile import VoiceProfileStore
from backend.voice_identity.registry import VoiceRegistry

logger = logging.getLogger(__name__)

# schema_meta 中持久化"当前选中声音"的键
META_SELECTED_VOICE = "selected_voice"


class VoiceIdentityService:
    """Voice Identity 统一服务入口

    组合层次: Service → Manager → Registry/Cache → Store → DB
    """

    def __init__(
        self,
        manager: Optional[VoiceManager] = None,
        registry: Optional[VoiceRegistry] = None,
        cache: Optional[VoiceCacheManager] = None,
        db: Optional[VoiceIdentityDB] = None,
    ):
        self._db = db or get_db()
        self._store = (manager.store if manager else None) or VoiceProfileStore(self._db)
        self._registry = registry or VoiceRegistry(self._store)
        self._cache = cache or (manager.cache if manager else None)
        self._manager = manager or VoiceManager(
            store=self._store, registry=self._registry, cache=self._cache
        )

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def manager(self) -> VoiceManager:
        return self._manager

    @property
    def registry(self) -> VoiceRegistry:
        return self._registry

    @property
    def cache(self) -> Optional[VoiceCacheManager]:
        return self._cache

    @property
    def db(self) -> VoiceIdentityDB:
        return self._db

    # ------------------------------------------------------------------
    # API
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
        """创建声音 (CREATED→PROCESSING→READY)"""
        return self._manager.create_voice(
            name=name, type=type, owner=owner, engine=engine, voice_id=voice_id,
            reference_audio=reference_audio, style=style, metadata=metadata,
            language=language,
        )

    def get_voice(self, voice_id: str) -> Optional[VoiceProfile]:
        """查询声音 (任意状态)"""
        return self._manager.get_voice(voice_id)

    def list_voice(
        self,
        owner: Optional[str] = None,
        type: Optional[str] = None,
        status: Optional[str] = None,
        engine: Optional[str] = None,
        discoverable_only: bool = True,
    ) -> List[VoiceProfile]:
        """列出声音 (默认仅可发现)"""
        return self._registry.list_voice(
            owner=owner, type=type, status=status, engine=engine,
            discoverable_only=discoverable_only,
        )

    def delete_voice(self, voice_id: str, soft: bool = True) -> bool:
        """删除声音

        soft=True: 软删 (status=deleted, 保留缓存与数据)
        soft=False: 硬删 (级联清理 + 清缓存)
        若删除的是当前选中声音, 清除选中状态。
        """
        if self.get_selected_voice_id() == voice_id:
            self._db.delete_meta(META_SELECTED_VOICE)
        return self._manager.delete_voice(voice_id, soft=soft)

    def select_voice(self, voice_id: str) -> VoiceProfile:
        """选择当前使用声音 (单激活策略)

        - 不存在/已删除 → VoiceIdentityServiceError
        - 非 ready/active → 先注册 (→ready)
        - 若当前有其他 active 声音 → 先去激活 (active→ready)
        - 激活目标 (ready→active) + 加载缓存
        - 持久化选中状态 (schema_meta)
        """
        profile = self._manager.get_voice(voice_id)
        if profile is None:
            raise VoiceIdentityServiceError(f"声音不存在: {voice_id}")
        if profile.status == "deleted":
            raise VoiceIdentityServiceError(f"已删除声音不可选择: {voice_id}")

        # 单激活: 去激活其他 active 声音 (active→ready, 保留可发现)
        current = self.get_selected_voice_id()
        if current and current != voice_id:
            cur_profile = self._manager.get_voice(current)
            if cur_profile and cur_profile.status == "active":
                try:
                    self._store.deactivate(current)
                    if self._cache is not None:
                        self._cache.unload(current)
                    logger.info(f"去激活旧选中声音: {current}")
                except Exception as e:
                    logger.warning(f"去激活旧声音失败 {current}: {e}")

        # 确保目标可发现 (ready/active)
        if profile.status not in ("ready", "active"):
            try:
                self._registry.register_voice(voice_id)  # →ready
            except Exception as e:
                raise VoiceIdentityServiceError(f"声音未就绪, 无法选择: {e}") from e

        # 激活
        try:
            profile = self._manager.activate_voice(voice_id)
        except VoiceManagerError as e:
            raise VoiceIdentityServiceError(f"激活失败: {e}") from e

        # 持久化选中
        self._db.set_meta(META_SELECTED_VOICE, voice_id)
        logger.info(f"已选择声音: {voice_id}")
        return profile

    # ------------------------------------------------------------------
    # V2.1 声音克隆
    # ------------------------------------------------------------------

    def clone_voice(
        self,
        audio_path: str,
        name: str,
        engine: str = "qwen3",
        owner: str = "system",
        type: str = "user",
        voice_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        language: str = "zh",
        auto_prepare: bool = True,
    ) -> Result[CloneResult]:
        """声音克隆入口 (V2.1 基础 + V2.2 auto_prepare)

        委托 VoiceClonePipeline 编排:
            验证 → 分析 → 创建 Profile → 注册 → Cache → (V2.2) Adapter.prepare_voice

        参数:
            audio_path:    参考音频路径
            name:          声音展示名
            engine:        引擎 (qwen3/gpt_sovits/edge)
            owner:         归属者
            type:          类型 (克隆默认 user)
            voice_id:      显式 voice_id (缺省自动生成)
            metadata:      扩展元数据 (gpt_sovits 需含 sovits_model/gpt_model)
            language:      主语言
            auto_prepare:  V2.2 是否触发 Adapter.prepare_voice (需 adapter 注入)

        返回:
            Result[CloneResult]; 成功携带 profile+feature+audio_info,
            失败携带原因字符串 (不抛异常, 调用方按需 unwrap_or_raise)

        注意:
            - 不破坏已有 create_voice/select_voice; 克隆走独立 Pipeline
            - 克隆成功后 Profile 处于 ready 状态, 可后续 select_voice 激活
            - Cache/Adapter 失败不会回滚 Profile, 会在 CloneResult.warnings 中记录
            - V2.1 兼容: 未注入 adapter 时 auto_prepare 自动失效, 行为同 V2.1
        """
        pipeline = self._get_pipeline()
        return pipeline.clone_voice(
            audio_path=audio_path, name=name, engine=engine, owner=owner,
            type=type, voice_id=voice_id, metadata=metadata, language=language,
            auto_prepare=auto_prepare,
        )

    def clone_voice_with_adapter(
        self,
        audio_path: str,
        name: str,
        engine: str = "qwen3",
        owner: str = "system",
        type: str = "user",
        voice_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        language: str = "zh",
        auto_prepare: bool = True,
        adapter: Optional[TTSAdapter] = None,
    ) -> Result[CloneResult]:
        """请求级 Adapter 上下文绑定克隆 (并发安全, Phase 工程化项)

        与 clone_voice 区别: 不修改全局 _adapter, 使用请求级临时 adapter 实例,
        避免并发请求互相覆盖。

        参数:
            adapter: 请求级 adapter; None 则用全局 _adapter (退化为 clone_voice 行为)

        返回:
            Result[CloneResult]
        """
        if adapter is None:
            return self.clone_voice(
                audio_path=audio_path, name=name, engine=engine, owner=owner,
                type=type, voice_id=voice_id, metadata=metadata, language=language,
                auto_prepare=auto_prepare,
            )
        # 请求级临时 pipeline, 复用 manager/registry/cache, 独立 adapter
        tmp_pipeline = VoiceClonePipeline(
            manager=self._manager,
            registry=self._registry,
            cache=self._cache,
            adapter=adapter,
        )
        return tmp_pipeline.clone_voice(
            audio_path=audio_path, name=name, engine=engine, owner=owner,
            type=type, voice_id=voice_id, metadata=metadata, language=language,
            auto_prepare=auto_prepare,
        )

    def _get_pipeline(self) -> VoiceClonePipeline:
        """懒加载 Pipeline (复用 service 的 manager/registry/cache; V2.2 注入 adapter)"""
        cached = getattr(self, "_pipeline", None)
        if cached is None:
            cached = VoiceClonePipeline(
                manager=self._manager,
                registry=self._registry,
                cache=self._cache,
                adapter=getattr(self, "_adapter", None),
            )
            self._pipeline = cached  # type: ignore[attr-defined]
        return cached

    def set_pipeline(self, pipeline: VoiceClonePipeline) -> None:
        """显式注入 Pipeline (测试/高级装配用)"""
        self._pipeline = pipeline  # type: ignore[assignment]
        logger.info("VoiceIdentityService 已注入 VoiceClonePipeline")

    # ------------------------------------------------------------------
    # V2.2 TTS Adapter 注入
    # ------------------------------------------------------------------

    def set_adapter(self, adapter: Optional[TTSAdapter]) -> None:
        """注入 TTSAdapter (V2.2)

        注入后 clone_voice(auto_prepare=True) 会调用 adapter.prepare_voice,
        填充 CloneResult 的 adapter/cache_path/embedding_hash/quality_score 字段。
        """
        self._adapter = adapter  # type: ignore[attr-defined]
        # 同步到已存在的 pipeline
        pipeline = getattr(self, "_pipeline", None)
        if pipeline is not None:
            pipeline.set_adapter(adapter)
        if adapter is not None:
            logger.info(f"Service 已注入 TTSAdapter: {adapter.name}")
        else:
            logger.info("Service 已移除 TTSAdapter")

    def get_adapter(self) -> Optional[TTSAdapter]:
        """获取已注入的 TTSAdapter"""
        return getattr(self, "_adapter", None)

    def load_adapter_from_config(
        self, engine: Optional[str] = None, config: Optional[VoiceCloneConfig] = None,
    ) -> Result[TTSAdapter]:
        """从 voice_clone_config.json 加载并注入 Adapter

        参数:
            engine: 引擎名 (缺省用 config.default_engine)
            config: 显式配置 (缺省 load_config())
        返回:
            Ok(TTSAdapter) 已注入; Err(原因)
        """
        cfg = config or load_config()
        eng = engine or cfg.default_engine
        result = build_adapter_from_config(eng, cfg)
        if result.is_ok:
            self.set_adapter(result.unwrap())
        return result

    def synthesize(
        self, voice_id: str, text: str, language: str = "zh",
    ) -> Result[str]:
        """用已克隆声音合成语音 (V2.2)

        需先注入 TTSAdapter (经 set_adapter / load_adapter_from_config)。
        返回 Ok(音频文件路径) / Err(原因)
        """
        adapter = self.get_adapter()
        if adapter is None:
            return Err("未注入 TTSAdapter, 无法合成 (请先 set_adapter 或 load_adapter_from_config)")
        return adapter.synthesize(voice_id=voice_id, text=text, language=language)

    # ------------------------------------------------------------------
    # 选中状态
    # ------------------------------------------------------------------

    def get_selected_voice_id(self) -> Optional[str]:
        """当前选中的 voice_id (持久化, 重启可恢复)"""
        return self._db.get_meta(META_SELECTED_VOICE)

    def get_selected_voice(self) -> Optional[VoiceProfile]:
        """当前选中的 Profile (不存在/已删除返回 None)"""
        vid = self.get_selected_voice_id()
        if vid is None:
            return None
        p = self._manager.get_voice(vid)
        if p is None or p.status == "deleted":
            return None
        return p

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """服务健康快照 (供 V1.7 审计/WebUI)"""
        return {
            "db": self._db.health(),
            "cache": self._cache.stats() if self._cache else None,
            "selected_voice": self.get_selected_voice_id(),
            "discoverable_count": len(self._registry.list_voice()),
            "active_count": len(self._manager.get_active_voices()),
        }

    # ------------------------------------------------------------------
    # 工厂 (生产接线)
    # ------------------------------------------------------------------

    @classmethod
    def create_default(
        cls,
        qwen3_adapter: Optional[Any] = None,
        gpt_sovits_adapter: Optional[Any] = None,
        db: Optional[VoiceIdentityDB] = None,
    ) -> "VoiceIdentityService":
        """生产默认装配: db → store → registry → cache → manager → service

        适配器参数缺省 None 时, CacheManager 仍可工作 (缓存操作静默跳过),
        待引擎就绪后经 set 注入或重新装配。
        """
        _db = db or get_db()
        store = VoiceProfileStore(_db)
        registry = VoiceRegistry(store)
        cache = VoiceCacheManager(
            qwen3_adapter=qwen3_adapter,
            gpt_sovits_adapter=gpt_sovits_adapter,
            db=_db,
        )
        manager = VoiceManager(store=store, registry=registry, cache=cache)
        return cls(manager=manager, registry=registry, cache=cache, db=_db)


class VoiceIdentityServiceError(Exception):
    """Voice Identity Service 业务异常"""
