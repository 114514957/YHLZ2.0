"""
YHLZ 2.0 GPT-SoVITS 引擎 (M0.3)

BaseTTSEngine 包装 backend.tts.adapters.gpt_sovits_adapter.GPTSovitsAdapter,
使 GPT-SoVITS 可注册进 TTSManager 回退链 (Primary → Secondary → Fallback)。

说明:
- Gradio 交互全部收敛在 adapter 内 (M0.2 唯一实现约束)
- GPT-SoVITS 由权重决定声音, voice 参数传入时经 adapter 告警忽略
"""
import logging
from typing import AsyncGenerator, Optional, Tuple

import numpy as np

from backend.tts.base import BaseTTSEngine
from backend.tts.adapters.gpt_sovits_adapter import GPTSovitsAdapter

logger = logging.getLogger(__name__)

#: 默认 voice 值 (manager 默认参数), 传入 adapter 时不映射为 voice_id
_DEFAULT_VOICES = {"", "default", "Vivian"}


class GPTSovitsTTSEngine(BaseTTSEngine):
    """GPT-SoVITS 引擎 (Gradio 服务, 高保真)"""

    name = "gpt-sovits"

    def __init__(self, base_url: Optional[str] = None, **kwargs):
        super().__init__()
        self._adapter = GPTSovitsAdapter(base_url=base_url, **kwargs)

    @property
    def adapter(self) -> GPTSovitsAdapter:
        """底层适配器 (仅供测试/诊断)"""
        return self._adapter

    def load(self) -> bool:
        ok = self._adapter.load()
        self.is_loaded = ok
        return ok

    def unload(self) -> None:
        self._adapter.unload()
        self.is_loaded = False

    def release_gpu(self) -> None:
        self.unload()

    def synthesize(
        self,
        text: str,
        voice: str = "Vivian",
        rate: str = "+0%",
        **kwargs
    ) -> Tuple[np.ndarray, int]:
        voice_id = None if voice in _DEFAULT_VOICES else voice
        return self._adapter.generate(text, voice_id=voice_id, **kwargs)

    async def stream_synthesize_text(
        self,
        text: str,
        voice: str = "Vivian",
        **kwargs
    ) -> AsyncGenerator[Tuple[np.ndarray, int], None]:
        """GPT-SoVITS 非流式, 整段模拟流式"""
        audio, sr = self.synthesize(text, voice=voice, **kwargs)
        yield audio, sr

    def health_check(self) -> dict:
        return self._adapter.health_check()

    def change_weights(self, sovits_model: str, gpt_model: str, text_lang: str = "zh"):
        """热切换 GPT-SoVITS 权重"""
        self._adapter.change_weights(sovits_model, gpt_model, text_lang)

    def get_available_voices(self) -> list:
        return [{"id": "gpt-sovits", "name": "GPT-SoVITS (权重决定声音)"}]


gpt_sovits_engine = GPTSovitsTTSEngine()
