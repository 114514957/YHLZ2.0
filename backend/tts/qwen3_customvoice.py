"""
YHLZ 2.0 Qwen3-TTS CustomVoice 本地引擎 (faster-qwen3-tts 加速版)
基于 Qwen3-TTS-12Hz-0.6B-CustomVoice 模型，使用 CUDA graph 加速 6-10x
支持真正的流式音频输出 (generate_custom_voice_streaming)
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
    """Qwen3-TTS CustomVoice 本地引擎 (faster-qwen3-tts, CUDA graph 加速)"""

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
            from faster_qwen3_tts.model import FasterQwen3TTS

            if not os.path.isdir(self._model_path):
                logger.error(f"CustomVoice 模型路径不存在: {self._model_path}")
                return False

            logger.info(f"正在加载 CustomVoice 模型 (faster-qwen3-tts): {self._model_path}")
            t0 = time.time()

            self._model = FasterQwen3TTS.from_pretrained(
                self._model_path,
                device="cuda",
                dtype=torch.bfloat16,
                local_files_only=True,
            )

            elapsed = time.time() - t0
            logger.info(f"CustomVoice 模型加载完成, 耗时 {elapsed:.1f}s")

            # CUDA graph 预热 (消除首次推理的 kernel 编译开销)
            logger.info("正在预热 CUDA graph (warmup)...")
            t1 = time.time()
            self._model.warmup(prefill_len=100)
            logger.info(f"CUDA graph 预热完成, 耗时 {time.time() - t1:.1f}s")

            self.is_loaded = True

            # 端到端预热: 实际合成一次短文本, 吸收首次调用的 prefill/CUDA 开销,
            # 使流式首块延迟从 ~4-6s 降至 ~0.4s (预热失败不影响引擎加载)
            try:
                logger.info("正在端到端预热 (synthesize 一次短文本)...")
                t2 = time.time()
                warm_audio, warm_sr = self.synthesize("你好，这里是元亨。", voice=self._default_speaker)
                logger.info(
                    f"端到端预热完成, 产出 {len(warm_audio)} samples, 耗时 {time.time() - t2:.1f}s"
                )
            except Exception as e:
                logger.warning(f"端到端预热失败 (可忽略): {e}")

            return True

        except ImportError as e:
            logger.error(f"faster-qwen3-tts 依赖缺失: {e}")
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
        """真流式合成: 使用 generate_custom_voice_streaming, 逐 chunk 输出音频"""
        if not self.is_loaded or self._model is None:
            audio, sr = self.synthesize(text, voice=voice)
            yield audio, sr
            return

        if not text or not text.strip():
            yield np.zeros(1000, dtype=np.float32), self._sample_rate
            return

        if voice not in SPEAKERS:
            voice = self._default_speaker

        try:
            logger.info(f"[CustomVoice] 流式合成: {text[:50]}... | 说话人: {voice}")
            t0 = time.time()
            chunk_count = 0

            # generate_custom_voice_streaming 返回 (audio_chunk, sr, info)
            for audio_chunk, sr, info in self._model.generate_custom_voice_streaming(
                text=text,
                language="chinese",
                speaker=voice,
                chunk_size=8,  # 每次 8 个 token 的音频片段 (降低首片延迟)
            ):
                if audio_chunk is not None and len(audio_chunk) > 0:
                    yield audio_chunk.astype(np.float32), sr
                    chunk_count += 1

            elapsed = time.time() - t0
            logger.info(f"[CustomVoice] 流式合成完成: {chunk_count} chunks, 耗时 {elapsed:.1f}s")

        except Exception as e:
            logger.error(f"CustomVoice 流式合成失败: {e}")
            import traceback
            traceback.print_exc()
            # 回退到非流式
            audio, sr = self.synthesize(text, voice=voice)
            yield audio, sr

    def get_available_voices(self) -> list:
        return [{"id": k, "name": v} for k, v in SPEAKERS.items()]

    def _get_mock_audio(self, text: str) -> Tuple[np.ndarray, int]:
        duration = max(0.5, len(text) * 0.05)
        n_samples = int(duration * self._sample_rate)
        return np.zeros(n_samples, dtype=np.float32), self._sample_rate


qwen3_customvoice_engine = Qwen3TTSCustomVoiceEngine()
