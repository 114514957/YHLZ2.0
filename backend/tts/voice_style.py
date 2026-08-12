"""
YHLZ 2.0 VoiceStyle 统一数据结构 (M0.5)

目标: 统一 Emotion → Voice Style → TTS Adapter 的接口。
- Emotion 系统 (emotion_classifier.py) 输出 VoiceStyle
- TTS Adapter (adapters/*) 接收 VoiceStyle, 翻译为引擎私有参数
- 禁止 emotion 分类逻辑进入具体 TTS 引擎实现

VoiceStyle 字段 (对齐任务要求示例):
    {
        "emotion": "happy",   # 情绪标签 (metadata, 适配器不应依赖此字段做分类)
        "speed": 1.1,         # 语速倍率 (1.0 = 正常)
        "pitch": 3,           # 音调偏移 (半音, 0 = 正常)
        "energy": 1.2         # 能量/强度倍率 (1.0 = 正常)
    }

设计原则:
- 适配器只消费数值字段 (speed/pitch/energy), emotion 字段仅供日志/未来引擎原生情绪标签使用
- 适配器不得在内部重新实现情绪分类 (那属于 emotion_classifier 职责)
- 不支持的数值字段静默忽略并 debug 日志, 不报错 (保持引擎间容错)
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class VoiceStyle:
    """统一声音风格描述 (Emotion 系统输出 / TTS Adapter 输入)

    字段语义:
        emotion: 情绪标签 (happy/calm/sad/angry/neutral), metadata 性质;
                 适配器不应基于此字段做分类决策, 应使用下面的数值字段
        speed:   语速倍率, 1.0 = 正常, >1 加速, <1 减速
        pitch:   音调偏移 (半音), 0 = 正常, 正数升调, 负数降调
        energy:  能量/强度倍率, 1.0 = 正常, >1 增强, <1 减弱
    """
    emotion: str = "neutral"
    speed: float = 1.0
    pitch: float = 0.0
    energy: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "VoiceStyle":
        """从 dict 构造, 缺失字段回填默认值; None/空 → DEFAULT_VOICE_STYLE"""
        if not d or not isinstance(d, dict):
            return cls()
        return cls(
            emotion=str(d.get("emotion", "neutral")) or "neutral",
            speed=float(d.get("speed", 1.0)),
            pitch=float(d.get("pitch", 0.0)),
            energy=float(d.get("energy", 1.0)),
        )

    def merge(self, override: Optional["VoiceStyle"]) -> "VoiceStyle":
        """字段级 merge: override 非 None 的字段覆盖 self (None/默认值不覆盖)"""
        if override is None:
            return self
        return VoiceStyle(
            emotion=override.emotion if override.emotion != "neutral" else self.emotion,
            speed=override.speed if override.speed != 1.0 else self.speed,
            pitch=override.pitch if override.pitch != 0.0 else self.pitch,
            energy=override.energy if override.energy != 1.0 else self.energy,
        )


# 默认 VoiceStyle (中性, 无风格调整)
DEFAULT_VOICE_STYLE = VoiceStyle()

# 情绪 → VoiceStyle 映射表 (Emotion 系统唯一真相源)
# 适配器禁止重新实现此映射; 只能消费数值字段
EMOTION_STYLE_MAP: Dict[str, Dict[str, Any]] = {
    "happy":   {"emotion": "happy",   "speed": 1.1,  "pitch": 3.0,  "energy": 1.2},
    "calm":    {"emotion": "calm",    "speed": 0.95, "pitch": 0.0,  "energy": 0.9},
    "sad":     {"emotion": "sad",     "speed": 0.9,  "pitch": -2.0, "energy": 0.8},
    "angry":   {"emotion": "angry",   "speed": 1.05, "pitch": 2.0,  "energy": 1.3},
    "neutral": {"emotion": "neutral", "speed": 1.0,  "pitch": 0.0,  "energy": 1.0},
}


def get_style_for_emotion(emotion: str) -> VoiceStyle:
    """按情绪名取 VoiceStyle; 未知情绪回退 neutral"""
    entry = EMOTION_STYLE_MAP.get(emotion)
    if entry is None:
        logger.debug(f"未知情绪 '{emotion}', 回退 neutral VoiceStyle")
        entry = EMOTION_STYLE_MAP["neutral"]
    return VoiceStyle.from_dict(entry)


def speed_to_rate(speed: float) -> str:
    """语速倍率 → Edge/Qwen3 rate 字符串 (如 1.1 → '+10%', 0.9 → '-10%')

    供适配器翻译使用; 引擎私有转换集中在 voice_style 模块, 避免分散
    """
    pct = round((speed - 1.0) * 100)
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}%"
