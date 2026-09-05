"""Session ownership, cancellation, and capability negotiation for the voice path.

This module intentionally depends only on the Python standard library.  Provider,
device, transport, and database adapters must use this boundary instead of owning
turn state themselves.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple, Union


PROTOCOL_VERSION = "1.0"


class KernelError(RuntimeError):
    """Raised when an adapter violates the session lifecycle."""


class KernelState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    RECOVERING = "recovering"
    FAILED = "failed"
    STOPPED = "stopped"


class TurnState(str, Enum):
    RECEIVING = "receiving"
    THINKING = "thinking"
    SPEAKING = "speaking"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class DuplexMode(str, Enum):
    C = "C"
    B = "B"


class AudioRoute(str, Enum):
    SPEAKER_MIC = "speaker_mic"
    HEADSET = "headset"
    UNKNOWN = "unknown"


class EventKind(str, Enum):
    CAPABILITY = "CAPABILITY"
    STATE = "STATE"
    TURN_OPENED = "TURN_OPENED"
    INPUT_FINAL = "INPUT_FINAL"
    TOKEN = "TOKEN"
    AUDIO_START = "AUDIO_START"
    AUDIO_CHUNK = "AUDIO_CHUNK"
    AUDIO_DONE = "AUDIO_DONE"
    INTERRUPT = "INTERRUPT"
    COMPLETE = "COMPLETE"
    TASK = "TASK"
    ERROR = "ERROR"
    STALE = "STALE"


class ErrorCode(str, Enum):
    CAPABILITY_DEGRADED = "VOICE-CAPABILITY-DEGRADED"
    INVALID_TRANSITION = "VOICE-INVALID-TRANSITION"
    STALE_EVENT = "VOICE-STALE-EVENT"
    TASK_CANCEL_FAILED = "VOICE-CANCEL-FAILED"
    TASK_CANCEL_TIMEOUT = "VOICE-CANCEL-TIMEOUT"
    MEMORY_WRITE_BLOCKED = "MEMORY-WRITE-BLOCKED"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Capabilities that distinguish a verified C path from a B fallback."""

    continuous_capture: bool = False
    concurrent_input_output: bool = False
    audio_route: str = AudioRoute.UNKNOWN.value
    audio_route_verified: bool = False
    vad_verified: bool = False
    wake_word_verified: bool = False
    aec_reference_available: bool = False
    aec_verified: bool = False
    echo_isolation_verified: bool = False
    asr_tts_concurrent: bool = False
    cancel_asr: bool = False
    cancel_generation: bool = False
    cancel_tts: bool = False
    cancel_playback: bool = False
    playback_verified: bool = False
    resource_budget_verified: bool = False

    def assess(self) -> "CapabilityAssessment":
        required = (
            ("continuous_capture", self.continuous_capture),
            ("concurrent_input_output", self.concurrent_input_output),
            ("audio_route_verified", self.audio_route_verified),
            ("vad_verified", self.vad_verified),
            ("wake_word_verified", self.wake_word_verified),
            ("asr_tts_concurrent", self.asr_tts_concurrent),
            ("cancel_asr", self.cancel_asr),
            ("cancel_generation", self.cancel_generation),
            ("cancel_tts", self.cancel_tts),
            ("cancel_playback", self.cancel_playback),
            ("playback_verified", self.playback_verified),
            ("resource_budget_verified", self.resource_budget_verified),
        )
        missing = [name for name, available in required if not available]
        try:
            route = AudioRoute(self.audio_route)
        except ValueError:
            route = AudioRoute.UNKNOWN
            missing.append("audio_route")
        if route == AudioRoute.SPEAKER_MIC:
            if not self.aec_reference_available:
                missing.append("aec_reference_available")
            if not self.aec_verified:
                missing.append("aec_verified")
        elif route == AudioRoute.HEADSET:
            if not self.echo_isolation_verified:
                missing.append("echo_isolation_verified")
        else:
            missing.append("audio_route_identified")
        return CapabilityAssessment(
            mode=DuplexMode.C if not missing else DuplexMode.B,
            missing_for_c=tuple(dict.fromkeys(missing)),
        )


@dataclass(frozen=True)
class CapabilityAssessment:
    mode: DuplexMode
    missing_for_c: Tuple[str, ...] = ()

    @property
    def c_verified(self) -> bool:
        return self.mode == DuplexMode.C


@dataclass(frozen=True)
class TurnLease:
    """Opaque lease that adapters must present before publishing output."""

    session_id: str
    turn_id: str
    generation: int
    trace_id: str


@dataclass(frozen=True)
class SessionEvent:
    protocol_version: str
    session_id: str
    turn_id: Optional[str]
    generation: int
    seq: int
    kind: str
    actor: str
    timestamp: str
    trace_id: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, redact: bool = False) -> Dict[str, Any]:
        payload = _sanitize_payload(self.payload) if redact else dict(self.payload)
        return {
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "generation": self.generation,
            "seq": self.seq,
            "kind": self.kind,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "payload": payload,
        }


@dataclass
class CancellationHandle:
    """Adapter-owned work with an optional observable terminal state."""

    name: str
    cancel: Callable[[], Any]
    wait_terminal: Optional[Callable[[float], Any]] = None


@dataclass(frozen=True)
class AbortResult:
    requested: bool
    turn_id: Optional[str]
    generation: int
    completed_tasks: Tuple[str, ...] = ()
    timed_out_tasks: Tuple[str, ...] = ()
    failed_tasks: Tuple[str, ...] = ()


@dataclass
class _TurnRecord:
    lease: TurnLease
    source: str
    input_type: str
    state: TurnState = TurnState.RECEIVING
    opened_at: float = field(default_factory=time.time)
    terminal_reason: str = ""


@dataclass(frozen=True)
class _AbortPlan:
    record: _TurnRecord
    handles: Tuple[CancellationHandle, ...]
    reason: str
    outcome: str
    generation: int


_REDACTED_KEYS = {
    "audio",
    "audio_ref",
    "content",
    "input",
    "raw_audio",
    "text",
    "transcript",
}


def _sanitize_payload(value: Any, key: str = "") -> Any:
    """Keep operational journals useful without persisting user media or text."""
    if key.lower() in _REDACTED_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): _sanitize_payload(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventJournal:
    """Bounded, redacted runtime event retention with optional JSONL persistence."""

    def __init__(
        self,
        path: Optional[Union[str, Path]] = None,
        memory_limit: int = 2048,
    ) -> None:
        if memory_limit <= 0:
            raise ValueError("memory_limit must be positive")
        self._path = Path(path) if path else None
        self._events: Deque[Dict[str, Any]] = deque(maxlen=memory_limit)
        self._lock = threading.RLock()

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def append(self, event: SessionEvent) -> Dict[str, Any]:
        record = event.to_dict(redact=True)
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._events.append(record)
            if self._path:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(encoded + "\n")
        return record

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            if limit <= 0:
                return []
            # Consumers may annotate a snapshot; never let that mutate the
            # retained audit record (including nested payload dictionaries).
            return copy.deepcopy(list(self._events)[-limit:])


class SessionKernel:
    """The sole owner of a session's active turn and cancellation generation."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        journal: Optional[EventJournal] = None,
    ) -> None:
        self.session_id = session_id or "sess_" + uuid.uuid4().hex
        self._journal = journal or EventJournal()
        self._state_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._state = KernelState.STARTING
        self._duplex = CapabilityAssessment(DuplexMode.B, ("not_assessed",))
        self._generation = 0
        self._seq = 0
        self._active: Optional[_TurnRecord] = None
        self._tasks: Dict[str, List[CancellationHandle]] = {}
        self._abort_in_progress = False

    @property
    def state(self) -> KernelState:
        with self._state_lock:
            return self._state

    @property
    def duplex(self) -> CapabilityAssessment:
        with self._state_lock:
            return self._duplex

    def start(self, capabilities: ProviderCapabilities) -> CapabilityAssessment:
        with self._lifecycle_lock:
            with self._state_lock:
                if self._state == KernelState.STOPPED:
                    raise KernelError("stopped session cannot be restarted")
                self._duplex = capabilities.assess()
                self._emit_locked(
                    EventKind.CAPABILITY,
                    "system",
                    None,
                    self._generation,
                    "",
                    {
                        "mode": self._duplex.mode.value,
                        "c_verified": self._duplex.c_verified,
                        "missing_for_c": list(self._duplex.missing_for_c),
                        "audio_route": capabilities.audio_route,
                    },
                )
                if not self._duplex.c_verified:
                    self._emit_locked(
                        EventKind.ERROR,
                        "system",
                        None,
                        self._generation,
                        "",
                        {
                            "code": ErrorCode.CAPABILITY_DEGRADED.value,
                            "retryable": True,
                            "component": "duplex_capability",
                            "mode": DuplexMode.B.value,
                            "missing_for_c": list(self._duplex.missing_for_c),
                        },
                    )
                self._transition_locked(KernelState.READY, "capability_assessed")
                return self._duplex

    def degrade_capability(
        self,
        missing: Union[str, Tuple[str, ...], List[str]],
        *,
        reason: str = "runtime_degraded",
        component: str = "runtime",
    ) -> CapabilityAssessment:
        """Apply a monotonic runtime downgrade without cancelling the turn.

        A capability can be verified at startup and then become unavailable
        while a session is running (for example, an AEC reference disappears).
        The downgrade is deliberately separate from turn cancellation: B is a
        valid fallback, while the caller decides whether a particular fault
        also requires an interrupt or a restart.
        """
        if isinstance(missing, str):
            items = (missing,)
        else:
            items = tuple(missing)
        normalized = tuple(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))
        if not normalized:
            raise ValueError("missing must contain at least one capability name")
        safe_reason = str(reason or "runtime_degraded")[:160]
        safe_component = str(component or "runtime")[:160]

        with self._lifecycle_lock:
            with self._state_lock:
                # A stopped kernel cannot be made ready by a late adapter
                # callback.  The adapter event is still relayed separately.
                if self._state == KernelState.STOPPED:
                    return self._duplex
                previous = self._duplex
                merged = tuple(dict.fromkeys((*previous.missing_for_c, *normalized)))
                changed = previous.mode != DuplexMode.B or merged != previous.missing_for_c
                self._duplex = CapabilityAssessment(DuplexMode.B, merged)
                if not changed:
                    return self._duplex

                active = self._active
                turn_id = active.lease.turn_id if active else None
                generation = active.lease.generation if active else self._generation
                trace_id = active.lease.trace_id if active else ""
                payload = {
                    "mode": DuplexMode.B.value,
                    "c_verified": False,
                    "previous_mode": previous.mode.value,
                    "previous_missing_for_c": list(previous.missing_for_c),
                    "missing_for_c": list(merged),
                    "runtime": True,
                    "reason": safe_reason,
                    "component": safe_component,
                }
                self._emit_locked(
                    EventKind.CAPABILITY,
                    "system",
                    turn_id,
                    generation,
                    trace_id,
                    payload,
                )
                self._emit_locked(
                    EventKind.ERROR,
                    "system",
                    turn_id,
                    generation,
                    trace_id,
                    {
                        "code": ErrorCode.CAPABILITY_DEGRADED.value,
                        "retryable": True,
                        "component": safe_component,
                        "mode": DuplexMode.B.value,
                        "missing_for_c": list(merged),
                        "runtime": True,
                        "reason": safe_reason,
                    },
                )
                return self._duplex

    def begin_turn(self, source: str, input_type: str) -> TurnLease:
        with self._lifecycle_lock:
            if self._abort_in_progress:
                self._emit_invalid_transition_locked("begin_turn_during_abort")
                raise KernelError("session is recovering from a cancelled turn")
            if self._active is not None:
                self._abort_active_turn("superseded_by_new_turn", timeout_s=0.0)
            with self._state_lock:
                if self._state not in (KernelState.READY, KernelState.LISTENING):
                    self._emit_invalid_transition_locked("begin_turn")
                    raise KernelError("session is not ready for input: {0}".format(self._state.value))
                turn_id = "turn_" + uuid.uuid4().hex
                trace_id = "trace_" + uuid.uuid4().hex
                lease = TurnLease(
                    session_id=self.session_id,
                    turn_id=turn_id,
                    generation=self._generation,
                    trace_id=trace_id,
                )
                self._active = _TurnRecord(lease=lease, source=source, input_type=input_type)
                self._tasks[turn_id] = []
                self._emit_locked(
                    EventKind.TURN_OPENED,
                    "user",
                    turn_id,
                    lease.generation,
                    trace_id,
                    {"source": source, "input_type": input_type},
                )
                self._transition_locked(KernelState.LISTENING, "turn_opened", lease)
                return lease

    def mark_input_final(self, lease: TurnLease) -> bool:
        with self._state_lock:
            record = self._active_record_locked(lease)
            if record is None:
                self._record_stale_locked(lease, "INPUT_FINAL")
                return False
            if self._state != KernelState.LISTENING or record.state != TurnState.RECEIVING:
                self._emit_invalid_transition_locked("mark_input_final")
                return False
            record.state = TurnState.THINKING
            self._emit_locked(
                EventKind.INPUT_FINAL,
                "user",
                lease.turn_id,
                lease.generation,
                lease.trace_id,
                {"input_type": record.input_type},
            )
            self._transition_locked(KernelState.THINKING, "input_final", lease)
            return True

    def mark_speaking(self, lease: TurnLease, speech_id: str) -> bool:
        with self._state_lock:
            record = self._active_record_locked(lease)
            if record is None:
                self._record_stale_locked(lease, "AUDIO_START")
                return False
            if self._state != KernelState.THINKING or record.state != TurnState.THINKING:
                self._emit_invalid_transition_locked("mark_speaking")
                return False
            record.state = TurnState.SPEAKING
            self._emit_locked(
                EventKind.AUDIO_START,
                "assistant",
                lease.turn_id,
                lease.generation,
                lease.trace_id,
                {"speech_id": speech_id},
            )
            self._transition_locked(KernelState.SPEAKING, "audio_started", lease)
            return True

    def publish_output(
        self,
        lease: TurnLease,
        kind: Union[EventKind, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[SessionEvent]:
        event_kind = kind.value if isinstance(kind, EventKind) else str(kind)
        with self._state_lock:
            if self._active_record_locked(lease) is None:
                self._record_stale_locked(lease, event_kind)
                return None
            if event_kind == EventKind.AUDIO_DONE.value:
                record = self._active
                if record is None or record.state != TurnState.SPEAKING:
                    self._emit_invalid_transition_locked("AUDIO_DONE")
                    return None
            return self._emit_locked(
                event_kind,
                "assistant",
                lease.turn_id,
                lease.generation,
                lease.trace_id,
                payload or {},
            )

    def register_cancellable(self, lease: TurnLease, handle: CancellationHandle) -> bool:
        with self._state_lock:
            if self._active_record_locked(lease) is None:
                self._record_stale_locked(lease, "REGISTER_TASK")
                return False
            self._tasks[lease.turn_id].append(handle)
            self._emit_locked(
                EventKind.TASK,
                "system",
                lease.turn_id,
                lease.generation,
                lease.trace_id,
                {"action": "registered", "task": handle.name},
            )
            return True

    def abort_active_turn(self, reason: str, timeout_s: float = 3.0) -> AbortResult:
        with self._lifecycle_lock:
            return self._abort_active_turn(reason, timeout_s)

    async def abort_active_turn_async(
        self,
        reason: str,
        timeout_s: float = 3.0,
        *,
        _outcome: str = "interrupted",
        _emit_interrupt: bool = True,
    ) -> AbortResult:
        """Cancel a turn without blocking the caller's asyncio event loop."""
        with self._lifecycle_lock:
            with self._state_lock:
                if self._abort_in_progress:
                    return AbortResult(False, None, self._generation)
                active = self._active
                if active is None:
                    return AbortResult(False, None, self._generation)
                self._abort_in_progress = True
                self._generation += 1
                active.state = TurnState.INTERRUPTED
                active.terminal_reason = reason
                handles = tuple(self._tasks.get(active.lease.turn_id, ()))
                self._transition_locked(KernelState.RECOVERING, reason, active.lease)
                if _emit_interrupt:
                    self._emit_locked(
                        EventKind.INTERRUPT,
                        "system",
                        active.lease.turn_id,
                        active.lease.generation,
                        active.lease.trace_id,
                        {"reason": reason, "superseded_generation": self._generation},
                    )

        completed: List[str] = []
        timed_out: List[str] = []
        failed: List[str] = []
        deadline = asyncio.get_running_loop().time() + max(timeout_s, 0.0)
        try:
            for handle in handles:
                try:
                    cancel_result = handle.cancel()
                    if inspect.isawaitable(cancel_result):
                        await cancel_result
                except Exception as exc:
                    failed.append(handle.name)
                    self._record_task_error(active.lease, ErrorCode.TASK_CANCEL_FAILED, handle.name, str(exc))
                    continue
                if handle.wait_terminal is None:
                    completed.append(handle.name)
                    continue
                remaining = max(0.0, deadline - asyncio.get_running_loop().time())
                try:
                    wait_result = await _await_terminal_handle(
                        handle.wait_terminal,
                        remaining,
                    )
                    if wait_result:
                        completed.append(handle.name)
                    else:
                        timed_out.append(handle.name)
                        self._record_task_error(
                            active.lease,
                            ErrorCode.TASK_CANCEL_TIMEOUT,
                            handle.name,
                            "terminal wait elapsed",
                        )
                except (asyncio.TimeoutError, TimeoutError):
                    timed_out.append(handle.name)
                    self._record_task_error(
                        active.lease,
                        ErrorCode.TASK_CANCEL_TIMEOUT,
                        handle.name,
                        "terminal wait elapsed",
                    )
                except Exception as exc:
                    failed.append(handle.name)
                    self._record_task_error(active.lease, ErrorCode.TASK_CANCEL_FAILED, handle.name, str(exc))
        finally:
            with self._lifecycle_lock:
                with self._state_lock:
                    self._tasks.pop(active.lease.turn_id, None)
                    if self._active is active:
                        self._active = None
                    self._emit_locked(
                        EventKind.COMPLETE,
                        "system",
                        active.lease.turn_id,
                        active.lease.generation,
                        active.lease.trace_id,
                        {"outcome": _outcome, "committed": False, "reason": reason},
                    )
                    self._abort_in_progress = False
                    self._transition_locked(KernelState.READY, "interrupted_recovered")
        return AbortResult(
            True,
            active.lease.turn_id,
            self._generation,
            tuple(completed),
            tuple(timed_out),
            tuple(failed),
        )

    async def fail_active_turn_async(
        self,
        code: Union[ErrorCode, str],
        detail: str = "",
        timeout_s: float = 3.0,
    ) -> bool:
        """Record a failure and asynchronously close the active turn."""
        with self._lifecycle_lock:
            with self._state_lock:
                active = self._active
                if active is None:
                    return False
                self._emit_locked(
                    EventKind.ERROR,
                    "system",
                    active.lease.turn_id,
                    active.lease.generation,
                    active.lease.trace_id,
                    {
                        "code": code.value if isinstance(code, ErrorCode) else str(code),
                        "detail": detail,
                    },
                )
        await self.abort_active_turn_async(
            "failed",
            timeout_s=timeout_s,
            _outcome="failed",
            _emit_interrupt=False,
        )
        return True

    def _abort_active_turn(
        self,
        reason: str,
        timeout_s: float,
        *,
        outcome: str = "interrupted",
        emit_interrupt: bool = True,
    ) -> AbortResult:
        with self._state_lock:
            if self._abort_in_progress:
                return AbortResult(False, None, self._generation)
            active = self._active
            if active is None:
                return AbortResult(False, None, self._generation)
            self._abort_in_progress = True
            self._generation += 1
            active.state = TurnState.INTERRUPTED
            active.terminal_reason = reason
            handles = tuple(self._tasks.get(active.lease.turn_id, ()))
            self._transition_locked(KernelState.RECOVERING, reason, active.lease)
            if emit_interrupt:
                self._emit_locked(
                    EventKind.INTERRUPT,
                    "system",
                    active.lease.turn_id,
                    active.lease.generation,
                    active.lease.trace_id,
                    {"reason": reason, "superseded_generation": self._generation},
                )

        completed: List[str] = []
        timed_out: List[str] = []
        failed: List[str] = []
        deadline = time.monotonic() + max(timeout_s, 0.0)
        for handle in handles:
            try:
                handle.cancel()
            except Exception as exc:
                failed.append(handle.name)
                self._record_task_error(active.lease, ErrorCode.TASK_CANCEL_FAILED, handle.name, str(exc))
                continue
            if handle.wait_terminal is None:
                completed.append(handle.name)
                continue
            remaining = max(0.0, deadline - time.monotonic())
            try:
                if handle.wait_terminal(remaining):
                    completed.append(handle.name)
                else:
                    timed_out.append(handle.name)
                    self._record_task_error(active.lease, ErrorCode.TASK_CANCEL_TIMEOUT, handle.name, "terminal wait elapsed")
            except Exception as exc:
                failed.append(handle.name)
                self._record_task_error(active.lease, ErrorCode.TASK_CANCEL_FAILED, handle.name, str(exc))

        with self._state_lock:
            self._tasks.pop(active.lease.turn_id, None)
            if self._active is active:
                self._active = None
            self._emit_locked(
                EventKind.COMPLETE,
                "system",
                active.lease.turn_id,
                active.lease.generation,
                active.lease.trace_id,
                {"outcome": outcome, "committed": False, "reason": reason},
            )
            self._abort_in_progress = False
            self._transition_locked(KernelState.READY, "interrupted_recovered")
        return AbortResult(
            True,
            active.lease.turn_id,
            self._generation,
            tuple(completed),
            tuple(timed_out),
            tuple(failed),
        )

    def complete_turn(self, lease: TurnLease, committed: bool = False) -> bool:
        """Close a current turn; callers must perform any Memory write separately."""
        with self._lifecycle_lock:
            with self._state_lock:
                record = self._active_record_locked(lease)
                if record is None:
                    self._record_stale_locked(lease, "COMPLETE")
                    return False
                if record.state not in (TurnState.THINKING, TurnState.SPEAKING):
                    self._emit_invalid_transition_locked("COMPLETE")
                    return False
                record.state = TurnState.COMPLETED
                self._tasks.pop(lease.turn_id, None)
                self._active = None
                self._emit_locked(
                    EventKind.COMPLETE,
                    "assistant",
                    lease.turn_id,
                    lease.generation,
                    lease.trace_id,
                    {"outcome": "completed", "committed": bool(committed)},
                )
                self._transition_locked(KernelState.READY, "turn_completed")
                return True

    def fail_active_turn(self, code: Union[ErrorCode, str], detail: str = "") -> bool:
        with self._lifecycle_lock:
            with self._state_lock:
                active = self._active
                if active is None:
                    return False
                active.state = TurnState.FAILED
                self._emit_locked(
                    EventKind.ERROR,
                    "system",
                    active.lease.turn_id,
                    active.lease.generation,
                    active.lease.trace_id,
                    {"code": str(code.value if isinstance(code, ErrorCode) else code), "detail": detail},
                )
            self._abort_active_turn(
                "failed",
                timeout_s=0.0,
                outcome="failed",
                emit_interrupt=False,
            )
            return True

    def is_current(self, lease: TurnLease) -> bool:
        """Return whether a lease may still publish output."""
        with self._state_lock:
            return self._active_record_locked(lease) is not None

    def stop(self) -> AbortResult:
        with self._lifecycle_lock:
            result = self._abort_active_turn("session_stopped", timeout_s=0.0)
            with self._state_lock:
                self._transition_locked(KernelState.STOPPED, "stopped")
            return result

    def reopen(self) -> None:
        """Explicitly re-arm runtime state after a complete stop.

        Reopening keeps the session identity and journal, but advances the
        generation so leases and callbacks from the previous run remain stale.
        No provider, memory store, or persistent data is touched here.
        """
        with self._lifecycle_lock:
            with self._state_lock:
                if self._state != KernelState.STOPPED:
                    raise KernelError("only a stopped session can be reopened")
                if any(self._tasks.values()):
                    raise KernelError("cannot reopen while stale tasks remain registered")
                self._generation += 1
                self._active = None
                self._tasks.clear()
                self._abort_in_progress = False
                self._duplex = CapabilityAssessment(DuplexMode.B, ("not_assessed",))
                self._transition_locked(KernelState.STARTING, "runtime_reopened")

    def snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            active = self._active
            return {
                "session_id": self.session_id,
                "state": self._state.value,
                "duplex_mode": self._duplex.mode.value,
                "c_verified": self._duplex.c_verified,
                "missing_for_c": list(self._duplex.missing_for_c),
                "generation": self._generation,
                "seq": self._seq,
                "active_turn_id": active.lease.turn_id if active else None,
                "active_turn_state": active.state.value if active else None,
            }

    def recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._journal.recent(limit)

    def record_system_event(
        self,
        kind: Union[EventKind, str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        generation: Optional[int] = None,
        turn_id: Optional[str] = None,
        trace_id: str = "",
    ) -> SessionEvent:
        """Record an adapter event without granting it turn ownership."""
        with self._lifecycle_lock:
            with self._state_lock:
                return self._emit_locked(
                    kind,
                    "system",
                    turn_id,
                    self._generation if generation is None else int(generation),
                    trace_id,
                    payload or {},
                )

    def _active_record_locked(self, lease: TurnLease) -> Optional[_TurnRecord]:
        active = self._active
        if active is None:
            return None
        if lease.session_id != self.session_id:
            return None
        if active.lease.turn_id != lease.turn_id:
            return None
        if active.lease.generation != lease.generation:
            return None
        if lease.generation != self._generation:
            return None
        return active

    def _transition_locked(
        self,
        target: KernelState,
        reason: str,
        lease: Optional[TurnLease] = None,
    ) -> None:
        previous = self._state
        self._state = target
        self._emit_locked(
            EventKind.STATE,
            "system",
            lease.turn_id if lease else None,
            lease.generation if lease else self._generation,
            lease.trace_id if lease else "",
            {"from": previous.value, "to": target.value, "reason": reason},
        )

    def _emit_invalid_transition_locked(self, action: str) -> None:
        self._emit_locked(
            EventKind.ERROR,
            "system",
            self._active.lease.turn_id if self._active else None,
            self._generation,
            self._active.lease.trace_id if self._active else "",
            {
                "code": ErrorCode.INVALID_TRANSITION.value,
                "action": action,
                "state": self._state.value,
            },
        )

    def _record_stale_locked(self, lease: TurnLease, attempted_kind: str) -> None:
        self._emit_locked(
            EventKind.STALE,
            "system",
            lease.turn_id,
            lease.generation,
            lease.trace_id,
            {"code": ErrorCode.STALE_EVENT.value, "attempted_kind": attempted_kind},
        )

    def _record_task_error(
        self,
        lease: TurnLease,
        code: ErrorCode,
        task_name: str,
        detail: str,
    ) -> None:
        with self._state_lock:
            self._emit_locked(
                EventKind.ERROR,
                "system",
                lease.turn_id,
                lease.generation,
                lease.trace_id,
                {"code": code.value, "component": task_name, "detail": detail},
            )

    def _emit_locked(
        self,
        kind: Union[EventKind, str],
        actor: str,
        turn_id: Optional[str],
        generation: int,
        trace_id: str,
        payload: Dict[str, Any],
    ) -> SessionEvent:
        self._seq += 1
        event = SessionEvent(
            protocol_version=PROTOCOL_VERSION,
            session_id=self.session_id,
            turn_id=turn_id,
            generation=generation,
            seq=self._seq,
            kind=kind.value if isinstance(kind, EventKind) else str(kind),
            actor=actor,
            timestamp=_utc_timestamp(),
            trace_id=trace_id,
            payload=dict(payload),
        )
        self._journal.append(event)
        return event


async def _await_terminal_handle(waiter: Callable[[float], Any], timeout_s: float) -> bool:
    """Bound a sync or async cancellation observer without blocking Kernel."""
    budget = max(float(timeout_s), 0.0)
    grace = budget if budget > 0 else 0.01
    try:
        if inspect.iscoroutinefunction(waiter):
            result = waiter(budget)
        else:
            task = asyncio.create_task(asyncio.to_thread(waiter, budget))
            try:
                result = await asyncio.wait_for(asyncio.shield(task), timeout=grace)
            except asyncio.TimeoutError:
                task.add_done_callback(_consume_late_terminal_task)
                return False
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout=grace)
        return bool(result)
    except (asyncio.TimeoutError, TimeoutError):
        return False


def _consume_late_terminal_task(task: asyncio.Task) -> None:
    """Drain a late sync observer result without exposing provider details."""
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
    "AudioRoute",
    "AbortResult",
    "CancellationHandle",
    "CapabilityAssessment",
    "DuplexMode",
    "ErrorCode",
    "EventJournal",
    "EventKind",
    "KernelError",
    "KernelState",
    "PROTOCOL_VERSION",
    "ProviderCapabilities",
    "SessionEvent",
    "SessionKernel",
    "TurnLease",
    "TurnState",
]
