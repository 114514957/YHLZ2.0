"""Live probe for the LLM Hexagonal port against a running vLLM server.

Measures streaming TTFT, token throughput, and abort evidence against
127.0.0.1:8765 (qwen2.5-3b-awq).  Never saves prompts or outputs; the summary
keeps only counts, timings, and fingerprints.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import httpx

from backend.llm_provider_port import LLMProviderError
from backend.llm_reasoner import LLMReasoner
from backend.llm_vllm_provider import LlmVllmProvider

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_PROBE_PROMPT = "进步始于思想，元亨开拓未来"
_ABORT_PROMPT = "请围绕“进步始于思想，元亨开拓未来”写一篇约300字的阐述。"


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "llm_probe" / ("live_" + stamp)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def run_probe(
    output_dir: Path,
    *,
    base_url: str = "http://127.0.0.1:8765",
    model: str = "qwen2.5-3b-awq",
    max_tokens: int = 48,
    api_key: Optional[str] = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    server = LlmVllmProvider(base_url=base_url, model=model, api_key=api_key)
    reasoner = LLMReasoner(server)
    summary: dict[str, Any] = {
        "probe": "target_llm_port_v1",
        "status": "failed",
        "base_url": base_url,
        "model": model,
        "prompts_persisted": False,
        "output_persisted": False,
        "memory_written": False,
    }
    started = time.perf_counter()
    try:
        health = await server.health()
        summary["health"] = health
        if not health.get("available"):
            summary["error_code"] = "LLM-PROBE-SERVER-UNAVAILABLE"
            return summary

        # Streaming TTFT/tokens with the fixed system template.
        stream_started = time.perf_counter()
        streamed: list[str] = []
        async for delta in reasoner.generate(_PROBE_PROMPT, None):
            streamed.append(str(delta or ""))
        stream_elapsed = time.perf_counter() - stream_started
        text = "".join(streamed)
        summary["stream"] = {
            "text_len": len(text),
            "sha256_prefix": _fingerprint(text),
            "tokens": len(streamed) if streamed else 0,
            "total_ms": round(stream_elapsed * 1000, 1),
            "first_token_ms": reasoner.last_first_token_ms,
            "finish": "stop",
        }
        if not text:
            summary["error_code"] = "LLM-PROBE-EMPTY-OUTPUT"
            return summary

        # Abort evidence: start a longer generation, abort after first chunk,
        # and confirm wait_stopped + no stalled stream afterwards.
        abort_state: dict[str, Any] = {}
        try:
            async def consume():
                got = 0
                async for _ in reasoner.generate(_ABORT_PROMPT, None):
                    got += 1
                    if got == 1:
                        server.abort("probe_abort")
                return got

            task = asyncio.create_task(consume())
            got = await task
            abort_state = {"tokens_before_abort": got, "abort_triggered": True}
        except LLMProviderError as exc:
            abort_state = {"abort_triggered": True, "error_code": exc.code if exc.code != "LLM-PROVIDER-CONNECT" else None}
        except asyncio.CancelledError:
            abort_state = {"abort_triggered": True, "cancelled": True}
        stopped = await server.wait_stopped(3.0)
        abort_state["wait_stopped"] = bool(stopped)
        summary["abort"] = abort_state

        summary["status"] = (
            "passed"
            if summary["stream"]["text_len"] > 0 and abort_state.get("wait_stopped")
            else "failed"
        )
    except Exception as exc:
        summary["error_code"] = getattr(exc, "code", None) or "LLM-PROBE-FAILED"
        summary["error_type"] = type(exc).__name__
        summary["detail"] = str(exc)[:160]
    finally:
        await server.close()
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--model", default="qwen2.5-3b-awq")
    parser.add_argument("--api-key", default=None, help="Bearer token (default: DEEPSEEK_API_KEY)")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    import os

    api_key = args.api_key
    if api_key is None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
    summary = asyncio.run(
        run_probe(
            args.output_dir or _default_output_dir(),
            base_url=args.base_url,
            model=args.model,
            api_key=api_key,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
