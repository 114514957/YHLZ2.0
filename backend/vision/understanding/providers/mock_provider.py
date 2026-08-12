"""
YHLZ Vision Understanding V1.0 - Mock Provider (测试用)

职责:
    - 提供无 VLM 模型环境下的合成理解结果
    - 用于单元测试 / 集成测试 / CI 环境
    - 模拟理解失败 / 异常 / 空结果等场景

设计原则:
    - 无外部依赖 (仅 numpy)
    - 可配置行为 (场景类型 / 描述 / 主体 / 错误模式)
    - 不进入生产代码路径
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.vision.understanding.interface import UnderstandingOptions
from backend.vision.understanding.providers.base import ProviderError, VLMProvider
from backend.vision.understanding.schema import (
    SceneType,
    SubjectPosition,
    UnderstandingResult,
    UnderstandingSubject,
)

logger = logging.getLogger(__name__)


class MockVLMProvider(VLMProvider):
    """Mock VLM Provider (测试专用)

    用法:
        # 正常模式
        provider = MockVLMProvider()
        result = provider.understand(image)  # 返回合成理解结果

        # 模拟空场景
        provider = MockVLMProvider(mode="empty")

        # 模拟异常
        provider = MockVLMProvider(mode="exception")

        # 模拟不可用
        provider = MockVLMProvider(mode="unavailable")

        # 自定义返回
        provider = MockVLMProvider(
            scene_type="desktop",
            description="桌面上有一个浏览器窗口",
            subjects=[UnderstandingSubject(name="window", category="ui")],
        )
    """

    name: str = "mock"

    def __init__(
        self,
        mode: str = "ok",                  # ok / empty / exception / unavailable
        scene_type: str = SceneType.DESKTOP.value,
        description: str = "",
        summary: str = "",
        subjects: Optional[List[UnderstandingSubject]] = None,
        confidence: float = 0.95,
        available: bool = True,
    ):
        self._mode = mode
        self._scene_type = scene_type
        self._description = description
        self._summary = summary
        self._subjects = subjects or [
            UnderstandingSubject(
                name="window",
                category="ui",
                position=SubjectPosition(x=10, y=10, w=400, h=300),
                confidence=0.92,
            ),
            UnderstandingSubject(
                name="taskbar",
                category="ui",
                position=SubjectPosition(x=0, y=700, w=800, h=50),
                confidence=0.88,
            ),
        ]
        self._confidence = confidence
        self._available = available
        self._call_count = 0

    def is_available(self) -> bool:
        return self._available

    def understand(
        self,
        image: Any,
        prompt: Optional[str] = None,
        options: Optional[UnderstandingOptions] = None,
    ) -> UnderstandingResult:
        self._call_count += 1

        if not self._available:
            raise ProviderError("Mock VLM Provider 不可用")

        if self._mode == "exception":
            raise ProviderError("Mock VLM 异常 (mode=exception)")

        if self._mode == "unavailable":
            raise ProviderError("Mock VLM 服务不可用 (mode=unavailable)")

        if image is None:
            raise ProviderError("输入图像为空")

        if self._mode == "empty":
            # 空场景: 无主体, 描述为空场景
            return UnderstandingResult.create_ok(
                source="mock",
                scene_type=SceneType.EMPTY.value,
                description="画面为纯色或空白, 无显著内容。",
                summary="这是一个空场景。",
                subjects=[],
                confidence=self._confidence,
                metadata={"provider": self.name, "mode": self._mode},
            )

        # ok 模式: 生成合成理解结果
        source = "mock"
        question = (options.question if options else None) or ""
        if question:
            # QA 模式: summary 回答问题
            summary = self._summary or (
                f"画面显示一个桌面环境, 包含窗口和任务栏。回答: {question}"
            )
            description = self._description or (
                "这是一个模拟的桌面场景: 屏幕上有浏览器窗口和任务栏, "
                "主体有窗口和任务栏元素。"
            )
        else:
            summary = self._summary or "画面显示一个桌面环境, 包含窗口和任务栏。"
            description = self._description or (
                "这是一个模拟的桌面场景: 屏幕上有浏览器窗口和任务栏, "
                "主体有窗口和任务栏元素, 整体为典型的桌面界面。"
            )

        result = UnderstandingResult.create_ok(
            source=source,
            scene_type=self._scene_type,
            description=description,
            subjects=self._subjects,
            summary=summary,
            confidence=self._confidence,
            metadata={"provider": self.name, "mode": self._mode},
        )
        return result

    def set_mode(self, mode: str) -> None:
        """运行时切换模式"""
        self._mode = mode

    def set_available(self, available: bool) -> None:
        """运行时切换可用性"""
        self._available = available

    @property
    def call_count(self) -> int:
        return self._call_count

    def reset(self) -> None:
        self._call_count = 0
        self._mode = "ok"
        self._available = True

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["mode"] = self._mode
        info["call_count"] = self._call_count
        return info


__all__ = ["MockVLMProvider"]
