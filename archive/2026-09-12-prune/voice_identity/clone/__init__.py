"""
YHLZ Voice Identity System V2.1 - Voice Clone Pipeline 包

模块结构:
    clone/
    ├── __init__.py          ← 本文件: 统一导出
    ├── result.py            ← Result[T] / Ok / Err (Rust 风格结果对象)
    ├── audio_validator.py   ← validate_audio() → Result[AudioInfo]
    ├── voice_analyzer.py    ← analyze_voice() → Result[VoiceFeature]
    └── clone_pipeline.py    ← VoiceClonePipeline.clone_voice() → Result[CloneResult]

架构层次 (对齐 Prompt):
    Service (V1.6)
      ↓
    Pipeline (V2.1 本包)
      ↓
    Manager (V1.4) / Registry (V1.3) / Cache (V1.5)
      ↓
    Store (V1.2) → DB (V1.1)

依赖关系:
    - 仅依赖已有 V1.x 模块, 不修改其代码
    - 不直接调 TTS 引擎, 经 Cache 间接 (对齐 V1.4 Manager 约束)
    - 不直接调 DB, 经 Manager/Registry/Cache

使用:
    from backend.voice_identity.clone import (
        VoiceClonePipeline, CloneResult,
        validate_audio, analyze_voice,
        AudioInfo, VoiceFeature,
        Ok, Err, Result,
    )
"""
from __future__ import annotations

from backend.voice_identity.clone.audio_validator import (
    AudioInfo,
    SUPPORTED_FORMATS,
    MAX_DURATION_S,
    MIN_DURATION_S,
    MIN_SAMPLE_RATE,
    validate_audio,
)
from backend.voice_identity.clone.clone_pipeline import (
    CloneResult,
    VoiceClonePipeline,
)
from backend.voice_identity.clone.result import Err, Ok, Result, ResultError
from backend.voice_identity.clone.voice_analyzer import VoiceFeature, analyze_voice

__all__ = [
    # 结果对象
    "Result",
    "Ok",
    "Err",
    "ResultError",
    # 音频验证
    "AudioInfo",
    "validate_audio",
    "SUPPORTED_FORMATS",
    "MIN_DURATION_S",
    "MAX_DURATION_S",
    "MIN_SAMPLE_RATE",
    # 声音分析
    "VoiceFeature",
    "analyze_voice",
    # 克隆流水线
    "VoiceClonePipeline",
    "CloneResult",
    # V2.2 TTS Adapter (从 backend.voice_identity.adapter 导入, 避免循环)
    # 见: from backend.voice_identity.adapter import TTSAdapter, VoiceCacheInfo
]

__version__ = "2.2.0"
