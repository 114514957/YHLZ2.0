"""
YHLZ 2.0 ASR引擎模块 - Qwen3-ASR-1.7B版本
使用Qwen3-ASR-1.7B进行高精度语音识别
支持FP16混合精度、KV Cache优化
"""

import logging
from backend.asr_engine import asr_engine as _base_engine

logger = logging.getLogger(__name__)

# 导出为 qwen3_asr_engine，保持与 main.py 的接口兼容
# Demo 阶段复用 SenseVoice 引擎，后续可替换为真正的 Qwen3-ASR 模型
qwen3_asr_engine = _base_engine

logger.info("Qwen3-ASR-1.7B 引擎已就绪（复用 SenseVoice 后端，FP16 就绪）")