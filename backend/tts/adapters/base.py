"""
YHLZ 2.0 TTS 引擎适配器抽象基类 (M0.2)

统一引擎调用接口, 供未来 Voice Identity System 使用:
    generate()     统一合成入口 (文本 → 音频)
    load()         加载/连接引擎
    unload()       卸载/释放
    health_check() 健康状态上报

设计原则:
- 未来 VIS 只依赖本接口, 不感知具体引擎 (Qwen3 / GPT-SoVITS / Edge)
- 引擎具体实现类只允许出现在本包内, 其他模块禁止直接调用引擎/Gradio
- 保持与 BaseTTSEngine 兼容的 (audio, sample_rate) 数据协议
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import numpy as np

from backend.tts.voice_style import VoiceStyle

logger = logging.getLogger(__name__)


class BaseVoiceEngineAdapter(ABC):
    """TTS 引擎适配器抽象基类"""

    #: 适配器名称 (与 TTSManager 引擎注册名对齐)
    name: str = "base"
    #: 引擎类型: qwen3 / gpt_sovits / edge
    engine_type: str = "base"

    def __init__(self):
        self.is_loaded = False

    @abstractmethod
    def load(self) -> bool:
        """加载/连接引擎, 返回是否成功"""
        raise NotImplementedError

    @abstractmethod
    def unload(self) -> None:
        """卸载/释放引擎资源"""
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        text: str,
        voice_id: Optional[str] = None,
        voice_style: Optional[VoiceStyle] = None,
        **params,
    ) -> Tuple[np.ndarray, int]:
        """统一合成入口: 文本 → (音频, 采样率)

        voice_id:    目标声音标识; 不支持的引擎应忽略并告警, 不应报错
        voice_style: M0.5 统一声音风格 (emotion/speed/pitch/energy);
                     适配器只消费数值字段, 禁止在内部重新做情绪分类
        params:      引擎私有参数 (由各 adapter 自行解释)
        """
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> dict:
        """健康状态: 返回可 JSON 序列化 dict, 至少含 ok 字段"""
        raise NotImplementedError

    def can_serve(self) -> bool:
        """是否可立即提供合成服务"""
        return self.is_loaded

    def get_available_voices(self) -> list:
        """可用音色列表 (多声音引擎返回注册的声音)"""
        return []

    # ------------------------------------------------------------------
    # 公共兜底工具
    # ------------------------------------------------------------------

    def _mock_audio(self, text: str, sample_rate: int = 24000) -> Tuple[np.ndarray, int]:
        """生成静默音频 (合成失败兜底, 保持 (audio, sr) 协议)"""
        duration = max(0.5, len(text) * 0.05)
        n_samples = int(duration * sample_rate)
        return np.zeros(n_samples, dtype=np.float32), sample_rate
