"""
YHLZ Voice Identity System V2.2 - TTS Adapter 包

模块结构:
    adapter/
    ├── __init__.py          ← 本文件: 统一导出
    ├── tts_adapter.py       ← TTSAdapter 抽象基类 + VoiceCacheInfo + 注册表
    ├── qwen3_adapter.py     ← Qwen3 TTS 适配器 (mock + real)
    └── gpt_sovits_adapter.py ← GPT-SoVITS 适配器 (mock + real)

架构层次 (对齐 V2.2 Prompt):
    Pipeline (V2.2 升级)
      ↓
    TTSAdapter (V2.2 本包, 抽象接口)
      ↓
    Qwen3TTSAdapter / GPTSoVITSAdapter (具体实现)
      ↓
    backend.tts.adapters / Gradio Client (引擎层)

使用:
    from backend.voice_identity.adapter import (
        TTSAdapter, VoiceCacheInfo,
        Qwen3TTSAdapter, GPTSoVITSAdapter,
        build_adapter, list_adapters, register_adapter,
    )
"""
from __future__ import annotations

from backend.voice_identity.adapter.gpt_sovits_adapter import GPTSoVITSAdapter
from backend.voice_identity.adapter.qwen3_adapter import Qwen3TTSAdapter
from backend.voice_identity.adapter.tts_adapter import (
    TTSAdapter,
    VoiceCacheInfo,
    build_adapter,
    get_adapter_class,
    list_adapters,
    register_adapter,
)

__all__ = [
    # 抽象
    "TTSAdapter",
    "VoiceCacheInfo",
    # 具体实现
    "Qwen3TTSAdapter",
    "GPTSoVITSAdapter",
    # 注册表
    "register_adapter",
    "get_adapter_class",
    "list_adapters",
    "build_adapter",
]

__version__ = "2.2.0"
