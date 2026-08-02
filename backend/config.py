"""
YHLZ 2.0 配置管理模块
GPU: RTX 4060 Laptop 8GB
模型: SenseVoiceSmall(ASR) + Qwen3-TTS-0.6B-CustomVoice(TTS) + 云端LLM
"""

import os
from typing import Optional, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 加载环境变量
load_dotenv()


class Config(BaseModel):
    """主配置类"""
    
    # DeepSeek API配置
    deepseek_api_key: str = Field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = Field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    deepseek_model: str = Field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    
    # 阿里云通义千问API配置（自动从环境变量读取）
    dashscope_api_key: str = Field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", ""))
    dashscope_model: str = Field(default_factory=lambda: os.getenv("DASHSCOPE_MODEL", "qwen-turbo"))
    
    # 多模态模型配置（视觉理解，llm_engine 使用）
    vl_model: str = Field(default_factory=lambda: os.getenv("VL_MODEL", "qwen-vl-plus"))
    
    # API提供商选择
    api_provider: str = Field(default_factory=lambda: os.getenv("API_PROVIDER", "dashscope"))
    
    # ── ASR: SenseVoiceSmall (FunASR) ──
    asr_model: str = Field(default_factory=lambda: os.getenv("ASR_MODEL", "funasr-SenseVoiceSmall"))
    asr_device: str = Field(default_factory=lambda: os.getenv("ASR_DEVICE", "cuda"))
    use_fp16: bool = Field(default_factory=lambda: os.getenv("USE_FP16", "true").lower() == "true")
    use_kv_cache: bool = Field(default_factory=lambda: os.getenv("USE_KV_CACHE", "true").lower() == "true")
    asr_fast_mode: bool = Field(default_factory=lambda: os.getenv("ASR_FAST_MODE", "true").lower() == "true")
    # ASR 精度/后处理配置
    asr_language: str = Field(default_factory=lambda: os.getenv("ASR_LANGUAGE", "zh"))
    asr_mode: str = Field(default_factory=lambda: os.getenv("ASR_MODE", "accuracy"))
    asr_beam_size: int = Field(default_factory=lambda: int(os.getenv("ASR_BEAM_SIZE", "10")))
    asr_best_of: int = Field(default_factory=lambda: int(os.getenv("ASR_BEST_OF", "10")))
    asr_patience: float = Field(default_factory=lambda: float(os.getenv("ASR_PATIENCE", "2.0")))
    asr_temperature: str = Field(default_factory=lambda: os.getenv("ASR_TEMPERATURE", "0.0,0.1,0.2"))
    asr_no_speech_threshold: float = Field(default_factory=lambda: float(os.getenv("ASR_NO_SPEECH_THRESHOLD", "0.4")))
    asr_log_prob_threshold: float = Field(default_factory=lambda: float(os.getenv("ASR_LOG_PROB_THRESHOLD", "-0.5")))
    asr_compression_ratio_threshold: float = Field(default_factory=lambda: float(os.getenv("ASR_COMPRESSION_RATIO_THRESHOLD", "2.4")))
    asr_multi_pass_enabled: bool = Field(default_factory=lambda: os.getenv("ASR_MULTI_PASS_ENABLED", "true").lower() == "true")
    asr_multi_pass_confidence_threshold: float = Field(default_factory=lambda: float(os.getenv("ASR_MULTI_PASS_CONFIDENCE_THRESHOLD", "-0.3")))
    asr_audio_enhancement_enabled: bool = Field(default_factory=lambda: os.getenv("ASR_AUDIO_ENHANCEMENT_ENABLED", "true").lower() == "true")
    asr_text_postprocessing_enabled: bool = Field(default_factory=lambda: os.getenv("ASR_TEXT_POSTPROCESSING_ENABLED", "true").lower() == "true")

    # ── TTS: Qwen3-TTS-0.6B-CustomVoice (bf16, GPU) ──
    tts_engine: str = Field(default_factory=lambda: os.getenv("TTS_ENGINE", "qwen3-tts-customvoice"))
    tts_max_chunk_length: int = Field(default_factory=lambda: int(os.getenv("TTS_MAX_CHUNK_LENGTH", "50")))

    # ── 情绪→音色映射 (仅 Edge-TTS 多音色时有效，CustomVoice 单音色时禁用) ──
    emotion_enabled: bool = Field(default_factory=lambda: os.getenv("EMOTION_ENABLED", "false").lower() == "true")
    emotion_confidence_threshold: float = Field(default_factory=lambda: float(os.getenv("EMOTION_CONFIDENCE_THRESHOLD", "0.5")))

    # ── 回声过滤 ──
    echo_filter_enabled: bool = Field(default_factory=lambda: os.getenv("ECHO_FILTER_ENABLED", "true").lower() == "true")

    # ── 低延迟TTS ──
    tts_first_chunk_min_ms: int = Field(default_factory=lambda: int(os.getenv("TTS_FIRST_CHUNK_MIN_MS", "300")))
    tts_fallback_buffer_enabled: bool = Field(default_factory=lambda: os.getenv("TTS_FALLBACK_BUFFER_ENABLED", "false").lower() == "true")

    # ── 上下文 ──
    max_context_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_CONTEXT_TOKENS", "8000")))
    summary_threshold: int = Field(default_factory=lambda: int(os.getenv("SUMMARY_THRESHOLD", "7000")))

    # ── 音频 ──
    tts_buffer_ms: int = Field(default_factory=lambda: int(os.getenv("TTS_BUFFER_MS", "10")))
    sample_rate: int = Field(default_factory=lambda: int(os.getenv("SAMPLE_RATE", "16000")))

    @property
    def is_valid(self) -> bool:
        """检查配置是否有效"""
        if self.api_provider == "dashscope":
            return bool(self.dashscope_api_key)
        else:
            return bool(self.deepseek_api_key)

    @property
    def current_api_key(self) -> str:
        """获取当前API提供商的密钥"""
        if self.api_provider == "dashscope":
            return self.dashscope_api_key
        else:
            return self.deepseek_api_key


# 全局配置实例
config = Config()