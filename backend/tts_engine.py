"""
[兼容层] TTS引擎统一入口
实际实现位于 backend/tts/ 包 (抽象基类 + Edge引擎 + 管理器)。
本模块保持旧接口 (from backend.tts_engine import tts_engine) 不变,
并按 config.tts_engine 激活引擎 (edge-tts / auto)。
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import config
from backend.tts.base import BaseTTSEngine, TTSEngineError
from backend.tts.edge import EdgeTTSEngine
from backend.tts.qwen3_tts import Qwen3TTSEngine
from backend.tts.qwen3_customvoice import Qwen3TTSCustomVoiceEngine
from backend.tts.manager import TTSManager

logger = logging.getLogger(__name__)


def _build_default_manager() -> TTSManager:
    """注册引擎并按配置激活"""
    manager = TTSManager()
    manager.register_engine("qwen3-tts-customvoice", Qwen3TTSCustomVoiceEngine())
    manager.register_engine("qwen3-tts", Qwen3TTSEngine())
    manager.register_engine("edge-tts", EdgeTTSEngine())

    engine_name = getattr(config, "tts_engine", "qwen3-tts-customvoice")
    if not manager.activate(engine_name):
        logger.warning(f"TTS引擎激活失败: {engine_name}, 使用edge-tts兜底")
        manager.activate("edge-tts")
    return manager


tts_manager = _build_default_manager()

# 旧接口兼容: tts_engine 指向管理器 (代理 synthesize/stream_synthesize_text 等)
tts_engine = tts_manager

__all__ = [
    "tts_engine",
    "tts_manager",
    "TTSManager",
    "BaseTTSEngine",
    "EdgeTTSEngine",
    "TTSEngineError",
]
