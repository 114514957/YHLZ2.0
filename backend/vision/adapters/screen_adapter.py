"""
YHLZ Vision Foundation V1.0 - 屏幕采集 Adapter

职责:
    - 实现电脑屏幕截图采集
    - 支持全屏截图 / 区域截图
    - 使用 mss 库 (跨平台, 高性能)
    - 异常隔离, 不抛

依赖:
    - mss (跨平台屏幕采集)
    - numpy
    - cv2 (可选, 用于格式转换)

设计原则:
    - 不绑定单一库: 可替换为 pyautogui / PIL ImageGrab
    - Mock 模式: 无屏幕环境 (headless) 下返回错误帧而非崩溃
    - 权限检查由 Service 层完成, Adapter 仅做可用性检查
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

from backend.vision.adapters.base import BaseVisionAdapter
from backend.vision.schema import VisionCaptureRequest, VisionSource

logger = logging.getLogger(__name__)


class ScreenAdapter(BaseVisionAdapter):
    """屏幕采集 Adapter (基于 mss)

    用法:
        adapter = ScreenAdapter()
        if adapter.is_available():
            frame = adapter.capture(VisionCaptureRequest(source="screen"))

    特性:
        - 跨平台 (Windows / macOS / Linux)
        - 支持多显示器 (默认主屏, 可通过 metadata.monitor 指定)
        - 无需 connect/disconnect (无状态)
        - headless 环境返回错误帧
    """

    name: str = "ScreenAdapter"
    source: str = VisionSource.SCREEN.value

    def __init__(self):
        self._mss = None
        self._mss_checked = False
        self._monitors_cache: List[Dict[str, Any]] = []

    def _check_available(self) -> bool:
        """检查 mss 是否可用 + 是否有屏幕设备"""
        try:
            import mss
            self._mss = mss
            with mss.mss() as sct:
                monitors = sct.monitors
                # monitors[0] 是全部屏幕的合并区域, 实际显示器从 [1] 开始
                self._monitors_cache = list(monitors[1:]) if len(monitors) > 1 else []
            self._mss_checked = True
            return len(self._monitors_cache) > 0 or len(monitors) >= 1
        except ImportError:
            logger.warning("mss 未安装, ScreenAdapter 不可用")
            return False
        except Exception as e:
            logger.warning(f"ScreenAdapter 可用性检查失败: {e}")
            return False

    def list_devices(self) -> List[Dict[str, Any]]:
        """列出可用显示器"""
        if not self._mss_checked:
            self._check_available()
        devices = []
        for i, m in enumerate(self._monitors_cache):
            devices.append({
                "index": i,
                "name": f"Monitor {i}",
                "type": "screen",
                "width": m.get("width", 0),
                "height": m.get("height", 0),
            })
        if not devices:
            # headless 或检测失败, 返回空列表
            logger.warning("未检测到显示器设备")
        return devices

    def _do_capture(self, request: VisionCaptureRequest) -> np.ndarray:
        """执行屏幕截图

        Args:
            request: 采集请求 (region/device_index 通过 metadata.monitor 指定)

        Returns:
            numpy ndarray (HxWxC, BGR)
        """
        import mss

        monitor_index = (request.metadata or {}).get("monitor", 1)  # 默认主屏
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index >= len(monitors):
                # 索引越界, 使用主屏
                monitor_index = min(1, len(monitors) - 1)
            monitor = monitors[monitor_index] if monitor_index < len(monitors) else monitors[0]

            # mss.grab() 返回 BGRA
            sct_img = sct.grab(monitor)
            # 转为 numpy 数组 (HxWx4, BGRA)
            arr = np.array(sct_img)
            # BGRA → BGR (去掉 alpha 通道)
            if arr.ndim == 3 and arr.shape[2] == 4:
                arr = arr[:, :, :3]
            return arr

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["library"] = "mss"
        info["monitors"] = len(self._monitors_cache)
        return info
