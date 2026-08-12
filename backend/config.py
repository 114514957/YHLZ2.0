"""
YHLZ 2.0 配置管理模块
GPU: RTX 4060 Laptop 8GB
模型: SenseVoiceSmall(ASR) + Qwen3-TTS-0.6B-CustomVoice(TTS) + 云端LLM
"""

import os
from pathlib import Path
from typing import Optional, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 加载环境变量 (始终以项目根目录 .env 为准, 避免从子目录启动时读到精简版 .env)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=True)


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

    # ── Agent (V3.0) ──
    agent_enabled: bool = Field(default_factory=lambda: os.getenv("AGENT_ENABLED", "true").lower() == "true")
    agent_test_mode: bool = Field(default_factory=lambda: os.getenv("YHLZ_AGENT_TEST_MODE", "false").lower() == "true")
    agent_max_iterations: int = Field(default_factory=lambda: int(os.getenv("AGENT_MAX_ITERATIONS", "5")))
    agent_tool_timeout: float = Field(default_factory=lambda: float(os.getenv("AGENT_TOOL_TIMEOUT", "10.0")))
    agent_enable_memory: bool = Field(default_factory=lambda: os.getenv("AGENT_ENABLE_MEMORY", "true").lower() == "true")
    agent_memory_db: str = Field(default_factory=lambda: os.getenv("YHLZ_AGENT_MEMORY_DB", "backend/data/agent_memories.db"))
    agent_short_term_size: int = Field(default_factory=lambda: int(os.getenv("AGENT_SHORT_TERM_SIZE", "20")))
    agent_enable_auto_extract: bool = Field(default_factory=lambda: os.getenv("AGENT_ENABLE_AUTO_EXTRACT", "true").lower() == "true")

    # ── Vision Foundation V1.0 ──
    vision_enabled: bool = Field(default_factory=lambda: os.getenv("VISION_ENABLED", "false").lower() == "true")
    vision_screen_enabled: bool = Field(default_factory=lambda: os.getenv("VISION_SCREEN_ENABLED", "false").lower() == "true")
    vision_camera_enabled: bool = Field(default_factory=lambda: os.getenv("VISION_CAMERA_ENABLED", "false").lower() == "true")
    vision_capture_interval: float = Field(default_factory=lambda: float(os.getenv("VISION_CAPTURE_INTERVAL", "1.0")))
    vision_save_policy: str = Field(default_factory=lambda: os.getenv("VISION_SAVE_POLICY", "memory"))
    vision_max_frame_width: int = Field(default_factory=lambda: int(os.getenv("VISION_MAX_FRAME_WIDTH", "1920")))
    vision_max_frame_height: int = Field(default_factory=lambda: int(os.getenv("VISION_MAX_FRAME_HEIGHT", "1080")))
    vision_allow_region_capture: bool = Field(default_factory=lambda: os.getenv("VISION_ALLOW_REGION_CAPTURE", "true").lower() == "true")
    vision_test_mode: bool = Field(default_factory=lambda: os.getenv("YHLZ_VISION_TEST_MODE", "false").lower() == "true")

    # ── Vision Perception V1.0 ──
    perception_enabled: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_ENABLED", "false").lower() == "true")
    perception_ocr_enabled: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_OCR_ENABLED", "false").lower() == "true")
    perception_detection_enabled: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_DETECTION_ENABLED", "false").lower() == "true")
    perception_allow_image_save: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_ALLOW_IMAGE_SAVE", "false").lower() == "true")
    perception_max_image_size: int = Field(default_factory=lambda: int(os.getenv("PERCEPTION_MAX_IMAGE_SIZE", "1920")))
    perception_min_confidence: float = Field(default_factory=lambda: float(os.getenv("PERCEPTION_MIN_CONFIDENCE", "0.0")))
    perception_save_policy: str = Field(default_factory=lambda: os.getenv("PERCEPTION_SAVE_POLICY", "memory"))
    perception_ocr_provider: str = Field(default_factory=lambda: os.getenv("PERCEPTION_OCR_PROVIDER", "mock"))  # mock / paddleocr / tesseract
    perception_ocr_language: str = Field(default_factory=lambda: os.getenv("PERCEPTION_OCR_LANGUAGE", "ch"))
    perception_detection_provider: str = Field(default_factory=lambda: os.getenv("PERCEPTION_DETECTION_PROVIDER", "mock"))  # mock / yolo
    perception_detection_model: str = Field(default_factory=lambda: os.getenv("PERCEPTION_DETECTION_MODEL", "yolov8n.pt"))
    perception_detection_device: str = Field(default_factory=lambda: os.getenv("PERCEPTION_DETECTION_DEVICE", "cpu"))
    perception_test_mode: bool = Field(default_factory=lambda: os.getenv("YHLZ_PERCEPTION_TEST_MODE", "false").lower() == "true")
    perception_tool_timeout: float = Field(default_factory=lambda: float(os.getenv("PERCEPTION_TOOL_TIMEOUT", "10.0")))

    # ── Vision Understanding V1.0 ──
    understanding_enabled: bool = Field(default_factory=lambda: os.getenv("UNDERSTANDING_ENABLED", "false").lower() == "true")
    understanding_allow_image_save: bool = Field(default_factory=lambda: os.getenv("UNDERSTANDING_ALLOW_IMAGE_SAVE", "false").lower() == "true")
    understanding_max_image_size: int = Field(default_factory=lambda: int(os.getenv("UNDERSTANDING_MAX_IMAGE_SIZE", "1920")))
    understanding_save_policy: str = Field(default_factory=lambda: os.getenv("UNDERSTANDING_SAVE_POLICY", "memory"))
    understanding_provider: str = Field(default_factory=lambda: os.getenv("UNDERSTANDING_PROVIDER", "mock"))  # mock / openai_vlm
    understanding_timeout: float = Field(default_factory=lambda: float(os.getenv("UNDERSTANDING_TIMEOUT", "30.0")))
    understanding_max_tokens: int = Field(default_factory=lambda: int(os.getenv("UNDERSTANDING_MAX_TOKENS", "512")))
    understanding_vlm_base_url: str = Field(default_factory=lambda: os.getenv("UNDERSTANDING_VLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    understanding_vlm_api_key: str = Field(default_factory=lambda: os.getenv("UNDERSTANDING_VLM_API_KEY", ""))
    understanding_vlm_model: str = Field(default_factory=lambda: os.getenv("UNDERSTANDING_VLM_MODEL", ""))
    understanding_test_mode: bool = Field(default_factory=lambda: os.getenv("YHLZ_UNDERSTANDING_TEST_MODE", "false").lower() == "true")
    understanding_tool_timeout: float = Field(default_factory=lambda: float(os.getenv("UNDERSTANDING_TOOL_TIMEOUT", "15.0")))

    # ── Vision Memory V1.0 ──
    vision_memory_enabled: bool = Field(default_factory=lambda: os.getenv("VISION_MEMORY_ENABLED", "false").lower() == "true")
    vision_memory_allow_raw_image_save: bool = Field(default_factory=lambda: os.getenv("VISION_MEMORY_ALLOW_RAW_IMAGE_SAVE", "false").lower() == "true")
    vision_memory_db_path: str = Field(default_factory=lambda: os.getenv("VISION_MEMORY_DB_PATH", "backend/data/vision_memories.db"))
    vision_memory_default_importance: str = Field(default_factory=lambda: os.getenv("VISION_MEMORY_DEFAULT_IMPORTANCE", "medium"))  # low / medium / high
    vision_memory_max_query_limit: int = Field(default_factory=lambda: int(os.getenv("VISION_MEMORY_MAX_QUERY_LIMIT", "100")))
    vision_memory_test_mode: bool = Field(default_factory=lambda: os.getenv("YHLZ_VISION_MEMORY_TEST_MODE", "false").lower() == "true")
    vision_memory_tool_timeout: float = Field(default_factory=lambda: float(os.getenv("VISION_MEMORY_TOOL_TIMEOUT", "10.0")))

    # ── Personality Engine V3.4 ──
    personality_enabled: bool = Field(default_factory=lambda: os.getenv("PERSONALITY_ENABLED", "false").lower() == "true")
    personality_allow_sensitive: bool = Field(default_factory=lambda: os.getenv("PERSONALITY_ALLOW_SENSITIVE", "false").lower() == "true")
    personality_db_path: str = Field(default_factory=lambda: os.getenv("PERSONALITY_DB_PATH", "backend/data/personality_profiles.db"))
    personality_max_profiles: int = Field(default_factory=lambda: int(os.getenv("PERSONALITY_MAX_PROFILES", "50")))
    personality_test_mode: bool = Field(default_factory=lambda: os.getenv("YHLZ_PERSONALITY_TEST_MODE", "false").lower() == "true")
    personality_tool_timeout: float = Field(default_factory=lambda: float(os.getenv("PERSONALITY_TOOL_TIMEOUT", "10.0")))

    # ── Vision Action V1.0 (Action Layer) ──
    action_enabled: bool = Field(default_factory=lambda: os.getenv("ACTION_ENABLED", "false").lower() == "true")
    action_require_confirm_high_risk: bool = Field(default_factory=lambda: os.getenv("ACTION_REQUIRE_CONFIRM_HIGH_RISK", "true").lower() == "true")
    action_default_risk_level: str = Field(default_factory=lambda: os.getenv("ACTION_DEFAULT_RISK_LEVEL", "low"))
    action_timeout: float = Field(default_factory=lambda: float(os.getenv("ACTION_TIMEOUT", "10.0")))
    action_history_max: int = Field(default_factory=lambda: int(os.getenv("ACTION_HISTORY_MAX", "200")))
    action_test_mode: bool = Field(default_factory=lambda: os.getenv("YHLZ_ACTION_TEST_MODE", "false").lower() == "true")
    action_tool_timeout: float = Field(default_factory=lambda: float(os.getenv("ACTION_TOOL_TIMEOUT", "10.0")))

    # ── Embodied AI V4.0 (Embodied Layer) ──
    embodied_enabled: bool = Field(default_factory=lambda: os.getenv("EMBODIED_ENABLED", "false").lower() == "true")
    embodied_require_confirm_high_risk: bool = Field(default_factory=lambda: os.getenv("EMBODIED_REQUIRE_CONFIRM_HIGH_RISK", "true").lower() == "true")
    embodied_default_environment: str = Field(default_factory=lambda: os.getenv("EMBODIED_DEFAULT_ENVIRONMENT", "mock"))
    embodied_state_history_max: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_STATE_HISTORY_MAX", "100")))
    embodied_feedback_max: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_FEEDBACK_MAX", "200")))
    embodied_loop_max_iterations: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_LOOP_MAX_ITERATIONS", "5")))
    embodied_action_timeout: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_ACTION_TIMEOUT", "10.0")))
    embodied_test_mode: bool = Field(default_factory=lambda: os.getenv("YHLZ_EMBODIED_TEST_MODE", "false").lower() == "true")
    embodied_tool_timeout: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_TOOL_TIMEOUT", "10.0")))
    embodied_memory_max: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_MEMORY_MAX", "100")))
    embodied_predictor_enabled: bool = Field(default_factory=lambda: os.getenv("EMBODIED_PREDICTOR_ENABLED", "true").lower() == "true")
    # ── Embodied AI V4.2 (Environment Reasoning Layer) ──
    embodied_event_log_max: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_EVENT_LOG_MAX", "200")))
    embodied_memory_path: str = Field(default_factory=lambda: os.getenv("EMBODIED_MEMORY_PATH", ""))
    # ── Embodied AI V4.3 (Experience Learning Layer) ──
    embodied_experience_enabled: bool = Field(default_factory=lambda: os.getenv("EMBODIED_EXPERIENCE_ENABLED", "true").lower() == "true")
    embodied_policy_path: str = Field(default_factory=lambda: os.getenv("EMBODIED_POLICY_PATH", ""))
    embodied_failure_pattern_threshold: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_FAILURE_PATTERN_THRESHOLD", "2")))
    embodied_policy_min_suggestions: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_POLICY_MIN_SUGGESTIONS", "3")))
    embodied_policy_min_hit_rate: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_POLICY_MIN_HIT_RATE", "0.5")))
    embodied_planning_use_recipe: bool = Field(default_factory=lambda: os.getenv("EMBODIED_PLANNING_USE_RECIPE", "true").lower() == "true")
    embodied_policy_max: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_POLICY_MAX", "100")))
    # ── Embodied AI V4.4 (Adaptive Strategy Layer) ──
    embodied_policy_max_age_days: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_POLICY_MAX_AGE_DAYS", "30")))
    embodied_policy_recovery_threshold: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_POLICY_RECOVERY_THRESHOLD", "3")))
    embodied_audit_log_max: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_AUDIT_LOG_MAX", "500")))
    embodied_audit_log_path: str = Field(default_factory=lambda: os.getenv("EMBODIED_AUDIT_LOG_PATH", ""))
    embodied_trend_window: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_TREND_WINDOW", "10")))
    embodied_rank_hit_rate_weight: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_RANK_HIT_RATE_WEIGHT", "0.5")))
    embodied_rank_acceptance_weight: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_RANK_ACCEPTANCE_WEIGHT", "0.3")))
    embodied_rank_recency_weight: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_RANK_RECENCY_WEIGHT", "0.2")))
    embodied_policy_scene_enabled: bool = Field(default_factory=lambda: os.getenv("EMBODIED_POLICY_SCENE_ENABLED", "true").lower() == "true")
    embodied_policy_goal_type_enabled: bool = Field(default_factory=lambda: os.getenv("EMBODIED_POLICY_GOAL_TYPE_ENABLED", "true").lower() == "true")
    # ── Embodied AI V4.5 (Meta Strategy Management 元策略治理) ──
    embodied_policy_min_archive_age_days: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_POLICY_MIN_ARCHIVE_AGE_DAYS", "30")))
    embodied_policy_min_archive_hit_rate: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_POLICY_MIN_ARCHIVE_HIT_RATE", "0.3")))
    # ── Embodied AI V4.6 (Cross-Goal Strategic Planning 跨目标战略规划) ──
    embodied_planning_enabled: bool = Field(default_factory=lambda: os.getenv("EMBODIED_PLANNING_ENABLED", "false").lower() == "true")
    embodied_planning_max_budget: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_PLANNING_MAX_BUDGET", "100")))
    embodied_planning_min_group_size: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_PLANNING_MIN_GROUP_SIZE", "2")))
    embodied_planning_priority_weight_high: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_PLANNING_PRIORITY_WEIGHT_HIGH", "2.0")))
    embodied_planning_priority_weight_medium: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_PLANNING_PRIORITY_WEIGHT_MEDIUM", "1.5")))
    embodied_planning_priority_weight_low: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_PLANNING_PRIORITY_WEIGHT_LOW", "1.0")))
    embodied_planning_min_steps_per_goal: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_PLANNING_MIN_STEPS_PER_GOAL", "1")))
    # ── Embodied AI V4.7 (Long Horizon Planning Layer 长期任务规划层) ──
    embodied_mission_max_phases: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_MISSION_MAX_PHASES", "10")))
    embodied_mission_retry_limit: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_MISSION_RETRY_LIMIT", "2")))
    embodied_mission_resume_enabled: bool = Field(default_factory=lambda: os.getenv("EMBODIED_MISSION_RESUME_ENABLED", "true").lower() == "true")
    embodied_risk_failure_threshold: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_RISK_FAILURE_THRESHOLD", "3")))
    embodied_risk_blocked_threshold: int = Field(default_factory=lambda: int(os.getenv("EMBODIED_RISK_BLOCKED_THRESHOLD", "2")))
    embodied_deadline_warning_hours: float = Field(default_factory=lambda: float(os.getenv("EMBODIED_DEADLINE_WARNING_HOURS", "24.0")))
    # ── Embodied AI V5.0 (Adaptive Companion Architecture 自适应伙伴架构) ──
    companion_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_ENABLED", "false").lower() == "true")
    companion_agent_timeout: float = Field(default_factory=lambda: float(os.getenv("COMPANION_AGENT_TIMEOUT", "10.0")))
    companion_route_rule_version: str = Field(default_factory=lambda: os.getenv("COMPANION_ROUTE_RULE_VERSION", "v1"))
    # ── Embodied AI V5.1 (Companion Coordination Enhancement 伙伴协同增强) ──
    companion_delegate_workers: int = Field(default_factory=lambda: int(os.getenv("COMPANION_DELEGATE_WORKERS", "4")))
    companion_route_topk: int = Field(default_factory=lambda: int(os.getenv("COMPANION_ROUTE_TOPK", "3")))
    companion_stats_max_records: int = Field(default_factory=lambda: int(os.getenv("COMPANION_STATS_MAX_RECORDS", "500")))
    # ── Embodied AI V5.2 (Companion Perception & Strategy Integration 感知-战略集成) ──
    companion_pipeline_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_PIPELINE_ENABLED", "true").lower() == "true")
    companion_pipeline_strict: bool = Field(default_factory=lambda: os.getenv("COMPANION_PIPELINE_STRICT", "false").lower() == "true")
    # ── Embodied AI V5.3 (Companion Execution & Feedback Loop 执行-反馈闭环) ──
    companion_loop_max_iterations: int = Field(default_factory=lambda: int(os.getenv("COMPANION_LOOP_MAX_ITERATIONS", "3")))
    companion_execute_confirm: bool = Field(default_factory=lambda: os.getenv("COMPANION_EXECUTE_CONFIRM", "false").lower() == "true")
    companion_feedback_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_FEEDBACK_ENABLED", "true").lower() == "true")
    # ── Embodied AI V5.4 (Companion Self-Correction & Learning 自我修正与学习) ──
    companion_correction_max_attempts: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CORRECTION_MAX_ATTEMPTS", "3")))
    companion_learning_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_LEARNING_ENABLED", "true").lower() == "true")
    companion_correction_strict: bool = Field(default_factory=lambda: os.getenv("COMPANION_CORRECTION_STRICT", "false").lower() == "true")
    # ── Embodied AI V5.5 (Companion Identity & Adaptive Personality 身份与自适应人格) ──
    companion_personality_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_PERSONALITY_ENABLED", "true").lower() == "true")
    companion_personality_base: str = Field(default_factory=lambda: os.getenv("COMPANION_PERSONALITY_BASE", "铁哥们"))
    companion_personality_adjust_step: float = Field(default_factory=lambda: float(os.getenv("COMPANION_PERSONALITY_ADJUST_STEP", "0.1")))
    # ── Embodied AI V5.6 (Companion Relationship & Personality Stability 关系与人格稳定) ──
    companion_personality_decay_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_PERSONALITY_DECAY_ENABLED", "true").lower() == "true")
    companion_relationship_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_RELATIONSHIP_ENABLED", "true").lower() == "true")
    companion_statistics_window_days: int = Field(default_factory=lambda: int(os.getenv("COMPANION_STATISTICS_WINDOW_DAYS", "30")))
    companion_decay_rate: float = Field(default_factory=lambda: float(os.getenv("COMPANION_DECAY_RATE", "0.05")))
    # ── Embodied AI V5.7 (Experience Memory Layer 经历记忆层) ──
    companion_experience_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_EXPERIENCE_ENABLED", "true").lower() == "true")
    companion_experience_max_records: int = Field(default_factory=lambda: int(os.getenv("COMPANION_EXPERIENCE_MAX_RECORDS", "200")))
    companion_experience_decay_rate: float = Field(default_factory=lambda: float(os.getenv("COMPANION_EXPERIENCE_DECAY_RATE", "0.1")))
    # ── Embodied AI V5.8 (Reflection & Cognitive Integrity 反思与认知完整性) ──
    companion_verification_confirm_threshold: int = Field(default_factory=lambda: int(os.getenv("COMPANION_VERIFICATION_CONFIRM_THRESHOLD", "2")))
    companion_verification_reject_threshold: int = Field(default_factory=lambda: int(os.getenv("COMPANION_VERIFICATION_REJECT_THRESHOLD", "2")))
    companion_pattern_min_occurrences: int = Field(default_factory=lambda: int(os.getenv("COMPANION_PATTERN_MIN_OCCURRENCES", "3")))
    # ── Embodied AI V5.9 (Creative Intelligence & Value Discovery 创造智能与价值发现) ──
    companion_creative_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_CREATIVE_ENABLED", "true").lower() == "true")
    companion_creative_opportunity_min_evidence: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CREATIVE_OPPORTUNITY_MIN_EVIDENCE", "2")))
    companion_creative_opportunity_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CREATIVE_OPPORTUNITY_MAX", "20")))
    companion_creative_repetition_min_occurrences: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CREATIVE_REPETITION_MIN_OCCURRENCES", "3")))
    companion_creative_failure_min_occurrences: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CREATIVE_FAILURE_MIN_OCCURRENCES", "2")))
    companion_creative_relationship_trust_min: float = Field(default_factory=lambda: float(os.getenv("COMPANION_CREATIVE_RELATIONSHIP_TRUST_MIN", "0.7")))
    companion_creative_value_threshold: float = Field(default_factory=lambda: float(os.getenv("COMPANION_CREATIVE_VALUE_THRESHOLD", "0.6")))
    companion_creative_defer_threshold: float = Field(default_factory=lambda: float(os.getenv("COMPANION_CREATIVE_DEFER_THRESHOLD", "0.35")))
    companion_creative_proposal_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CREATIVE_PROPOSAL_MAX", "30")))
    companion_creative_simulation_min_success_rate: float = Field(default_factory=lambda: float(os.getenv("COMPANION_CREATIVE_SIMULATION_MIN_SUCCESS_RATE", "0.7")))
    companion_creative_simulation_revise_rate: float = Field(default_factory=lambda: float(os.getenv("COMPANION_CREATIVE_SIMULATION_REVISE_RATE", "0.4")))
    companion_creative_memory_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CREATIVE_MEMORY_MAX", "100")))
    companion_creative_memory_path: str = Field(default_factory=lambda: os.getenv("COMPANION_CREATIVE_MEMORY_PATH", ""))
    companion_creative_audit_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CREATIVE_AUDIT_MAX", "500")))
    # ── Embodied AI V6.0 (Long-term Identity & Growth Continuity 长期身份与成长连续) ──
    companion_persistence_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_PERSISTENCE_ENABLED", "false").lower() == "true")
    companion_persistence_path: str = Field(default_factory=lambda: os.getenv("COMPANION_PERSISTENCE_PATH", ""))
    companion_persistence_schema_version: str = Field(default_factory=lambda: os.getenv("COMPANION_PERSISTENCE_SCHEMA_VERSION", "6.0.0"))
    companion_persistence_audit_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_PERSISTENCE_AUDIT_MAX", "500")))
    companion_memory_importance_high_threshold: float = Field(default_factory=lambda: float(os.getenv("COMPANION_MEMORY_IMPORTANCE_HIGH_THRESHOLD", "0.7")))
    companion_experience_archive_days: int = Field(default_factory=lambda: int(os.getenv("COMPANION_EXPERIENCE_ARCHIVE_DAYS", "30")))
    companion_experience_recycle_value: float = Field(default_factory=lambda: float(os.getenv("COMPANION_EXPERIENCE_RECYCLE_VALUE", "0.3")))
    companion_experience_archive_keep_value: float = Field(default_factory=lambda: float(os.getenv("COMPANION_EXPERIENCE_ARCHIVE_KEEP_VALUE", "0.7")))
    companion_identity_history_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_IDENTITY_HISTORY_MAX", "200")))
    companion_growth_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_GROWTH_ENABLED", "true").lower() == "true")
    companion_growth_window_days: int = Field(default_factory=lambda: int(os.getenv("COMPANION_GROWTH_WINDOW_DAYS", "30")))
    companion_growth_max_events: int = Field(default_factory=lambda: int(os.getenv("COMPANION_GROWTH_MAX_EVENTS", "5000")))
    # ── Embodied AI V6.1.1 (Emotion Representation & Growth Rhythm 情绪表征与成长节律) ──
    companion_emotion_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_EMOTION_ENABLED", "true").lower() == "true")
    companion_emotion_decay_rate: float = Field(default_factory=lambda: float(os.getenv("COMPANION_EMOTION_DECAY_RATE", "0.05")))
    companion_emotion_update_step: float = Field(default_factory=lambda: float(os.getenv("COMPANION_EMOTION_UPDATE_STEP", "0.1")))
    companion_emotion_decay_window_days: float = Field(default_factory=lambda: float(os.getenv("COMPANION_EMOTION_DECAY_WINDOW_DAYS", "7.0")))
    companion_emotion_consecutive_limit: int = Field(default_factory=lambda: int(os.getenv("COMPANION_EMOTION_CONSECUTIVE_LIMIT", "3")))
    companion_emotion_floor: float = Field(default_factory=lambda: float(os.getenv("COMPANION_EMOTION_FLOOR", "0.1")))
    companion_rhythm_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_RHYTHM_ENABLED", "true").lower() == "true")
    companion_rhythm_consolidate_threshold: int = Field(default_factory=lambda: int(os.getenv("COMPANION_RHYTHM_CONSOLIDATE_THRESHOLD", "20")))
    companion_rhythm_consolidate_days: int = Field(default_factory=lambda: int(os.getenv("COMPANION_RHYTHM_CONSOLIDATE_DAYS", "7")))
    companion_rhythm_daily_snapshot: bool = Field(default_factory=lambda: os.getenv("COMPANION_RHYTHM_DAILY_SNAPSHOT", "true").lower() == "true")
    companion_rhythm_auto_reflection: bool = Field(default_factory=lambda: os.getenv("COMPANION_RHYTHM_AUTO_REFLECTION", "true").lower() == "true")
    # ── Embodied AI V6.2 (Multimodal Interaction & Perception 多模态交互与感知) ──
    companion_expression_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_EXPRESSION_ENABLED", "true").lower() == "true")
    companion_expression_threshold: float = Field(default_factory=lambda: float(os.getenv("COMPANION_EXPRESSION_THRESHOLD", "0.7")))
    perception_enabled: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_ENABLED", "false").lower() == "true")
    vision_enabled: bool = Field(default_factory=lambda: os.getenv("VISION_ENABLED", "false").lower() == "true")
    ocr_enabled: bool = Field(default_factory=lambda: os.getenv("OCR_ENABLED", "false").lower() == "true")
    detection_enabled: bool = Field(default_factory=lambda: os.getenv("DETECTION_ENABLED", "false").lower() == "true")
    perception_permission_required: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_PERMISSION_REQUIRED", "true").lower() == "true")
    perception_audit_enabled: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_AUDIT_ENABLED", "true").lower() == "true")
    perception_min_confidence: float = Field(default_factory=lambda: float(os.getenv("PERCEPTION_MIN_CONFIDENCE", "0.5")))
    perception_default_ocr: str = Field(default_factory=lambda: os.getenv("PERCEPTION_DEFAULT_OCR", "ocr_mock"))
    perception_default_detection: str = Field(default_factory=lambda: os.getenv("PERCEPTION_DEFAULT_DETECTION", "detection_mock"))
    # ── Embodied AI V6.3 (Embodied Perception & Action Integration 具身感知与行动集成) ──
    perception_real_enabled: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_REAL_ENABLED", "false").lower() == "true")
    tesseract_enabled: bool = Field(default_factory=lambda: os.getenv("TESSERACT_ENABLED", "false").lower() == "true")
    template_detection_enabled: bool = Field(default_factory=lambda: os.getenv("TEMPLATE_DETECTION_ENABLED", "false").lower() == "true")
    memory_gate_enabled: bool = Field(default_factory=lambda: os.getenv("MEMORY_GATE_ENABLED", "true").lower() == "true")
    pipeline_perception_enabled: bool = Field(default_factory=lambda: os.getenv("PIPELINE_PERCEPTION_ENABLED", "true").lower() == "true")
    camera_access_enabled: bool = Field(default_factory=lambda: os.getenv("CAMERA_ACCESS_ENABLED", "false").lower() == "true")
    memory_gate_approve_threshold: float = Field(default_factory=lambda: float(os.getenv("MEMORY_GATE_APPROVE_THRESHOLD", "0.6")))
    memory_gate_reject_threshold: float = Field(default_factory=lambda: float(os.getenv("MEMORY_GATE_REJECT_THRESHOLD", "0.3")))
    perception_template_match_threshold: float = Field(default_factory=lambda: float(os.getenv("PERCEPTION_TEMPLATE_MATCH_THRESHOLD", "0.7")))
    # ── Embodied AI V6.4 (Perception-Memory Cognitive Integration 感知-记忆认知集成) ──
    reflection_enabled: bool = Field(default_factory=lambda: os.getenv("REFLECTION_ENABLED", "true").lower() == "true")
    reflection_score_threshold: float = Field(default_factory=lambda: float(os.getenv("REFLECTION_SCORE_THRESHOLD", "0.6")))
    counterfactual_enabled: bool = Field(default_factory=lambda: os.getenv("COUNTERFACTUAL_ENABLED", "true").lower() == "true")
    experience_provenance_enabled: bool = Field(default_factory=lambda: os.getenv("EXPERIENCE_PROVENANCE_ENABLED", "true").lower() == "true")
    multimodal_experience_enabled: bool = Field(default_factory=lambda: os.getenv("MULTIMODAL_EXPERIENCE_ENABLED", "true").lower() == "true")
    perception_stats_snapshot_enabled: bool = Field(default_factory=lambda: os.getenv("PERCEPTION_STATS_SNAPSHOT_ENABLED", "true").lower() == "true")
    nms_enabled: bool = Field(default_factory=lambda: os.getenv("NMS_ENABLED", "true").lower() == "true")
    # ── Embodied AI V6.5 (Cognitive Reflection & Autonomous Growth 认知反思与自主成长) ──
    pattern_analysis_enabled: bool = Field(default_factory=lambda: os.getenv("PATTERN_ANALYSIS_ENABLED", "true").lower() == "true")
    growth_proposal_enabled: bool = Field(default_factory=lambda: os.getenv("GROWTH_PROPOSAL_ENABLED", "true").lower() == "true")
    growth_auto_apply: bool = Field(default_factory=lambda: os.getenv("GROWTH_AUTO_APPLY", "false").lower() == "true")
    identity_guard_enabled: bool = Field(default_factory=lambda: os.getenv("IDENTITY_GUARD_ENABLED", "true").lower() == "true")
    growth_audit_enabled: bool = Field(default_factory=lambda: os.getenv("GROWTH_AUDIT_ENABLED", "true").lower() == "true")
    # ── Embodied AI V6.6 (Autonomous Growth Maturation 自主成长成熟化) ──
    companion_reflection_emotion_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_REFLECTION_EMOTION_ENABLED", "true").lower() == "true")
    companion_growth_cycle_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_GROWTH_CYCLE_ENABLED", "true").lower() == "true")
    companion_growth_cycle_days: int = Field(default_factory=lambda: int(os.getenv("COMPANION_GROWTH_CYCLE_DAYS", "1")))
    companion_growth_cycle_min_experience_delta: int = Field(default_factory=lambda: int(os.getenv("COMPANION_GROWTH_CYCLE_MIN_EXPERIENCE_DELTA", "5")))
    companion_growth_cycle_max_pending: int = Field(default_factory=lambda: int(os.getenv("COMPANION_GROWTH_CYCLE_MAX_PENDING", "50")))
    companion_growth_trend_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_GROWTH_TREND_ENABLED", "true").lower() == "true")
    # ── Embodied AI V6.8 (Hybrid Intelligence Layer 混合智能层) ──
    companion_hybrid_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_HYBRID_ENABLED", "true").lower() == "true")
    companion_hybrid_cloud_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_HYBRID_CLOUD_ENABLED", "true").lower() == "true")
    companion_hybrid_high_cost_threshold: float = Field(default_factory=lambda: float(os.getenv("COMPANION_HYBRID_HIGH_COST_THRESHOLD", "0.01")))
    companion_hybrid_low_value_threshold: float = Field(default_factory=lambda: float(os.getenv("COMPANION_HYBRID_LOW_VALUE_THRESHOLD", "0.3")))
    companion_hybrid_max_tokens: int = Field(default_factory=lambda: int(os.getenv("COMPANION_HYBRID_MAX_TOKENS", "4096")))
    companion_hybrid_audit_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_HYBRID_AUDIT_MAX", "2000")))
    # ── Embodied AI V7.0 (Embodied Presence Layer 具身表达层) ──
    companion_presence_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_PRESENCE_ENABLED", "true").lower() == "true")
    companion_presence_intensity_step: float = Field(default_factory=lambda: float(os.getenv("COMPANION_PRESENCE_INTENSITY_STEP", "0.15")))
    companion_presence_memory_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_PRESENCE_MEMORY_MAX", "2000")))
    companion_presence_hybrid_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_PRESENCE_HYBRID_LINK", "true").lower() == "true")
    # ── Embodied AI V8.0 (Constitution Engine 宪法治理引擎) ──
    companion_constitution_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_CONSTITUTION_ENABLED", "true").lower() == "true")
    companion_constitution_ledger_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_CONSTITUTION_LEDGER_MAX", "5000")))
    companion_constitution_hybrid_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_CONSTITUTION_HYBRID_LINK", "true").lower() == "true")
    companion_constitution_growth_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_CONSTITUTION_GROWTH_LINK", "true").lower() == "true")
    # ── Embodied AI V8.5 (Creative Intelligence Engine 元创造力引擎) ──
    companion_meta_creative_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_META_CREATIVE_ENABLED", "true").lower() == "true")
    companion_meta_creative_max_sparks: int = Field(default_factory=lambda: int(os.getenv("COMPANION_META_CREATIVE_MAX_SPARKS", "10")))
    companion_meta_creative_memory_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_META_CREATIVE_MEMORY_MAX", "1000")))
    companion_meta_creative_constitution_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_META_CREATIVE_CONSTITUTION_LINK", "true").lower() == "true")
    companion_meta_creative_hybrid_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_META_CREATIVE_HYBRID_LINK", "true").lower() == "true")
    # ── Embodied AI V9.0 (Autonomous Research & Exploration 自主研究探索) ──
    companion_research_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_RESEARCH_ENABLED", "true").lower() == "true")
    companion_research_max_loops: int = Field(default_factory=lambda: int(os.getenv("COMPANION_RESEARCH_MAX_LOOPS", "3")))
    companion_research_audit_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_RESEARCH_AUDIT_MAX", "2000")))
    companion_research_constitution_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_RESEARCH_CONSTITUTION_LINK", "true").lower() == "true")
    companion_research_creative_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_RESEARCH_CREATIVE_LINK", "true").lower() == "true")
    companion_research_hybrid_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_RESEARCH_HYBRID_LINK", "true").lower() == "true")
    # ── Embodied AI V9.5 (Meta-Cognition Engine 元认知引擎) ──
    companion_meta_cognition_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_META_COGNITION_ENABLED", "true").lower() == "true")
    companion_meta_cognition_audit_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_META_COGNITION_AUDIT_MAX", "2000")))
    companion_meta_cognition_constitution_link: bool = Field(default_factory=lambda: os.getenv("COMPANION_META_COGNITION_CONSTITUTION_LINK", "true").lower() == "true")
    companion_meta_cognition_memory_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_META_COGNITION_MEMORY_MAX", "1000")))
    # ── Embodied AI V10.1 (Memory Stabilization 记忆稳定化) ──
    companion_memory_stabilize_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_MEMORY_STABILIZE_ENABLED", "true").lower() == "true")
    companion_memory_stabilize_prune_value_threshold: float = Field(default_factory=lambda: float(os.getenv("COMPANION_MEMORY_STABILIZE_PRUNE_VALUE_THRESHOLD", "0.3")))
    companion_memory_stabilize_prune_age_days: int = Field(default_factory=lambda: int(os.getenv("COMPANION_MEMORY_STABILIZE_PRUNE_AGE_DAYS", "90")))
    companion_memory_stabilize_compress_similarity: float = Field(default_factory=lambda: float(os.getenv("COMPANION_MEMORY_STABILIZE_COMPRESS_SIMILARITY", "0.9")))
    companion_memory_stabilize_audit_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_MEMORY_STABILIZE_AUDIT_MAX", "2000")))
    # ── Embodied AI V10.1 (Interaction Protocol 交互协议层) ──
    companion_interaction_enabled: bool = Field(default_factory=lambda: os.getenv("COMPANION_INTERACTION_ENABLED", "true").lower() == "true")
    companion_interaction_max_context_len: int = Field(default_factory=lambda: int(os.getenv("COMPANION_INTERACTION_MAX_CONTEXT_LEN", "200")))
    companion_interaction_max_pending: int = Field(default_factory=lambda: int(os.getenv("COMPANION_INTERACTION_MAX_PENDING", "20")))
    companion_interaction_context_max_len: int = Field(default_factory=lambda: int(os.getenv("COMPANION_INTERACTION_CONTEXT_MAX_LEN", "200")))
    companion_interaction_max_flows: int = Field(default_factory=lambda: int(os.getenv("COMPANION_INTERACTION_MAX_FLOWS", "500")))
    companion_interaction_latency_max_samples: int = Field(default_factory=lambda: int(os.getenv("COMPANION_INTERACTION_LATENCY_MAX_SAMPLES", "1000")))
    companion_interaction_audit_max: int = Field(default_factory=lambda: int(os.getenv("COMPANION_INTERACTION_AUDIT_MAX", "2000")))

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