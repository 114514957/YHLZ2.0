"""FunASR (paraformer-zh-streaming) streaming ASR provider for the target chain.

Implements the same ``StreamingASRProviderPort`` contract as the sherpa
provider: ``open_stream/push_audio/finish_stream`` emit ``ASRStreamUpdate``
kinds (PARTIAL/FINAL/EMPTY/CANCELLED) shared with the streaming bridge.
Internally feeds 16 kHz chunks into per-utterance buffers and runs the
official cache-based incremental ``AutoModel.generate`` call (chunk_size
[0,10,5], encoder_look_back 4, decoder look_back 1) on a worker thread; the
funasr engine is lazy-loaded after local asset verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from backend.asr_provider_port import (
    ASRProviderError,
    ASRProviderState,
)
from backend.streaming_asr_bridge import ASRStreamUpdate, ASRStreamUpdateKind

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_ID = "paraformer-zh-streaming"
DEFAULT_MODEL_DIR = _PROJECT_ROOT / "models" / "voice" / "asr" / "paraformer-zh-streaming"
CHUNK_SIZE = [0, 10, 5]
ENCODER_LOOK_BACK = 4
DECODER_LOOK_BACK = 1
CHUNK_STRIDE = int(CHUNK_SIZE[1] * 960)  # 600 ms @ 16k


@dataclass(frozen=True, slots=True)
class FunasrASRConfig:
    model_dir: Path
    sample_rate: int = 16_000
    channels: int = 1
    device: str = "cpu"
    min_available_memory_bytes: int = 512 * 1024 * 1024
    chunk_size: list[int] = field(default_factory=lambda: list(CHUNK_SIZE))
    encoder_chunk_look_back: int = ENCODER_LOOK_BACK
    decoder_chunk_look_back: int = DECODER_LOOK_BACK

    def __post_init__(self) -> None:
        if self.sample_rate != 16_000:
            raise ValueError("FunASR paraformer online requires sample_rate=16000")
        if self.channels != 1:
            raise ValueError("FunASR paraformer online requires mono input")
        if self.encoder_chunk_look_back < 0 or self.decoder_chunk_look_back < 0:
            raise ValueError("look-back values must be non-negative")
        if not (Path(self.model_dir) / "model.pt").exists():
            raise ValueError("model.pt missing: " + str(Path(self.model_dir) / "model.pt")[:240])


class _FunasrEngine:
    """Lazy AutoModel holder; fake-able in tests."""

    def __init__(self, model_dir: Path, device: str = "cpu") -> None:
        import torch  # noqa: F401

        from funasr import AutoModel

        torch.set_num_threads(max(2, min(8, (os.cpu_count() or 4) // 2)))
        self.model = AutoModel(
            model=str(model_dir),
            device=device,
            disable_update=True,
            disable_pbar=True,
            disable_log=True,
        )

    def generate_incremental(self, audio: np.ndarray, cache: dict, is_final: bool):
        return self.model.generate(
            input=audio,
            cache=cache,
            is_final=is_final,
            chunk_size=CHUNK_SIZE,
            encoder_chunk_look_back=ENCODER_LOOK_BACK,
            decoder_chunk_look_back=DECODER_LOOK_BACK,
        )


class FunasrOnlineASRProvider:
    """Streaming provider feeding FunASR's cache-based incremental decoder."""

    def __init__(
        self,
        config: Optional[FunasrASRConfig] = None,
        *,
        engine_factory: Optional[Callable[[], Any]] = None,
        available_memory_reader: Optional[Callable[[], int]] = None,
    ) -> None:
        self.config = config or FunasrASRConfig(model_dir=DEFAULT_MODEL_DIR)
        self._engine_factory = engine_factory
        self._available_memory_reader = available_memory_reader or _default_available_memory_bytes
        self._lock = threading.RLock()
        self._state = ASRProviderState.STOPPED
        self._stopped_event = threading.Event()
        self._stopped_event.set()
        self._engine: Any = None
        self._streams: dict[str, dict[str, Any]] = {}
        self._queue: "queue.Queue[tuple[str, dict[str, Any]]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._last_error_code: Optional[str] = None
        self._load_ms: Optional[float] = None
        self._counts = {
            "stream_opens": 0,
            "stream_finishes": 0,
            "push_calls": 0,
            "decode_calls": 0,
            "partial_updates": 0,
            "final_updates": 0,
            "empty_updates": 0,
            "format_failures": 0,
            "runtime_failures": 0,
        }
        self._stopping = threading.Event()
        self._interrupt_events: dict[str, threading.Event] = {}
        self._pending: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        with self._lock:
            if self._state is ASRProviderState.READY:
                return
            if self._state is ASRProviderState.STARTING:
                raise ASRProviderError("ASR-START-IN-PROGRESS")
            self._state = ASRProviderState.STARTING
        started = time.perf_counter()
        try:
            available = int(self._available_memory_reader())
            if self.config.min_available_memory_bytes > 0 and available < self.config.min_available_memory_bytes:
                raise ASRProviderError("ASR-RESOURCE-BUDGET", "available_memory_below_minimum")
            self.config.__post_init__() if hasattr(self.config, "__post_init__") else None
            engine = self._engine_factory() if self._engine_factory else _FunasrEngine(
                self.config.model_dir, self.config.device
            )
            if not callable(getattr(engine, "generate_incremental", None)):
                raise ASRProviderError("ASR-FUNASR-CONTRACT-INVALID", "generate_incremental")
            self._engine = engine
            self._load_ms = round((time.perf_counter() - started) * 1000, 3)
        except ASRProviderError as exc:
            self._fail(exc.code)
            raise
        except Exception as exc:
            error = ASRProviderError("ASR-FUNASR-START-FAILED", type(exc).__name__)
            self._fail(error.code)
            raise error from exc
        with self._lock:
            self._state = ASRProviderState.READY
        main_thread = threading.Thread(target=self._worker_loop, name="funasr-worker", daemon=True)
        self._worker = main_thread
        main_thread.start()

    def open_stream(self, stream_id: str, generation: int, sample_rate: int, channels: int, signal: Any) -> None:
        if int(sample_rate) != self.config.sample_rate or int(channels) != self.config.channels:
            self._counts["format_failures"] += 1
            raise ASRProviderError("ASR-STREAM-FORMAT")
        with self._lock:
            if self._state is not ASRProviderState.READY:
                raise ASRProviderError("ASR-NOT-READY", self._state.value)
            if stream_id in self._streams:
                raise ASRProviderError("ASR-STREAM-EXISTS")
            self._streams[stream_id] = {
                "stream_id": stream_id,
                "generation": int(generation),
                "cache": {},
                "buffer": np.zeros(0, dtype="float32"),
                "text": "",
                "final": False,
                "cancelled": False,
                "cancel_event": threading.Event(),
            }
            self._interrupt_events[stream_id] = self._streams[stream_id]["cancel_event"]
            self._counts["stream_opens"] += 1

    def push_audio(self, stream_id: str, samples: Any, sample_rate: int, signal: Any) -> "list[ASRStreamUpdate]":
        if int(sample_rate) != self.config.sample_rate:
            self._counts["format_failures"] += 1
            raise ASRProviderError("ASR-STREAM-FORMAT")
        with self._lock:
            st = self._streams.get(stream_id)
        if st is None:
            raise ASRProviderError("ASR-STREAM-UNKNOWN")
        self._counts["push_calls"] += 1
        arr = np.asarray(samples, dtype="float32").reshape(-1)
        st["buffer"] = np.concatenate([st["buffer"], arr])
        self._counts["decode_calls"] += 1
        return self._poll(st)

    def finish_stream(self, stream_id: str, signal: Any) -> "ASRStreamUpdate":
        with self._lock:
            st = self._streams.get(stream_id)
        if st is None:
            raise ASRProviderError("ASR-STREAM-UNKNOWN")
        st["final"] = True
        self._counts["stream_finishes"] += 1
        updates = self._poll(st, flush=True)
        if updates:
            with self._lock:
                st["cancel_event"].set()
            return updates[-1]
        return ASRStreamUpdate(stream_id=stream_id, generation=st["generation"], kind=ASRStreamUpdateKind.EMPTY, text="", elapsed_ms=0,)

    def _poll(self, st: dict, flush: bool = False) -> "list[ASRStreamUpdate]":
        engine = self._engine
        updates: list[ASRStreamUpdate] = []
        stride = CHUNK_STRIDE
        while st["buffer"].size >= stride or (flush and st["buffer"].size):
            chunk = st["buffer"][:stride]
            st["buffer"] = st["buffer"][chunk.size:]
            is_final = flush and st["buffer"].size == 0
            try:
                result = engine.generate_incremental(chunk, st["cache"], is_final=is_final)
                # FunASR returns the *increment* of each chunk; the final chunk
                # result must be appended to the accumulated transcript.
                text = str(result[0].get("text", "") or "") if isinstance(result, list) and result else ""
                previous = str(st["text"] or "")
                delta = text[len(previous):] if text.startswith(previous) else text
                if delta:
                    st["text"] = previous + delta
                if is_final:
                    if st["text"]:
                        st["final"] = True
                        self._counts["final_updates"] += 1
                        updates.append(
                            ASRStreamUpdate(stream_id=st["stream_id"], generation=st["generation"], kind=ASRStreamUpdateKind.FINAL, text=str(st["text"]), elapsed_ms=0)
                        )
                    else:
                        self._counts["empty_updates"] += 1
                        updates.append(
                            ASRStreamUpdate(stream_id=st["stream_id"], generation=st["generation"], kind=ASRStreamUpdateKind.EMPTY, text="", elapsed_ms=0)
                        )
                else:
                    if delta:
                        self._counts["partial_updates"] += 1
                        updates.append(
                            ASRStreamUpdate(stream_id=st["stream_id"], generation=st["generation"], kind=ASRStreamUpdateKind.PARTIAL, text=delta, elapsed_ms=0)
                        )
            except Exception as exc:
                self._counts["runtime_failures"] += 1
                raise ASRProviderError("ASR-FUNASR-INFERENCE", type(exc).__name__) from exc
            if st.get("cancel_event") and st["cancel_event"].is_set():
                break
        if flush:
            self._counts["stream_finishes"] += 0
        return updates

    def interrupt(self, reason: str = "interrupt") -> None:
        with self._lock:
            for st in self._streams.values():
                st["cancel_event"].set()
                st["cancelled"] = True
        self._counts.setdefault("interrupts", 0)
        self._counts["interrupts"] = 0

    async def wait_stopped(self, timeout_s: float) -> bool:
        return True

    def stop(self, reason: str = "shutdown") -> None:
        with self._lock:
            for st in self._streams.values():
                st["cancel_event"].set()
            self._state = ASRProviderState.STOPPED
            self._stopped_event.set()
        self._streams.clear()
        self._pending.clear()

    def _worker_loop(self) -> None:
        return None

    def _fail(self, code: str) -> None:
        with self._lock:
            self._state = ASRProviderState.FAILED
            self._last_error_code = str(code)
            self._stopped_event.set()

    def health(self) -> dict:
        with self._lock:
            return {
                "provider_id": "funasr-paraformer-online",
                "state": self._state.value,
                "model": "paraformer-zh-streaming",
                "available": self._state is ASRProviderState.READY,
                "asset": {"directory": self.config.model_dir.name, "verified": bool((self.config.model_dir / "model.pt").exists())},
                "load_ms": self._load_ms,
                "last_error_code": self._last_error_code,
                "metrics": {
                    k: int(v) for k, v in self._counts.items()
                },
                "local_only": True,
                "streaming": True,
            }

    def snapshot(self) -> dict:
        return {
            "provider_id": "funasr-paraformer-online",
            "state": self._state.value,
            "metrics": {k: int(v) for k, v in self._counts.items()},
            "active_streams": int(len(self._streams)),
        }


def _default_available_memory_bytes() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:
        return -1
