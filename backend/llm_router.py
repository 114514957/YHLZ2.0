# -*- coding: utf-8 -*-
"""LLM 路由：**唯一出口**（台账 1239）。任何要调模型的代码都从这里走。

设计取舍（照老爹定论，不自己发明）：
  · 只有 **cloud**（DeepSeek），**没有本地兜底**（1231）——断网/欠费就是真的不可用，
    所以这里**明确抛 `LLMUnavailable`**，让上层给老爹一句人话，而不是静默换模型。
  · 费用不设限，但**每次调用都记账**（1231）。
  · 重试 3 次（0.8/1.6/3.2 秒退避），只在网络/5xx 上重试。

对外三个函数：
    chat(messages, ...)          → OpenAI 兼容响应 dict
    chat_text(messages, ...)     → 只要文本
    chat_stream(messages, ...)   → 逐块 yield 文本增量
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterator, Optional

from backend.llm_endpoint import endpoint, is_cloud, provider
from backend.llm_usage import LLMUnavailable, record

__all__ = ["chat", "chat_text", "chat_stream", "LLMUnavailable", "health"]

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(body: dict, *, timeout: int, stream: bool) -> Any:
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        ep_base_url(), data=data,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + ep_key()})
    return _OPENER.open(req, timeout=timeout)


def ep_base_url() -> str:
    return endpoint()["base_url"]


def ep_key() -> str:
    return endpoint()["api_key"]


def _build(messages: list[dict], *, tools=None, temperature=None, max_tokens=None,
           stream: bool = False, tool_choice="auto") -> dict:
    ep = endpoint()
    body: dict[str, Any] = {
        "model": ep["model"],
        "messages": messages,
        "stream": bool(stream),
        "temperature": ep["temperature"] if temperature is None else float(temperature),
        "max_tokens": ep["max_tokens"] if max_tokens is None else int(max_tokens),
    }
    if tools:
        body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
    if stream:
        # 让服务端在最后一块带上 usage，记账才准
        body["stream_options"] = {"include_usage": True}
    return body


def _once(body: dict, timeout: int) -> tuple[dict, float]:
    t0 = time.time()
    with _post(body, timeout=timeout, stream=False) as r:
        payload = json.loads(r.read().decode())
    sec = time.time() - t0
    if "choices" not in payload:
        raise RuntimeError("响应异常：%s" % str(payload)[:160])
    return payload, sec


def chat(messages: list[dict], *, tools: Optional[list] = None,
         temperature: Optional[float] = None, max_tokens: Optional[int] = None,
         channel: str = "", retries: int = 3, timeout: Optional[int] = None) -> dict:
    """一次对话（带重试与记账）。失败抛 `LLMUnavailable`。"""
    ep = endpoint()
    body = _build(messages, tools=tools, temperature=temperature,
                  max_tokens=max_tokens)
    to = int(timeout or ep["timeout_s"])
    last = None
    t_all = time.time()
    for attempt in range(max(1, retries)):
        try:
            payload, sec = _once(body, to)
            u = payload.get("usage") or {}
            record(channel=channel, model=ep["model"], provider=ep["provider"],
                   prompt_tokens=int(u.get("prompt_tokens") or 0),
                   completion_tokens=int(u.get("completion_tokens") or 0),
                   seconds=sec, retries=attempt, ok=True)
            return payload
        except urllib.error.HTTPError as ex:
            last = ex
            if 400 <= int(getattr(ex, "code", 0)) < 500 and int(ex.code) != 429:
                break   # 4xx（除限流）重试没意义
        except Exception as ex:  # noqa: BLE001
            last = ex
        if attempt + 1 < max(1, retries):
            time.sleep(0.8 * (2 ** attempt))
    record(channel=channel, model=ep["model"], provider=ep["provider"],
           seconds=time.time() - t_all, retries=max(0, retries - 1), ok=False,
           error="%s: %s" % (type(last).__name__, last))
    raise LLMUnavailable("模型不可用（%s，已重试 %d 次）：%s: %s"
                         % (ep["model"], retries, type(last).__name__,
                            str(last)[:120]))


def chat_text(messages: list[dict], **kw) -> str:
    kw.pop("tools", None)
    payload = chat(messages, **kw)
    return str(((payload.get("choices") or [{}])[0].get("message") or {})
               .get("content") or "")


def chat_stream(messages: list[dict], *, tools: Optional[list] = None,
                temperature: Optional[float] = None,
                max_tokens: Optional[int] = None, channel: str = "",
                timeout: Optional[int] = None) -> Iterator[dict]:
    """流式：逐块 yield `{"type":"delta","text":...}`，最后 yield 一条
    `{"type":"end","finish_reason":...,"usage":...}`。失败抛 `LLMUnavailable`。

    注意：流式**不重试**——已经吐字了再重试会重复输出。失败由上层兜。
    """
    ep = endpoint()
    body = _build(messages, tools=tools, temperature=temperature,
                  max_tokens=max_tokens, stream=True)
    to = int(timeout or ep["timeout_s"])
    t0 = time.time()
    usage: dict = {}
    finish = ""
    try:
        with _post(body, timeout=to, stream=True) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except Exception:  # noqa: BLE001
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                for ch in obj.get("choices") or []:
                    delta = ch.get("delta") or {}
                    if delta.get("content"):
                        yield {"type": "delta", "text": delta["content"]}
                    if ch.get("finish_reason"):
                        finish = str(ch["finish_reason"])
        record(channel=channel, model=ep["model"], provider=ep["provider"],
               prompt_tokens=int(usage.get("prompt_tokens") or 0),
               completion_tokens=int(usage.get("completion_tokens") or 0),
               seconds=time.time() - t0, ok=True)
        yield {"type": "end", "finish_reason": finish, "usage": usage}
    except Exception as ex:  # noqa: BLE001
        record(channel=channel, model=ep["model"], provider=ep["provider"],
               seconds=time.time() - t0, ok=False,
               error="%s: %s" % (type(ex).__name__, ex))
        raise LLMUnavailable("流式调用失败：%s: %s" % (type(ex).__name__, str(ex)[:120]))


def health() -> dict:
    """给工作台/自检用：不真正发请求，只看解析结果。"""
    ep = endpoint()
    return {"provider": ep["provider"], "model": ep["model"],
            "base_url": ep["base_url"], "has_key": bool(ep["api_key"]),
            "cloud": is_cloud(), "provider_name": provider()}
