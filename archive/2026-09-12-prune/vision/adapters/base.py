"""
YHLZ Vision Foundation V1.0 - Adapter 基类 (实现通用逻辑)

职责:
    - 继承 VisionAdapter 抽象基类
    - 提供通用辅助方法 (resize / region 裁剪 / 时间统计)
    - 子类只需实现 _do_capture, 复用通用流程

设计原则:
    - 模板方法模式: base 控制流程, 子类实现具体采集
    - 异常隔离: _do_capture 抛出的异常被捕获并转为错误帧
    - 不绑定单一库
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import numpy as np

from backend.vision.interface import VisionAdapter
from backend.vision.schema import (
    VisionCaptureRequest,
    VisionFrame,
    VisionStatus,
)

logger = logging.getLogger(__name__)


class BaseVisionAdapter(VisionAdapter):
    """Adapter 基类 - 模板方法模式

    子类实现:
        _do_capture(request) -> np.ndarray  (返回图像, 异常向上抛)
        _check_available() -> bool          (检查设备和依赖)

    Base 负责:
        - 时间统计 (latency)
        - 异常捕获并转错误帧
        - region 裁剪
        - resize 缩放
        - 元数据填充
    """

    name: str = "base"
    source: str = "base"

    def is_available(self) -> bool:
        """默认实现: 调用子类 _check_available"""
        try:
            return self._check_available()
        except Exception as e:
            logger.warning(f"[{self.name}] is_available 检查异常: {e}")
            return False

    def _check_available(self) -> bool:
        """子类实现: 检查设备/库是否可用"""
        return True

    def capture(self, request: VisionCaptureRequest) -> VisionFrame:
        """采集流程 (模板方法)

        流程:
            1. 记录开始时间
            2. 调用 _do_capture (子类实现)
            3. region 裁剪 (如指定)
            4. resize 缩放 (如指定)
            5. 构造 VisionFrame (成功)
            6. 异常时构造错误帧
        """
        start = time.perf_counter()
        try:
            # 检查可用性
            if not self.is_available():
                latency = (time.perf_counter() - start) * 1000
                return self._error_frame(
                    request,
                    VisionStatus.NO_DEVICE.value,
                    f"{self.name} 设备不可用",
                    metadata={"latency_ms": round(latency, 2)},
                )

            # 子类执行采集
            image = self._do_capture(request)

            # 校验图像
            if image is None:
                latency = (time.perf_counter() - start) * 1000
                return self._error_frame(
                    request,
                    VisionStatus.ERROR.value,
                    f"{self.name} 采集返回空图像",
                    metadata={"latency_ms": round(latency, 2)},
                )

            # region 裁剪
            if request.region is not None:
                image = self._crop_region(image, request.region)

            # resize 缩放
            if request.resize is not None:
                image = self._resize(image, request.resize["width"], request.resize["height"])

            latency = (time.perf_counter() - start) * 1000
            metadata = {
                **(request.metadata or {}),
                "latency_ms": round(latency, 2),
                "adapter": self.name,
            }
            if request.region is not None:
                metadata["region"] = request.region
            if request.resize is not None:
                metadata["resize"] = request.resize

            frame = VisionFrame.create_ok(
                source=self.source,
                image=image,
                metadata=metadata,
            )
            logger.debug(f"[{self.name}] 采集成功 shape={image.shape} "
                         f"latency={latency:.1f}ms")
            return frame

        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] 采集异常: {e}", exc_info=True)
            return self._error_frame(
                request,
                VisionStatus.ERROR.value,
                f"{self.name} 采集异常: {type(e).__name__}: {e}",
                metadata={"latency_ms": round(latency, 2)},
            )

    def _do_capture(self, request: VisionCaptureRequest) -> np.ndarray:
        """子类实现: 执行实际采集, 返回 numpy ndarray

        约束:
            - 可抛异常, Base 会捕获
            - 返回 BGR 格式 (HxWxC), 与 OpenCV 一致
            - 单帧采集, 不做 region/resize (Base 已处理)
        """
        raise NotImplementedError

    # ── 通用辅助 ──────────────────────────────────────────────────
    def _crop_region(self, image: np.ndarray, region: Dict[str, int]) -> np.ndarray:
        """裁剪指定区域

        Args:
            image: 原图 (HxWxC)
            region: {x, y, w, h}
        """
        x, y, w, h = region["x"], region["y"], region["w"], region["h"]
        h_img, w_img = image.shape[:2]
        # 边界裁剪
        x = max(0, min(x, w_img - 1))
        y = max(0, min(y, h_img - 1))
        x2 = min(x + w, w_img)
        y2 = min(y + h, h_img)
        return image[y:y2, x:x2]

    def _resize(self, image: np.ndarray, width: int, height: int) -> np.ndarray:
        """缩放图像"""
        try:
            import cv2
            return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        except ImportError:
            logger.warning("cv2 未安装, resize 跳过")
            return image

    def _to_bgr(self, image: np.ndarray) -> np.ndarray:
        """确保图像为 BGR 格式 (3 通道)"""
        if image.ndim == 2:
            # 灰度转 BGR
            try:
                import cv2
                return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            except ImportError:
                return np.stack([image] * 3, axis=-1)
        elif image.shape[2] == 4:
            # RGBA 转 BGR
            try:
                import cv2
                return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
            except ImportError:
                return image[:, :, :3]
        return image
