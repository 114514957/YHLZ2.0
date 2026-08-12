"""
YHLZ 2.0 TTS 引擎适配器包 (M0.2)

统一引擎调用层: 未来 Voice Identity System 只通过本包接口调用引擎,
不感知具体引擎 (Qwen3 / GPT-SoVITS / Edge) 实现。

base.py              BaseVoiceEngineAdapter 抽象基类 (generate/load/unload/health_check)
qwen3_adapter.py     Qwen3-TTS 适配器 (语音克隆, M0.1 多声音缓存透传)
gpt_sovits_adapter.py  GPT-SoVITS 适配器 (GradioClient 唯一实现)
edge_adapter.py      Edge-TTS 适配器 (预留接口)
"""
import logging
from typing import Optional

from backend.tts.adapters.base import BaseVoiceEngineAdapter
from backend.tts.adapters.qwen3_adapter import Qwen3TTSAdapter
from backend.tts.adapters.gpt_sovits_adapter import GPTSovitsAdapter, GradioClient
from backend.tts.adapters.edge_adapter import EdgeTTSAdapter

logger = logging.getLogger(__name__)

__all__ = [
    "BaseVoiceEngineAdapter",
    "Qwen3TTSAdapter",
    "GPTSovitsAdapter",
    "GradioClient",
    "EdgeTTSAdapter",
    "create_tts_adapter",
    "list_adapters",
]

#: 适配器注册表: name -> (factory, available)
_ADAPTER_REGISTRY = {
    "qwen3": (Qwen3TTSAdapter, True),
    "qwen3-tts": (Qwen3TTSAdapter, True),
    "gpt-sovits": (GPTSovitsAdapter, True),
    "gpt_sovits": (GPTSovitsAdapter, True),
    "edge": (EdgeTTSAdapter, True),
    "edge-tts": (EdgeTTSAdapter, True),
}


def create_tts_adapter(engine_name: str, **kwargs) -> BaseVoiceEngineAdapter:
    """按引擎名创建适配器实例

    未来 VIS 示例:
        adapter = create_tts_adapter(voice_spec.engine)   # qwen3 / gpt-sovits / edge
        audio, sr = adapter.generate(text, voice_id=voice_id)
    """
    key = str(engine_name).strip().lower()
    if key not in _ADAPTER_REGISTRY:
        raise ValueError(
            f"未知引擎适配器: {engine_name}, 可用: {list(_ADAPTER_REGISTRY.keys())}"
        )
    factory, _ = _ADAPTER_REGISTRY[key]
    return factory(**kwargs)


def list_adapters() -> list:
    """适配器清单 (去重)"""
    seen = set()
    result = []
    for factory, _ in _ADAPTER_REGISTRY.values():
        if factory in seen:
            continue
        seen.add(factory)
        result.append({"name": factory.name, "engine_type": factory.engine_type})
    return result
