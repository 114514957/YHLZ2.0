"""
YHLZ 2.0 情绪分类器 (轻量规则版)
用于 TTS 情绪→音色映射 (蓝图1.4, 对齐 NachoBot EmotionClassifier 思路)

规则版先行: 正则关键词五分类 (happy/calm/sad/angry/neutral),
无置信度时回退 default。后续可替换为 zero-shot 模型 (MoritzLaurer/mDeBERTa 范式)。
"""

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 情绪五分类 (对齐 NEKO OUTWARD_EMOTION_ANALYSIS_PROMPT)
EMOTIONS = ["happy", "calm", "sad", "angry", "neutral"]

# 关键词规则表 (中文+简单英文)
_EMOTION_KEYWORDS: Dict[str, list] = {
    "happy": [
        "哈哈", "嘻嘻", "开心", "高兴", "好耶", "太好了", "真棒", "棒极了", "喜欢",
        "爱了", "有趣", "好玩", "万岁", "笑死", "哈哈哈", "耶", "嘿嘿", "哈哈",
        "惊喜", "期待", "好开心", "幸福", "快乐", "太好啦",
    ],
    "calm": [
        "嗯嗯", "好的", "明白了", "知道了", "放心", "慢慢来", "别急", "没关系",
        "没事", "安静", "平静", "放松", "缓缓", "不急", "淡定", "安心",
    ],
    "sad": [
        "难过", "伤心", "委屈", "难过死", "好烦", "烦死了", "唉", "呜呜", "哭了",
        "想哭", "失落", "失望", "遗憾", "孤独", "寂寞", "悲伤", "痛苦", "心疼",
        "累了", "好累", "无助", "丧",
    ],
    "angry": [
        "生气", "愤怒", "气死", "可恶", "讨厌", "滚", "烦人", "受够", "别惹我",
        "恼火", "暴躁", "抓狂", "忍不了", "无语", "神经病",
    ],
}

# 情绪→Edge-TTS 音色映射 (对齐 NachoBot tag_preset_map 思路)
EMOTION_VOICE_MAP: Dict[str, str] = {
    "happy": "zh-CN-XiaoyiNeural",     # 小艺: 活泼
    "calm": "zh-CN-XiaoxiaoNeural",    # 晓晓: 温柔
    "sad": "zh-CN-XiaomoNeural",       # 晓墨: 低沉
    "angry": "zh-CN-YunjianNeural",    # 云健: 稳重
    "neutral": "zh-CN-XiaoxiaoNeural", # 默认
}

# 感叹号/语气词增强权重
_INTENSIFIERS = ["！", "!", "啦", "呀", "嘛", "呢"]


def classify_emotion(text: str) -> Dict[str, float]:
    """
    规则版情绪分类

    Returns:
        {"emotion": str, "confidence": float}
    """
    if not text:
        return {"emotion": "neutral", "confidence": 0.0}

    scores = {emotion: 0.0 for emotion in EMOTIONS}

    # 关键词计数 (每个关键词按出现次数加权)
    for emotion, keywords in _EMOTION_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            count = text.count(kw)
            if count > 0:
                # 短词(2字)权重0.8, 长词(≥3字)权重1.2
                weight = 1.2 if len(kw) >= 3 else 0.8
                score += count * weight
        scores[emotion] = score

    # 强度增强: 感叹号加重 happy/angry
    exclaim_count = sum(text.count(p) for p in ["!", "！"])
    if exclaim_count >= 2:
        scores["happy"] += 0.5
        scores["angry"] += 0.5

    # 取最高分
    best_emotion = max(scores, key=scores.get)
    best_score = scores[best_emotion]

    if best_score <= 0:
        return {"emotion": "neutral", "confidence": 0.0}

    # 归一化置信度 (0~1)
    total = sum(scores.values())
    confidence = min(1.0, best_score / total if total > 0 else 0.0)

    # 无竞争情绪时提高置信度
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
    if second == 0:
        confidence = min(1.0, confidence + 0.3)

    logger.debug(f"情绪分类: {text[:20]} → {best_emotion} (conf={confidence:.2f})")
    return {"emotion": best_emotion, "confidence": confidence}


def resolve_voice_for_emotion(
    text: str,
    base_voice: str = "zh-CN-XiaoxiaoNeural",
    enabled: bool = True,
    confidence_threshold: float = 0.5,
) -> str:
    """
    根据文本情绪选择音色 (低置信度回退 base_voice)

    Args:
        text: 待合成文本
        base_voice: 默认音色
        enabled: 是否启用情绪→音色映射
        confidence_threshold: 置信度阈值, 低于则回退默认音色

    Returns:
        Edge-TTS 音色ID
    """
    if not enabled:
        return base_voice

    try:
        result = classify_emotion(text)
        if result["confidence"] >= confidence_threshold:
            voice = EMOTION_VOICE_MAP.get(result["emotion"])
            if voice:
                logger.info(f"情绪音色: {result['emotion']}(conf={result['confidence']:.2f}) → {voice}")
                return voice
        return base_voice
    except Exception as e:
        logger.warning(f"情绪音色解析失败, 使用默认: {e}")
        return base_voice


def get_emotion_voice(emotion: str, base_voice: str = "zh-CN-XiaoxiaoNeural") -> str:
    """按显式情绪名取音色 (供 /synthesize emotion 参数使用)"""
    return EMOTION_VOICE_MAP.get(emotion, base_voice)
