"""
YHLZ 2.0 GPT-SoVITS 引擎适配器 (M0.2)

封装 GPT-SoVITS Gradio 客户端 (唯一实现, 禁止其他模块直接调用 Gradio):
- GradioClient: 低层 HTTP 客户端 (从 updates/live_stream/backend/tts_service.py 迁移)
- GPTSovitsAdapter: 统一适配器接口 generate/load/unload/health_check

说明:
- GPT-SoVITS 权重决定声音, 无 voice_id 概念; 传入 voice_id 时记录告警并忽略
- generate() 内部走 /inference → 下载音频 → 解码为 (np.ndarray, sample_rate)
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.tts.adapters.base import BaseVoiceEngineAdapter
from backend.tts.voice_style import VoiceStyle

logger = logging.getLogger(__name__)


class GradioClient:
    """GPT-SoVITS Gradio HTTP 客户端 (唯一实现)

    [M0.2] 原位于 updates/live_stream/backend/tts_service.py,
    现迁移至本模块, 作为全仓库唯一 Gradio 调用实现。
    """

    def __init__(self, base_url: str, ssl_verify: bool = False, timeout: int = 300):
        self.base_url = base_url if base_url.endswith("/") else (base_url + "/")
        self.ssl_verify = ssl_verify
        self.timeout = timeout
        self._session: Optional[Any] = None
        self._fn_map: Dict[str, int] = {}
        import aiohttp
        self._aiohttp = aiohttp

    async def ensure(self):
        """建立会话并拉取 /config 函数映射 (幂等)"""
        if self._session is None:
            connector = self._aiohttp.TCPConnector(ssl=self.ssl_verify)
            self._session = self._aiohttp.ClientSession(
                timeout=self._aiohttp.ClientTimeout(total=self.timeout),
                connector=connector,
                headers={"User-Agent": "yhlz/tts-adapter/gpt-sovits"},
            )
            try:
                await self._load_config()
            except Exception:
                # 失败时关闭会话, 避免连接泄漏
                await self.close()
                raise

    async def _load_config(self):
        assert self._session is not None
        url = self.base_url + "config"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            cfg = await resp.json()
            deps = cfg.get("dependencies") or []
            for i, dep in enumerate(deps):
                api_name = (dep or {}).get("api_name")
                if api_name:
                    self._fn_map[str(api_name).strip().lstrip("/")] = int((dep or {}).get("id", i))

    async def close(self):
        if self._session is not None:
            s = self._session
            self._session = None
            try:
                await s.close()
            except Exception:
                pass

    async def predict(self, api_name: str, *args: Any) -> Any:
        await self.ensure()
        assert self._session is not None
        fn = self._fn_map.get(api_name.strip().lstrip("/"))
        if fn is None:
            raise RuntimeError(f"API '{api_name}' not found in gradio config")
        url = self.base_url + "api/predict/"
        data = {
            "data": list(args),
            "fn_index": fn,
            "session_hash": str(int(time.time() * 1000)),
        }
        async with self._session.post(url, json=data) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"Gradio predict failed: {resp.status} {text[:200]}")
            j = await resp.json()
            if j.get("error"):
                raise RuntimeError(f"Gradio API error: {j.get('error')}")
            return j.get("data")

    async def download_audio(self, url: str) -> bytes:
        """下载 Gradio 音频文件字节"""
        await self.ensure()
        assert self._session is not None
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


def _decode_to_numpy(audio_bytes: bytes) -> Tuple[np.ndarray, int]:
    """音频字节 → (float32 mono 音频, 采样率)"""
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        sample_rate = audio.frame_rate
        channels = audio.channels
        sample_width = audio.sample_width

        samples = audio.get_array_of_samples()
        audio_np = np.array(samples, dtype=np.float32)

        if sample_width == 2:
            audio_np = audio_np / 32768.0
        elif sample_width == 4:
            audio_np = audio_np / 2147483648.0
        elif sample_width == 1:
            audio_np = audio_np / 128.0

        if channels == 2:
            audio_np = audio_np.reshape(-1, 2).mean(axis=1)

        return audio_np, sample_rate
    except Exception as e:
        logger.error(f"音频解码失败: {e}")
        raise


class GPTSovitsAdapter(BaseVoiceEngineAdapter):
    """GPT-SoVITS 适配器 (高保真, Gradio 服务)"""

    name = "gpt-sovits"
    engine_type = "gpt_sovits"

    def __init__(
        self,
        base_url: str = "http://localhost:9872/",
        ssl_verify: bool = False,
        timeout: int = 300,
    ):
        super().__init__()
        self._base_url = base_url
        self._ssl_verify = ssl_verify
        self._timeout = timeout
        self._client: Optional[GradioClient] = None

    @property
    def client(self) -> Optional[GradioClient]:
        """底层 Gradio 客户端 (仅供测试/诊断)"""
        return self._client

    # ------------------------------------------------------------------
    # BaseVoiceEngineAdapter 接口
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """连接 Gradio 服务并拉取函数映射 (不切换权重)"""
        if self.is_loaded and self._client is not None:
            return True
        if self._client is None:
            self._client = GradioClient(
                self._base_url,
                ssl_verify=self._ssl_verify,
                timeout=self._timeout,
            )
        try:
            asyncio.run(self._client.ensure())
            self.is_loaded = True
            logger.info(
                "GPT-SoVITS 适配器已连接: %s (%d endpoints)",
                self._base_url,
                len(self._client._fn_map),
            )
            return True
        except Exception as e:
            logger.error(f"GPT-SoVITS 适配器连接失败: {e}")
            self.is_loaded = False
            return False

    def unload(self) -> None:
        if self._client is not None:
            try:
                asyncio.run(self._client.close())
            except Exception:
                pass
            self._client = None
        self.is_loaded = False
        logger.info("GPT-SoVITS 适配器已断开")

    def generate(
        self,
        text: str,
        voice_id: Optional[str] = None,
        voice_style: Optional[VoiceStyle] = None,
        **params,
    ) -> Tuple[np.ndarray, int]:
        """统一合成入口: /inference → 下载 → 解码为 (np.ndarray, sample_rate)

        M0.5: voice_style.speed 覆盖 speed_factor 参数 (直接数值映射);
        pitch/energy 当前 GPT-SoVITS 不支持, 静默忽略并 debug 日志。
        禁止在此重新做情绪分类 — emotion 字段仅 metadata。

        支持参数 (params): text_lang / ref_audio_path / ref_text_path / ref_text /
        top_k / top_p / temperature / text_split_method / batch_size / speed_factor /
        ref_text_free / split_bucket / fragment_interval / seed / keep_random /
        parallel_infer / repetition_penalty / sample_steps / super_sampling
        """
        if voice_id not in (None, "default", ""):
            logger.warning(
                f"GPT-SoVITS 不支持 voice_id (权重决定声音), 忽略: {voice_id}"
            )

        # VoiceStyle 翻译: 只消费数值字段, 不依赖 emotion 标签
        if voice_style is not None:
            params["speed_factor"] = voice_style.speed
            if voice_style.pitch != 0.0:
                logger.debug(f"GPT-SoVITS 不支持 pitch 调整, 忽略: {voice_style.pitch}")
            if voice_style.energy != 1.0:
                logger.debug(f"GPT-SoVITS 不支持 energy 调整, 忽略: {voice_style.energy}")

        if not self.is_loaded and not self.load():
            logger.warning("GPT-SoVITS 未就绪, 返回兜底音频")
            return self._mock_audio(text)

        assert self._client is not None

        ref_audio_dict = None
        ref_audio_path = params.get("ref_audio_path")
        if isinstance(ref_audio_path, str) and ref_audio_path.strip():
            ref_audio_dict = {
                "path": ref_audio_path.strip(),
                "orig_name": ref_audio_path.strip().split("/")[-1],
                "meta": {"_type": "gradio.FileData"},
            }

        ref_text = params.get("ref_text") or ""
        ref_text_path = params.get("ref_text_path")
        if not ref_text and isinstance(ref_text_path, str) and ref_text_path.strip():
            try:
                with open(ref_text_path.strip(), "r", encoding="utf-8") as f:
                    ref_text = f.read().strip()
            except Exception:
                ref_text = ""

        text_lang = params.get("text_lang", "zh")

        try:
            logger.info(f"[GPT-SoVITS] 合成: {text[:50]}...")
            t0 = time.time()

            data = asyncio.run(self._client.predict(
                "/inference",
                text,
                text_lang,
                ref_audio_dict,
                [],
                ref_text,
                text_lang,
                int(params.get("top_k", 5)),
                float(params.get("top_p", 1.0)),
                float(params.get("temperature", 1.0)),
                params.get("text_split_method", "cut5"),
                int(params.get("batch_size", 2)),
                float(params.get("speed_factor", 1.0)),
                bool(params.get("ref_text_free", False)),
                bool(params.get("split_bucket", True)),
                float(params.get("fragment_interval", 0.3)),
                int(params.get("seed", -1)),
                bool(params.get("keep_random", True)),
                bool(params.get("parallel_infer", True)),
                float(params.get("repetition_penalty", 1.35)),
                str(params.get("sample_steps", 32)),
                bool(params.get("super_sampling", True)),
            ))

            audio_url = None
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                audio_url = data[0].get("url")

            if not audio_url:
                logger.error(f"Unexpected inference result: {repr(data)[:200]}")
                return self._mock_audio(text)

            buf = asyncio.run(self._client.download_audio(audio_url))
            audio, sr = _decode_to_numpy(buf)
            logger.info(
                f"[GPT-SoVITS] 合成完成: {len(audio)} samples, {sr}Hz, 耗时 {time.time() - t0:.1f}s"
            )
            return audio, sr

        except Exception as e:
            logger.error(f"GPT-SoVITS 合成失败: {e}")
            import traceback
            traceback.print_exc()
            return self._mock_audio(text)

    def health_check(self) -> dict:
        if self._client is None:
            return {
                "ok": False,
                "loaded": False,
                "name": self.name,
                "base_url": self._base_url,
                "reason": "未连接",
            }
        try:
            asyncio.run(self._client.ensure())  # 幂等
            return {
                "ok": True,
                "loaded": True,
                "name": self.name,
                "base_url": self._base_url,
                "endpoints": len(self._client._fn_map),
            }
        except Exception as e:
            return {
                "ok": False,
                "loaded": False,
                "name": self.name,
                "base_url": self._base_url,
                "reason": str(e),
            }

    def can_serve(self) -> bool:
        return self.is_loaded and self._client is not None

    # ------------------------------------------------------------------
    # GPT-SoVITS 特有能力 (权重热切换)
    # ------------------------------------------------------------------

    def change_weights(
        self,
        sovits_model: str,
        gpt_model: str,
        text_lang: str = "zh",
    ) -> None:
        """热切换 SoVITS/GPT 权重 (调用 /change_sovits_weights + /change_gpt_weights)"""
        if not self.is_loaded and not self.load():
            raise RuntimeError("GPT-SoVITS 未就绪, 无法切换权重")
        assert self._client is not None
        result = asyncio.run(
            self._client.predict(
                "/change_sovits_weights", sovits_model, text_lang, text_lang
            )
        )
        logger.info("Changed SoVITS weights: %s", result)
        result = asyncio.run(self._client.predict("/change_gpt_weights", gpt_model))
        logger.info("Changed GPT weights: %s", result)
