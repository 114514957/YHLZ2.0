"""
YHLZ 2.0 TTS 管理器
引擎注册 + 配置切换 + 故障回退
对齐 NEKO TtsRuntimeMixin: _activate_configured_tts_fallback 范式

M0.3 变更: 多级回退链 (Primary → Secondary → Fallback)
- 按注册顺序构成回退链, 激活失败/合成失败均沿链降级
- 明确 fallback 日志: "TTS Engine {x} unavailable, fallback to {y}"
"""

import logging
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import numpy as np

from backend.tts.base import BaseTTSEngine, TTSEngineError

logger = logging.getLogger(__name__)


class TTSManager:
    """TTS引擎管理器: 统一入口, 多级自动回退"""

    def __init__(self):
        self._engines: Dict[str, BaseTTSEngine] = {}
        self._active_name: Optional[str] = None

    # ------------------------------------------------------------------
    # 注册表
    # ------------------------------------------------------------------

    def register_engine(self, name: str, engine: BaseTTSEngine):
        """注册引擎 (注册顺序即回退链顺序)"""
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

    def describe_chain(self) -> List[str]:
        """当前回退链 (按注册顺序)"""
        return list(self._engines.keys())

    # ------------------------------------------------------------------
    # 回退链核心
    # ------------------------------------------------------------------

    def _activate_next(
        self,
        failed_name: Optional[str],
        reason: str = "unavailable",
        exclude: Optional[set] = None,
    ) -> Optional[BaseTTSEngine]:
        """激活回退链中下一个可用引擎; 成功返回引擎, 失败返回 None

        沿注册顺序跳过 failed_name / 当前激活引擎 / exclude 中已试引擎,
        逐个尝试加载, 首个可用者成为新激活引擎, 并输出明确 fallback 日志。
        """
        exclude = exclude or set()
        for name in self._engines:
            if name == failed_name or name == self._active_name or name in exclude:
                continue
            engine = self._engines[name]
            try:
                ok = engine.is_loaded or engine.load()
            except Exception as e:
                logger.error(f"TTS Engine {name} load 异常: {e}")
                ok = False
            if ok:
                previous = failed_name or self._active_name or "当前激活引擎"
                logger.warning(
                    f"TTS Engine {previous} {reason}, fallback to {name}"
                )
                self._active_name = name
                return engine
            logger.warning(f"TTS Engine {name} unavailable, 继续回退")
        logger.error("TTS fallback 链耗尽: 无可用TTS引擎")
        return None

    def _activate_fallback(self, failed_name: Optional[str] = None) -> bool:
        """沿回退链激活下一个可用引擎 (激活期降级)"""
        return self._activate_next(failed_name) is not None

    def _resolve_active(self) -> Optional[BaseTTSEngine]:
        """当前激活引擎; 无激活时先走回退链"""
        if self._active_name:
            engine = self._engines.get(self._active_name)
            if engine is not None:
                return engine
        if self._activate_fallback():
            return self._engines[self._active_name]
        return None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

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

        logger.warning(f"TTS Engine {name} unavailable, 尝试回退")
        # 目标引擎不可用但当前激活引擎仍健康: 保持现状, 不做无谓降级
        if self._active_name and self._engines.get(self._active_name).is_loaded:
            logger.info(f"目标引擎 {name} 不可用, 保持当前引擎: {self._active_name}")
            return True
        return self._activate_fallback(failed_name=name)

    @property
    def active_engine(self) -> Optional[BaseTTSEngine]:
        return self._engines.get(self._active_name) if self._active_name else None

    @property
    def is_loaded(self) -> bool:
        engine = self.active_engine
        return bool(engine and engine.is_loaded)

    def load(self) -> bool:
        """加载当前激活引擎; 失败沿回退链降级"""
        if self._active_name:
            engine = self._engines.get(self._active_name)
            if engine and (engine.is_loaded or engine.load()):
                return True
            logger.warning(f"TTS Engine {self._active_name} unavailable, 尝试回退")
            return self._activate_fallback(failed_name=self._active_name)
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

    # ------------------------------------------------------------------
    # 合成 (含运行期多级回退)
    # ------------------------------------------------------------------

    def synthesize(
        self,
        text: str,
        voice: str = "Vivian",
        rate: str = "+0%",
        **kwargs
    ) -> Tuple[np.ndarray, int]:
        """整段合成, 失败沿回退链自动降级"""
        engine = self._resolve_active()
        if engine is None:
            raise TTSEngineError("无可用TTS引擎 (fallback 链耗尽)")

        tried: set = set()
        while True:
            name = self._active_name
            if name in tried:
                raise TTSEngineError("TTS合成失败, 回退链已耗尽")
            tried.add(name)
            try:
                return engine.synthesize(text, voice=voice, rate=rate, **kwargs)
            except Exception as e:
                next_engine = self._activate_next(
                    name, reason="synthesize 失败", exclude=tried
                )
                if next_engine is None:
                    raise TTSEngineError(
                        f"TTS合成失败, 回退链已耗尽: {type(e).__name__}: {e}"
                    ) from e
                engine = next_engine

    async def stream_synthesize_text(
        self,
        text: str,
        voice: str = "Vivian",
        **kwargs
    ) -> AsyncGenerator[Tuple[np.ndarray, int], None]:
        """流式合成, 失败沿回退链自动降级"""
        engine = self._resolve_active()
        if engine is None:
            logger.error("无可用TTS引擎, 流式合成失败")
            return

        tried: set = set()
        while True:
            name = self._active_name
            if name in tried:
                logger.error("TTS流式合成失败, 回退链已耗尽")
                return
            tried.add(name)
            try:
                async for chunk in engine.stream_synthesize_text(text, voice=voice, **kwargs):
                    yield chunk
                return
            except Exception as e:
                next_engine = self._activate_next(
                    name, reason="stream 失败", exclude=tried
                )
                if next_engine is None:
                    logger.error(
                        f"TTS流式合成失败, 回退链已耗尽: {type(e).__name__}: {e}"
                    )
                    return
                engine = next_engine
