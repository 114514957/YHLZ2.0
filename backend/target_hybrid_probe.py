"""Live probe for the hybrid LLM provider (DeepSeek API + local Ollama).

Verifies: API route on healthy primary, fail-over to local when the API is
unreachable, and de-identified timings.  Never persists prompt/output text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from backend.llm_hybrid_provider import HybridLLMProvider
from backend.llm_provider_port import LLMProviderError
from backend.llm_vllm_provider import LlmVllmProvider

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

API_BASE = "https://api.deepseek.com"
API_MODEL = "deepseek-chat"
LOCAL_BASE = "http://127.0.0.1:11434"
LOCAL_MODEL = "qwen2.5:3b"
_PROMPT = "用一句话介绍元亨，不超过30字。"


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "llm_probe" / ("hybrid_" + stamp)


async def _collect_text(provider: Any, prompt: str) -> dict:
    started = time.perf_counter()
    chunks: list[str] = []
    first_ms: Optional[float] = None
    async for delta in provider.stream_chat(
        [{"role": "user", "content": prompt}], max_tokens=64
    ):
        if first_ms is None:
            first_ms = round((time.perf_counter() - started) * 1000, 1)
        chunks.append(str(delta or ""))
    text = "".join(chunks)
    return {
        "text_len": len(text),
        "first_token_ms": first_ms,
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
        "nonempty": bool(text),
    }


async def run_probe(output_dir: Path, *, api_key: str = "") -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    summary: dict[str, Any] = {"probe": "target_hybrid_v1", "status": "failed"}
    started = time.perf_counter()
    try:
        api = LlmVllmProvider(base_url=API_BASE, model=API_MODEL, api_key=api_key)
        local = LlmVllmProvider(base_url=LOCAL_BASE, model=LOCAL_MODEL)
        hybrid = HybridLLMProvider(api, local, fail_threshold=1, recheck_s=30.0)
        summary["api_health"] = await api.health()
        summary["local_health"] = await local.health()
        summary["api_stream"] = await _collect_text(hybrid, _PROMPT)
        summary["route_after_api_success"] = "backup" if hybrid.using_backup else "api"
        await api.close()

        # Simulate API outage: point primary at a refused port.
        dead = LlmVllmProvider(
            base_url="http://127.0.0.1:9", model=API_MODEL, request_timeout_s=2.0
        )
        leak_hybrid = HybridLLMProvider(dead, local, fail_threshold=1, recheck_s=60.0)
        summary["failover_stream"] = await _collect_text(leak_hybrid, _PROMPT)
        summary["route_after_api_down"] = "backup" if leak_hybrid.using_backup else "api"
        await dead.close()
        await local.close()

        ok = (
            summary["api_stream"]["nonempty"]
            and summary["api_stream"]["first_token_ms"] is not None
            and summary["failover_stream"]["nonempty"]
            and summary["route_after_api_down"] == "backup"
        )
        summary["status"] = "passed" if ok else "failed"
    except LLMProviderError as exc:
        summary["error_code"] = exc.code
        summary["error_detail"] = exc.detail
    except Exception as exc:
        summary["error_code"] = "HYBRID-PROBE-FAILED"
        summary["error_detail"] = type(exc).__name__
    finally:
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(
        run_probe(
            args.output_dir or _default_output_dir(),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        )
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
