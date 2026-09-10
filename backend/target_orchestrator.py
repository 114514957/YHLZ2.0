"""Turn Orchestrator (ADR-007 pipeline core): LLM tool-decision loop.

Event(text) -> LLM decide (tools exposed) -> CapabilityRegistry gated
execution -> results appended -> LLM finalize.  Provider-agnostic: the caller
injects an async ``llm_turn`` callable so this component stays testable with
fakes and runnable against any OpenAI-compatible endpoint (DeepSeek/Ollama).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

LLMTurn = Callable[
    [list[dict[str, Any]], list[dict[str, Any]]],
    Awaitable[dict[str, Any]],
]

Approver = Callable[[dict[str, Any]], Awaitable[bool]]


def _strip_leaked_toolcall(content: str) -> str:
    """Remove provider-native tool-call text leaked when no tool schema was
    given (e.g. '<|tool_call>call:memory_recall{...}<tool_call|>')."""
    import re

    c = str(content or "")
    if "<|tool_call" in c or "<tool_call" in c:
        c = re.sub(r"<\|?tool_call.*?(\|>|>)", " ", c, flags=re.S)
        c = re.sub(r"<\|?tool_call.*", " ", c, flags=re.S)
    return c.strip()


def _to_data_url(src: str) -> str:
    """Local image path -> data URI; http(s)/data URLs pass through."""
    import base64
    import pathlib

    s = str(src)
    if s.startswith(("http://", "https://", "data:")):
        return s
    p = pathlib.Path(s)
    if not p.exists():
        return ""
    ext = p.suffix.lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif",
            "webp": "webp", "bmp": "bmp"}.get(ext, "png")
    try:
        b = base64.b64encode(p.read_bytes()).decode()
    except Exception:
        return ""
    return f"data:image/{mime};base64,{b}"


def build_openai_compatible_llm_turn(
    *,
    base_url: str = "https://api.deepseek.com/v1/chat/completions",
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
    client: Any = None,
    temperature: float = 0.1,
    max_tokens: int = 500,
    fallback_base_url: Optional[str] = None,
    fallback_model: Optional[str] = None,
    on_delta: Optional[Callable[[str], None]] = None,
    reasoning_effort: Optional[str] = None,
) -> LLMTurn:
    """Factory for the shared real-model turn path (OpenAI-compatible HTTP).

    Dual-rail (ledger 0168): if the primary provider is unreachable, retry the
    same payload on the local fallback (Ollama OpenAI-compatible), so the
    daemon keeps serving when the cloud goes down.

    ``on_delta``: when given, the provider call becomes token-streaming and
    every content delta is forwarded to the callback as it arrives (live
    typing). Reasoning deltas are skipped. Tool rounds stay usable: the
    streamed result still carries aggregated ``tool_calls``.

    ``reasoning_effort``: only applied to the primary provider (Gemma llama.cpp
    knows none/low/medium/high); stripped on fallback so Qwen/Ollama never see
    it. ``"none"`` = 极速 (no thinking, fast TTFT), ``"medium"`` = 思考模式.
    """
    if api_key is None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
    fallback_url = fallback_base_url
    fb_model = fallback_model

    async def _llm_turn(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if on_delta is not None:
            from backend.llm_stream import stream_openai_compatible

            async def _try_stream(url: str, key: str) -> dict[str, Any]:
                payload: dict[str, Any] = {"model": model}
                if url.startswith("http://127.0.0.1:11434"):
                    payload = {"model": fb_model or model}
                async def _on(ev: dict[str, Any]) -> None:
                    if ev["kind"] == "delta" and ev["stage"] == "content":
                        on_delta(ev["delta"])
                return await stream_openai_compatible(
                    base_url=url, api_key=key, model=payload["model"],
                    messages=messages, on_event=_on,
                    temperature=float(temperature),
                    max_tokens=int(max_tokens),
                    reasoning_effort=reasoning_effort,
                )

            try:
                return await _try_stream(base_url, api_key)
            except Exception:
                if fallback_url:
                    return await _try_stream(fallback_url, "")
                raise

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        async def _post(c: Any, url: str, hdrs: dict, body: dict) -> dict[str, Any]:
            r = await c.post(url, headers=hdrs, json=body)
            r.raise_for_status()
            out = r.json()
            if "choices" not in out:
                raise RuntimeError(json.dumps(out, ensure_ascii=False)[:200])
            return out["choices"][0]["message"]

        import httpx

        async with httpx.AsyncClient(timeout=60) as c:
            try:
                return await _post(c, base_url, headers, payload)
            except Exception:
                if fallback_url:
                    fb_payload = dict(payload)
                    fb_payload["model"] = fb_model or fb_payload["model"]
                    fb_payload.pop("reasoning_effort", None)
                    try:
                        return await _post(c, fallback_url, {}, fb_payload)
                    except Exception as exc2:
                        raise RuntimeError(
                            f"dual-rail failed: {type(exc2).__name__}") from exc2
                raise

    return _llm_turn


@dataclass(slots=True)
class ToolUse:
    name: str
    arguments: dict[str, Any]
    ok: bool
    output: Optional[str] = None
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass(slots=True)
class TurnResult:
    answer: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    iterations: int = 0
    elapsed_ms: float = 0.0


class TurnOrchestrator:
    """ReAct-lite loop: LLM -> tool calls -> gated registry execution -> loop.

    ``max_tool_rounds`` bounds the number of tool rounds; the final round is
    forced to answer without tools (no runaway loops).
    """

    def __init__(
        self,
        registry: Any,
        *,
        max_tool_rounds: int = 2,
        max_tokens: int = 400,
        temperature: float = 0.2,
        approver: Optional[Approver] = None,
    ) -> None:
        self.registry = registry
        self.max_tool_rounds = max(1, int(max_tool_rounds))
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.approver = approver

    def _export_tools(self) -> list[dict]:
        return self.registry.export_openai_tools()

    async def run(
        self,
        turn_text: str,
        system_prompt: str,
        llm_turn: LLMTurn,
        history: Optional[list[dict[str, Any]]] = None,
        with_tools: bool = True,
        early_context: str = "",
        images: Optional[list[str]] = None,
        allowed_tools: Optional[set] = None,
    ) -> TurnResult:
        started = time.perf_counter()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if early_context:
            messages.append({"role": "system",
                             "content": str(early_context)[:1500]})
        user_content: Any = str(turn_text)
        if images:
            parts: list[dict[str, Any]] = [
                {"type": "text", "text": str(turn_text) or "（看图）"}]
            for p in images:
                url = _to_data_url(p)
                if url:
                    parts.append({"type": "image_url",
                                  "image_url": {"url": url}})
            if len(parts) > 1:
                user_content = parts
        messages += [
            *(history or [])[-6:],
            {"role": "user", "content": user_content},
        ]
        # with_tools=False (casual chat): no tool schema at all — keeps the
        # model in persona voice (ledger 0215: 27-tool schema nudges Gemma
        # into "assistant executing tasks" framing, killing persona).
        tools = self._export_tools() if with_tools else []
        if allowed_tools is not None:
            tools = [t for t in tools
                     if t.get("function", {}).get("name") in allowed_tools]
        tool_uses: list[ToolUse] = []
        answer = ""
        iterations = 0
        for _ in range(self.max_tool_rounds + 1):
            iterations += 1
            with_tools = iterations <= self.max_tool_rounds and bool(tools)
            if not with_tools and iterations > 1:
                messages = messages + [
                    {"role": "system",
                     "content": "这是最后一轮：请直接根据上面已有的工具结果回答用户，不要再次调用或提及检索。"}
                ]
            msg = await llm_turn(messages, tools if with_tools else [])
            content = _strip_leaked_toolcall(str(msg.get("content") or ""))
            tcs = msg.get("tool_calls") or []
            if not tcs:
                cut = content.find("<tool_calls>")
                if cut >= 0:
                    content = content[:cut].strip()
                answer = content
                break
            messages.append(
                {"role": "assistant", "content": content or None,
                 "tool_calls": tcs}
            )
            for tc in tcs:
                name = tc["function"]["name"]
                if allowed_tools is not None and name not in allowed_tools:
                    messages.append({
                        "role": "tool", "tool_call_id": tc["id"],
                        "name": name,
                        "content": json.dumps(
                            {"error": "tool not allowed in this channel"})})
                    continue
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                cap = self.registry.get_by_openai_name(name)
                denied = False
                needs_approval = (
                    cap is not None and cap.side_effect and self.approver is not None
                    and any(r.endswith(".approval") for r in cap.requires)
                )
                if needs_approval:
                    t0 = time.perf_counter()
                    granted = await self.approver(
                        {"name": cap.name, "args": dict(args),
                         "risk": cap.risk}
                    )
                    if not granted:
                        denied = True
                        tool_uses.append(
                            ToolUse(
                                name=name, arguments=args, ok=False,
                                error="user denied approval",
                                elapsed_ms=round(
                                    (time.perf_counter() - t0) * 1000, 1),
                            )
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": name,
                                "content": '{"error": "user denied approval"}',
                            }
                        )
                if denied:
                    continue
                t0 = time.perf_counter()
                out = await self.registry.execute_openai_async(name, args)
                use = ToolUse(
                    name=name,
                    arguments=args,
                    ok=bool(out.get("ok")),
                    output=str(out.get("output") or "") if out.get("ok") else None,
                    error=str(out.get("error") or "") if not out.get("ok") else "",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
                )
                tool_uses.append(use)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": name,
                        "content": (
                            use.output
                            if use.ok
                            else json.dumps({"error": use.error}, ensure_ascii=False)
                        )[:4000],
                    }
                )
        if not answer:
            # one recovery attempt: force a direct, tool-free answer (guards
            # against empty final content, e.g. reasoning eating all tokens)
            try:
                retry_msgs = messages + [
                    {"role": "system",
                     "content": "请直接用中文作答，不要调用任何工具，"
                                "不要输出思考过程。"}]
                msg2 = await llm_turn(retry_msgs, [])
                answer = str(msg2.get("content") or "").strip()
            except Exception:
                answer = ""
        if not answer:
            answer = "(本轮未能生成答复)"
        return TurnResult(
            answer=answer,
            tool_uses=tool_uses,
            iterations=iterations,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
