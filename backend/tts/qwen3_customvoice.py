"""
YHLZ 2.0 Qwen3-TTS CustomVoice 本地引擎
基于 Qwen3-TTS-12Hz-0.6B-CustomVoice 模型，无需参考音频，直接选说话人
"""
import logging
import os
import time
import numpy as np
from typing import Tuple, AsyncGenerator

from backend.tts.base import BaseTTSEngine

logger = logging.getLogger(__name__)

MODEL_PATH = os.environ.get(
    "QWEN3_TTS_CUSTOMVOICE_PATH",
    r"D:\HF_Models\Qwen\models\Qwen--Qwen3-TTS-12Hz-0.6B-CustomVoice\snapshots\master"
)

# 说话人列表
SPEAKERS = {
    "Vivian": "Vivian（明亮的年轻女声，中文母语）",
}


class Qwen3TTSCustomVoiceEngine(BaseTTSEngine):
    """Qwen3-TTS CustomVoice 本地引擎 (0.6B, 多说话人)"""

    name = "qwen3-tts-customvoice"

    def __init__(self):
        super().__init__()
        self._model = None
        self._model_path = MODEL_PATH
        self._sample_rate = 24000
        self._default_speaker = "Vivian"

    def load(self) -> bool:
        if self.is_loaded:
            return True

        try:
            import torch
            from qwen_tts import Qwen3TTSModel

            if not os.path.isdir(self._model_path):
                logger.error(f"CustomVoice 模型路径不存在: {self._model_path}")
                return False

            logger.info(f"正在加载 CustomVoice 模型: {self._model_path}")
            t0 = time.time()

            self._model = Qwen3TTSModel.from_pretrained(
                self._model_path,
                device_map="cuda:0",
                dtype=torch.bfloat16,
            )

            elapsed = time.time() - t0
            logger.info(f"CustomVoice 模型加载完成, 耗时 {elapsed:.1f}s")
            self.is_loaded = True
            return True

        except ImportError as e:
            logger.error(f"CustomVoice 依赖缺失: {e}")
            return False
        except Exception as e:
            logger.error(f"CustomVoice 加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        self.is_loaded = False

        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("CustomVoice 引擎已卸载")

    def release_gpu(self) -> None:
        self.unload()

    def synthesize(
        self,
        text: str,
        voice: str = "Vivian",
        rate: str = "+0%",
        **kwargs
    ) -> Tuple[np.ndarray, int]:
        if not self.is_loaded or self._model is None:
            logger.warning("CustomVoice 未加载")
            return self._get_mock_audio(text)

        if not text or not text.strip():
            return np.zeros(1000, dtype=np.float32), self._sample_rate

        # 如果 voice 不在支持列表中，用默认
        if voice not in SPEAKERS:
            voice = self._default_speaker

        try:
            logger.info(f"[CustomVoice] 合成: {text[:50]}... | 说话人: {voice}")
            t0 = time.time()

            wavs, sr = self._model.generate_custom_voice(
                text=text,
                language="chinese",
                speaker=voice,
            )

            audio = wavs[0].astype(np.float32)
            elapsed = time.time() - t0
            logger.info(f"[CustomVoice] 合成完成: {len(audio)} samples, {sr}Hz, 耗时 {elapsed:.1f}s")

            return audio, sr

        except Exception as e:
            logger.error(f"CustomVoice 合成失败: {e}")
            import traceback
            traceback.print_exc()
            return self._get_mock_audio(text)

    async def stream_synthesize_text(
        self,
        text: str,
        voice: str = "Vivian",
        **kwargs
    ) -> AsyncGenerator[Tuple[np.ndarray, int], None]:
        audio, sr = self.synthesize(text, voice=voice)
        yield audio, sr

    def get_available_voices(self) -> list:
        return [{"id": k, "name": v} for k, v in SPEAKERS.items()]

    def _get_mock_audio(self, text: str) -> Tuple[np.ndarray, int]:
        duration = max(0.5, len(text) * 0.05)
        n_samples = int(duration * self._sample_rate)
        return np.zeros(n_samples, dtype=np.float32), self._sample_rate


qwen3_customvoice_engine = Qwen3TTSCustomVoiceEngine()