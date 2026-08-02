"""
YHLZ 2.0 TTS 引擎抽象基类
对齐 NachoBot BaseTTSModel 范式: 只定义 synthesize() / stream_synthesize_text() 两个核心方法,
换引擎成本从"改代码"降为"改配置"。
"""

import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class BaseTTSEngine(ABC):
    """TTS引擎抽象基类"""

    name: str = "base"

    def __init__(self):
        self.is_loaded = False

    @abstractmethod
    def load(self) -> bool:
        """加载引擎, 返回是否成功"""
        raise NotImplementedError

    @abstractmethod
    def unload(self) -> None:
        """卸载引擎, 释放资源"""
        raise NotImplementedError

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        **kwargs
    ) -> Tuple[np.ndarray, int]:
        """整段文本转语音 (音频, 采样率)"""
        raise NotImplementedError

    @abstractmethod
    async def stream_synthesize_text(
        self,
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        **kwargs
    ) -> AsyncGenerator[Tuple[np.ndarray, int], None]:
        """流式文本转语音, 逐块产出 (音频, 采样率)"""
        raise NotImplementedError

    def get_available_voices(self) -> List[dict]:
        """可用音色列表"""
        return []

    def release_gpu(self) -> None:
        """释放GPU显存 (无GPU引擎为空实现)"""
        pass


class TTSEngineError(Exception):
    """TTS引擎异常"""
    pass
