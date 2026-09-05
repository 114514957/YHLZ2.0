"""No-device smoke probe for the Qwen ``TTSProviderPort`` adapter.

This executable is intentionally separate from ``main.py``.  It loads one
local model in a short-lived process, exercises the provider protocol, and
writes only redacted metrics under an explicitly supplied artifacts directory.
No microphone, speaker, network request, business data or ``memory`` access is
performed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

# Allow the documented ``python backend\\...py`` form as well as ``-m``.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tts_provider_port import TTSRequest, TTSStreamNormalizer
from backend.tts_qwen_provider import QwenTTSConfig, create_qwen_provider, qwen_capabilities


DEFAULT_TEXT = "你好，这里是元亨。我们正在验证统一语音端口。"
DEFAULT_CANCEL_TEXT = "这是用于验证适配器取消边界的长文本。" * 64


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


async def _collect(session: Any) -> list[Any]:
    return [event async for event in session.audio_events()]


def _event_kinds(events: list[Any]) -> list[str]:
    return [str(event.kind) for event in events]


async def _run(args: argparse.Namespace) -> dict:
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    config = QwenTTSConfig(
        model_dir=Path(args.model_dir),
        speaker=args.speaker,
        language=args.language,
        chunk_size=args.chunk_size,
        max_new_tokens=args.max_new_tokens,
        queue_maxsize=args.queue_maxsize,
        stop_timeout_s=args.stop_timeout_s,
        warmup_text=None if args.no_warmup else args.warmup_text,
    )
    if args.process_isolated:
        from backend.tts_qwen_process import create_qwen_process_provider

        provider = create_qwen_process_provider(
            config,
            worker_id="qwen-process-adapter-probe",
            startup_timeout_s=args.startup_timeout_s,
        )
        capabilities = qwen_capabilities(worker_isolated=True)
    else:
        provider = create_qwen_provider(config, worker_isolated=False, worker_id="qwen-adapter-probe")
        capabilities = qwen_capabilities(worker_isolated=False)
    normal_request = TTSRequest(
        session_id="adapter-probe-session",
        turn_id="adapter-probe-turn",
        speech_id="adapter-probe-normal",
        provider_epoch=0,
        voice_id=args.speaker,
    )
    normal_session = await provider.open(normal_request)
    # Consume and normalize in the same task that receives events.  Replaying
    # a completed stream would measure TTFA from the end of generation.
    normalizer = TTSStreamNormalizer(normal_request, capabilities)
    normal_events: list[Any] = []
    normalizer_error = None
    normalized_count = 0

    async def consume_normal() -> None:
        nonlocal normalizer_error, normalized_count
        async for event in normal_session.audio_events():
            normal_events.append(event)
            if normalizer_error is not None:
                continue
            try:
                normalized_count += len(normalizer.accept(event))
            except Exception as exc:
                normalizer_error = {
                    "type": type(exc).__name__,
                    "code": getattr(exc, "code", None),
                }

    normal_events_task = asyncio.create_task(consume_normal())
    await asyncio.sleep(0)
    await normal_session.push_text(args.text)
    await normal_session.commit_text()
    await normal_events_task
    normal_wait = await normal_session.wait_stopped(args.stop_timeout_s)
    idle_after_normal = await provider.wait_idle_stopped(args.stop_timeout_s)
    normalizer.update_provider_metrics(normal_session.metrics())

    cancel_request = TTSRequest(
        session_id="adapter-probe-session",
        turn_id="adapter-probe-cancel-turn",
        speech_id="adapter-probe-cancel",
        provider_epoch=0,
        voice_id=args.speaker,
    )
    cancel_session = await provider.open(cancel_request)
    cancel_events_task = asyncio.create_task(_collect(cancel_session))
    await asyncio.sleep(0)
    await cancel_session.push_text(args.cancel_text)
    await cancel_session.commit_text()
    await asyncio.sleep(max(0.0, args.cancel_delay_s))
    cancel_requested_at = time.perf_counter()
    await cancel_session.cancel("adapter_probe_cancel")
    cancel_events = await cancel_events_task
    # Consume the terminal STOPPED event before calling the proxy's
    # wait_stopped; doing the reverse would create a harmless duplicate
    # callback and make the stale-event counter look like a provider fault.
    cancel_wait = await cancel_session.wait_stopped(args.stop_timeout_s)
    cancel_idle = await provider.wait_idle_stopped(args.stop_timeout_s)
    provider_metrics = dict(provider.metrics())
    provider_health = dict(provider.health())
    provider.shutdown(timeout_s=args.stop_timeout_s)

    result = {
        "probe_version": "qwen-adapter-v1",
        "timestamp": time.time(),
        "python": sys.version,
        "platform": platform.platform(),
        "device_access": False,
        "offline_mode": True,
        "process_isolated": bool(args.process_isolated),
        "model_dir": str(config.model_dir),
        "config": config.to_dict(),
        "capabilities": capabilities.to_dict(),
        "normal": {
            "text_fingerprint": _fingerprint(args.text),
            "event_kinds": _event_kinds(normal_events),
            "normalized_event_count": normalized_count,
            "normalizer_metrics": normalizer.metrics(state="ready").to_dict(),
            "normalizer_error": normalizer_error,
            "wait_stopped": normal_wait,
            "idle_after_normal": idle_after_normal,
        },
        "cancel": {
            "text_fingerprint": _fingerprint(args.cancel_text),
            "event_kinds": _event_kinds(cancel_events),
            "wait_stopped": cancel_wait,
            "idle_after_cancel": cancel_idle,
            "stop_observation_s": round(time.perf_counter() - cancel_requested_at, 6),
            "done_seen": "DONE" in _event_kinds(cancel_events),
        },
        "provider_metrics_before_shutdown": provider_metrics,
        "provider_health_before_shutdown": provider_health,
        "acceptance": {
            "pcm_contract": normalizer_error is None and normalizer.done,
            "protocol_stop_observed": bool(normal_wait and cancel_wait),
            "text_stream_capability": capabilities.text_stream,
            "c_certification": "not_run",
        },
    }
    _write_json(out_dir / "summary.json", result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--speaker", default="Vivian")
    parser.add_argument("--language", default="chinese")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--cancel-text", default=DEFAULT_CANCEL_TEXT)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--queue-maxsize", type=int, default=32)
    parser.add_argument("--stop-timeout-s", type=float, default=3.0)
    parser.add_argument("--cancel-delay-s", type=float, default=0.5)
    parser.add_argument("--warmup-text", default="你好。")
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--process-isolated", action="store_true")
    parser.add_argument("--startup-timeout-s", type=float, default=90.0)
    return parser.parse_args()


if __name__ == "__main__":
    parsed = _parse_args()
    print(json.dumps(asyncio.run(_run(parsed)), ensure_ascii=False, indent=2))
