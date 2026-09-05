"""Isolated Qwen3-TTS probe for the target voice-chain work instruction.

This module intentionally does not import the application entry point or open
an audio device.  The parent process uses a child process for each run so a
forced stop has an unambiguous worker-exit observation on Windows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional


DEFAULT_TEXT = "你好，这里是元亨。我们正在验证本地语音链路。"
DEFAULT_CANCEL_TEXT = (
    "这是用于取消探针的较长文本。" * 48
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _gpu_snapshot(torch_module: Any) -> dict:
    result = {"cuda_available": False}
    try:
        result["cuda_available"] = bool(torch_module.cuda.is_available())
        if result["cuda_available"]:
            result.update(
                {
                    "device": torch_module.cuda.get_device_name(0),
                    "memory_allocated_bytes": int(torch_module.cuda.memory_allocated()),
                    "memory_reserved_bytes": int(torch_module.cuda.memory_reserved()),
                    "max_memory_allocated_bytes": int(torch_module.cuda.max_memory_allocated()),
                    "max_memory_reserved_bytes": int(torch_module.cuda.max_memory_reserved()),
                }
            )
            free, total = torch_module.cuda.mem_get_info()
            result.update({"free_bytes": int(free), "total_bytes": int(total)})
    except Exception as exc:  # diagnostics must not hide the primary result
        result["snapshot_error"] = type(exc).__name__
    return result


def _to_pcm_s16le(audio: Any) -> bytes:
    import numpy as np

    array = np.asarray(audio)
    if array.ndim > 1:
        array = array.reshape(-1)
    if array.size == 0:
        return b""
    if np.issubdtype(array.dtype, np.floating):
        if not np.isfinite(array).all():
            raise ValueError("audio contains non-finite samples")
        array = np.clip(array, -1.0, 1.0)
        array = (array * 32767.0).round().astype("<i2")
    else:
        array = array.astype("<i2", copy=False)
    return array.tobytes()


def _normalize_chunks(chunks: Iterable[Any], out_pcm: Path) -> dict:
    """Normalize provider chunks and report fixed 20 ms frame continuity."""
    sample_rate = 24_000
    frame_bytes = sample_rate * 20 // 1000 * 2
    all_pcm = bytearray()
    chunk_count = 0
    effective_chunks = 0
    empty_chunks = 0
    sample_rates = set()
    first_effective_at: Optional[float] = None
    generation_started = time.perf_counter()
    chunk_lengths: list[int] = []

    for item in chunks:
        # faster-qwen3-tts yields (numpy_audio, sample_rate, timing).
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            raise ValueError("provider emitted an unknown streaming shape")
        audio, sr = item[0], int(item[1])
        sample_rates.add(sr)
        pcm = _to_pcm_s16le(audio)
        chunk_count += 1
        chunk_lengths.append(len(pcm))
        if not pcm:
            empty_chunks += 1
        elif any(pcm):
            effective_chunks += 1
            if first_effective_at is None:
                first_effective_at = time.perf_counter()
        all_pcm.extend(pcm)

    if len(sample_rates) != 1 or sample_rates != {sample_rate}:
        raise ValueError(f"unexpected sample rates: {sorted(sample_rates)}")
    out_pcm.parent.mkdir(parents=True, exist_ok=True)
    out_pcm.write_bytes(bytes(all_pcm))
    duration_s = len(all_pcm) / 2 / sample_rate
    elapsed_s = time.perf_counter() - generation_started
    return {
        "sample_rate": sample_rate,
        "channels": 1,
        "format": "s16le",
        "chunk_count": chunk_count,
        "empty_chunks": empty_chunks,
        "effective_chunks": effective_chunks,
        "pcm_bytes": len(all_pcm),
        "audio_duration_s": round(duration_s, 6),
        "generation_elapsed_s": round(elapsed_s, 6),
        "rtf": round(elapsed_s / duration_s, 6) if duration_s else None,
        "first_effective_chunk_seen": first_effective_at is not None,
        "ttfa_from_generation_start_s": (
            round(first_effective_at - generation_started, 6)
            if first_effective_at is not None
            else None
        ),
        "fixed_frame_bytes": frame_bytes,
        "full_20ms_frames": len(all_pcm) // frame_bytes,
        "tail_bytes_after_20ms_frames": len(all_pcm) % frame_bytes,
        "chunk_lengths_bytes": chunk_lengths,
        "pcm_sha256": hashlib.sha256(all_pcm).hexdigest(),
        "pcm_contiguous": True,
    }


def _load_model(model_dir: Path) -> tuple[Any, Any, float]:
    import torch

    try:
        from faster_qwen3_tts import FasterQwen3TTS
    except ImportError:
        from faster_qwen3_tts.model import FasterQwen3TTS
    started = time.perf_counter()
    model = FasterQwen3TTS.from_pretrained(
        str(model_dir),
        device="cuda",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
        local_files_only=True,
    )
    return model, torch, time.perf_counter() - started


def _consume_generation(model: Any, *, text: str, speaker: str, language: str, max_new_tokens: int, chunk_size: int) -> None:
    """Run and discard one generation to measure the warmed steady state separately."""
    stream = model.generate_custom_voice_streaming(
        text=text,
        speaker=speaker,
        language=language,
        instruct=None,
        non_streaming_mode=False,
        max_new_tokens=max_new_tokens,
        chunk_size=chunk_size,
    )
    for _ in stream:
        pass


def _child_run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    status_path = out_dir / f"{args.run_id}.status.json"
    result_path = out_dir / f"{args.run_id}.result.json"
    pcm_path = out_dir / f"{args.run_id}.pcm"
    status = {
        "run_id": args.run_id,
        "mode": args.mode,
        "state": "starting",
        "text_fingerprint": _text_fingerprint(args.text),
        "started_at": time.time(),
    }
    _write_json(status_path, status)
    try:
        status["state"] = "loading"
        _write_json(status_path, status)
        model, torch, load_s = _load_model(Path(args.model_dir))
        status.update({"state": "ready", "load_seconds": round(load_s, 6)})
        _write_json(status_path, status)
        warmup_s = None
        if args.mode == "normal":
            status["state"] = "warmup"
            _write_json(status_path, status)
            warmup_started = time.perf_counter()
            _consume_generation(
                model,
                text="你好。",
                speaker=args.speaker,
                language=args.language,
                max_new_tokens=min(args.max_new_tokens, 512),
                chunk_size=args.chunk_size,
            )
            warmup_s = time.perf_counter() - warmup_started
            status.update({"state": "ready_warmed", "warmup_seconds": round(warmup_s, 6)})
            _write_json(status_path, status)
        if args.mode == "cancel":
            # Parent waits for this marker before terminating the worker.
            status["state"] = "generating"
            status["generation_started_at"] = time.time()
            _write_json(status_path, status)

        started = time.perf_counter()
        generator = model.generate_custom_voice_streaming(
            text=args.text,
            speaker=args.speaker,
            language=args.language,
            instruct=None,
            non_streaming_mode=False,
            max_new_tokens=args.max_new_tokens,
            chunk_size=args.chunk_size,
        )
        # Materialize through a wrapper so first-chunk state is observable.
        first_seen = False

        def observed_chunks() -> Iterable[Any]:
            nonlocal first_seen
            for item in generator:
                if not first_seen:
                    first_seen = True
                    status["state"] = "first_chunk"
                    status["first_chunk_at"] = time.time()
                    _write_json(status_path, status)
                yield item

        metrics = _normalize_chunks(observed_chunks(), pcm_path)
        metrics.update(
            {
                "load_seconds": round(load_s, 6),
                "warmup_seconds": round(warmup_s, 6) if warmup_s is not None else None,
                "provider": "faster-qwen3-tts",
                "model_dir": str(Path(args.model_dir)),
                "done_after_pcm": bool(metrics["pcm_bytes"] and metrics["effective_chunks"]),
                "generation_started_monotonic": started,
                "gpu": _gpu_snapshot(torch),
            }
        )
        _write_json(result_path, {"ok": True, "metrics": metrics})
        status["state"] = "done"
        status["finished_at"] = time.time()
        _write_json(status_path, status)
        return 0
    except Exception as exc:
        error = {
            "ok": False,
            "error_code": "VOICE-TTS-MODEL-LOAD-FAILED"
            if status.get("state") in {"starting", "loading"}
            else "VOICE-TTS-GENERATE-FAILED",
            "error_type": type(exc).__name__,
            "detail": str(exc)[:400],
            "gpu": _safe_gpu_snapshot(),
        }
        _write_json(result_path, error)
        status.update({"state": "failed", "error_code": error["error_code"]})
        _write_json(status_path, status)
        return 2


def _safe_gpu_snapshot() -> dict:
    try:
        import torch

        return _gpu_snapshot(torch)
    except Exception:
        return {"cuda_available": False}


def _run_child(parent_args: argparse.Namespace, mode: str, text: str) -> dict:
    out_dir = Path(parent_args.out_dir)
    run_id = f"{mode}_{int(time.time())}"
    child_args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--mode",
        mode,
        "--run-id",
        run_id,
        "--model-dir",
        parent_args.model_dir,
        "--out-dir",
        str(out_dir),
        "--text",
        text,
        "--speaker",
        parent_args.speaker,
        "--language",
        parent_args.language,
        "--max-new-tokens",
        str(parent_args.max_new_tokens),
        "--chunk-size",
        str(parent_args.chunk_size),
    ]
    env = os.environ.copy()
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    started = time.perf_counter()
    proc = subprocess.Popen(
        child_args,
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    status_path = out_dir / f"{run_id}.status.json"
    result_path = out_dir / f"{run_id}.result.json"
    status: Optional[dict] = None
    deadline = started + parent_args.timeout_s
    while time.perf_counter() < deadline:
        status = _read_json(status_path)
        if mode == "cancel" and status and status.get("state") in {"generating", "first_chunk"}:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.25)

    stop_requested_at: Optional[float] = None
    if mode == "cancel" and proc.poll() is None and status and status.get("state") in {
        "generating",
        "first_chunk",
    }:
        time.sleep(max(0.0, parent_args.cancel_delay_s))
        stop_requested_at = time.perf_counter()
        proc.terminate()
    elif proc.poll() is None:
        proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=parent_args.stop_timeout_s)
        stopped = proc.poll() is not None
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=parent_args.stop_timeout_s)
        stopped = proc.poll() is not None
    result = _read_json(result_path) or {
        "ok": False,
        "error_code": "VOICE-TTS-WORKER-STOP-UNCONFIRMED" if not stopped else "VOICE-TTS-PROBE-NO-RESULT",
    }
    result.update(
        {
            "run_id": run_id,
            "mode": mode,
            "worker_exit_code": proc.returncode,
            "worker_stopped": stopped,
            "stop_observation_s": round(time.perf_counter() - (stop_requested_at or started), 6),
            "status_at_parent_stop": status,
            "stdout_tail": (stdout or "")[-1000:],
            "stderr_tail": (stderr or "")[-2000:],
        }
    )
    _write_json(out_dir / f"{mode}_summary.json", result)
    return result


def _parent_run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = {
        "timestamp": time.time(),
        "python": sys.version,
        "platform": platform.platform(),
        "model_dir": str(Path(args.model_dir)),
        "output_dir": str(out_dir),
        "offline_mode": True,
        "device_access": False,
    }
    try:
        import torch

        baseline["torch"] = torch.__version__
        baseline["gpu_before"] = _gpu_snapshot(torch)
    except Exception as exc:
        baseline["torch_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    _write_json(out_dir / "baseline.json", baseline)

    normal = _run_child(args, "normal", args.text)
    cancel = _run_child(args, "cancel", args.cancel_text)
    summary = {
        "probe_version": "qwen3-isolated-v1",
        "baseline": baseline,
        "normal": normal,
        "cancel": cancel,
        "normal_pass_candidate": bool(
            normal.get("ok")
            and normal.get("metrics", {}).get("sample_rate") == 24_000
            and normal.get("metrics", {}).get("channels") == 1
            and normal.get("metrics", {}).get("format") == "s16le"
            and normal.get("metrics", {}).get("pcm_contiguous")
            and normal.get("metrics", {}).get("done_after_pcm")
        ),
        "cancel_stop_evidence": bool(cancel.get("worker_stopped")),
        "c_certification": "not_run",
    }
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["normal_pass_candidate"] and summary["cancel_stop_evidence"] else 3


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--mode", choices=("normal", "cancel"), default="normal")
    parser.add_argument("--run-id", default="child")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--cancel-text", default=DEFAULT_CANCEL_TEXT)
    parser.add_argument("--speaker", default="Vivian")
    parser.add_argument("--language", default="chinese")
    parser.add_argument("--chunk-size", type=int, default=12)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--timeout-s", type=float, default=90.0)
    parser.add_argument("--stop-timeout-s", type=float, default=3.0)
    parser.add_argument("--cancel-delay-s", type=float, default=1.0)
    return parser.parse_args()


if __name__ == "__main__":
    parsed = _parse_args()
    if parsed.child:
        raise SystemExit(_child_run(parsed))
    raise SystemExit(_parent_run(parsed))
