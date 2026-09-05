"""A small, testable orchestration layer for the YHLZ target voice chain.

The chain consumes VAD/ASR candidates rather than opening a device itself.  This
keeps device ownership in a future media adapter while making wake-word routing,
turn cancellation, and output ordering deterministic today.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Protocol

from backend.memory_guard import ReadOnlyMemoryFacade
from backend.session_kernel import (
    CancellationHandle,
    ErrorCode,
    EventKind,
    KernelError,
    ProviderCapabilities,
    SessionKernel,
    TurnLease,
)
from backend.voice_gate import GateDecision, GateEvent, WakeWordGate
from backend.tts_provider_port import (
    TTSEventKind,
    TTSProviderCapabilities,
    TTSProviderEvent,
    TTSProviderPortError,
    TTSRequest,
    TTSStreamNormalizer,
    coerce_capabilities,
    coerce_provider_event,
    is_tts_provider_port,
    is_tts_provider_session,
)


logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Raised for a target-chain contract violation."""


class PlaybackStopObserver(Protocol):
    """Optional playback evidence required for a physical-stop acceptance test."""

    def wait_stopped(self, timeout_s: float) -> Any: ...


class SpeechStopObserver(Protocol):
    """Optional TTS evidence required for a physical-stop acceptance test."""

    def wait_stopped(self, timeout_s: float) -> Any: ...


class CancellationSignal:
    """Thread-safe cooperative cancellation signal for provider adapters."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._cancel_reason: Optional[str] = None
        self._done = threading.Event()
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._callback_lock = threading.RLock()
        self._cancel_callbacks = []
        self._terminal_waiters = []

    def bind_task(self, task: asyncio.Task) -> None:
        """Bind provider cancellation to the task that owns this signal."""
        self._task = task
        self._loop = task.get_loop()

    def cancel(self, reason: str = "cancelled") -> None:
        with self._callback_lock:
            first_cancel = not self._cancelled.is_set()
            self._cancelled.set()
            if first_cancel:
                self._cancel_reason = str(reason or "cancelled")[:160]
            callbacks = list(self._cancel_callbacks) if first_cancel else []
            if first_cancel:
                self._cancel_callbacks.clear()
        for callback in callbacks:
            self._invoke_cancel_callback(callback)
        task = self._task
        loop = self._loop
        if task is None or loop is None or task.done() or loop.is_closed():
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        # A failing worker may ask the Kernel to close its own turn.  Setting
        # the cooperative flag is enough in that case; self-cancellation would
        # interrupt the error/COMPLETE path before it can finish.
        if running_loop is loop and task is asyncio.current_task():
            return
        if running_loop is loop:
            task.cancel()
        else:
            loop.call_soon_threadsafe(task.cancel)

    def add_cancel_callback(self, callback: Any) -> None:
        """Register a prompt, idempotent side effect for cancellation.

        Playback adapters should expose a short, synchronous ``interrupt`` or
        ``stop`` method.  Async callbacks are scheduled on the owning loop but
        are not part of the Kernel's terminal wait budget.
        """
        if not callable(callback):
            raise TypeError("cancel callback must be callable")
        with self._callback_lock:
            if not self._cancelled.is_set():
                self._cancel_callbacks.append(callback)
                return
        self._invoke_cancel_callback(callback)

    def add_terminal_waiter(self, waiter: Any) -> None:
        """Register optional evidence that a provider has actually stopped.

        The waiter receives the remaining cancellation budget and returns a
        truthy terminal result. It is invoked only by ``wait_terminal`` after
        the target-chain task has itself ended.
        """
        if not callable(waiter):
            raise TypeError("terminal waiter must be callable")
        with self._callback_lock:
            self._terminal_waiters.append(waiter)

    def _invoke_cancel_callback(self, callback: Any) -> None:
        try:
            result = callback()
            if not inspect.isawaitable(result):
                return
            loop = self._loop
            if loop is None or loop.is_closed():
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                return
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is loop:
                task = loop.create_task(result)
                task.add_done_callback(_consume_async_cancel_task)
            else:
                future = asyncio.run_coroutine_threadsafe(_await_cancel_callback(result), loop)
                future.add_done_callback(_consume_async_cancel_future)
        except Exception:
            logger.exception("cancellation callback failed")

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def cancel_reason(self) -> Optional[str]:
        """Return the first cancellation cause for outcome classification."""
        with self._callback_lock:
            return self._cancel_reason

    def mark_done(self) -> None:
        self._done.set()

    async def wait_terminal(self, timeout_s: float) -> bool:
        budget = max(float(timeout_s), 0.0)
        deadline = time.monotonic() + budget
        # A zero budget can still carry useful terminal evidence when the
        # worker has already marked itself done.  Poll the cross-thread event
        # in short async slices instead of using ``to_thread``: executor
        # startup can consume the whole budget and prevent physical observers
        # from being called at all.
        if not self._done.is_set() and budget > 0:
            observer_reserve = min(0.01, budget * 0.25)
            wait_deadline = deadline - observer_reserve
            while not self._done.is_set():
                remaining = wait_deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(0.005, remaining))
        task_done = self._done.is_set()
        with self._callback_lock:
            waiters = tuple(self._terminal_waiters)
        for waiter in waiters:
            remaining = max(0.0, deadline - time.monotonic())
            # Even an exhausted budget gets one non-blocking observation
            # attempt.  This distinguishes "not observed" from a confirmed
            # stop without extending the cancellation budget.
            if not await _await_terminal_waiter(waiter, remaining):
                return False
        # A physical observer alone cannot certify that the owning task has
        # released its resources; both signals are required for a terminal
        # result.  The observers above are nevertheless always attempted.
        return task_done or self._done.is_set()


@dataclass(frozen=True)
class AudioChunk:
    """Provider-neutral audio metadata and payload."""

    samples: Any
    sample_rate: int
    channels: int = 1
    format: str = "pcm_f32le"

    def __post_init__(self) -> None:
        if self.samples is None:
            raise ValueError("audio samples must not be None")
        if self.sample_rate <= 0:
            raise ValueError("audio sample_rate must be positive")
        if self.channels <= 0:
            raise ValueError("audio channels must be positive")
        if not str(self.format).strip():
            raise ValueError("audio format must not be empty")


@dataclass(frozen=True)
class PipelineOutcome:
    status: str
    turn_id: Optional[str]
    text: str = ""
    committed: bool = False
    error_code: Optional[str] = None


@dataclass(frozen=True)
class PipelineSubmission:
    decision: GateDecision
    lease: Optional[TurnLease] = None
    task: Optional[asyncio.Task] = None


class _TTSControl:
    """Turn-bound lifecycle slot registered before a provider session opens."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.session: Any = None
        self.opened = False
        self.closed = False
        self.cancel_requested = False
        self.terminal_confirmed = False

    def attach(self, session: Any) -> bool:
        with self._lock:
            self.session = session
            self.opened = True
            return self.cancel_requested

    def mark_closed(self) -> None:
        with self._lock:
            self.closed = True

    @property
    def needs_terminal_observation(self) -> bool:
        with self._lock:
            return not self.terminal_confirmed

    def request_cancel(self, reason: str = "turn_cancelled") -> Any:
        with self._lock:
            self.cancel_requested = True
            session = self.session
        if session is None:
            return None
        return session.cancel(str(reason or "turn_cancelled")[:160])

    async def wait_stopped(self, timeout_s: float) -> Any:
        with self._lock:
            session = self.session
            closed = self.closed
        if session is None:
            # No session was opened (for example, cancellation won the race
            # before the provider task was scheduled), so there is no worker
            # resource whose physical stop needs observing.
            if closed:
                with self._lock:
                    self.terminal_confirmed = True
                return True
            return False
        method = getattr(session, "wait_stopped", None)
        if inspect.iscoroutinefunction(method):
            result = await method(timeout_s)
        else:
            result = await asyncio.to_thread(method, timeout_s)
            if inspect.isawaitable(result):
                result = await result
        if result:
            with self._lock:
                self.terminal_confirmed = True
        return result


def _coerce_audio(value: Any) -> AudioChunk:
    if isinstance(value, AudioChunk):
        return value
    if isinstance(value, tuple) and len(value) >= 2:
        return AudioChunk(value[0], int(value[1]))
    if isinstance(value, dict):
        return AudioChunk(
            value.get("samples", value.get("audio")),
            int(value.get("sample_rate", 16000)),
            int(value.get("channels", 1)),
            str(value.get("format", "pcm_f32le")),
        )
    raise PipelineError("TTS adapter must return AudioChunk, (samples, sample_rate), or a mapping")


async def _aiter(value: Any) -> AsyncIterator[Any]:
    """Adapt async iterables, sync iterables, and awaitable iterables.

    Synchronous iterators are advanced in worker threads so a local model or
    TTS implementation cannot block the event loop that owns cancellation and
    microphone ingress.
    """
    if inspect.isawaitable(value):
        value = await value
    if hasattr(value, "__aiter__"):
        async for item in value:
            yield item
        return
    if isinstance(value, (str, bytes, bytearray)):
        yield value
        return
    iterator = iter(value)
    while True:
        has_item, item = await asyncio.to_thread(_next_sync, iterator)
        if not has_item:
            return
        yield item


def _next_sync(iterator: Any) -> tuple[bool, Any]:
    """Advance one synchronous iterator without leaking StopIteration."""
    try:
        return True, next(iterator)
    except StopIteration:
        return False, None


async def _invoke_provider(method: Any, *args: Any) -> Any:
    """Call a provider without letting synchronous work block the loop."""
    if inspect.iscoroutinefunction(method):
        return await method(*args)
    if inspect.isasyncgenfunction(method):
        return method(*args)
    value = await asyncio.to_thread(method, *args)
    return await value if inspect.isawaitable(value) else value


def _is_audio_pair(value: Any) -> bool:
    """Recognize the common single-block ``(samples, sample_rate)`` result."""
    return (
        isinstance(value, tuple)
        and len(value) >= 2
        and isinstance(value[1], (int, float))
    )


async def _audio_iter(value: Any) -> AsyncIterator[Any]:
    """Adapt one audio block and streaming audio providers to one iterator."""
    if isinstance(value, (AudioChunk, Mapping)) or _is_audio_pair(value):
        yield value
        return
    async for item in _aiter(value):
        yield item


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class TargetVoiceChain:
    """Wake-gated turn coordinator with optional reasoning, speech, and playback ports."""

    def __init__(
        self,
        *,
        kernel: Optional[SessionKernel] = None,
        gate: Optional[WakeWordGate] = None,
        reasoner: Any = None,
        speech: Any = None,
        tts_provider: Any = None,
        playback: Any = None,
        memory: Optional[ReadOnlyMemoryFacade] = None,
        tts_voice_id: str = "default",
        tts_style: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if speech is not None and tts_provider is not None:
            raise ValueError("provide speech or tts_provider, not both")
        if tts_provider is not None and not is_tts_provider_port(tts_provider):
            raise TypeError("tts_provider does not implement TTSProviderPort")
        # A provider may be passed through the historical ``speech`` slot for
        # callers migrating incrementally; structural detection keeps the
        # legacy synthesize() path untouched for all other objects.
        if tts_provider is None and is_tts_provider_port(speech):
            tts_provider, speech = speech, None
        self.kernel = kernel or SessionKernel()
        self.gate = gate or WakeWordGate()
        self.reasoner = reasoner
        self.speech = speech
        self.tts_provider = tts_provider
        self.playback = playback
        self.memory = memory or ReadOnlyMemoryFacade()
        if not str(tts_voice_id).strip():
            raise ValueError("tts_voice_id must not be empty")
        self.tts_voice_id = str(tts_voice_id)
        if tts_style is not None and not isinstance(tts_style, Mapping):
            raise TypeError("tts_style must be a mapping or None")
        self.tts_style = dict(tts_style or {})
        self._submission_lock = asyncio.Lock()
        self._tasks: Dict[str, asyncio.Task] = {}
        self._signals: Dict[str, CancellationSignal] = {}
        self._tts_sessions: Dict[str, Any] = {}
        self._tts_controls: Dict[str, _TTSControl] = {}
        self._tts_provider_epoch = 0
        self._tts_capabilities_cache: Optional[TTSProviderCapabilities] = None
        self._last_tts_metrics: Optional[dict] = None
        self._tts_cleanup_blocked = False
        self._turn_observer: Optional[Callable[[str, str, Any], Any]] = None

    def set_turn_observer(self, observer: Any) -> None:
        """Register an optional turn-completion watcher (memory extraction etc.).

        ``observer(lease_turn_id, user_text, outcome)`` — fire-and-forget
        semantics; exceptions are swallowed so turns never regress.
        """
        if observer is not None and not callable(observer):
            raise TypeError("turn observer must be callable")
        self._turn_observer = observer

    def _notify_turn_observer(self, lease: TurnLease, text: str, outcome: Any) -> None:
        observer = self._turn_observer
        if observer is None:
            return
        try:
            result = observer(lease.turn_id, text, outcome)
            if inspect.isawaitable(result):
                asyncio.ensure_future(result)
        except Exception:
            pass

    def start(self, capabilities: ProviderCapabilities):
        return self.kernel.start(capabilities)

    def set_tts_provider(self, provider: Any) -> None:
        """Select a provider only while the target chain is strictly idle."""
        old_provider = self.tts_provider
        if provider is not old_provider and old_provider is not None:
            # A persistent worker may have reusable capacity while its last
            # session still lacks physical-stop evidence.  Let the provider
            # boundary explain that state before replacing the selected port.
            switch_guard = getattr(old_provider, "assert_strict_idle", None)
            if callable(switch_guard):
                switch_guard()
        if (
            self.kernel.snapshot().get("active_turn_id")
            or self._tts_sessions
            or self._tts_cleanup_blocked
            or any(not control.terminal_confirmed for control in self._tts_controls.values())
        ):
            raise PipelineError("TTS provider can only change while the chain is idle")
        if provider is not None and not is_tts_provider_port(provider):
            raise TypeError("provider does not implement TTSProviderPort")
        self.tts_provider = provider
        self.speech = None
        self._tts_provider_epoch += 1
        self._tts_capabilities_cache = None
        provider_id = None
        if provider is not None:
            try:
                provider_id = self._get_tts_capabilities().provider_id
            except Exception:
                provider_id = "unavailable"
        self.kernel.record_system_event(
            EventKind.TASK,
            {
                "action": "tts_provider_selected",
                "provider_id": provider_id,
                "provider_epoch": self._tts_provider_epoch,
            },
        )

    def set_tts_voice(self, voice_id: str) -> None:
        """Select a provider voice at an idle boundary without touching assets."""
        if (
            self.kernel.snapshot().get("active_turn_id")
            or self._tts_sessions
            or self._tts_cleanup_blocked
            or any(not control.terminal_confirmed for control in self._tts_controls.values())
        ):
            raise PipelineError("TTS voice can only change while the chain is idle")
        if not str(voice_id).strip():
            raise ValueError("voice_id must not be empty")
        self.tts_voice_id = str(voice_id)
        self.kernel.record_system_event(
            EventKind.TASK,
            {
                "action": "tts_voice_selected",
                "voice_id": self.tts_voice_id,
                "provider_epoch": self._tts_provider_epoch,
            },
        )

    async def submit_transcript(
        self,
        transcript: str,
        *,
        source: str = "microphone",
        timestamp: Optional[float] = None,
    ) -> PipelineSubmission:
        """Route a VAD-final ASR candidate through the single wake gate."""
        decision = self.gate.observe(transcript, timestamp=timestamp)
        if decision.event != GateEvent.INPUT_ACCEPTED:
            return PipelineSubmission(decision)
        if self.reasoner is None:
            raise PipelineError("reasoner adapter is required for an accepted input")
        if self.tts_provider is not None:
            self._prune_tts_controls()
            if self._tts_cleanup_blocked or any(
                control.needs_terminal_observation for control in self._tts_controls.values()
            ):
                self.kernel.record_system_event(
                    EventKind.ERROR,
                    {
                        "code": "VOICE-TTS-CLEANUP-PENDING",
                        "component": "tts",
                        "retryable": True,
                    },
                )
                raise PipelineError("TTS provider cleanup is not confirmed")

        async with self._submission_lock:
            # A new accepted candidate supersedes the current turn.  The old
            # lease is invalidated before a new one is issued.
            active_id = self.kernel.snapshot().get("active_turn_id")
            old_task = self._tasks.get(active_id) if active_id else None
            if active_id:
                abort_result = await self.kernel.abort_active_turn_async("new_input", timeout_s=3.0)
                task_stopped = await self._await_task_shutdown(old_task, timeout_s=3.0)
                if self.tts_provider is not None and (
                    abort_result.timed_out_tasks
                    or abort_result.failed_tasks
                    or not task_stopped
                ):
                    self._tts_cleanup_blocked = True
                    raise PipelineError("previous TTS provider stop was not confirmed")
            lease = self.kernel.begin_turn(source=source, input_type="transcript")
            if not self.kernel.mark_input_final(lease):
                raise PipelineError("kernel rejected final input")
            signal = CancellationSignal()
            signal.add_cancel_callback(
                lambda: self._playback_cancel_callback(
                    signal.cancel_reason or "turn_cancelled"
                )
            )
            signal.add_cancel_callback(self._speech_cancel_callback)
            if self.tts_provider is not None:
                tts_control = _TTSControl()
                self._tts_controls[lease.turn_id] = tts_control
                # Read the signal's first reason at invocation time so a
                # provider error is distinguishable from user barge-in.
                signal.add_cancel_callback(
                    lambda: tts_control.request_cancel(
                        signal.cancel_reason or "turn_cancelled"
                    )
                )
                signal.add_terminal_waiter(tts_control.wait_stopped)
            playback_waiter = self._playback_stop_waiter()
            if playback_waiter is not None:
                signal.add_terminal_waiter(playback_waiter)
            speech_waiter = self._speech_stop_waiter()
            if speech_waiter is not None:
                signal.add_terminal_waiter(speech_waiter)
            task = asyncio.create_task(self._run_turn(lease, decision.text, signal))
            signal.bind_task(task)
            handle = CancellationHandle(
                name="turn:" + lease.turn_id,
                cancel=signal.cancel,
                wait_terminal=signal.wait_terminal,
            )
            if not self.kernel.register_cancellable(lease, handle):
                self._tts_controls.pop(lease.turn_id, None)
                task.cancel()
                await self._await_task_shutdown(task, timeout_s=1.0)
                raise PipelineError("kernel rejected turn cancellation handle")
            self._tasks[lease.turn_id] = task
            self._signals[lease.turn_id] = signal
            return PipelineSubmission(decision, lease, task)

    async def interrupt(self, reason: str = "user_interrupt", timeout_s: float = 3.0):
        async with self._submission_lock:
            active_id = self.kernel.snapshot().get("active_turn_id")
            active_task = self._tasks.get(active_id) if active_id else None
            result = await self.kernel.abort_active_turn_async(reason, timeout_s=timeout_s)
            task_stopped = await self._await_task_shutdown(active_task, timeout_s=timeout_s)
            if self.tts_provider is not None and (
                result.timed_out_tasks or result.failed_tasks or not task_stopped
            ):
                self._tts_cleanup_blocked = True
            self._prune_tts_controls()
            return result

    async def retry_tts_cleanup(self, timeout_s: float = 0.0) -> bool:
        """Retry bounded Provider stop observations without starting a turn."""
        if self.tts_provider is None:
            return True
        controls = tuple(self._tts_controls.values())
        for control in controls:
            if control.needs_terminal_observation:
                try:
                    await control.wait_stopped(max(float(timeout_s), 0.0))
                except Exception:
                    continue
        self._prune_tts_controls()
        self._tts_cleanup_blocked = any(
            control.needs_terminal_observation for control in self._tts_controls.values()
        )
        return not self._tts_cleanup_blocked

    async def sleep(self, reason: str = "idle_timeout") -> GateDecision:
        if self.kernel.snapshot().get("active_turn_id"):
            await self.interrupt(reason)
        return self.gate.sleep()

    def start_playback(self) -> bool:
        """Explicitly open an attached output port before runtime ingress."""
        playback = self.playback
        if playback is None:
            return False
        method = getattr(playback, "start", None)
        if not callable(method):
            return False
        try:
            result = method()
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                raise PipelineError("VOICE-PLAYBACK-ASYNC-LIFECYCLE")
            self._sync_tts_playback_state(active=False)
            return True
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError(
                "VOICE-PLAYBACK-START-FAILED:" + type(exc).__name__
            ) from exc

    def close_playback_sync(self) -> bool:
        """Release an attached output port at a synchronous lifecycle boundary."""
        playback = self.playback
        if playback is None:
            return False
        method = getattr(playback, "close", None)
        if not callable(method):
            method = getattr(playback, "shutdown", None)
        if not callable(method):
            return False
        try:
            result = method()
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                raise PipelineError("VOICE-PLAYBACK-ASYNC-LIFECYCLE")
            self._sync_tts_playback_state(active=False)
            return True
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError(
                "VOICE-PLAYBACK-CLOSE-FAILED:" + type(exc).__name__
            ) from exc

    async def close_playback(self) -> bool:
        """Release playback off the event loop after the turn has stopped."""
        return await asyncio.to_thread(self.close_playback_sync)

    async def shutdown(self) -> None:
        try:
            if self.kernel.snapshot().get("active_turn_id"):
                await self.interrupt("shutdown", timeout_s=1.0)
            await self.close_playback()
        finally:
            self.kernel.stop()

    def reopen(self) -> None:
        """Re-arm the in-memory chain after an explicit runtime stop."""
        if any(not task.done() for task in self._tasks.values()):
            raise PipelineError("cannot reopen while a turn task is still active")
        if self._tts_sessions or any(
            not control.terminal_confirmed for control in self._tts_controls.values()
        ):
            raise PipelineError("cannot reopen while a TTS provider session is active")
        self.gate.sleep()
        # A restarted runtime is a new provider epoch even when the selected
        # provider and voice remain unchanged; late worker events are stale.
        self._tts_provider_epoch += 1
        self._tts_capabilities_cache = None
        self.kernel.reopen()

    async def wait_idle(self) -> None:
        """Await all owned turn tasks without retaining stale task handles."""
        while True:
            tasks = tuple(task for task in self._tasks.values() if not task.done())
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    def snapshot(self) -> dict:
        state = self.kernel.snapshot()
        state["wake_gate"] = self.gate.snapshot()
        state["owned_tasks"] = len(self._tasks)
        state["memory"] = self.memory.runtime_status()
        state["ports"] = {
            "speech_attached": self.speech is not None or self.tts_provider is not None,
            "speech_cancel_supported": self._speech_cancel_supported()
            or self._tts_provider_capability_flag("cancel_observable"),
            "speech_stop_observable": self._speech_stop_waiter() is not None
            or self._tts_provider_capability_flag("cancel_observable"),
            "tts_provider_attached": self.tts_provider is not None,
            "tts_provider_epoch": self._tts_provider_epoch,
            "tts_provider_port_valid": is_tts_provider_port(self.tts_provider),
            "tts_provider_capabilities": self._tts_capabilities_snapshot(),
            "tts_sessions": len(self._tts_sessions),
            "tts_voice_id": self.tts_voice_id,
            "tts_provider_health": self._tts_provider_health_snapshot(),
            "tts_provider_metrics": self._tts_provider_metrics_snapshot(),
            "tts_controls_pending": sum(
                not control.terminal_confirmed for control in self._tts_controls.values()
            ),
            "tts_cleanup_blocked": self._tts_cleanup_blocked,
            "playback_attached": self.playback is not None,
            "playback_cancel_supported": self._playback_cancel_supported(),
            "playback_stop_observable": self._playback_stop_waiter() is not None,
            "playback_finish_observable": self._playback_finish_method() is not None,
            "playback_health": self._playback_health_snapshot(),
        }
        return state

    def _tts_capabilities_snapshot(self) -> Optional[dict]:
        provider = self.tts_provider
        if provider is None:
            return None
        try:
            return self._get_tts_capabilities().to_dict()
        except Exception as exc:
            return {
                "provider_id": "unavailable",
                "error_code": "VOICE-TTS-CAPABILITY-ERROR",
                "detail": str(exc)[:160],
            }

    def _tts_provider_capability_flag(self, name: str) -> bool:
        if self.tts_provider is None:
            return False
        try:
            capabilities = self._get_tts_capabilities()
            return bool(getattr(capabilities, name, False))
        except Exception:
            return False

    def _get_tts_capabilities(self) -> TTSProviderCapabilities:
        """Bind one immutable capability declaration to the current epoch."""
        if self.tts_provider is None:
            raise TTSProviderPortError("VOICE-TTS-PROVIDER-MISSING")
        if self._tts_capabilities_cache is None:
            self._tts_capabilities_cache = coerce_capabilities(
                self.tts_provider.describe_capabilities()
            )
        return self._tts_capabilities_cache

    def _tts_provider_health_snapshot(self) -> Optional[dict]:
        provider = self.tts_provider
        if provider is None:
            return None
        try:
            value = provider.health()
            if inspect.isawaitable(value):
                return {"state": "unavailable", "error_code": "VOICE-TTS-ASYNC-HEALTH"}
            return dict(value) if isinstance(value, Mapping) else {"value": str(value)[:160]}
        except Exception as exc:
            return {
                "state": "failed",
                "error_code": "VOICE-TTS-HEALTH-ERROR",
                "detail": str(exc)[:160],
            }

    def _tts_provider_metrics_snapshot(self) -> Optional[dict]:
        self._prune_tts_controls()
        active = []
        for speech_id, session in tuple(self._tts_sessions.items()):
            try:
                value = session.metrics()
                if inspect.isawaitable(value):
                    value = {"state": "unavailable", "error_code": "VOICE-TTS-ASYNC-METRICS"}
                elif isinstance(value, Mapping):
                    value = dict(value)
                else:
                    value = {"value": str(value)[:160]}
            except Exception as exc:
                value = {"state": "failed", "error_code": "VOICE-TTS-METRICS-ERROR", "detail": str(exc)[:160]}
            active.append({"speech_id": speech_id, "metrics": value})
        if active:
            return {"active": active, "last": self._last_tts_metrics}
        return self._last_tts_metrics

    def _playback_health_snapshot(self) -> Optional[dict]:
        """Expose only bounded operational playback state, never audio data."""
        playback = self.playback
        method = getattr(playback, "health", None) if playback is not None else None
        if not callable(method):
            return None
        try:
            value = method()
            if inspect.isawaitable(value):
                close = getattr(value, "close", None)
                if callable(close):
                    close()
                return {"error_code": "VOICE-PLAYBACK-ASYNC-HEALTH"}
            if not isinstance(value, Mapping):
                return {"error_code": "VOICE-PLAYBACK-HEALTH-INVALID"}
            allowed = {
                "state",
                "started",
                "stream_active",
                "device",
                "sample_rate",
                "channels",
                "playing",
                "queue_depth",
                "queue_duration_ms",
                "active_turn_id",
                "generation",
                "last_error_code",
            }
            return {
                str(key): value[key]
                for key in allowed
                if key in value
                and isinstance(value[key], (str, int, float, bool, type(None)))
            }
        except Exception as exc:
            return {
                "error_code": "VOICE-PLAYBACK-HEALTH-ERROR",
                "detail": type(exc).__name__,
            }

    def _prune_tts_controls(self) -> None:
        for turn_id, control in tuple(self._tts_controls.items()):
            if not control.needs_terminal_observation:
                self._tts_controls.pop(turn_id, None)

    async def _await_task_shutdown(
        self,
        task: Optional[asyncio.Task],
        *,
        timeout_s: float,
    ) -> bool:
        """Force and bounded-wait an owned task after Kernel invalidation."""
        if task is None or task is asyncio.current_task():
            return task is None or task.done()
        if not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=max(float(timeout_s), 0.05),
            )
        except asyncio.TimeoutError:
            return False
        except asyncio.CancelledError:
            # A provider task may propagate cancellation instead of returning
            # a PipelineOutcome; it is still terminal once the task is done.
            return task.done()
        except Exception:
            # Consume provider exceptions here so shutdown cannot create an
            # unobserved-task warning.  Kernel already recorded the turn error.
            return task.done()
        return task.done()

    async def _run_turn(
        self,
        lease: TurnLease,
        text: str,
        signal: CancellationSignal,
    ) -> PipelineOutcome:
        if self.tts_provider is not None:
            return await self._run_turn_with_tts_provider(lease, text, signal)
        response_parts = []
        speech_id = "speech_" + uuid.uuid4().hex
        speaking = False
        try:
            generator = await _invoke_provider(self.reasoner.generate, text, signal)
            async for chunk in _aiter(generator):
                if signal.is_cancelled() or not self.kernel.is_current(lease):
                    return PipelineOutcome("interrupted", lease.turn_id, "".join(response_parts))
                chunk_text = str(chunk or "")
                if not chunk_text:
                    continue
                response_parts.append(chunk_text)
                event = self.kernel.publish_output(
                    lease,
                    EventKind.TOKEN,
                    {"text": chunk_text, "index": len(response_parts) - 1},
                )
                if event is None:
                    return PipelineOutcome("interrupted", lease.turn_id, "".join(response_parts))

            full_text = "".join(response_parts)
            if self.speech is not None and full_text:
                speech_generator = await _invoke_provider(
                    self.speech.synthesize,
                    full_text,
                    signal,
                )
                async for raw_chunk in _audio_iter(speech_generator):
                    if signal.is_cancelled() or not self.kernel.is_current(lease):
                        return PipelineOutcome("interrupted", lease.turn_id, full_text)
                    chunk = _coerce_audio(raw_chunk)
                    if not speaking:
                        if not self.kernel.mark_speaking(lease, speech_id):
                            return PipelineOutcome("interrupted", lease.turn_id, full_text)
                        speaking = True
                    self.kernel.publish_output(
                        lease,
                        EventKind.AUDIO_CHUNK,
                        {
                            "speech_id": speech_id,
                            "sample_rate": chunk.sample_rate,
                            "channels": chunk.channels,
                            "format": chunk.format,
                            "duration_ms": _duration_ms(chunk),
                        },
                    )
                    if self.playback is not None:
                        await self._play_audio_chunk(chunk, lease, signal)
                if speaking:
                    if not await self._finish_playback(lease, signal):
                        return PipelineOutcome("interrupted", lease.turn_id, full_text)
                    self.kernel.publish_output(
                        lease,
                        EventKind.AUDIO_DONE,
                        {"speech_id": speech_id, "normal": True},
                    )

            if signal.is_cancelled() or not self.kernel.is_current(lease):
                return PipelineOutcome("interrupted", lease.turn_id, full_text)
            self.kernel.complete_turn(lease, committed=False)
            outcome = PipelineOutcome("completed", lease.turn_id, full_text, committed=False)
            self._notify_turn_observer(lease, text, outcome)
            return outcome
        except asyncio.CancelledError:
            # ``interrupt`` invalidates the lease before cancelling this task;
            # no normal completion or audio-done event can be emitted here.
            return PipelineOutcome("interrupted", lease.turn_id, "".join(response_parts))
        except TTSProviderPortError as exc:
            if self.kernel.is_current(lease):
                signal.mark_done()
                await self.kernel.fail_active_turn_async(exc.code, exc.detail)
            return PipelineOutcome(
                "failed",
                lease.turn_id,
                "".join(response_parts),
                error_code=exc.code,
            )
        except Exception as exc:
            if self.kernel.is_current(lease):
                # Mark the worker terminal before the Kernel waits on its
                # cancellation handle.  The worker returns immediately after
                # the failure event is closed, so this does not expose output.
                signal.mark_done()
                await self.kernel.fail_active_turn_async("PIPELINE_ERROR", str(exc))
            return PipelineOutcome(
                "failed",
                lease.turn_id,
                "".join(response_parts),
                error_code="PIPELINE_ERROR",
            )
        finally:
            signal.mark_done()
            self._tasks.pop(lease.turn_id, None)
            self._signals.pop(lease.turn_id, None)

    async def _run_turn_with_tts_provider(
        self,
        lease: TurnLease,
        text: str,
        signal: CancellationSignal,
    ) -> PipelineOutcome:
        """Run reasoning and a text/audio dual stream through the new port."""
        response_parts = []
        speech_id = "speech_" + uuid.uuid4().hex
        session = None
        audio_task: Optional[asyncio.Task] = None
        normalizer: Optional[TTSStreamNormalizer] = None
        owner_task = asyncio.current_task()
        provider_state: Dict[str, Any] = {
            "speaking": False,
            "done": False,
            "committed": False,
            "error": None,
            "handling_error": False,
        }
        try:
            if signal.is_cancelled() or not self.kernel.is_current(lease):
                return PipelineOutcome("interrupted", lease.turn_id)
            capabilities = self._get_tts_capabilities()
            request = TTSRequest(
                session_id=lease.session_id,
                turn_id=lease.turn_id,
                speech_id=speech_id,
                provider_epoch=self._tts_provider_epoch,
                voice_id=self.tts_voice_id,
                style=self.tts_style,
            )
            session = await _invoke_provider(self.tts_provider.open, request)
            if not is_tts_provider_session(session):
                raise TTSProviderPortError(
                    "VOICE-TTS-SESSION-INVALID",
                    "provider.open() did not return TTSProviderSession",
                )
            self._tts_sessions[speech_id] = session
            control = self._tts_controls.get(lease.turn_id)
            if control is None:
                raise TTSProviderPortError(
                    "VOICE-TTS-CONTROL-MISSING",
                    "provider turn control was not registered",
                )
            cancel_won_race = control.attach(session)
            if cancel_won_race:
                await _maybe_await(session.cancel("turn_cancelled"))
            normalizer = TTSStreamNormalizer(request, capabilities)
            audio_task = asyncio.create_task(
                self._consume_tts_provider_audio(
                    lease,
                    signal,
                    session,
                    request,
                    capabilities,
                    normalizer,
                    speech_id,
                    provider_state,
                )
            )
            # Audio is a concurrent half of the turn.  A provider failure must
            # interrupt a stalled reasoner immediately; waiting for another
            # token would otherwise leave the turn alive indefinitely.
            audio_task.add_done_callback(
                lambda completed: self._tts_audio_task_done(
                    completed,
                    signal,
                    provider_state,
                    owner_task,
                )
            )

            generator = await _invoke_provider(self.reasoner.generate, text, signal)
            async for chunk in _aiter(generator):
                if signal.is_cancelled() or not self.kernel.is_current(lease):
                    return PipelineOutcome("interrupted", lease.turn_id, "".join(response_parts))
                if audio_task.done():
                    if audio_task.cancelled():
                        return PipelineOutcome("interrupted", lease.turn_id, "".join(response_parts))
                    audio_error = audio_task.exception()
                    if audio_error is not None:
                        raise audio_error
                chunk_text = str(chunk or "")
                if not chunk_text:
                    continue
                response_parts.append(chunk_text)
                event = self.kernel.publish_output(
                    lease,
                    EventKind.TOKEN,
                    {"text": chunk_text, "index": len(response_parts) - 1},
                )
                if event is None:
                    return PipelineOutcome("interrupted", lease.turn_id, "".join(response_parts))
                # This is the NEKO-style text half of the dual stream.  A
                # provider that internally buffers still remains B by its
                # declared capability; the chain does not hide that fact.
                await _invoke_provider(session.push_text, chunk_text)
                self.kernel.record_system_event(
                    EventKind.TASK,
                    {
                        "component": "tts",
                        "event_kind": "TTS_TEXT",
                        "speech_id": speech_id,
                        "provider_epoch": request.provider_epoch,
                        "index": len(response_parts) - 1,
                        "text": chunk_text,
                        "final": False,
                    },
                    generation=lease.generation,
                    turn_id=lease.turn_id,
                    trace_id=lease.trace_id,
                )

            full_text = "".join(response_parts)
            await _invoke_provider(session.commit_text)
            # Mark the commit only after the provider accepted it.  Audio can
            # race with this await; DONE observed before its return must fail
            # closed instead of being treated as a valid flush.
            provider_state["committed"] = True
            self.kernel.record_system_event(
                EventKind.TASK,
                {
                    "component": "tts",
                    "event_kind": "TTS_TEXT",
                    "speech_id": speech_id,
                    "provider_epoch": request.provider_epoch,
                    "final": True,
                },
                generation=lease.generation,
                turn_id=lease.turn_id,
                trace_id=lease.trace_id,
            )
            await audio_task
            if signal.is_cancelled() or not self.kernel.is_current(lease):
                return PipelineOutcome("interrupted", lease.turn_id, full_text)
            if not provider_state["done"]:
                raise TTSProviderPortError(
                    "VOICE-TTS-NO-DONE",
                    "provider audio stream ended without DONE",
                )
            self.kernel.complete_turn(lease, committed=False)
            outcome = PipelineOutcome("completed", lease.turn_id, full_text, committed=False)
            self._notify_turn_observer(lease, text, outcome)
            return outcome
        except asyncio.CancelledError:
            provider_error = provider_state.get("error")
            if (
                provider_error is not None
                and signal.cancel_reason == "tts_provider_error"
            ):
                provider_state["handling_error"] = True
                if audio_task is not None:
                    if not audio_task.done():
                        audio_task.cancel()
                    await asyncio.gather(audio_task, return_exceptions=True)
                if isinstance(provider_error, TTSProviderPortError):
                    error_code = provider_error.code
                    error_detail = provider_error.detail
                else:
                    error_code = "PIPELINE_ERROR"
                    error_detail = str(provider_error)
                if self.kernel.is_current(lease):
                    signal.mark_done()
                    await self.kernel.fail_active_turn_async(error_code, error_detail)
                return PipelineOutcome(
                    "failed",
                    lease.turn_id,
                    "".join(response_parts),
                    error_code=error_code,
                )
            # A caller may cancel the owner task directly (for example a
            # runtime timeout) without going through the Kernel handle.  Make
            # sure the provider still receives one stop request.
            if not signal.is_cancelled():
                signal.cancel("turn_cancelled")
            if audio_task is not None:
                if not audio_task.done():
                    audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)
            return PipelineOutcome("interrupted", lease.turn_id, "".join(response_parts))
        except TTSProviderPortError as exc:
            provider_state["handling_error"] = True
            if not signal.is_cancelled():
                signal.cancel("tts_provider_error")
            if audio_task is not None:
                if not audio_task.done():
                    audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)
            if self.kernel.is_current(lease):
                signal.mark_done()
                await self.kernel.fail_active_turn_async(exc.code, exc.detail)
            return PipelineOutcome(
                "failed",
                lease.turn_id,
                "".join(response_parts),
                error_code=exc.code,
            )
        except Exception as exc:
            provider_state["handling_error"] = True
            if not signal.is_cancelled():
                signal.cancel("tts_pipeline_error")
            if audio_task is not None:
                if not audio_task.done():
                    audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)
            if self.kernel.is_current(lease):
                signal.mark_done()
                await self.kernel.fail_active_turn_async("PIPELINE_ERROR", str(exc))
            return PipelineOutcome(
                "failed",
                lease.turn_id,
                "".join(response_parts),
                error_code="PIPELINE_ERROR",
            )
        finally:
            if audio_task is not None:
                if not audio_task.done():
                    audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)
            if normalizer is not None:
                try:
                    provider_metrics = session.metrics() if session is not None else {}
                    if inspect.isawaitable(provider_metrics):
                        provider_metrics = {}
                    normalizer.update_provider_metrics(provider_metrics)
                    self._last_tts_metrics = normalizer.metrics(
                        state="stopped" if signal.is_cancelled() else "ready"
                    ).to_dict()
                    self.kernel.record_system_event(
                        EventKind.TASK,
                        {
                            "component": "tts",
                            "event_kind": "METRICS",
                            "speech_id": speech_id,
                            "provider_epoch": self._tts_provider_epoch,
                            "metrics": self._last_tts_metrics,
                        },
                        generation=lease.generation,
                        turn_id=lease.turn_id,
                        trace_id=lease.trace_id,
                    )
                except Exception:
                    self._last_tts_metrics = None
            self._tts_sessions.pop(speech_id, None)
            control = self._tts_controls.get(lease.turn_id)
            if control is not None:
                control.mark_closed()
                keep_for_terminal_observation = (
                    control.cancel_requested and control.needs_terminal_observation
                )
                if keep_for_terminal_observation:
                    # A failed turn can reach this path through the provider
                    # audio task rather than ``interrupt()``.  Preserve the
                    # same strict idle gate until a later stop observation
                    # confirms the worker is really gone.
                    self._tts_cleanup_blocked = True
                if not keep_for_terminal_observation:
                    self._tts_controls.pop(lease.turn_id, None)
            signal.mark_done()
            self._tasks.pop(lease.turn_id, None)
            self._signals.pop(lease.turn_id, None)

    def _tts_audio_task_done(
        self,
        task: asyncio.Task,
        signal: CancellationSignal,
        state: Dict[str, Any],
        owner_task: Optional[asyncio.Task],
    ) -> None:
        """Propagate an audio-half failure while the text half is waiting."""
        if task.cancelled() or state.get("handling_error"):
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is None:
            return
        state["error"] = error
        # Keep user cancellation authoritative when it won the race.  A
        # provider error gets its own reason so the owner can emit an ERROR
        # event instead of incorrectly reporting an interruption.
        if not signal.is_cancelled():
            signal.cancel("tts_provider_error")
        elif signal.cancel_reason == "tts_provider_error":
            return
        if owner_task is not None and not owner_task.done():
            owner_task.cancel()

    async def _consume_tts_provider_audio(
        self,
        lease: TurnLease,
        signal: CancellationSignal,
        session: Any,
        request: TTSRequest,
        capabilities: TTSProviderCapabilities,
        normalizer: TTSStreamNormalizer,
        speech_id: str,
        state: Dict[str, Any],
    ) -> None:
        """Consume provider events while reasoning continues pushing text."""
        provider_sequence = 0
        try:
            events = await _invoke_provider(session.audio_events)
            async for raw_event in _audio_event_iter(events):
                event = coerce_provider_event(
                    raw_event,
                    request=request,
                    default_sequence=provider_sequence,
                )
                if event.kind == TTSEventKind.DONE.value and not state["committed"]:
                    raise TTSProviderPortError(
                        "VOICE-TTS-DONE-BEFORE-COMMIT",
                        "provider emitted DONE before commit_text",
                    )
                if (
                    event.kind == TTSEventKind.PCM_CHUNK.value
                    and event.speech_id == request.speech_id
                    and event.provider_epoch == request.provider_epoch
                ):
                    provider_sequence += 1
                for normalized in normalizer.accept(event):
                    if normalized.kind == TTSEventKind.READY.value:
                        self.kernel.record_system_event(
                            EventKind.TASK,
                            {
                                "component": "tts",
                                "event_kind": "READY",
                                "provider_id": capabilities.provider_id,
                                "speech_id": speech_id,
                                "provider_epoch": request.provider_epoch,
                            },
                            generation=lease.generation,
                            turn_id=lease.turn_id,
                            trace_id=lease.trace_id,
                        )
                        continue
                    if normalized.kind == TTSEventKind.FIRST_CHUNK.value:
                        self.kernel.record_system_event(
                            EventKind.TASK,
                            {
                                "component": "tts",
                                "event_kind": "FIRST_CHUNK",
                                "speech_id": speech_id,
                                "provider_epoch": request.provider_epoch,
                                "first_chunk_ms": normalizer.first_chunk_ms,
                            },
                            generation=lease.generation,
                            turn_id=lease.turn_id,
                            trace_id=lease.trace_id,
                        )
                        continue
                    if normalized.kind == TTSEventKind.PCM_CHUNK.value:
                        if signal.is_cancelled() or not self.kernel.is_current(lease):
                            continue
                        chunk = normalized.chunk
                        if chunk is None:
                            continue
                        if not state["speaking"]:
                            if not self.kernel.mark_speaking(lease, speech_id):
                                continue
                            state["speaking"] = True
                        self.kernel.publish_output(
                            lease,
                            EventKind.AUDIO_CHUNK,
                            {
                                "speech_id": speech_id,
                                "provider_id": capabilities.provider_id,
                                "provider_epoch": request.provider_epoch,
                                "sample_rate": chunk.sample_rate,
                                "channels": chunk.channels,
                                "format": chunk.format,
                                "duration_ms": chunk.duration_ms,
                                "sequence": chunk.sequence,
                            },
                        )
                        if self.playback is not None:
                            # Legacy playback adapters consume TargetVoiceChain
                            # AudioChunk; this conversion stays at the edge.
                            await self._play_audio_chunk(
                                AudioChunk(
                                    chunk.data,
                                    chunk.sample_rate,
                                    chunk.channels,
                                    "pcm_s16le",
                                ),
                                lease,
                                signal,
                            )
                        continue
                    if normalized.kind == TTSEventKind.DONE.value:
                        if state["speaking"] and self.kernel.is_current(lease):
                            drained = await self._finish_playback(lease, signal)
                            if not drained:
                                if signal.is_cancelled() or not self.kernel.is_current(lease):
                                    return
                                raise TTSProviderPortError(
                                    "VOICE-PLAYBACK-DRAIN-UNCONFIRMED",
                                    "playback did not confirm physical drain",
                                )
                            self.kernel.publish_output(
                                lease,
                                EventKind.AUDIO_DONE,
                                {
                                    "speech_id": speech_id,
                                    "provider_id": capabilities.provider_id,
                                    "provider_epoch": request.provider_epoch,
                                    "normal": True,
                                },
                            )
                        state["done"] = True
                        continue
                    if normalized.kind == TTSEventKind.STOPPED.value:
                        continue
            if not signal.is_cancelled() and not state["done"]:
                raise TTSProviderPortError(
                    "VOICE-TTS-NO-DONE",
                    "provider audio iterator ended before DONE",
                )
        except asyncio.CancelledError:
            raise


    async def _play_audio_chunk(
        self,
        chunk: AudioChunk,
        lease: TurnLease,
        signal: CancellationSignal,
    ) -> bool:
        """Queue one block and make its physical ownership visible to TTS."""
        playback = self.playback
        if playback is None:
            return True
        result = await _invoke_provider(playback.play, chunk, lease, signal)
        if result is False:
            if signal.is_cancelled() or not self.kernel.is_current(lease):
                return False
            raise TTSProviderPortError(
                "VOICE-PLAYBACK-REJECTED",
                "playback rejected a current PCM block",
            )
        self._sync_tts_playback_state(active=True)
        return True

    async def _finish_playback(
        self,
        lease: TurnLease,
        signal: CancellationSignal,
    ) -> bool:
        """Wait for a new playback port's callback drain before AUDIO_DONE."""
        method = self._playback_finish_method()
        if method is None:
            return True
        result = await _invoke_provider(method, lease, signal)
        if result:
            self._sync_tts_playback_state(active=False)
            return True
        if signal.is_cancelled() or not self.kernel.is_current(lease):
            return False
        raise TTSProviderPortError(
            "VOICE-PLAYBACK-DRAIN-UNCONFIRMED",
            "playback did not confirm physical drain",
        )

    def _sync_tts_playback_state(self, *, active: Optional[bool] = None) -> None:
        """Keep the provider's strict-idle gate behind actual playback state."""
        provider = self.tts_provider
        setter = getattr(provider, "set_playback_state", None) if provider is not None else None
        if not callable(setter):
            return
        health = self._playback_health_snapshot() or {}
        queue_depth = _nonnegative_int(health.get("queue_depth", 0))
        queue_duration_ms = _nonnegative_int(health.get("queue_duration_ms", 0))
        if active is None:
            active = bool(
                health.get("playing")
                or health.get("active_turn_id")
                or queue_depth
                or queue_duration_ms
            )
        try:
            result = setter(
                active=bool(active),
                queue_depth=queue_depth,
                queue_duration_ms=queue_duration_ms,
            )
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                raise TTSProviderPortError(
                    "VOICE-TTS-PLAYBACK-STATE-ASYNC",
                    "playback state updates must be synchronous",
                )
        except TTSProviderPortError:
            raise
        except Exception as exc:
            raise TTSProviderPortError(
                "VOICE-TTS-PLAYBACK-STATE-SYNC-FAILED",
                type(exc).__name__,
            ) from exc

    def _playback_cancel_callback(self, reason: str = "turn_cancelled") -> Any:
        """Stop queued audio but retain a busy gate until silence is observed."""
        if self.playback is None:
            return None
        method = None
        for name in ("interrupt", "stop", "cancel"):
            candidate = getattr(self.playback, name, None)
            if callable(candidate):
                method = candidate
                break
        if method is None:
            return None
        try:
            try:
                result = method(str(reason or "turn_cancelled")[:160])
            except TypeError:
                result = method()
            # The device callback may still contain an old tail even after its
            # queue is cleared.  ``wait_stopped`` will clear this gate only
            # after it observes a silent callback.
            self._sync_tts_playback_state(active=True)
            return result
        except Exception as exc:
            self.kernel.record_system_event(
                EventKind.ERROR,
                {
                    "code": "VOICE-TTS-PLAYBACK-STATE-SYNC-FAILED",
                    "component": "target_chain",
                    "detail": type(exc).__name__,
                    "retryable": True,
                },
            )
            raise

    def _speech_cancel_callback(self) -> Any:
        """Ask the injected TTS adapter to stop generating old audio."""
        if self.speech is None:
            return None
        for name in ("interrupt", "stop", "cancel"):
            method = getattr(self.speech, name, None)
            if callable(method):
                return method()
        return None

    def _speech_stop_waiter(self) -> Optional[Any]:
        """Return explicit physical-stop evidence if the TTS adapter offers it."""
        if self.speech is None:
            return None
        method = getattr(self.speech, "wait_stopped", None)
        return method if callable(method) else None

    def _speech_cancel_supported(self) -> bool:
        if self.speech is None:
            return False
        return any(
            callable(getattr(self.speech, name, None))
            for name in ("interrupt", "stop", "cancel")
        )

    def _playback_stop_waiter(self) -> Optional[Any]:
        """Return explicit physical-stop evidence if the adapter offers it."""
        if self.playback is None:
            return None
        method = getattr(self.playback, "wait_stopped", None)
        if not callable(method):
            return None

        async def wait_for_playback_stop(timeout_s: float) -> bool:
            confirmed = bool(await _invoke_provider(method, timeout_s))
            self._sync_tts_playback_state(active=not confirmed)
            return confirmed

        return wait_for_playback_stop

    def _playback_finish_method(self) -> Optional[Any]:
        if self.playback is None:
            return None
        method = getattr(self.playback, "finish", None)
        return method if callable(method) else None

    def _playback_cancel_supported(self) -> bool:
        if self.playback is None:
            return False
        return any(
            callable(getattr(self.playback, name, None))
            for name in ("interrupt", "stop", "cancel")
        )


async def _audio_event_iter(value: Any) -> AsyncIterator[Any]:
    """Adapt provider event streams without treating mappings as iterables."""
    if inspect.isawaitable(value):
        value = await value
    if hasattr(value, "__aiter__"):
        async for item in value:
            yield item
        return
    if isinstance(value, Mapping):
        yield value
        return
    async for item in _aiter(value):
        yield item

def _duration_ms(chunk: AudioChunk) -> int:
    try:
        samples = chunk.samples
        if isinstance(samples, (bytes, bytearray, memoryview)):
            sample_count = len(samples) // 2 // max(chunk.channels, 1)
        else:
            shape = getattr(samples, "shape", None)
            sample_count = int(shape[0]) if shape else len(samples)
        return int(round(sample_count * 1000 / chunk.sample_rate))
    except Exception:
        return 0


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


async def _await_cancel_callback(awaitable: Any) -> None:
    await awaitable


def _consume_async_cancel_task(task: asyncio.Task) -> None:
    """Consume asynchronous cancel-hook failures after logging them."""
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("asynchronous cancellation callback failed")


def _consume_async_cancel_future(future: Any) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("cross-thread cancellation callback failed")


async def _await_terminal_waiter(waiter: Any, timeout_s: float) -> bool:
    """Run a sync or async terminal observer without blocking cancellation."""
    try:
        if timeout_s <= 0:
            # Give an async observer one scheduling turn so it can perform an
            # instantaneous state read (and leave an audit count), but never
            # let it wait beyond the exhausted cancellation budget.
            if inspect.iscoroutinefunction(waiter):
                task = asyncio.create_task(waiter(0.0))
                await asyncio.sleep(0)
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    return False
                return bool(task.result())
            task = asyncio.create_task(asyncio.to_thread(waiter, 0.0))
            task.add_done_callback(_consume_background_task)
            await asyncio.sleep(0)
            if not task.done():
                return False
            result = task.result()
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                return False
            return bool(result)
        if inspect.iscoroutinefunction(waiter):
            result = waiter(timeout_s)
        else:
            task = asyncio.create_task(asyncio.to_thread(waiter, timeout_s))
            task.add_done_callback(_consume_background_task)
            try:
                result = await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
            except asyncio.TimeoutError:
                return False
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout=timeout_s)
        return bool(result)
    except (asyncio.TimeoutError, TimeoutError):
        return False


def _consume_background_task(task: asyncio.Task) -> None:
    """Consume late observer results so cancellation never leaks warnings."""
    if task.cancelled():
        return
    try:
        result = task.result()
    except Exception:
        return
    if inspect.isawaitable(result):
        close = getattr(result, "close", None)
        if callable(close):
            close()


__all__ = [
    "AudioChunk",
    "CancellationSignal",
    "PlaybackStopObserver",
    "SpeechStopObserver",
    "PipelineError",
    "PipelineOutcome",
    "PipelineSubmission",
    "TargetVoiceChain",
]
