"""
YHLZ Voice Identity System V2.1 - Voice Clone Pipeline 克隆流水线

职责:
    - 编排完整克隆流程: 验证 → 分析 → 创建 Profile → Registry 注册 → Cache 初始化
    - 不破坏已有核心模块 (Service/Manager/Registry/Cache)
    - 返回 Result[CloneResult], 失败时尽量回滚已创建的 Profile

API:
    pipeline.clone_voice(
        audio_path, name, engine, owner, type, voice_id, metadata, language
    ) → Result[CloneResult]

架构层次 (对齐 Prompt):
    Service
      ↓
    Pipeline (本模块)
      ↓
    Manager / Registry / Cache (V1.4/V1.3/V1.5 已有模块)
      ↓
    Store → DB

流程:
    输入音频
      ↓
    audio_validator.validate_audio   → AudioInfo
      ↓
    voice_analyzer.analyze_voice     → VoiceFeature
      ↓
    manager.create_voice             → VoiceProfile (creating → ready)
      ↓
    registry.register_voice          → VoiceProfile (确保可发现)
      ↓
    cache.prepare                    → 填充 embedding 到 feature
      ↓
    返回 CloneResult { profile, feature, audio_info }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

from backend.voice_identity.cache_manager import VoiceCacheManager
from backend.voice_identity.clone.audio_validator import AudioInfo, validate_audio
from backend.voice_identity.clone.result import Err, Ok, Result
from backend.voice_identity.clone.voice_analyzer import VoiceFeature, analyze_voice
from backend.voice_identity.manager import VoiceManager
from backend.voice_identity.models import VoiceProfile
from backend.voice_identity.quality_gate import (
    GATE_THRESHOLD_READY,
    GATE_THRESHOLD_WARNING,
    STATUS_READY,
    STATUS_REJECT,
    STATUS_WARNING,
    QualityGate,
    QualityGateResult,
    get_quality_gate,
)
from backend.voice_identity.registry import VoiceRegistry, VoiceRegistryError

if TYPE_CHECKING:
    # 仅类型注解用, 运行时不导入 (避免 adapter ↔ clone 循环)
    from backend.voice_identity.adapter.tts_adapter import TTSAdapter, VoiceCacheInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CloneResult:
    """克隆流程产物

    V2.1 字段 (向后兼容):
        profile:        最终 VoiceProfile (status=ready, 已注册)
        feature:        声音特征快照 (含 embedding 填充结果)
        audio_info:     原始音频元信息
        cache_prepared: Cache.prepare 是否成功
        warnings:       非致命警告列表 (如 Cache 失败但 Profile 已创建)

    V2.2 新增字段 (auto_prepare=True 且 adapter 注入时填充, 否则 None):
        adapter:        适配器名 (qwen3 / gpt_sovits)
        cache_path:     Adapter 返回的缓存路径
        embedding_hash: 说话人向量哈希
        quality_score:  克隆质量评分 0.0~1.0

    V2.3-Phase5 新增字段 (自动质量门禁):
        quality_report:   质量门禁报告 (dict, 含各维度子分)
        quality_status:   门禁状态 ready/warning/reject
    """
    profile: VoiceProfile
    feature: VoiceFeature
    audio_info: AudioInfo
    cache_prepared: bool
    warnings: list = field(default_factory=list)
    # V2.2 扩展
    adapter: Optional[str] = None
    cache_path: Optional[str] = None
    embedding_hash: Optional[str] = None
    quality_score: Optional[float] = None
    # V2.3-Phase5 质量门禁
    quality_report: Optional[dict] = None
    quality_status: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "voice_id": self.profile.voice_id,
            "name": self.profile.name,
            "status": self.profile.status,
            "engine": self.profile.engine,
            "cache_prepared": self.cache_prepared,
            "warnings": self.warnings,
            "feature": self.feature.to_dict(),
            "audio": self.audio_info.to_dict(),
            # V2.2 扩展
            "adapter": self.adapter,
            "cache_path": self.cache_path,
            "embedding_hash": self.embedding_hash,
            "quality_score": self.quality_score,
            # V2.3-Phase5 质量门禁
            "quality_report": self.quality_report,
            "quality_status": self.quality_status,
        }


class VoiceClonePipeline:
    """声音克隆流水线 (编排 Validator → Analyzer → Manager → Registry → Cache → Adapter)

    构造参数:
        manager:  V1.4 VoiceManager (必需, 提供 create_voice)
        registry: V1.3 VoiceRegistry (可选, 缺省用 manager.registry)
        cache:    V1.5 VoiceCacheManager (可选, 缺省用 manager.cache; None 时跳过缓存)
        adapter:  V2.2 TTSAdapter (可选, 配合 auto_prepare=True 触发真实克隆)

    设计原则:
        - 不直接调 DB, 经 Manager/Registry/Cache
        - 不直接调 TTS 引擎, 经 Cache.prepare 间接 (V2.1) / 经 TTSAdapter 间接 (V2.2)
        - 失败回滚: Cache 失败不回滚 Profile (保留可手动修复); 验证/分析失败不创建 Profile
        - 幂等: 同一 voice_id 已存在时返回 Err (不覆盖)
        - V2.1 兼容: adapter=None + auto_prepare=False 时行为与 V2.1 完全一致
    """

    def __init__(
        self,
        manager: VoiceManager,
        registry: Optional[VoiceRegistry] = None,
        cache: Optional[VoiceCacheManager] = None,
        adapter: Optional[TTSAdapter] = None,
    ):
        self._manager = manager
        self._registry = registry or manager.registry
        self._cache = cache if cache is not None else manager.cache
        self._adapter = adapter

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
    def adapter(self) -> Optional[TTSAdapter]:
        """V2.2 注入的 TTSAdapter"""
        return self._adapter

    def set_adapter(self, adapter: Optional[TTSAdapter]) -> None:
        """V2.2 运行时切换 Adapter"""
        self._adapter = adapter
        logger.info(f"Pipeline 已切换 Adapter: {adapter.name if adapter else None}")

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def clone_voice(
        self,
        audio_path: str,
        name: str,
        engine: str = "qwen3",
        owner: str = "system",
        type: str = "user",
        voice_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        language: str = "zh",
        auto_prepare: bool = True,
    ) -> Result[CloneResult]:
        """执行声音克隆

        参数:
            audio_path:    参考音频路径
            auto_prepare:  V2.2 是否在 Profile 创建后调用 TTSAdapter.prepare_voice
                           (需 adapter 注入; 默认 True 兼容 V2.1 行为: 无 adapter 时跳过)
            name:        声音展示名 (如 "元亨默认")
            engine:      引擎 (qwen3 / gpt_sovits / edge)
            owner:       归属者
            type:        类型 (character/user/system; 克隆默认 user)
            voice_id:    显式 voice_id (缺省自动生成)
            metadata:    扩展元数据 (gpt_sovits 需含 sovits_model/gpt_model)
            language:    主语言

        返回:
            Ok(CloneResult) / Err(原因)

        失败语义:
            - 验证/分析失败 → Err, 不创建 Profile
            - voice_id 已存在 → Err, 不覆盖
            - Profile 创建失败 → Err
            - Registry 注册失败 → Err 并回滚 Profile (delete soft)
            - Cache prepare 失败 → 仍返 Ok, warnings 记录 (Profile 已就绪可手动修复)
        """
        warnings: list = []

        # 1. 音频验证
        v_result = validate_audio(audio_path)
        if v_result.is_err():
            return Err(f"[validate] {v_result.error}")
        audio_info = v_result.unwrap()

        # 2. 声音分析
        a_result = analyze_voice(audio_info)
        if a_result.is_err():
            return Err(f"[analyze] {a_result.error}")
        feature = a_result.unwrap()

        # 3. 创建 VoiceProfile (creating → ready, 含 cache.prepare)
        #    合并特征到 style, metadata 到 metadata
        style = feature.to_style_metadata()
        merged_meta = dict(metadata or {})
        # gpt_sovits 必须从 metadata 取权重路径
        if engine == "gpt_sovits" and not merged_meta.get("sovits_model"):
            warnings.append(
                "gpt_sovits 引擎未提供 metadata.sovits_model, Cache.prepare 将失败"
            )

        try:
            profile = self._manager.create_voice(
                name=name, type=type, owner=owner, engine=engine,
                voice_id=voice_id, reference_audio=audio_path,
                style=style, metadata=merged_meta, language=language,
            )
        except Exception as e:
            return Err(f"[create_voice] {e}")
        vid = profile.voice_id
        logger.info(f"克隆 Profile 已创建: {vid}")

        # 4. Registry 注册 (确保可发现; create_voice 已转 ready, 这里幂等)
        try:
            profile = self._registry.register_voice(vid)
        except VoiceRegistryError as e:
            # 回滚: 软删 Profile
            logger.warning(f"注册失败, 回滚 Profile {vid}: {e}")
            try:
                self._manager.delete_voice(vid, soft=True)
            except Exception as rb_err:
                logger.error(f"回滚失败 {vid}: {rb_err}")
            return Err(f"[register] {e}")

        # 5. Cache prepare 已在 manager.create_voice 内部触发 (V1.4 流程)
        #    这里仅检查结果并填充 embedding 字段
        cache_prepared = False
        if self._cache is not None:
            try:
                cache_prepared = self._cache.exists(vid)
                if not cache_prepared:
                    warnings.append(
                        f"Cache.prepare 未能为 {vid} 建立缓存 "
                        "(适配器未注入或引擎不支持); Profile 已就绪, 可后续手动 prepare"
                    )
            except Exception as e:
                warnings.append(f"Cache.exists 检查异常: {e}")
        else:
            warnings.append("未注入 CacheManager, 跳过缓存准备")

        # 6. V2.2 TTSAdapter.prepare_voice (auto_prepare=True 且 adapter 注入时)
        #    填充 CloneResult 扩展字段 (adapter/cache_path/embedding_hash/quality_score)
        adapter_name: Optional[str] = None
        cache_path: Optional[str] = None
        embedding_hash: Optional[str] = None
        quality_score: Optional[float] = None
        if auto_prepare and self._adapter is not None:
            try:
                ap_result = self._adapter.prepare_voice(
                    audio_path=audio_path, feature=feature, metadata=merged_meta,
                )
                if ap_result.is_ok:
                    info: VoiceCacheInfo = ap_result.unwrap()
                    adapter_name = info.adapter
                    cache_path = info.cache_path
                    embedding_hash = info.embedding_hash
                    quality_score = info.quality_score
                    logger.info(
                        f"Adapter prepare 成功: adapter={adapter_name} "
                        f"hash={embedding_hash} quality={quality_score}"
                    )
                else:
                    warnings.append(
                        f"Adapter.prepare_voice 失败 (不致命): {ap_result.error}"
                    )
            except Exception as e:
                warnings.append(f"Adapter.prepare_voice 异常 (不致命): {e}")
        elif auto_prepare and self._adapter is None:
            # V2.1 兼容: 无 adapter 时跳过, 不告警 (保持 V2.1 行为)
            logger.debug("auto_prepare=True 但未注入 Adapter, 跳过 (V2.1 兼容)")

        # 7. V2.3-Phase5 质量门禁评估
        #    基于 VoiceFeature (SNR/能量/时长) + Adapter quality_score
        #    REJECT 时尝试将 Profile 状态降级为 warning (不删除, 允许手动修复后重新激活)
        quality_report: Optional[dict] = None
        quality_status: Optional[str] = None
        try:
            gate = get_quality_gate()
            gate_result: QualityGateResult = gate.evaluate(
                feature=feature,
                adapter_quality_score=quality_score,
                audio_info=audio_info,
            )
            quality_report = gate_result.to_dict()
            quality_status = gate_result.status

            if gate_result.is_reject:
                # REJECT: 标记 Profile 状态为 warning (不进入 active), 记录告警
                warnings.append(
                    f"质量门禁 REJECT: {gate_result.reason} (Profile 标记为 warning, 禁止激活)"
                )
                try:
                    updated = self._manager.store.update(vid, status=STATUS_WARNING)
                    profile = updated
                except Exception as st_err:
                    warnings.append(f"质量门禁 REJECT 后状态更新失败: {st_err}")
            elif gate_result.status == STATUS_WARNING:
                warnings.append(f"质量门禁 WARNING: {gate_result.reason}")

            logger.info(
                f"质量门禁: voice_id={vid} score={gate_result.score:.3f} "
                f"status={gate_result.status}"
            )
        except Exception as qe:
            warnings.append(f"质量门禁评估异常 (不致命): {qe}")
            logger.warning(f"质量门禁评估异常 {vid}: {qe}")

        # 8. 返回结果
        result = CloneResult(
            profile=profile,
            feature=feature,
            audio_info=audio_info,
            cache_prepared=cache_prepared,
            warnings=warnings,
            adapter=adapter_name,
            cache_path=cache_path,
            embedding_hash=embedding_hash,
            quality_score=quality_score,
            quality_report=quality_report,
            quality_status=quality_status,
        )
        logger.info(
            f"克隆完成: voice_id={vid} cache_prepared={cache_prepared} "
            f"adapter={adapter_name} quality={quality_status} warnings={len(warnings)}"
        )
        return Ok(result)

    # ------------------------------------------------------------------
    # 便捷: 仅验证 + 分析 (不创建 Profile, 用于预检)
    # ------------------------------------------------------------------

    def preview(
        self,
        audio_path: str,
    ) -> Result[tuple]:
        """预检: 仅验证 + 分析, 不创建 Profile

        返回 Ok((AudioInfo, VoiceFeature)) / Err(原因)
        """
        v = validate_audio(audio_path)
        if v.is_err():
            return Err(f"[validate] {v.error}")
        a = analyze_voice(v.unwrap())
        if a.is_err():
            return Err(f"[analyze] {a.error}")
        return Ok((v.unwrap(), a.unwrap()))
