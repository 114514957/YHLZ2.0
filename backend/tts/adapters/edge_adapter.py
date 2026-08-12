"""
YHLZ 2.0 Edge-TTS 引擎适配器 (M0.2) — 预留接口

说明:
- 底层引擎 backend.tts.edge.EdgeTTSEngine 已实现 (在线, 免费, 无需 GPU)
- 但 Edge 引擎从未注册进 TTSManager (集成审计 R5), 本适配器为占位
- M0.2 仅预留统一接口槽位, generate() 未实现, 由后续阶段完成
"""
import logging
from typing import Optional, Tuple

import numpy as np

from backend.tts.adapters.base import BaseVoiceEngineAdapter
from backend.tts.voice_style import VoiceStyle

logger = logging.getLogger(__name__)


class EdgeTTSAdapter(BaseVoiceEngineAdapter):
    """Edge-TTS 适配器 (预留接口)"""

    name = "edge-tts"
    engine_type = "edge"

    def __init__(self):
        super().__init__()
        self._reserved = True

    def load(self) -> bool:
        logger.warning("EdgeTTSAdapter 为预留接口 (M0.2), load 未实现")
        self.is_loaded = False
        return False

    def unload(self) -> None:
        self.is_loaded = False

    def generate(
        self,
        text: str,
        voice_id: Optional[str] = None,
        voice_style: Optional[VoiceStyle] = None,
        **params,
    ) -> Tuple[np.ndarray, int]:
        """预留接口: 未实现 (M0.5 签名已对齐 voice_style)"""
        raise NotImplementedError(
            "EdgeTTSAdapter 为预留接口 (M0.2), 待后续阶段实现; "
            "底层引擎 backend.tts.edge.EdgeTTSEngine 已可用"
        )

    def health_check(self) -> dict:
        return {
            "ok": False,
            "loaded": False,
            "name": self.name,
            "reserved": True,
            "reason": "预留接口, 待实现",
        }

    def can_serve(self) -> bool:
        return False
