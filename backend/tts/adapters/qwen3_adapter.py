"""
YHLZ 2.0 Qwen3-TTS 引擎适配器 (M0.2)

包装 backend.tts.qwen3_tts.Qwen3TTSEngine (语音克隆引擎),
透传 M0.1 多声音缓存能力 (load_voice_cache / get_voice_cache / clear_voice_cache)。
保持原有功能不变, 仅迁移调用入口。
"""
import logging
import os
from typing import Optional, Tuple

import numpy as np

from backend.tts.adapters.base import BaseVoiceEngineAdapter
from backend.tts.qwen3_tts import Qwen3TTSEngine, qwen3_tts_engine, DEFAULT_VOICE_ID
from backend.tts.voice_style import VoiceStyle, speed_to_rate

logger = logging.getLogger(__name__)


class Qwen3TTSAdapter(BaseVoiceEngineAdapter):
    """Qwen3-TTS 适配器 (语音克隆, 多声音缓存)"""

    name = "qwen3-tts"
    engine_type = "qwen3"

    def __init__(self, engine: Optional[Qwen3TTSEngine] = None):
        super().__init__()
        self._engine: Qwen3TTSEngine = engine or qwen3_tts_engine
        self.is_loaded = self._engine.is_loaded

    @property
    def engine(self) -> Qwen3TTSEngine:
        """底层引擎实例 (仅供测试/诊断)"""
        return self._engine

    # ------------------------------------------------------------------
    # BaseVoiceEngineAdapter 接口
    # ------------------------------------------------------------------

    def load(self) -> bool:
        ok = self._engine.load()
        self.is_loaded = ok
        return ok

    def unload(self) -> None:
        self._engine.unload()
        self.is_loaded = False

    def generate(
        self,
        text: str,
        voice_id: Optional[str] = None,
        voice_style: Optional[VoiceStyle] = None,
        rate: str = "+0%",
        **params,
    ) -> Tuple[np.ndarray, int]:
        """统一合成入口; voice_id 直通 M0.1 多声音缓存

        M0.5: voice_style.speed 覆盖 rate 参数 (speed→rate 字符串翻译);
        pitch/energy 当前 Qwen3-TTS 不支持, 静默忽略并 debug 日志。
        禁止在此重新做情绪分类 — emotion 字段仅 metadata。
        """
        # VoiceStyle 翻译: 只消费数值字段, 不依赖 emotion 标签
        if voice_style is not None:
            rate = speed_to_rate(voice_style.speed)
            if voice_style.pitch != 0.0:
                logger.debug(f"Qwen3-TTS 不支持 pitch 调整, 忽略: {voice_style.pitch}")
            if voice_style.energy != 1.0:
                logger.debug(f"Qwen3-TTS 不支持 energy 调整, 忽略: {voice_style.energy}")
        return self._engine.synthesize(text, voice_id=voice_id, rate=rate, **params)

    def health_check(self) -> dict:
        return {
            "ok": self._engine.is_loaded,
            "loaded": self._engine.is_loaded,
            "name": self.name,
            "model_path_exists": os.path.isdir(self._engine._model_path),
            "multi_voice": True,
            "voice_cache": self._engine.get_voice_cache_stats(),
        }

    def can_serve(self) -> bool:
        return self._engine.is_loaded

    # ------------------------------------------------------------------
    # M0.1 多声音能力透传 (底层能力, 不绑定 Voice Identity)
    # ------------------------------------------------------------------

    def load_voice(
        self,
        voice_id: str = DEFAULT_VOICE_ID,
        ref_audio: Optional[str] = None,
        x_vector_only_mode: bool = True,
    ) -> Optional[dict]:
        """加载指定声音: 提取说话人特征并缓存"""
        return self._engine.load_voice_cache(voice_id, ref_audio, x_vector_only_mode)

    def get_voice(self, voice_id: str = DEFAULT_VOICE_ID) -> Optional[dict]:
        """读取指定声音缓存 {prompt, embedding, metadata}"""
        return self._engine.get_voice_cache(voice_id)

    def clear_voice(self, voice_id: Optional[str] = None) -> int:
        """清空指定 (或全部) 声音缓存, 返回清理数量"""
        return self._engine.clear_voice_cache(voice_id)

    def get_available_voices(self) -> list:
        stats = self._engine.get_voice_cache_stats()
        return [
            {"id": vid, "cached": True}
            for vid in stats["voice_ids"]
        ]
