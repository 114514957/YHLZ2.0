"""
YHLZ Vision Understanding V1.0 - VLM Adapter 抽象接口

职责:
    - 定义 VLMAdapter 抽象接口
    - Service 不直接调用 VLM 库, 经 Adapter 间接调用
    - 所有异常转换为错误结果, 不向外抛

接口:
    class VLMAdapter:
        name: str
        def is_available() -> bool
        def understand(image, prompt, options) -> UnderstandingResult

设计原则:
    1. 不修改 Agent Core / Voice 模块 / Vision Foundation / Perception
    2. Adapter 可替换: 抽象基类 + 注册表
    3. 所有异常转换为错误结果, 不抛
    4. 不绑定单一 VLM 实现 (支持未来 Qwen-VL / GPT-4V / 其他)
    5. 业务代码不直接调用 Provider (经 Adapter)
"""
from __future__ import annotations

import abc
from typing import Any, Dict, Optional

from backend.vision.understanding.schema import UnderstandingResult


# ----------------------------------------------------------------------
# 异常
# ----------------------------------------------------------------------

class UnderstandingAdapterError(Exception):
    """Understanding Adapter 操作异常"""


# ----------------------------------------------------------------------
# Options
# ----------------------------------------------------------------------

class UnderstandingOptions:
    """理解选项 (传递给 Adapter / Provider)

    与 UnderstandingRequest 字段对应, 只携带执行参数, 不携带 image。

    Attributes:
        prompt: 自定义提示词 (None=内置模板)
        question: 视觉问答问题 (qa 模式)
        language: 输出语言 (zh / en)
        max_tokens: 最大输出 token 数
        temperature: 采样温度
        timeout: 超时秒数
        extra: 额外参数 (Provider 特定)
    """

    def __init__(
        self,
        prompt: Optional[str] = None,
        question: Optional[str] = None,
        language: str = "zh",
        max_tokens: int = 512,
        temperature: float = 0.3,
        timeout: float = 30.0,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.prompt = prompt
        self.question = question
        self.language = language
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.extra: Dict[str, Any] = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "question": self.question,
            "language": self.language,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UnderstandingOptions":
        return cls(
            prompt=d.get("prompt"),
            question=d.get("question"),
            language=d.get("language", "zh"),
            max_tokens=int(d.get("max_tokens", 512)),
            temperature=float(d.get("temperature", 0.3)),
            timeout=float(d.get("timeout", 30.0)),
            extra=d.get("extra"),
        )


# ----------------------------------------------------------------------
# VLM Adapter
# ----------------------------------------------------------------------

class VLMAdapter(abc.ABC):
    """VLM Adapter 抽象基类

    子类必须实现:
        name (类属性): 适配器名
        is_available(): 检测 VLM 模型是否可用
        understand(): 执行视觉理解, 返回 UnderstandingResult

    约束:
        - 所有方法返回 UnderstandingResult, 不抛异常 (内部捕获并转错误结果)
        - 不直接调用 Service / Manager 状态
        - 通过 Provider 间接调用底层模型 (业务代码不直接调 Provider)
    """

    name: str = "abstract_vlm"
    source: str = "vlm"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """检测 VLM 模型 / 服务是否可用"""
        raise NotImplementedError

    @abc.abstractmethod
    def understand(
        self,
        image: Any,
        prompt: Optional[str] = None,
        options: Optional[UnderstandingOptions] = None,
    ) -> UnderstandingResult:
        """执行视觉理解

        Args:
            image: numpy ndarray (HxWxC, BGR)
            prompt: 自定义提示词 (None=使用 Provider 内置模板)
            options: 理解选项

        Returns:
            UnderstandingResult: 成功含语义结果, 失败含 error
        """
        raise NotImplementedError

    def get_info(self) -> Dict[str, Any]:
        """获取 Adapter 信息"""
        return {
            "name": self.name,
            "source": self.source,
            "type": "vlm",
            "available": self.is_available(),
        }

    # ── 内部辅助 ──────────────────────────────────────────────────
    def _error_result(
        self,
        error: str,
        provider: str = "unknown",
        status: str = "error",
    ) -> UnderstandingResult:
        """构造错误 UnderstandingResult"""
        return UnderstandingResult.create_error(
            source=self.source,
            status=status,
            error=error,
            metadata={"provider": provider},
        )


__all__ = [
    "UnderstandingAdapterError",
    "UnderstandingOptions",
    "VLMAdapter",
]
