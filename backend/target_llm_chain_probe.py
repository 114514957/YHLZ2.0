"""Live composition probe: hybrid LLM + Qwen1.7B TTS through the target chain.

Runs the target composition root with the production hybrid reasoner and a
real Qwen1.7B TTS provider (worker process, no audio device).  Injects one
wake-word text turn ("元亨，…") and observes kernel events only as counts —
no prompt, transcript, reply or PCM is persisted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from backend.llm_hybrid_compose import create_hybrid_reasoner
from backend.session_kernel import ProviderCapabilities


def _fingerprint(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
from backend.target_composition import TargetVoiceComposition, TargetVoiceCompositionConfig
from backend.tts_qwen_provider import QwenTTSConfig

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MODEL_DIR = _PROJECT_ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
_PROBE_TEXT = "元亨，能听到吗"


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "llm_chain_probe" / ("chain_" + stamp)


async def run_probe(
    output_dir: Path,
    *,
    model_dir: Path = _DEFAULT_MODEL_DIR,
    probe_text: str = _PROBE_TEXT,
    max_tokens: int = 64,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    reasoner = create_hybrid_reasoner(max_tokens=max_tokens)
    composition = TargetVoiceComposition(
        TargetVoiceCompositionConfig(qwen=QwenTTSConfig(model_dir=model_dir)),
        reasoner=reasoner,
    )
    # Memory batch-1 wiring: turn observer -> cloud-candidate/local-screen ->
    # cloud adjudication -> L2 store (ledger 0137/0138).
    from backend.target_memory import TargetMemoryService
    from backend.target_memory_llm import MemoryLLMService

    memory = TargetMemoryService()
    memory.set_llm_hooks(MemoryLLMService(reasoner.provider))
    memory_events: list[dict] = []
    memory_done = asyncio.Event()

    async def on_turn(turn_id: str, user_text: str, outcome: Any) -> None:
        try:
            if outcome is None or getattr(outcome, "status", None) != "completed":
                return
            cands = await memory.submit_candidates(
                text=str(getattr(outcome, "text", "") or ""),
                transcript=str(user_text),
                evidence_ref=f"ledger-{int(time.time())}",
            )
            adjudicated = await memory.adjudicate_async(cands)
            memory_events.append(
                {
                    "turn_id": str(turn_id),
                    "candidate_count": len(adjudicated),
                    "final_items": [
                        {
                            "id": i.id,
                            "importance": i.importance,
                            "status": i.status,
                            "type": i.type,
                            "summary_len": len(i.summary),
                            "fingerprint": _fingerprint(i.summary)[:16],
                        }
                        for i in adjudicated
                    ],
                }
            )
        except Exception as exc:
            memory_events.append({"turn_id": str(turn_id), "error": type(exc).__name__, "detail": str(exc)[:120]})
        finally:
            memory_done.set()

    composition.add_turn_observer(on_turn)
    chain_memory = memory
    summary: dict[str, Any] = {
        "probe": "target_llm_chain_v1",
        "status": "failed",
        "prompts_persisted": False,
        "reply_persisted": False,
        "memory_written": False,
        "audio_persisted": False,
    }
    started = time.perf_counter()
    try:
        composition.chain.start(
            ProviderCapabilities(continuous_capture=True)
        )
        submission = await composition.chain.submit_transcript(probe_text, source="probe")
        if submission.task is None:
            raise RuntimeError("wake gate did not accept probe transcript")
        outcome = await submission.task
        kernel_events = composition.kernel.recent_events(512)
        kinds = [str(e.get("kind", "")) for e in kernel_events]
        from collections import Counter

        counts = Counter(kinds)
        await composition.chain.wait_idle()
        try:
            await asyncio.wait_for(memory_done.wait(), timeout=25.0)
        except asyncio.TimeoutError:
            memory_events.append({"timeout": True})
        summary.update(
            {
                "status": "passed" if outcome.status == "completed" else "failed",
                "outcome": {
                    "status": outcome.status,
                    "error_code": outcome.error_code,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                },
                "event_counts": dict(sorted(counts.items())),
                "token_events": int(counts.get("TOKEN", 0)),
                "turn": composition.chain.kernel.snapshot().get("active_turn_state"),
                "hybrid_using_backup": bool(reasoner.provider.using_backup),
                "reasoner_first_token_ms": reasoner.last_first_token_ms,
                "reasoner_tokens": reasoner.last_tokens,
                "tts_metrics": composition.chain.snapshot().get("ports", {}).get("tts_provider_metrics"),
                "memory_events": memory_events,
                "memory_health": chain_memory.health(),
            }
        )
    except Exception as exc:
        summary["error_code"] = getattr(exc, "code", None) or "LLM-CHAIN-PROBE-FAILED"
        summary["error_detail"] = type(exc).__name__
        summary["detail"] = str(exc)[:160]
    finally:
        try:
            await composition.shutdown("llm_chain_probe_complete")
        except Exception as shutdown_exc:
            summary["shutdown_error"] = type(shutdown_exc).__name__
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=_DEFAULT_MODEL_DIR)
    parser.add_argument("--probe-text", default=_PROBE_TEXT)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(
        run_probe(
            args.output_dir or _default_output_dir(),
            model_dir=args.model_dir,
            probe_text=args.probe_text,
            max_tokens=args.max_tokens,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
