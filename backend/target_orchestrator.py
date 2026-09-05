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


def build_openai_compatible_llm_turn(
    *,
    base_url: str = "https://api.deepseek.com/v1/chat/completions",
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
    client: Any = None,
    temperature: float = 0.1,
    max_tokens: int = 500,
) -> LLMTurn:
    """Factory for the shared real-model turn path (OpenAI-compatible HTTP).

    Removes per-script httpx boilerplate; the orchestrator and any entry layer
    reuse one tested implementation (ledger 0150: unified adapter path).
    """
    if api_key is None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")

    async def _llm_turn(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {api_key}"}

        async def _post(c: Any) -> dict[str, Any]:
            r = await c.post(base_url, headers=headers, json=payload)
            body = r.json()
            if "choices" not in body:
                raise RuntimeError(json.dumps(body, ensure_ascii=False)[:200])
            return body["choices"][0]["message"]

        if client is not None:
            return await _post(client)
        import httpx

        async with httpx.AsyncClient(timeout=60) as c:
            return await _post(c)

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
    ) -> TurnResult:
        started = time.perf_counter()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *(history or [])[-6:],
            {"role": "user", "content": str(turn_text)},
        ]
        tools = self._export_tools()
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
            content = str(msg.get("content") or "").strip()
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
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                cap = self.registry.get_by_openai_name(name)
                denied = False
                if cap is not None and cap.side_effect and self.approver is not None:
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
                out = self.registry.execute_openai(name, args)
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
            answer = "(本轮未能生成答复)"
        return TurnResult(
            answer=answer,
            tool_uses=tool_uses,
            iterations=iterations,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
