"""
YHLZ Voice Identity System V2.2 - 配置加载器

职责:
    - 读取 voice_clone_config.json
    - 提供 dataclass 配置对象, 给 Pipeline / Adapter / API 使用
    - 缺失字段用默认值; 文件缺失用全默认

不依赖 Pydantic, 保持轻量 (stdlib only)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "voice_clone_config.json",
)


@dataclass
class Qwen3Config:
    mode: str = "mock"
    model_path: str = ""
    cache_dir: str = "cache/voice_clone"


@dataclass
class GPTSoVITSConfig:
    mode: str = "mock"
    gradio_url: str = "http://129.5.0.1:9872"
    cache_dir: str = "cache/voice_clone"


@dataclass
class ValidationConfig:
    min_duration_s: float = 3.0
    max_duration_s: float = 60.0
    min_sample_rate: int = 16000
    supported_formats: List[str] = field(
        default_factory=lambda: [".wav", ".mp3", ".flac", ".ogg", ".m4a"]
    )


@dataclass
class UploadConfig:
    max_size_mb: int = 50
    temp_dir: str = "cache/voice_clone/_uploads"
    # 上传音频 TTL (秒), 超时自动清理 (默认 24h)
    ttl_seconds: int = 86400
    # 是否在克隆成功后立即删除上传音频
    cleanup_on_success: bool = False


@dataclass
class VoiceCloneConfig:
    default_engine: str = "qwen3"
    auto_prepare: bool = True
    qwen3: Qwen3Config = field(default_factory=Qwen3Config)
    gpt_sovits: GPTSoVITSConfig = field(default_factory=GPTSoVITSConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)

    def to_dict(self) -> dict:
        return {
            "default_engine": self.default_engine,
            "auto_prepare": self.auto_prepare,
            "qwen3": self.qwen3.__dict__,
            "gpt_sovits": self.gpt_sovits.__dict__,
            "validation": self.validation.__dict__,
            "upload": self.upload.__dict__,
        }


def load_config(path: Optional[str] = None) -> VoiceCloneConfig:
    """加载配置文件; 失败返全默认配置

    参数:
        path: 配置文件路径 (默认 voice_clone_config.json)
    """
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(cfg_path):
        logger.info(f"配置文件不存在, 用默认配置: {cfg_path}")
        return VoiceCloneConfig()

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning(f"配置文件解析失败, 用默认: {e}")
        return VoiceCloneConfig()

    # 过滤注释字段 (以 _ 开头)
    def _strip(d: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in d.items() if not k.startswith("_")}

    raw = _strip(raw)
    qwen3 = Qwen3Config(**_strip(raw.get("qwen3", {})))
    gpt = GPTSoVITSConfig(**_strip(raw.get("gpt_sovits", {})))
    val = ValidationConfig(**_strip(raw.get("validation", {})))
    upl = UploadConfig(**_strip(raw.get("upload", {})))
    return VoiceCloneConfig(
        default_engine=raw.get("default_engine", "qwen3"),
        auto_prepare=raw.get("auto_prepare", True),
        qwen3=qwen3, gpt_sovits=gpt, validation=val, upload=upl,
    )


def build_adapter_from_config(
    engine: str,
    config: Optional[VoiceCloneConfig] = None,
):
    """根据配置构造 Adapter (返回 Result[TTSAdapter])"""
    from backend.voice_identity.adapter.tts_adapter import build_adapter
    cfg = config or load_config()
    if engine == "qwen3":
        return build_adapter("qwen3", {
            "mode": cfg.qwen3.mode,
            "model_path": cfg.qwen3.model_path or None,
            "cache_dir": cfg.qwen3.cache_dir,
        })
    if engine == "gpt_sovits":
        return build_adapter("gpt_sovits", {
            "mode": cfg.gpt_sovits.mode,
            "gradio_url": cfg.gpt_sovits.gradio_url,
            "cache_dir": cfg.gpt_sovits.cache_dir,
        })
    return build_adapter(engine, {})
