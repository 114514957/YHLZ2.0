"""Composition helpers for the hybrid LLM pipeline (API primary + local backup).

Keeps endpoint wiring out of the voice chain; the chain only ever sees the
``LLMReasoner`` bound to a conforming ``LLMProviderPort``.  Defaults match the
production hybrid decision (ledger 0114): DeepSeek API primary, local Ollama
``qwen2.5:3b`` backup on 127.0.0.1:11434.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from backend.env_loader import ensure_env_loaded
from backend.llm_hybrid_provider import HybridLLMProvider
from backend.llm_reasoner import LLMReasoner
from backend.llm_vllm_provider import LlmVllmProvider

API_BASE_URL = "https://api.deepseek.com"
API_MODEL = "deepseek-chat"
LOCAL_BASE_URL = "http://127.0.0.1:11434"
LOCAL_MODEL = "qwen2.5:3b"


def create_hybrid_llm_provider(
    *,
    api_key: Optional[str] = None,
    api_base_url: str = API_BASE_URL,
    api_model: str = API_MODEL,
    local_base_url: str = LOCAL_BASE_URL,
    local_model: str = LOCAL_MODEL,
    probe_timeout_s: float = 2.0,
    recheck_s: float = 60.0,
    fail_threshold: int = 2,
) -> HybridLLMProvider:
    """Build the API-first hybrid provider with production defaults."""
    ensure_env_loaded()
    key = api_key
    if key is None:
        key = os.getenv("DEEPSEEK_API_KEY", "")
    primary = LlmVllmProvider(
        base_url=api_base_url,
        model=api_model,
        api_key=key,
        request_timeout_s=60.0,
    )
    backup = LlmVllmProvider(
        base_url=local_base_url,
        model=local_model,
        request_timeout_s=60.0,
    )
    return HybridLLMProvider(
        primary,
        backup,
        probe_timeout_s=probe_timeout_s,
        recheck_s=recheck_s,
        fail_threshold=fail_threshold,
    )


def create_hybrid_reasoner(
    *,
    system_prompt: str = "先进始于计算，元亨开拓未来",
    temperature: float = 0.7,
    max_tokens: int = 256,
    provider: Optional[HybridLLMProvider] = None,
    memory_service: Any = None,
) -> LLMReasoner:
    """Build the reasoner used by the target composition root."""
    return LLMReasoner(
        provider or create_hybrid_llm_provider(),
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        memory_service=memory_service,
    )
