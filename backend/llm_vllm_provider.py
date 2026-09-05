"""Hexagonal driven-adapter: vLLM (OpenAI-compatible) streaming LLM provider.

Talks to a vLLM server (typically running inside WSL on 127.0.0.1:8765) over
HTTP SSE.  A failed or slow endpoint fails closed with stable error codes.
It never saves prompts, outputs, or any business text.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from backend.llm_provider_port import (
    LLM_PORT_VERSION,
    LLMProviderCapabilities,
    LLMProviderError,
    LLMProviderState,
    LLMStreamMetrics,
    _safe_payload,
)

DEFAULT_VLLM_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_VLLM_MODEL = "qwen2.5-3b-awq"


class LlmVllmProvider:
    """SSE streaming adapter for a vLLM OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_VLLM_BASE_URL,
        model: str = DEFAULT_VLLM_MODEL,
        request_timeout_s: float = 60.0,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        strict_models: bool = False,
    ) -> None:
        self.base_url = str(base_url or DEFAULT_VLLM_BASE_URL).rstrip("/")
        self.strict_models = bool(strict_models)
        self.model = str(model or DEFAULT_VLLM_MODEL)
        self.request_timeout_s = float(request_timeout_s)
        self.api_key = str(api_key or "")[:512]
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._headers = headers
        self._client = client or httpx.AsyncClient(
            timeout=self.request_timeout_s, headers=self._headers, transport=transport
        )
        self._owns_client = client is None
        self.state = LLMProviderState.IDLE
        self.last_error_code: Optional[str] = None
        self.last_error_detail: str = ""
        self._metrics = LLMStreamMetrics()
        self._stream_task: Optional[Any] = None

    async def _stream(self, resp: httpx.Response) -> AsyncIterator[str]:
        async for raw in resp.aiter_lines():
            if not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                return
            try:
                obj = json.loads(data)
            except Exception:
                continue
            if obj.get("error"):
                raise LLMProviderError(
                    "LLM-PROVIDER-STREAM-ERROR",
                    str(obj.get("error"))[:160],
                )
            for choice in obj.get("choices", []):
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if content:
                    yield str(content)

    async def stream_chat(
        self,
        messages: list[Dict[str, str]],
        *,
        signal: Optional[Any] = None,
        temperature: float = 0.7,
        max_tokens: int = 256,
        tools: Optional[list[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> AsyncIterator[str]:
        """Yield response text deltas; abort via task cancellation at the HTTP
        layer so the remote engine also stops the decode (provider abort)."""
        if self._stream_task is not None and not self._stream_task.done():
            raise LLMProviderError("LLM-PROVIDER-BUSY", "another stream is in flight")
        if not messages or not messages[-1].get("content"):
            raise LLMProviderError("LLM-PROVIDER-REQUEST-INVALID")

        self.state = LLMProviderState.STREAMING
        self.last_error_code = None
        self.last_error_detail = ""
        self._metrics = LLMStreamMetrics()
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": True,
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        started = time.perf_counter()
        current = asyncio.current_task()
        self._stream_task = current
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.request_timeout_s,
            ) as resp:
                if resp.status_code != 200:
                    raise LLMProviderError(
                        "LLM-PROVIDER-HTTP-" + str(resp.status_code),
                        (await resp.aread())[:160].decode("utf-8", "replace"),
                    )
                tokens = 0
                async for delta in self._stream(resp):
                    if signal is not None and signal.is_cancelled():
                        return
                    if self._metrics.first_token_ms is None:
                        self._metrics = LLMStreamMetrics(
                            first_token_ms=round((time.perf_counter() - started) * 1000, 1),
                            tokens=0,
                        )
                    self._metrics = type(self._metrics)(
                        first_token_ms=self._metrics.first_token_ms,
                        tokens=tokens + 1,
                        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                    )
                    tokens += 1
                    yield delta
                self._metrics = type(self._metrics)(
                    first_token_ms=self._metrics.first_token_ms,
                    tokens=tokens,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                    finish_reason="stop",
                )
        except asyncio.CancelledError:
            raise
        except LLMProviderError:
            self.state = LLMProviderState.FAILED
            self.last_error_code = "LLM-PROVIDER-CONNECT"
            raise
        except httpx.HTTPError as exc:
            self.state = LLMProviderState.FAILED
            self.last_error_code = "LLM-PROVIDER-CONNECT"
            self.last_error_detail = type(exc).__name__
            raise LLMProviderError("LLM-PROVIDER-CONNECT", type(exc).__name__) from exc
        finally:
            self.state = LLMProviderState.IDLE
            if self._stream_task is current:
                self._stream_task = None

    def abort(self, reason: str = "interrupt") -> None:
        task = self._stream_task
        if task is not None and not task.done():
            task.cancel()
        self.state = LLMProviderState.STOPPING

    async def wait_stopped(self, timeout_s: float) -> bool:
        task = self._stream_task
        if task is None or task.done():
            self.state = LLMProviderState.STOPPED
            return True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=float(timeout_s))
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return False
        self.state = LLMProviderState.STOPPED
        return True

    def stop(self, reason: str = "shutdown") -> None:
        self.abort(reason)
        if self._stream_task is not None and not self._stream_task.done():
            self._stream_task.cancel()
        self.state = LLMProviderState.STOPPED

    async def close(self) -> None:
        self.stop("close")
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> dict:
        try:
            resp = await self._client.get(f"{self.base_url}/v1/models", timeout=5.0)
            ok = resp.status_code == 200
            if resp.status_code == 404 and not self.strict_models:
                # Some OpenAI-compatible services (e.g. DeepSeek) expose no
                # /v1/models endpoint but serve chat completions fine.
                ok = True
            models: list[str] = []
            if resp.status_code == 200:
                body = resp.json()
                models = [m.get("id", "") for m in body.get("data", [])]
            return {
                "available": bool(ok),
                "port_version": LLM_PORT_VERSION,
                "model": self.model,
                "models": models[:5],
                "state": self.state.value,
                "error_code": self.last_error_code or None,
                "metrics": self._metrics.as_dict(),
            }
        except Exception as exc:
            return {
                "available": False,
                "port_version": LLM_PORT_VERSION,
                "model": self.model,
                "models": [],
                "state": self.state.value,
                "error_code": "LLM-PROVIDER-HEALTH",
                "error_type": type(exc).__name__,
                "metrics": self._metrics.as_dict(),
            }

    def capabilities(self) -> LLMProviderCapabilities:
        return LLMProviderCapabilities(
            provider_id="vllm-http",
            streaming=True,
            cancel_observable=True,
        )
