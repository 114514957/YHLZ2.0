"""Resource policy for memory background work.

Memory is allowed to keep functioning while the dialogue/voice path or an
8GB-GPU fine-tune is active.  The default is deliberately ``disabled`` for
model calls: no constructor may silently start a second Ollama/Qwen process.
Set ``YHLZ_MEMORY_LLM_MODE=local`` explicitly after a fine-tune window to opt
in to an already-running OpenAI-compatible endpoint.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryResourcePolicy:
    mode: str = "disabled"  # disabled | local
    base_url: str = "http://127.0.0.1:8081/v1/chat/completions"
    model: str = "gemma-4-e4b"
    request_timeout_s: float = 45.0
    max_tokens: int = 256
    reason: str = "default-safe"
    # L1 compression only (owner 2026-10-22: the model is local, so the cost of
    # draining the summary backlog is CPU/GPU time, not money). Candidate
    # extraction and adjudication stay off unless `mode == "local"`.
    summary_enabled: bool = False

    @property
    def llm_enabled(self) -> bool:
        return self.mode == "local"


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "active"}


def load_memory_resource_policy(env: dict[str, str] | None = None) -> MemoryResourcePolicy:
    e = os.environ if env is None else env
    requested = str(e.get("YHLZ_MEMORY_LLM_MODE", "disabled") or "disabled").strip().lower()
    if requested not in {"disabled", "local"}:
        requested = "disabled"
    # A training marker always wins.  This is a guard against an old launcher
    # inheriting a stale opt-in from the user's shell.
    if _truthy(e.get("YHLZ_TRAINING_ACTIVE", "")) or _truthy(e.get("YHLZ_FINETUNE_ACTIVE", "")):
        requested = "disabled"
        reason = "training-active"
    elif requested == "local":
        reason = "explicit-local-opt-in"
    else:
        reason = "default-safe"
    try:
        timeout = max(1.0, min(float(e.get("YHLZ_MEMORY_LLM_TIMEOUT", "45")), 300.0))
    except (TypeError, ValueError):
        timeout = 45.0
    try:
        tokens = max(32, min(int(e.get("YHLZ_MEMORY_LLM_MAX_TOKENS", "256")), 1024))
    except (TypeError, ValueError):
        tokens = 256
    # L1 compression may be enabled on its own: the local model costs time, not
    # money, and the summary backlog otherwise grows forever.
    summary_only = (str(e.get("YHLZ_MEMORY_SUMMARY_MODE", "disabled")).strip().lower()
                    == "local")
    return MemoryResourcePolicy(
        mode=requested,
        base_url=str(e.get("YHLZ_MEMORY_LLM_BASE_URL", "http://127.0.0.1:8081/v1/chat/completions")).strip(),
        model=str(e.get("YHLZ_MEMORY_LLM_MODEL", "gemma-4-e4b")).strip() or "gemma-4-e4b",
        request_timeout_s=timeout,
        max_tokens=tokens,
        reason=reason,
        # Independent of `mode`: training still wins, everything else is opt-in.
        summary_enabled=bool(summary_only and reason != "training-active"),
    )


class MemoryWorkDeferred(RuntimeError):
    """A resource pause is not a successful memory operation."""


class DeferredMemoryHooks:
    """No-model rail: preserve raw L1 backlog; never acknowledge truncation."""
    mode = "disabled"

    async def compress(self, dropped, prev=""):
        raise MemoryWorkDeferred("memory model disabled; raw backlog retained")

    async def candidates(self, context):
        return []

    async def adjudicate(self, item):
        raise MemoryWorkDeferred("memory adjudication disabled")



class SummaryOnlyHooks:
    """Local model allowed for L1 compression only.

    Candidate extraction and adjudication stay off: they would call the model
    on every turn and keep the single llama slot busy with speculative work.
    """

    mode = "summary-only"

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def compress(self, dropped, prev=""):
        return await self._inner.compress(dropped, prev=prev)

    async def candidates(self, context):
        return []

    async def adjudicate(self, item):
        raise MemoryWorkDeferred("adjudication disabled; summary-only mode")

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)


def build_memory_hooks(policy: MemoryResourcePolicy | None = None) -> tuple[Any, Any, MemoryResourcePolicy]:
    """Build hooks without starting a process or loading a model."""
    policy = policy or load_memory_resource_policy()
    if not policy.llm_enabled and not policy.summary_enabled:
        hooks = DeferredMemoryHooks()
        return hooks, hooks, policy
    from backend.llm_vllm_provider import LlmVllmProvider
    from backend.target_memory_llm import MemoryLLMService
    provider = LlmVllmProvider(
        base_url=policy.base_url.rsplit("/v1/chat/completions", 1)[0],
        model=policy.model,
        request_timeout_s=policy.request_timeout_s,
    )
    hooks = MemoryLLMService(provider, local=provider, resource_guard=True,
                             max_tokens=policy.max_tokens)
    if policy.llm_enabled:
        return hooks, hooks, policy
    wrapper = SummaryOnlyHooks(hooks)
    return wrapper, wrapper, policy


def semantic_mode(env: dict[str, str] | None = None) -> str:
    """Semantic sidecar mode: ``off`` | ``auto`` | ``on``.

    ``auto`` means "enable only once the background warm-up has actually
    loaded the model"; legacy value ``cpu`` is treated as ``on``. Default is
    ``off`` (owner decision 2026-10-22): the layer must be an explicit opt-in,
    never a silent 67-second load during a turn.
    """
    e = os.environ if env is None else env
    if _truthy(e.get("YHLZ_TRAINING_ACTIVE", "")) or _truthy(e.get("YHLZ_FINETUNE_ACTIVE", "")):
        return "off"
    raw = str(e.get("YHLZ_MEMORY_SEMANTIC_MODE", "off") or "off").strip().lower()
    if raw in {"cpu", "on", "1", "true", "yes"}:
        return "on"
    if raw == "auto":
        return "auto"
    return "off"


def semantic_model_allowed(env: dict[str, str] | None = None) -> bool:
    """Independent CPU semantic opt-in; a training marker always forbids loading.

    Lexical/FTS maintenance must not import torch, download or preload models.
    In ``auto`` mode this answers False until the warm-up thread has finished,
    so no caller ever blocks a turn on a cold model load.
    """
    mode = semantic_mode(env)
    if mode == "off":
        return False
    if mode == "auto":
        from backend.vector_memory import semantic_ready

        return semantic_ready()
    return True
