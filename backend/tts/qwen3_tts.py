"""
YHLZ 2.0 Qwen3-TTS 本地引擎
基于 Qwen3-TTS-12Hz-0.6B-Base 模型，本地推理，零网络延迟
"""
import logging
import os
import time
import numpy as np
from pathlib import Path
from typing import Tuple, Optional, AsyncGenerator, List

from backend.tts.base import BaseTTSEngine

logger = logging.getLogger(__name__)

# 模型路径
MODEL_PATH = os.environ.get(
    "QWEN3_TTS_MODEL_PATH",
    r"D:\HF_Models\Qwen\Qwen3-TTS-12Hz-0___6B-Base"
)

# 默认参考音频
DEFAULT_REF_AUDIO = os.environ.get(
    "QWEN3_TTS_REF_AUDIO",
    r"d:\YHLZ2.0\index-tts\examples\voice_01.wav"
)


class Qwen3TTSEngine(BaseTTSEngine):
    """Qwen3-TTS 本地引擎 (0.6B Base, 语音克隆)"""

    name = "qwen3-tts"

    def __init__(self):
        super().__init__()
        self._model = None
        self._prompt_cache = None
        self._model_path = MODEL_PATH
        self._ref_audio_path = DEFAULT_REF_AUDIO
        self._sample_rate = 24000  # 模型原生采样率

    def load(self) -> bool:
        """加载 Qwen3-TTS 模型"""
        if self.is_loaded:
            return True

        try:
            import torch
            from qwen_tts import Qwen3TTSModel

            if not os.path.isdir(self._model_path):
                logger.error(f"Qwen3-TTS 模型路径不存在: {self._model_path}")
                return False

            logger.info(f"正在加载 Qwen3-TTS 模型: {self._model_path}")
            t0 = time.time()

            self._model = Qwen3TTSModel.from_pretrained(
                self._model_path,
                device_map="cuda:0",
                dtype=torch.bfloat16,
            )

            elapsed = time.time() - t0
            logger.info(f"Qwen3-TTS 模型加载完成, 耗时 {elapsed:.1f}s")

            # 预热：创建语音克隆提示缓存
            self._warmup_prompt()

            self.is_loaded = True
            return True

        except ImportError as e:
            logger.error(f"Qwen3-TTS 依赖缺失: {e}")
            return False
        except Exception as e:
            logger.error(f"Qwen3-TTS 加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _warmup_prompt(self):
        """预热：从参考音频提取说话人向量并缓存"""
        if not os.path.isfile(self._ref_audio_path):
            logger.warning(f"参考音频不存在: {self._ref_audio_path}, 跳过预热")
            return

        try:
            import torch
            logger.info(f"正在提取说话人特征: {self._ref_audio_path}")
            t0 = time.time()

            self._prompt_cache = self._model.create_voice_clone_prompt(
                ref_audio=self._ref_audio_path,
                x_vector_only_mode=True,  # 仅用说话人向量，无需参考文本
            )

            elapsed = time.time() - t0
            logger.info(f"说话人特征提取完成, 耗时 {elapsed:.1f}s")
        except Exception as e:
            logger.error(f"预热失败: {e}")

    def unload(self) -> None:
        """卸载模型，释放显存"""
        if self._model is not None:
            del self._model
            self._model = None
        self._prompt_cache = None
        self.is_loaded = False

        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Qwen3-TTS 引擎已卸载，显存已释放")

    def release_gpu(self) -> None:
        self.unload()

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        rate: str = "+0%",
        **kwargs
    ) -> Tuple[np.ndarray, int]:
        """文本转语音"""
        if not self.is_loaded or self._model is None:
            logger.warning("Qwen3-TTS 未加载")
            return self._get_mock_audio(text)

        if not text or not text.strip():
            return np.zeros(1000, dtype=np.float32), self._sample_rate

        try:
            logger.info(f"[Qwen3-TTS] 合成: {text[:50]}...")
            t0 = time.time()

            wavs, sr = self._model.generate_voice_clone(
                text=text,
                language="chinese",
                voice_clone_prompt=self._prompt_cache,
            )

            audio = wavs[0].astype(np.float32)
            elapsed = time.time() - t0
            logger.info(f"[Qwen3-TTS] 合成完成: {len(audio)} samples, {sr}Hz, 耗时 {elapsed:.1f}s")

            return audio, sr

        except Exception as e:
            logger.error(f"Qwen3-TTS 合成失败: {e}")
            import traceback
            traceback.print_exc()
            return self._get_mock_audio(text)

    async def stream_synthesize_text(
        self,
        text: str,
        voice: str = "default",
        **kwargs
    ) -> AsyncGenerator[Tuple[np.ndarray, int], None]:
        """流式合成（Qwen3-TTS 非流式，返回整段模拟流式）"""
        audio, sr = self.synthesize(text, voice=voice)
        yield audio, sr

    def _get_mock_audio(self, text: str) -> Tuple[np.ndarray, int]:
        """生成静默音频（兜底）"""
        duration = max(0.5, len(text) * 0.05)
        sample_rate = self._sample_rate
        n_samples = int(duration * sample_rate)
        audio = np.zeros(n_samples, dtype=np.float32)
        return audio, sample_rate


# 全局实例
qwen3_tts_engine = Qwen3TTSEngine()