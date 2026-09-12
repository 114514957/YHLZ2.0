"""
YHLZ Vision Foundation V1.0 - Mock Adapter (测试用)

职责:
    - 提供无设备环境下的视觉采集 (返回合成图像)
    - 用于单元测试 / 集成测试 / CI 环境
    - 模拟权限拒绝 / 设备断开 / 异常等场景

设计原则:
    - 无外部依赖 (仅 numpy)
    - 可配置行为 (返回特定状态/错误)
    - 不进入生产代码路径
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from backend.vision.adapters.base import BaseVisionAdapter
from backend.vision.schema import VisionCaptureRequest, VisionSource, VisionStatus

logger = logging.getLogger(__name__)


class MockVisionAdapter(BaseVisionAdapter):
    """Mock 视觉 Adapter (测试专用)

    用法:
        # 正常模式
        adapter = MockVisionAdapter(width=640, height=480)
        frame = adapter.capture(request)  # 返回合成图像

        # 模拟失败
        adapter = MockVisionAdapter(mode="error", error_status="no_device",
                                    error_msg="模拟无设备")
        frame = adapter.capture(request)  # 返回错误帧

        # 模拟异常
        adapter = MockVisionAdapter(mode="exception")
        frame = adapter.capture(request)  # 返回异常错误帧
    """

    name: str = "MockVisionAdapter"
    source: str = VisionSource.MOCK.value

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        mode: str = "ok",                  # ok / error / exception
        error_status: str = "error",
        error_msg: str = "mock error",
        available: bool = True,
        capture_count_limit: int = -1,     # -1=无限, >0=N次后转为不可用
    ):
        self._width = width
        self._height = height
        self._mode = mode
        self._error_status = error_status
        self._error_msg = error_msg
        self._available = available
        self._capture_count_limit = capture_count_limit
        self._capture_count = 0
        self._frame_counter = 0

    def _check_available(self) -> bool:
        return self._available

    def _do_capture(self, request: VisionCaptureRequest) -> np.ndarray:
        # 计数检查
        self._capture_count += 1
        if self._capture_count_limit > 0 and self._capture_count > self._capture_count_limit:
            self._available = False
            raise RuntimeError("Mock 设备达到采集上限, 已转为不可用")

        if self._mode == "exception":
            raise RuntimeError(self._error_msg)

        if self._mode == "error":
            # error 模式应该由 capture() 捕获后构造错误帧
            # 但 _do_capture 抛异常会被 Base 捕获, 这里改用特殊标记
            # 实际上, Base 的 capture 流程不识别 mode, 所以 error 模式我们直接 raise
            raise RuntimeError(self._error_msg)

        # ok 模式: 生成合成图像
        self._frame_counter += 1
        # 生成 BGR 渐变图, 像素值随帧号变化 (便于测试区分)
        img = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        # 蓝色通道 = 帧号
        img[:, :, 0] = (self._frame_counter * 7) % 256
        # 绿色通道 = 行号
        for y in range(self._height):
            img[y, :, 1] = (y * 255 // self._height) % 256
        # 红色通道 = 列号
        for x in range(self._width):
            img[:, x, 2] = (x * 255 // self._width) % 256
        return img

    def list_devices(self) -> List[Dict[str, Any]]:
        if self._available:
            return [{
                "index": 0,
                "name": "Mock Device",
                "type": "mock",
                "width": self._width,
                "height": self._height,
            }]
        return []

    def set_mode(self, mode: str, error_status: str = "error", error_msg: str = "mock error") -> None:
        """运行时切换模式"""
        self._mode = mode
        self._error_status = error_status
        self._error_msg = error_msg

    def set_available(self, available: bool) -> None:
        """运行时切换可用性"""
        self._available = available

    def reset(self) -> None:
        """重置计数器与状态"""
        self._capture_count = 0
        self._frame_counter = 0
        self._available = True
        self._mode = "ok"

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["library"] = "mock"
        info["mode"] = self._mode
        info["capture_count"] = self._capture_count
        info["frame_counter"] = self._frame_counter
        return info
