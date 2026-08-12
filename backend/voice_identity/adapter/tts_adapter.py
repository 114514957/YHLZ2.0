"""
YHLZ Voice Identity System V2.2 - TTS Adapter 抽象接口

职责:
    - 定义统一 TTS 适配器接口, 屏蔽 Qwen3 / GPT-SoVITS / Edge 差异
    - Pipeline 不直接调用具体引擎, 经本接口间接调用
    - 所有异常转换为 Result, 不向外抛

接口:
    class TTSAdapter:
        name: str
        def prepare_voice(audio_path, feature, metadata) -> Result[VoiceCacheInfo]
        def synthesize(voice_id, text, language) -> Result[str]

设计原则 (对齐 V2.2 Prompt):
    1. V1.1~V2.1 接口兼容: 不修改已有模块
    2. Pipeline 不直接调用模型: 经 Adapter
    3. Adapter 可替换: 抽象基类 + 注册表
    4. 所有异常转换为 Result: prepare/synthesize 返 Result, 不抛
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from backend.voice_identity.clone.result import Err, Ok, Result
from backend.voice_identity.clone.voice_analyzer import VoiceFeature

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceCacheInfo:
    """声音缓存元信息 (prepare_voice 成功后返回)

    字段 (对齐 V2.2 CloneResult 扩展):
        adapter:        适配器名 (qwen3 / gpt_sovits / edge)
        cache_path:     缓存目录或文件路径 (None 表示仅内存)
        embedding_hash: 说话人向量哈希 (mock 模式为 audio hash)
        quality_score:  克隆质量评分 0.0~1.0 (None 表示未评分)
        extra:          引擎特定元数据
    """
    adapter: str
    cache_path: Optional[str] = None
    embedding_hash: Optional[str] = None
    quality_score: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "adapter": self.adapter,
            "cache_path": self.cache_path,
            "embedding_hash": self.embedding_hash,
            "quality_score": self.quality_score,
            "extra": self.extra,
        }


class TTSAdapter(abc.ABC):
    """TTS 适配器抽象基类

    子类必须实现:
        name (类属性): 适配器名
        prepare_voice(): 提取并缓存声音特征
        synthesize(): 用已缓存声音合成语音

    约束:
        - 所有方法返回 Result, 不抛异常
        - 不直接读写 voice_identity DB (经 Pipeline/Manager)
        - 可读取 VoiceFeature / metadata 决定 prepare 策略
    """

    name: str = "abstract"

    @abc.abstractmethod
    def prepare_voice(
        self,
        audio_path: str,
        feature: VoiceFeature,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Result[VoiceCacheInfo]:
        """提取并缓存声音特征

        参数:
            audio_path: 参考音频路径 (已通过 validate_audio)
            feature:    声学特征 (含 F0/能量/SNR 等)
            metadata:   引擎特定元数据 (gpt_sovits 需含 sovits_model/gpt_model)

        返回:
            Ok(VoiceCacheInfo) / Err(原因)
        """
        raise NotImplementedError

    @abc.abstractmethod
    def synthesize(
        self,
        voice_id: str,
        text: str,
        language: str = "zh",
    ) -> Result[str]:
        """用已缓存声音合成语音

        参数:
            voice_id: 已 prepare 的声音 ID
            text:     待合成文本
            language: 语言 (zh/en/ja)

        返回:
            Ok(音频文件路径) / Err(原因)
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 可选能力探测 (子类按需 override)
    # ------------------------------------------------------------------

    def can_serve(self) -> bool:
        """是否可服务 (引擎已加载 / Gradio 可达)"""
        return True

    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {"name": self.name, "ok": self.can_serve()}


# ── Adapter 注册表 (可替换原则) ──

_ADAPTER_REGISTRY: Dict[str, type] = {}


def register_adapter(name: str):
    """装饰器: 注册 Adapter 类

    使用:
        @register_adapter("qwen3")
        class Qwen3TTSAdapter(TTSAdapter): ...
    """
    def deco(cls: type) -> type:
        if not issubclass(cls, TTSAdapter):
            raise TypeError(f"{cls.__name__} 必须继承 TTSAdapter")
        _ADAPTER_REGISTRY[name] = cls
        logger.debug(f"已注册 TTS Adapter: {name} -> {cls.__name__}")
        return cls
    return deco


def get_adapter_class(name: str) -> Optional[type]:
    """按名获取 Adapter 类"""
    return _ADAPTER_REGISTRY.get(name)


def list_adapters() -> list:
    """列出已注册 Adapter 名"""
    return sorted(_ADAPTER_REGISTRY.keys())


def build_adapter(
    name: str,
    config: Optional[Dict[str, Any]] = None,
) -> Result[TTSAdapter]:
    """按名构造 Adapter 实例

    参数:
        name:   适配器名 (qwen3 / gpt_sovits / edge)
        config: 构造参数 (mode/model_path/cache_dir 等)

    返回:
        Ok(TTSAdapter) / Err(原因)
    """
    cls = get_adapter_class(name)
    if cls is None:
        return Err(f"未注册的 Adapter: {name} (已注册: {list_adapters()})")
    try:
        adapter = cls(**(config or {}))
        if not isinstance(adapter, TTSAdapter):
            return Err(f"{cls.__name__} 实例不是 TTSAdapter")
        return Ok(adapter)
    except Exception as e:
        return Err(f"构造 Adapter {name} 失败: {e}")
