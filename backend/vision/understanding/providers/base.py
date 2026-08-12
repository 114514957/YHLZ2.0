"""
YHLZ Vision Understanding V1.0 - Provider 抽象基类

职责:
    - 定义 VLMProvider 抽象接口
    - 屏蔽底层 VLM 差异 (Mock / OpenAI 兼容 VLM / 未来 Qwen-VL / GPT-4V)
    - Adapter 通过 Provider 调用底层模型

设计原则:
    - Provider 是底层封装层 (Adapter 调用 Provider)
    - Provider 可抛异常 (实现层)
    - Adapter 捕获 Provider 异常并转为错误结果
    - 不绑定单一模型: 每个模型一个 Provider 实现
"""
from __future__ import annotations

import abc
from typing import Any, Dict, Optional

from backend.vision.understanding.interface import UnderstandingOptions
from backend.vision.understanding.schema import (
    UnderstandingResult,
    UnderstandingSubject,
)


class ProviderError(Exception):
    """Provider 操作异常"""


class VLMProvider(abc.ABC):
    """VLM Provider 抽象基类

    子类必须实现:
        name (类属性): provider 名 (mock / openai_vlm / ...)
        is_available(): 模型 / 服务是否可用
        understand(image, prompt, options) -> UnderstandingResult

    可抛:
        ProviderError 或其子类 (由 Adapter 捕获)
    """

    name: str = "abstract_vlm_provider"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """检测模型 / 服务是否可用"""
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
            prompt: 自定义提示词 (None=内置模板)
            options: 理解选项

        Returns:
            UnderstandingResult: 语义结果 (Provider 直接产出完整结果)

        Raises:
            ProviderError: 服务不可用 / 网络失败 / 解析失败
        """
        raise NotImplementedError

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": "vlm",
            "available": self.is_available(),
        }


# ----------------------------------------------------------------------
# 内置提示词模板
# ----------------------------------------------------------------------

DEFAULT_DESCRIBE_PROMPT = (
    "请描述这张图片的场景。要求:\n"
    "1. 用一句 summary 概括画面内容\n"
    "2. description 用 3~5 句描述: 场景类型、主要对象、正在发生的事情、环境信息\n"
    "3. scene_type 从以下选择: desktop / document / image / web / video / game / empty / unknown\n"
    "4. subjects 列出主要主体 (name, category, confidence 0~1)\n"
    "5. 以 JSON 输出, 格式: {{scene_type, summary, description, subjects: [{{name, category, confidence}}]}}"
)

DEFAULT_QA_PROMPT = (
    "请观察这张图片并回答用户问题。要求:\n"
    "1. 直接回答用户的问题 (question), 简洁准确\n"
    "2. summary 为你的答案\n"
    "3. description 补充与问题相关的画面细节\n"
    "4. scene_type 从以下选择: desktop / document / image / web / video / game / empty / unknown\n"
    "5. 以 JSON 输出, 格式: {{scene_type, summary, description, subjects: [{{name, category, confidence}}]}}"
)


def build_prompt(source: str, question: Optional[str] = None) -> str:
    """按理解来源构造内置提示词

    Args:
        source: 理解来源 (describe / qa / vlm)
        question: 视觉问答问题 (qa 来源)
    """
    if source == "qa":
        q = question or "图片中是什么内容?"
        return DEFAULT_QA_PROMPT.replace("(question)", "").replace("用户问题", f"用户问题: {q}")
    if source == "describe":
        return DEFAULT_DESCRIBE_PROMPT
    return DEFAULT_DESCRIBE_PROMPT


__all__ = [
    "ProviderError",
    "VLMProvider",
    "build_prompt",
    "DEFAULT_DESCRIBE_PROMPT",
    "DEFAULT_QA_PROMPT",
]
