"""
YHLZ Voice Identity System V2.2 - Qwen3 TTS Adapter

职责:
    - 实现 TTSAdapter 接口, 屏蔽 Qwen3-TTS 引擎细节
    - 支持 mock 模式 (无 GPU / 测试用) 与 real 模式 (真实克隆)
    - 不修改 Pipeline, 经 TTSAdapter 抽象基类接入

模式:
    mock: 不加载模型, prepare 返回 fake VoiceCacheInfo; synthesize 写空 wav
    real: 调用 backend.tts.adapters.qwen3_adapter.Qwen3TTSAdapter
          - prepare: load_voice 提取 embedding → save_voice_cache_to_disk
          - synthesize: engine.synthesize → 写 wav 文件返回路径
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import wave
from typing import Any, Dict, Optional

from backend.voice_identity.adapter.tts_adapter import (
    TTSAdapter,
    VoiceCacheInfo,
    register_adapter,
)
from backend.voice_identity.clone.result import Err, Ok, Result
from backend.voice_identity.clone.voice_analyzer import VoiceFeature

logger = logging.getLogger(__name__)


def _hash_audio(path: str) -> str:
    """计算音频文件 MD5 (用于 mock embedding_hash)"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _write_sine_wav(path: str, duration_s: float = 1.0, sr: int = 24000) -> None:
    """写入正弦波 wav (mock synthesize 用)"""
    import math
    import struct
    n = int(duration_s * sr)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * 0.2 * math.sin(2 * math.pi * 440 * i / sr))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))


@register_adapter("qwen3")
class Qwen3TTSAdapter(TTSAdapter):
    """Qwen3-TTS 适配器

    构造参数:
        mode:        mock | real (默认 mock)
        model_path:  real 模式模型路径 (可选, 默认用全局 qwen3_tts_engine)
        cache_dir:   缓存根目录 (默认 cache/voice_clone)
        engine:      显式注入已加载的 Qwen3TTSAdapter (高级用, 测试 mock)
    """

    name = "qwen3"

    def __init__(
        self,
        mode: str = "mock",
        model_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        engine: Optional[Any] = None,
    ):
        if mode not in ("mock", "real"):
            raise ValueError(f"mode 必须为 mock/real, 实际: {mode}")
        self._mode = mode
        self._model_path = model_path
        self._cache_dir = cache_dir or os.path.join("cache", "voice_clone")
        os.makedirs(self._cache_dir, exist_ok=True)
        # real 模式: 懒加载引擎
        self._engine_adapter = engine  # backend.tts.adapters.qwen3_adapter.Qwen3TTSAdapter
        if mode == "real" and engine is None:
            logger.info("Qwen3 real 模式, 引擎懒加载 (首次 prepare/synthesize 触发)")

    @property
    def mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # TTSAdapter 接口
    # ------------------------------------------------------------------

    def prepare_voice(
        self,
        audio_path: str,
        feature: VoiceFeature,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Result[VoiceCacheInfo]:
        """提取说话人特征并缓存

        mock: 返回 fake VoiceCacheInfo (embedding_hash = audio md5)
        real: 调用 Qwen3TTSAdapter.load_voice + save_voice_cache_to_disk
        """
        if not os.path.exists(audio_path):
            return Err(f"参考音频不存在: {audio_path}")

        if self._mode == "mock":
            return self._prepare_mock(audio_path, feature, metadata)
        return self._prepare_real(audio_path, feature, metadata)

    def synthesize(
        self,
        voice_id: str,
        text: str,
        language: str = "zh",
    ) -> Result[str]:
        """用已缓存声音合成语音

        mock: 写 1s 正弦波 wav 到 cache_dir/<voice_id>/mock.wav
        real: 调用 Qwen3TTSAdapter.engine.synthesize → 写 wav
        """
        if not text:
            return Err("合成文本为空")
        if not voice_id:
            return Err("voice_id 为空")

        if self._mode == "mock":
            return self._synthesize_mock(voice_id, text)
        return self._synthesize_real(voice_id, text, language)

    def can_serve(self) -> bool:
        if self._mode == "mock":
            return True
        # real: 引擎已加载即可
        return self._get_engine_adapter().is_ok()

    # ------------------------------------------------------------------
    # mock 实现
    # ------------------------------------------------------------------

    def _prepare_mock(
        self,
        audio_path: str,
        feature: VoiceFeature,
        metadata: Optional[Dict[str, Any]],
    ) -> Result[VoiceCacheInfo]:
        audio_hash = _hash_audio(audio_path)
        # mock 质量评分: 基于 SNR (有则用, 无则 0.8)
        quality = 0.8
        if feature.snr_db is not None and feature.snr_db > 0:
            quality = min(1.0, 0.5 + feature.snr_db / 40.0)
        info = VoiceCacheInfo(
            adapter=self.name,
            cache_path=None,  # mock 无磁盘缓存
            embedding_hash=f"mock_{audio_hash}",
            quality_score=round(quality, 3),
            extra={"mode": "mock", "audio": audio_path},
        )
        logger.debug(f"Qwen3 mock prepare: {info.to_dict()}")
        return Ok(info)

    def _synthesize_mock(self, voice_id: str, text: str) -> Result[str]:
        vdir = os.path.join(self._cache_dir, voice_id)
        os.makedirs(vdir, exist_ok=True)
        out = os.path.join(vdir, "mock.wav")
        try:
            _write_sine_wav(out, duration_s=min(3.0, max(0.5, len(text) * 0.1)))
        except Exception as e:
            return Err(f"mock synthesize 写 wav 失败: {e}")
        return Ok(out)

    # ------------------------------------------------------------------
    # real 实现
    # ------------------------------------------------------------------

    def _get_engine_adapter(self) -> Result[Any]:
        """懒加载 backend.tts.adapters.qwen3_adapter.Qwen3TTSAdapter"""
        if self._engine_adapter is not None:
            return Ok(self._engine_adapter)
        try:
            from backend.tts.adapters.qwen3_adapter import Qwen3TTSAdapter as _Engine  # noqa: F401
            adapter = _Engine()
            if not adapter.load():
                return Err("Qwen3 引擎加载失败")
            self._engine_adapter = adapter
            return Ok(adapter)
        except Exception as e:
            return Err(f"加载 Qwen3 引擎失败: {e}")

    def _prepare_real(
        self,
        audio_path: str,
        feature: VoiceFeature,
        metadata: Optional[Dict[str, Any]],
    ) -> Result[VoiceCacheInfo]:
        ea_result = self._get_engine_adapter()
        if ea_result.is_err():
            return Err(f"[real] {ea_result.error}")
        ea = ea_result.unwrap()

        # 用音频文件名作 voice_id 占位 (Pipeline 会传入真实 voice_id 经 metadata)
        # 这里 prepare_voice 不直接知道 voice_id, 用 audio_hash 占位
        audio_hash = _hash_audio(audio_path)
        tmp_vid = f"qwen3_clone_{audio_hash}"
        try:
            entry = ea.load_voice(voice_id=tmp_vid, ref_audio=audio_path, x_vector_only_mode=True)
            if entry is None:
                return Err("Qwen3 load_voice 返回 None (提取失败)")
        except Exception as e:
            return Err(f"Qwen3 load_voice 异常: {e}")

        # 持久化到磁盘
        cache_path = None
        try:
            saved = ea.save_voice_cache_to_disk(tmp_vid, self._cache_dir)
            if saved:
                cache_path = saved
        except Exception as e:
            logger.warning(f"save_voice_cache_to_disk 失败 (不致命): {e}")

        # 质量评分: SNR + 时长启发式
        quality = 0.7
        if feature.snr_db is not None and feature.snr_db > 0:
            quality = min(1.0, 0.4 + feature.snr_db / 30.0)
        if feature.audio_info.duration_s >= 5.0:
            quality = min(1.0, quality + 0.1)

        info = VoiceCacheInfo(
            adapter=self.name,
            cache_path=cache_path,
            embedding_hash=f"qwen3_{audio_hash}",
            quality_score=round(quality, 3),
            extra={
                "mode": "real",
                "voice_id": tmp_vid,
                "engine_loaded": ea.is_loaded,
            },
        )
        logger.info(f"Qwen3 real prepare 成功: {info.to_dict()}")
        return Ok(info)

    def _synthesize_real(
        self,
        voice_id: str,
        text: str,
        language: str,
    ) -> Result[str]:
        ea_result = self._get_engine_adapter()
        if ea_result.is_err():
            return Err(f"[real] {ea_result.error}")
        ea = ea_result.unwrap()

        # voice_id 在 prepare 阶段用 audio_hash 命名, 这里需调用方传入相同 ID
        # 若 voice_id 不在缓存, 退化为默认音色
        try:
            import numpy as np  # type: ignore
            audio, sr = ea.engine.synthesize(text, voice_id=voice_id, rate="+0%")
        except Exception as e:
            return Err(f"Qwen3 synthesize 异常: {e}")

        # 写 wav 到 cache_dir/<voice_id>/synth_<ts>.wav
        vdir = os.path.join(self._cache_dir, voice_id)
        os.makedirs(vdir, exist_ok=True)
        out = os.path.join(vdir, f"synth_{int(wave._wave_time()) if hasattr(wave, '_wave_time') else ''}.wav")
        try:
            _write_pcm_wav(out, np.asarray(audio), sr)
        except Exception as e:
            return Err(f"写 wav 失败: {e}")
        return Ok(out)


def _write_pcm_wav(path: str, audio: "Any", sample_rate: int) -> None:
    """写 int16 PCM wav"""
    import numpy as np  # type: ignore
    if audio.dtype != np.int16:
        # 归一化 float → int16
        if audio.dtype == np.float32 or audio.dtype == np.float64:
            audio = np.clip(audio, -1.0, 1.0)
            audio = (audio * 32767).astype(np.int16)
        else:
            audio = audio.astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio.tobytes())
