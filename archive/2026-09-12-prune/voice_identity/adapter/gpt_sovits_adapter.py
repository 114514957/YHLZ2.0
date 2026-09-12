"""
YHLZ Voice Identity System V2.2 - GPT-SoVITS Adapter

职责:
    - 实现 TTSAdapter 接口, 对接 GPT-SoVITS Gradio 服务
    - 支持 mock 模式 (无 Gradio 服务时) 与 real 模式 (Gradio :9872)
    - 克隆能力: 经 change_weights 切换 sovits/gpt 模型权重

模式:
    mock: 不连 Gradio, prepare 返回 fake VoiceCacheInfo; synthesize 写空 wav
    real: 调用 GradioClient
          - prepare: 校验 metadata.sovits_model/gpt_model 路径存在
          - synthesize: /inference 接口合成 → 下载音频文件
"""
from __future__ import annotations

import hashlib
import logging
import os
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
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


@register_adapter("gpt_sovits")
class GPTSoVITSAdapter(TTSAdapter):
    """GPT-SoVITS 适配器

    构造参数:
        mode:        mock | real (默认 mock)
        gradio_url:  real 模式 Gradio 服务地址 (默认 http://129.5.0.1:9872)
        cache_dir:   缓存根目录 (默认 cache/voice_clone)
    """

    name = "gpt_sovits"

    def __init__(
        self,
        mode: str = "mock",
        gradio_url: str = "http://129.5.0.1:9872",
        cache_dir: Optional[str] = None,
    ):
        if mode not in ("mock", "real"):
            raise ValueError(f"mode 必须为 mock/real, 实际: {mode}")
        self._mode = mode
        self._gradio_url = gradio_url.rstrip("/")
        self._cache_dir = cache_dir or os.path.join("cache", "voice_clone")
        os.makedirs(self._cache_dir, exist_ok=True)
        self._client = None  # GradioClient 懒加载

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def gradio_url(self) -> str:
        return self._gradio_url

    # ------------------------------------------------------------------
    # TTSAdapter 接口
    # ------------------------------------------------------------------

    def prepare_voice(
        self,
        audio_path: str,
        feature: VoiceFeature,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Result[VoiceCacheInfo]:
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
        # real: 探测 Gradio 服务可达
        try:
            import urllib.request
            req = urllib.request.urlopen(f"{self._gradio_url}/config", timeout=2)
            return req.status == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # mock
    # ------------------------------------------------------------------

    def _prepare_mock(
        self,
        audio_path: str,
        feature: VoiceFeature,
        metadata: Optional[Dict[str, Any]],
    ) -> Result[VoiceCacheInfo]:
        audio_hash = _hash_audio(audio_path)
        quality = 0.75
        if feature.snr_db is not None and feature.snr_db > 0:
            quality = min(1.0, 0.5 + feature.snr_db / 40.0)
        info = VoiceCacheInfo(
            adapter=self.name,
            cache_path=None,
            embedding_hash=f"gptsv_{audio_hash}",
            quality_score=round(quality, 3),
            extra={"mode": "mock", "audio": audio_path},
        )
        return Ok(info)

    def _synthesize_mock(self, voice_id: str, text: str) -> Result[str]:
        # 复用 qwen3 mock 写 wav 逻辑
        from backend.voice_identity.adapter.qwen3_adapter import _write_sine_wav
        vdir = os.path.join(self._cache_dir, voice_id)
        os.makedirs(vdir, exist_ok=True)
        out = os.path.join(vdir, "mock.wav")
        try:
            _write_sine_wav(out, duration_s=min(3.0, max(0.5, len(text) * 0.1)))
        except Exception as e:
            return Err(f"mock synthesize 写 wav 失败: {e}")
        return Ok(out)

    # ------------------------------------------------------------------
    # real
    # ------------------------------------------------------------------

    def _get_client(self) -> Result[Any]:
        """懒加载 GradioClient"""
        if self._client is not None:
            return Ok(self._client)
        try:
            from gradio_client import Client  # type: ignore
            client = Client(self._gradio_url)
            self._client = client
            return Ok(client)
        except Exception as e:
            return Err(f"连接 GPT-SoVITS Gradio 失败 ({self._gradio_url}): {e}")

    def _prepare_real(
        self,
        audio_path: str,
        feature: VoiceFeature,
        metadata: Optional[Dict[str, Any]],
    ) -> Result[VoiceCacheInfo]:
        # GPT-SoVITS 需要预训练的 sovits/gpt 权重
        meta = metadata or {}
        sovits = meta.get("sovits_model") or meta.get("sovits_path")
        gpt = meta.get("gpt_model") or meta.get("gpt_path")
        if not sovits or not gpt:
            return Err(
                "GPT-SoVITS real 模式需 metadata.sovits_model 与 metadata.gpt_model"
            )
        if not os.path.exists(sovits):
            return Err(f"sovits_model 不存在: {sovits}")
        if not os.path.exists(gpt):
            return Err(f"gpt_model 不存在: {gpt}")

        client_r = self._get_client()
        if client_r.is_err():
            return Err(f"[real] {client_r.error}")
        client = client_r.unwrap()

        # 切换权重 (热切换)
        try:
            # GPT-SoVITS Gradio API id 通常为 /change_sovits_weights / /change_gpt_weights
            client.predict(sovits, api_name="/change_sovits_weights")
            client.predict(gpt, api_name="/change_gpt_weights")
        except Exception as e:
            return Err(f"GPT-SoVITS change_weights 失败: {e}")

        audio_hash = _hash_audio(audio_path)
        quality = 0.8
        if feature.snr_db is not None and feature.snr_db > 0:
            quality = min(1.0, 0.5 + feature.snr_db / 30.0)
        if feature.audio_info.duration_s >= 5.0:
            quality = min(1.0, quality + 0.1)

        info = VoiceCacheInfo(
            adapter=self.name,
            cache_path=sovits,  # 用 sovits 权重路径作 cache_path 标识
            embedding_hash=f"gptsv_{audio_hash}",
            quality_score=round(quality, 3),
            extra={
                "mode": "real",
                "sovits_model": sovits,
                "gpt_model": gpt,
                "gradio_url": self._gradio_url,
            },
        )
        logger.info(f"GPT-SoVITS real prepare 成功: {info.to_dict()}")
        return Ok(info)

    def _synthesize_real(
        self,
        voice_id: str,
        text: str,
        language: str,
    ) -> Result[str]:
        client_r = self._get_client()
        if client_r.is_err():
            return Err(f"[real] {client_r.error}")
        client = client_r.unwrap()

        # /inference 接口 (参数顺序按 GPT-SoVITS WebUI 约定)
        # 文本/语言/参考音频/参考文本/检索方式 etc, 这里用最小参数集
        try:
            result = client.predict(
                text, language, api_name="/inference",
            )
        except Exception as e:
            return Err(f"GPT-SoVITS inference 失败: {e}")

        # result 通常是 (audio_path, ...) 或文件路径
        out_path = result if isinstance(result, str) else (
            result[0] if isinstance(result, tuple) and len(result) > 0 else None
        )
        if not out_path or not os.path.exists(out_path):
            return Err(f"GPT-SoVITS 返回无效音频路径: {result}")

        # 复制到 cache_dir/<voice_id>/
        vdir = os.path.join(self._cache_dir, voice_id)
        os.makedirs(vdir, exist_ok=True)
        dst = os.path.join(vdir, f"synth_{_hash_audio(out_path)}.wav")
        try:
            import shutil
            shutil.copy(out_path, dst)
        except Exception as e:
            return Err(f"复制合成结果失败: {e}")
        return Ok(dst)
