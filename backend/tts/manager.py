"""
YHLZ 2.0 TTS 管理器
引擎注册 + 配置切换 + 故障回退
对齐 NEKO TtsRuntimeMixin: _activate_configured_tts_fallback 范式
"""

import logging
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import numpy as np

from backend.tts.base import BaseTTSEngine, TTSEngineError

logger = logging.getLogger(__name__)


class TTSManager:
    """TTS引擎管理器: 统一入口, 自动回退"""

    def __init__(self):
        self._engines: Dict[str, BaseTTSEngine] = {}
        self._active_name: Optional[str] = None

    def register_engine(self, name: str, engine: BaseTTSEngine):
        """注册引擎"""
        self._engines[name] = engine
        logger.info(f"已注册TTS引擎: {name}")

    def get_engine(self, name: str) -> Optional[BaseTTSEngine]:
        return self._engines.get(name)

    def get_available_engines(self) -> List[dict]:
        """可用引擎列表"""
        return [
            {
                "name": name,
                "description": engine.__class__.__doc__ or "",
                "requires_gpu": False,
                "loaded": engine.is_loaded,
            }
            for name, engine in self._engines.items()
        ]

    def activate(self, name: str) -> bool:
        """激活指定引擎 (auto 表示自动选择第一个可用)"""
        if name == "auto":
            for engine_name, engine in self._engines.items():
                if engine.is_loaded or engine.load():
                    self._active_name = engine_name
                    logger.info(f"TTS引擎自动激活: {engine_name}")
                    return True
            logger.error("没有可用TTS引擎")
            return False

        engine = self._engines.get(name)
        if engine is None:
            logger.error(f"未知TTS引擎: {name}, 可用: {list(self._engines.keys())}")
            return self._activate_fallback()

        if engine.is_loaded or engine.load():
            self._active_name = name
            logger.info(f"TTS引擎已激活: {name}")
            return True

        logger.warning(f"TTS引擎加载失败: {name}, 尝试回退")
        return self._activate_fallback()

    def _activate_fallback(self) -> bool:
        """故障回退: 激活除当前外的第一个可用引擎"""
        for engine_name, engine in self._engines.items():
            if engine_name == self._active_name:
                continue
            if engine.is_loaded or engine.load():
                logger.info(f"TTS引擎回退到: {engine_name}")
                self._active_name = engine_name
                return True
        logger.error("所有TTS引擎均不可用")
        return False

    @property
    def active_engine(self) -> Optional[BaseTTSEngine]:
        return self._engines.get(self._active_name) if self._active_name else None

    @property
    def is_loaded(self) -> bool:
        engine = self.active_engine
        return bool(engine and engine.is_loaded)

    def load(self) -> bool:
        """加载当前激活引擎"""
        engine = self.active_engine
        if engine is None:
            return self._activate_fallback()
        if engine.is_loaded:
            return True
        if engine.load():
            return True
        return self._activate_fallback()

    def unload(self) -> None:
        """卸载所有引擎"""
        for engine in self._engines.values():
            try:
                engine.unload()
            except Exception as e:
                logger.error(f"卸载TTS引擎失败: {e}")
        logger.info("TTS引擎已全部卸载")

    def release_gpu(self) -> None:
        """释放所有引擎GPU显存"""
        for engine in self._engines.values():
            try:
                engine.release_gpu()
            except Exception as e:
                logger.error(f"释放TTS显存失败: {e}")

    def get_available_voices(self) -> list:
        engine = self.active_engine
        if engine:
            return engine.get_available_voices()
        return []

    def synthesize(
        self,
        text: str,
        voice: str = "Vivian",
        rate: str = "+0%",
        **kwargs
    ) -> Tuple[np.ndarray, int]:
        """整段合成, 失败自动回退引擎"""
        engine = self.active_engine
        if engine is None:
            if not self._activate_fallback():
                raise TTSEngineError("无可用TTS引擎")
            engine = self.active_engine

        try:
            return engine.synthesize(text, voice=voice, rate=rate, **kwargs)
        except Exception as e:
            logger.error(f"TTS合成失败({self._active_name}), 尝试回退: {e}")
            if self._activate_fallback():
                engine = self.active_engine
                return engine.synthesize(text, voice=voice, rate=rate, **kwargs)
            raise

    async def stream_synthesize_text(
        self,
        text: str,
        voice: str = "Vivian",
        **kwargs
    ) -> AsyncGenerator[Tuple[np.ndarray, int], None]:
        """流式合成, 失败自动回退引擎"""
        engine = self.active_engine
        if engine is None:
            if not self._activate_fallback():
                logger.error("无可用TTS引擎, 流式合成失败")
                return
            engine = self.active_engine

        try:
            async for chunk in engine.stream_synthesize_text(text, voice=voice, **kwargs):
                yield chunk
        except Exception as e:
            logger.error(f"流式TTS合成失败({self._active_name}), 尝试回退: {e}")
            if self._activate_fallback():
                engine = self.active_engine
                async for chunk in engine.stream_synthesize_text(text, voice=voice, **kwargs):
                    yield chunk
