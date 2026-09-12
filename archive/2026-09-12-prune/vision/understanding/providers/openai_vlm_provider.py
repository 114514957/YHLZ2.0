"""
YHLZ Vision Understanding V1.0 - OpenAI 兼容 VLM Provider

职责:
    - 封装 OpenAI 兼容协议的 VLM 服务 (如 DashScope Qwen-VL / OpenAI GPT-4V)
    - 图片以 base64 编码发送
    - 解析 JSON 结构化输出 (scene_type / summary / description / subjects)

设计原则:
    - 懒加载 (首次调用时创建客户端, 不在 import 时加载)
    - 无 API key 时 is_available=False (不抛异常)
    - 网络 / 解析失败转换为 ProviderError
    - 测试环境用 YHLZ_UNDERSTANDING_TEST_MODE=true 跳过
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

from backend.vision.understanding.interface import UnderstandingOptions
from backend.vision.understanding.providers.base import ProviderError, VLMProvider, build_prompt
from backend.vision.understanding.schema import (
    SceneType,
    SubjectPosition,
    UnderstandingResult,
    UnderstandingSubject,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleVLMProvider(VLMProvider):
    """OpenAI 兼容 VLM Provider

    用法:
        provider = OpenAICompatibleVLMProvider(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-xxx",
            model="qwen-vl-plus",
        )
        if provider.is_available():
            result = provider.understand(image)

    特性:
        - 懒加载 (首次 understand 时创建客户端)
        - 无 API key / 未安装 openai 库时 is_available()=False
        - 输出 JSON 解析失败时自动降级 (整段文本作为 description)
    """

    name: str = "openai_vlm"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
        use_config: bool = True,
        auto_load: bool = False,
    ):
        # 默认从 config 读取 (DashScope Qwen-VL); use_config=False 时完全隔离测试
        try:
            from backend.config import config
            cfg_base = getattr(config, "understanding_vlm_base_url", "") or ""
            cfg_key = getattr(config, "understanding_vlm_api_key", "") or ""
            cfg_model = getattr(config, "understanding_vlm_model", "") or ""
            dashscope_key = getattr(config, "dashscope_api_key", "") or ""
            vl_model = getattr(config, "vl_model", "qwen-vl-plus") or "qwen-vl-plus"
        except Exception:
            cfg_base = cfg_key = cfg_model = ""
            dashscope_key = ""
            vl_model = "qwen-vl-plus"
        self._base_url = base_url or (
            cfg_base if use_config else ""
        ) or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self._api_key = api_key or (
            (cfg_key or dashscope_key) if use_config else ""
        )
        self._model = model or (
            cfg_model if use_config else ""
        ) or vl_model
        self._timeout = timeout
        self._client: Any = None
        self._client_error: Optional[str] = None

    def is_available(self) -> bool:
        """检测 VLM 服务是否可用 (有 API key + openai 库)"""
        if not self._api_key:
            return False
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_client(self) -> Any:
        """懒加载 OpenAI 客户端"""
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout=self._timeout,
            )
            logger.info(
                f"OpenAI VLM 客户端已创建 (model={self._model}, base_url={self._base_url})"
            )
            return self._client
        except Exception as e:
            self._client_error = f"OpenAI 客户端创建失败: {type(e).__name__}: {e}"
            logger.error(self._client_error, exc_info=True)
            raise ProviderError(self._client_error) from e

    def understand(
        self,
        image: Any,
        prompt: Optional[str] = None,
        options: Optional[UnderstandingOptions] = None,
    ) -> UnderstandingResult:
        """执行视觉理解

        Raises:
            ProviderError: 服务不可用 / 网络失败 / 解析失败
        """
        if image is None:
            raise ProviderError("输入图像为空")
        if not self.is_available():
            raise ProviderError("VLM 服务不可用 (未配置 API key 或未安装 openai 库)")

        opts = options or UnderstandingOptions()
        client = self._ensure_client()

        # 图片 → base64 (data URL)
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", image)
            if not ok:
                raise ProviderError("图片编码失败 (cv2.imencode)")
            b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"图片编码失败: {type(e).__name__}: {e}") from e

        # 构造提示词: 自定义优先, 否则按来源内置模板
        effective_prompt = prompt or build_prompt(
            "qa" if (opts.question and not prompt) else "describe",
            opts.question,
        )
        if opts.question:
            effective_prompt += f"\n\n用户问题: {opts.question}"

        # 请求 VLM
        try:
            resp = client.chat.completions.create(
                model=self._model,
                temperature=opts.temperature,
                max_tokens=opts.max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                            {"type": "text", "text": effective_prompt},
                        ],
                    }
                ],
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise ProviderError("VLM 返回空内容")
            return self._parse_result(content, opts)
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"VLM 请求失败: {type(e).__name__}: {e}") from e

    def _parse_result(
        self,
        content: str,
        options: Optional[UnderstandingOptions] = None,
    ) -> UnderstandingResult:
        """解析 VLM 输出为 UnderstandingResult

        VLM 按提示词要求返回 JSON, 但可能附带 markdown 代码块 / 前后说明文字。
        解析策略:
            1. 提取首个 { ... } JSON 块
            2. 解析失败 → 降级: 整段文本作为 description, scene_type=unknown
        """
        opts = options or UnderstandingOptions()
        data = self._extract_json(content)
        source = "qa" if opts.question else "vlm"

        if data is None:
            logger.warning("VLM 输出非 JSON, 降级为纯文本 description")
            return UnderstandingResult.create_ok(
                source=source,
                scene_type=SceneType.UNKNOWN.value,
                description=content,
                summary=content[:100],
                confidence=0.5,
                metadata={"provider": self.name, "raw": True},
            )

        scene_type = str(data.get("scene_type", SceneType.UNKNOWN.value))
        if scene_type not in {s.value for s in SceneType}:
            scene_type = SceneType.UNKNOWN.value

        subjects: List[UnderstandingSubject] = []
        for item in data.get("subjects", []) or []:
            if not isinstance(item, dict):
                continue
            pos = item.get("position")
            subjects.append(UnderstandingSubject(
                name=str(item.get("name", "")),
                category=str(item.get("category", "")),
                position=SubjectPosition.from_dict(pos) if isinstance(pos, dict) else None,
                confidence=float(item.get("confidence", 0.5)),
            ))

        return UnderstandingResult.create_ok(
            source=source,
            scene_type=scene_type,
            description=str(data.get("description", "")),
            summary=str(data.get("summary", "")),
            subjects=subjects,
            confidence=float(data.get("confidence", 0.5)),
            metadata={"provider": self.name, "model": self._model},
        )

    @staticmethod
    def _extract_json(content: str) -> Optional[Dict[str, Any]]:
        """从文本中提取首个 JSON 对象 (兼容 markdown 代码块)"""
        text = content.strip()
        # 去掉 markdown 代码块标记
        if text.startswith("```"):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        # 直接解析
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        # 提取首个 {...} 块
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        return None

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["model"] = self._model
        info["base_url"] = self._base_url
        info["client_error"] = self._client_error
        info["has_api_key"] = bool(self._api_key)
        return info


__all__ = ["OpenAICompatibleVLMProvider"]
