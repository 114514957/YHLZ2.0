"""
YHLZ Vision Foundation V1.0 - Adapter 抽象接口

职责:
    - 定义统一视觉适配器接口, 屏蔽 mss / cv2 / mock / 未来库差异
    - Service 不直接调用底层库, 经本接口间接调用
    - 所有异常转换为错误帧, 不向外抛

接口:
    class VisionAdapter:
        name: str
        def is_available() -> bool
        def list_devices() -> List[Dict]
        def capture(request: VisionCaptureRequest) -> VisionFrame
        def connect(device_index) -> bool
        def disconnect() -> None
        def get_info() -> Dict

设计原则:
    1. 不修改 Agent Core / Voice 模块
    2. Adapter 可替换: 抽象基类 + 注册
    3. 所有异常转换为 VisionFrame (status=error), 不抛
    4. 不绑定单一视觉库
"""
from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional

from backend.vision.schema import (
    VisionCaptureRequest,
    VisionFrame,
    VisionStatus,
)


class VisionAdapterError(Exception):
    """Vision Adapter 操作异常"""


class VisionAdapter(abc.ABC):
    """视觉适配器抽象基类

    子类必须实现:
        name (类属性): 适配器名
        is_available(): 检测设备是否可用
        capture(): 执行采集, 返回 VisionFrame

    约束:
        - 所有方法返回 Result/VisionFrame, 不抛异常
        - 不直接读写 Service/Manager 状态
        - 可读取 request 决定采集策略
        - connect/disconnect 可选实现 (Camera 需要, Screen 可空实现)
    """

    name: str = "abstract"
    source: str = "unknown"  # 对应 VisionSource

    @abc.abstractmethod
    def is_available(self) -> bool:
        """检测设备/库是否可用

        Returns:
            True 如果该适配器可正常工作 (设备存在, 依赖已安装)
        """
        raise NotImplementedError

    @abc.abstractmethod
    def capture(self, request: VisionCaptureRequest) -> VisionFrame:
        """执行视觉采集

        Args:
            request: 采集请求 (含 source/region/device_index/resize/metadata)

        Returns:
            VisionFrame: 成功含 image, 失败 status=error 且 error 字段描述原因

        约束:
            - 不抛异常, 内部捕获并转为错误帧
            - 尊重 permission 配置 (Service 层已检查, Adapter 仍可二次校验)
        """
        raise NotImplementedError

    def list_devices(self) -> List[Dict[str, Any]]:
        """列出可用设备

        Returns:
            设备列表 [{"index": 0, "name": "...", "type": "..."}]
            ScreenAdapter 通常返回单条虚拟设备
        """
        return []

    def connect(self, device_index: int = 0) -> bool:
        """连接设备 (Camera 类适配器需要, Screen 可空实现)

        Args:
            device_index: 设备索引

        Returns:
            True 连接成功
        """
        return True

    def disconnect(self) -> None:
        """断开设备连接"""
        pass

    def get_info(self) -> Dict[str, Any]:
        """获取适配器信息"""
        return {
            "name": self.name,
            "source": self.source,
            "available": self.is_available(),
            "devices": len(self.list_devices()),
        }

    # ── 内部辅助 ──────────────────────────────────────────────────
    def _error_frame(
        self,
        request: VisionCaptureRequest,
        status: str,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VisionFrame:
        """构造错误帧 (统一错误返回)"""
        return VisionFrame.create_error(
            source=self.source,
            status=status,
            error=error,
            metadata={**(request.metadata or {}), **(metadata or {})},
        )
