"""Streaming LLM layer (ledger 0204): unified event protocol over OpenAI-compatible
streaming (DeepSeek cloud / Ollama / llama.cpp).

Unified event vocabulary (the "统一口径" rule):
  on_event({"kind": "delta",
            "stage": "content" | "reasoning",   # gemma4 thinks first (reasoning_content)
            "delta": "<new text>",
            "text": "<full accumulated text>"})
  on_event({"kind": "done",
            "text": "...", "reasoning": "...",
            "usage": {"prompt": N, "completion": N},
            "finish": "stop"})

Consumers never touch provider-native formats; reasoning deltas stay separate so
a UI can show thinking or skip it without losing token stream.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

DeltaEvent = dict[str, Any]  # {"kind":"delta","stage":...,"delta":...,"text":...}
EventSink = Callable[[DeltaEvent], Awaitable[None]]


async def stream_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    on_event: EventSink,
    temperature: float = 0.7,
    max_tokens: int = 1200,
    reasoning_effort: Optional[str] = None,
    extra_headers: Optional[dict] = None,
) -> None:
    """Consume an OpenAI-compatible stream and emit unified events.

    Works for DeepSeek (/v1/chat/completions), Ollama, llama.cpp server —
    all expose the same SSE shape: data:{"choices":[{"delta":{content|
    reasoning_content}}]} ... data:[DONE].

    reasoning_effort: 'none' disables thinking on reasoning models (Gemma/…)
    -> fast TTFT; None/'low'/'high' keep thinking.
    """
    import httpx

    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)
    text = ""
    reasoning = ""
    finish = "stop"
    usage: dict = {}
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream("POST", base_url, json=payload,
                                 headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                u = chunk.get("usage")
                if u:
                    usage = u
                choice = (chunk.get("choices") or [{}])[0]
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}
                d_txt = delta.get("content") or ""
                r_txt = delta.get("reasoning_content") or ""
                if d_txt:
                    text += d_txt
                    await on_event({"kind": "delta", "stage": "content",
                                    "delta": d_txt, "text": text})
                if r_txt:
                    reasoning += r_txt
                    await on_event({"kind": "delta", "stage": "reasoning",
                                    "delta": r_txt, "text": reasoning})
    await on_event({
        "kind": "done", "text": text, "reasoning": reasoning,
        "usage": {"prompt": int(usage.get("prompt_tokens", 0)),
                  "completion": int(usage.get("completion_tokens", 0))},
        "finish": finish or "stop",
    })
