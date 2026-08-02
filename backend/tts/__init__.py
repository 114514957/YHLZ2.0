"""
YHLZ 2.0 TTS 引擎包
base.py     引擎抽象基类
edge.py     Edge-TTS 引擎
manager.py  TTS管理器(注册/切换/回退)
"""

from backend.tts.base import BaseTTSEngine, TTSEngineError
from backend.tts.edge import EdgeTTSEngine
from backend.tts.manager import TTSManager

__all__ = [
    "BaseTTSEngine",
    "TTSEngineError",
    "EdgeTTSEngine",
    "TTSManager",
]
