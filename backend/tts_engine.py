"""
[兼容层] TTS引擎统一入口
实际实现位于 backend/tts/ 包 (抽象基类 + Qwen3引擎 + GPT-SoVITS + Edge + 管理器)。
本模块保持旧接口 (from backend.tts_engine import tts_engine) 不变,
并按 config.tts_engine 激活引擎; 激活失败沿回退链自动降级 (M0.3):

    qwen3-tts-customvoice → qwen3-tts → gpt-sovits → edge-tts
    (Primary)              (Secondary) (GPT-SoVITS) (Fallback)
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import config
from backend.tts.base import BaseTTSEngine, TTSEngineError
from backend.tts.qwen3_tts import Qwen3TTSEngine
from backend.tts.qwen3_customvoice import Qwen3TTSCustomVoiceEngine
from backend.tts.gpt_sovits_engine import GPTSovitsTTSEngine
from backend.tts.edge import EdgeTTSEngine
from backend.tts.manager import TTSManager

logger = logging.getLogger(__name__)

#: 引擎注册表 (注册顺序 = 回退链顺序: Primary → Secondary → Fallback)
ENGINE_REGISTRY = [
    ("qwen3-tts-customvoice", Qwen3TTSCustomVoiceEngine),
    ("qwen3-tts", Qwen3TTSEngine),
    ("gpt-sovits", GPTSovitsTTSEngine),
    ("edge-tts", EdgeTTSEngine),
]


def _build_default_manager() -> TTSManager:
    """注册全部引擎并按配置激活; 激活失败沿链自动降级"""
    manager = TTSManager()
    for name, factory in ENGINE_REGISTRY:
        manager.register_engine(name, factory())

    engine_name = getattr(config, "tts_engine", "qwen3-tts-customvoice")
    logger.info(
        "TTS fallback 链: %s → ... → %s",
        " → ".join(manager.describe_chain()),
        engine_name,
    )
    if not manager.activate(engine_name):
        logger.error(f"TTS引擎激活失败: {engine_name}, 回退链也已耗尽")
        raise RuntimeError(
            f"本地TTS引擎 {engine_name} 激活失败, 回退链不可用, 请检查模型路径/服务"
        )
    return manager


tts_manager = _build_default_manager()

# 旧接口兼容: tts_engine 指向管理器 (代理 synthesize/stream_synthesize_text 等)
tts_engine = tts_manager

__all__ = [
    "tts_engine",
    "tts_manager",
    "TTSManager",
    "BaseTTSEngine",
    "TTSEngineError",
    "ENGINE_REGISTRY",
]
