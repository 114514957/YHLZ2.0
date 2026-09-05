"""Bounded, provider-driven acceptance execution for the target voice chain.

The executor is deliberately separate from :mod:`target_runtime`.  It does
not open a device, load a model, write a report, or infer a route from device
metadata.  A caller must provide an explicit acceptance provider, adapters,
and thresholds.  Without those inputs the result is ``not_executed`` rather
than a synthetic pass.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, Tuple, Union

from backend.media_adapter import DeviceDescriptor
from backend.session_kernel import AudioRoute, ProviderCapabilities
from backend.tts_provider_port import is_tts_provider_port


C_ACCEPTANCE_CHECKS = (
    "continuous_capture",
    "route_and_echo_control",
    "vad_and_wake_word",
    "asr_tts_concurrent",
    "cancel_asr",
    "asr_stop_confirmed",
    "cancel_generation",
    "cancel_tts",
    "cancel_playback",
    "playback_stop_confirmed",
    "resource_budget",
)


class AcceptanceRunStatus(str, Enum):
    NOT_EXECUTED = "not_executed"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class AcceptanceCheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_EXECUTED = "not_executed"
    TIMED_OUT = "timed_out"
    ERROR = "error"


MetricValue = Union[bool, int, float]
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,79}$")
_METRIC_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class AcceptanceThresholds:
    """Explicit limits supplied by the caller for one acceptance run."""

    per_check_timeout_s: float
    total_timeout_s: float
    max_stop_latency_ms: int
    min_capture_frames: int
    max_queue_depth: int
    max_queue_duration_ms: int

    def __post_init__(self) -> None:
        for name in ("per_check_timeout_s", "total_timeout_s"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(name + " must be finite and positive")
        if self.total_timeout_s < self.per_check_timeout_s:
            raise ValueError("total_timeout_s must cover one check timeout")
        for name in (
            "max_stop_latency_ms",
            "min_capture_frames",
            "max_queue_depth",
            "max_queue_duration_ms",
        ):
            value = int(getattr(self, name))
            if value <= 0:
                raise ValueError(name + " must be positive")

    def to_dict(self) -> dict:
        return {
            "per_check_timeout_s": float(self.per_check_timeout_s),
            "total_timeout_s": float(self.total_timeout_s),
            "max_stop_latency_ms": int(self.max_stop_latency_ms),
            "min_capture_frames": int(self.min_capture_frames),
            "max_queue_depth": int(self.max_queue_depth),
            "max_queue_duration_ms": int(self.max_queue_duration_ms),
        }


# Initial hard limits mapped from the NEKO operational budget.  These are
# runtime guardrails, not a claim that YHLZ has passed hardware calibration;
# real-device evidence may tighten them but may never widen them implicitly.
DEFAULT_ACCEPTANCE_THRESHOLDS = AcceptanceThresholds(
    per_check_timeout_s=5.0,
    total_timeout_s=60.0,
    max_stop_latency_ms=3_000,
    min_capture_frames=1,
    max_queue_depth=32,
    max_queue_duration_ms=5_000,
)


@dataclass(frozen=True, slots=True)
class AcceptanceAdapters:
    """Explicit provider/device objects available to an acceptance provider.

    The executor only reports presence.  It never calls lifecycle methods on
    these objects; an acceptance provider owns any real-device operation and
    must make that operation observable in its returned evidence.
    """

    input_source: Any = None
    vad: Any = None
    asr: Any = None
    reasoner: Any = None
    speech: Any = None
    playback: Any = None
    aec: Any = None

    def to_dict(self) -> dict:
        return {
            "input_source": self.input_source is not None,
            "vad": self.vad is not None,
            "asr": self.asr is not None,
            "reasoner": self.reasoner is not None,
            "speech": self.speech is not None,
            "playback": self.playback is not None,
            "aec": self.aec is not None,
        }

    def matches_identity(self, other: "AcceptanceAdapters") -> bool:
        """Match the exact runtime-owned adapter objects, by identity."""
        if not isinstance(other, AcceptanceAdapters):
            return False
        return all(
            left is right
            for left, right in (
                (self.input_source, other.input_source),
                (self.vad, other.vad),
                (self.asr, other.asr),
                (self.reasoner, other.reasoner),
                (self.speech, other.speech),
                (self.playback, other.playback),
                (self.aec, other.aec),
            )
        )


@dataclass(frozen=True, slots=True)
class AcceptanceExecutionContext:
    """Immutable context handed to one explicit acceptance provider."""

    device: DeviceDescriptor
    media_generation: int
    capabilities: ProviderCapabilities
    adapters: AcceptanceAdapters
    thresholds: AcceptanceThresholds
    run_id: str
    _cancel_event: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.media_generation < 0:
            raise ValueError("media_generation must not be negative")
        if not str(self.run_id).strip():
            raise ValueError("run_id must not be empty")

    def to_dict(self) -> dict:
        assessment = self.capabilities.assess()
        return {
            "device_id": self.device.device_id,
            "media_generation": self.media_generation,
            "capability_mode": assessment.mode.value,
            "adapters": self.adapters.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "run_id": self.run_id,
        }

    @property
    def cancellation_requested(self) -> bool:
        """Expose cooperative cancellation without serializing mutable state."""
        return self._cancel_event.is_set()


class AcceptanceCheckProvider(Protocol):
    """Provider port used by ``FullDuplexAcceptanceExecutor``.

    ``run_check`` may be synchronous or asynchronous.  A synchronous port is
    run in a worker thread and remains a failed/timeout result if it cannot
    finish inside the supplied budget; the executor never treats that as C.
    """

    def run_check(self, check: str, context: AcceptanceExecutionContext) -> Any: ...


def _has_callable(adapter: Any, *names: str) -> bool:
    return adapter is not None and any(
        callable(getattr(adapter, name, None)) for name in names
    )


def _has_all_callables(adapter: Any, *names: str) -> bool:
    return adapter is not None and all(
        callable(getattr(adapter, name, None)) for name in names
    )


def inspect_acceptance_adapters(
    adapters: AcceptanceAdapters,
    *,
    route: str,
) -> Tuple[str, ...]:
    """Return missing runtime ports without invoking any adapter method.

    This is a static contract check only.  It deliberately does not open a
    stream, call a model, enumerate a device, or request a stop.  The real
    acceptance provider still supplies measured evidence after this gate.
    """
    if not isinstance(adapters, AcceptanceAdapters):
        raise TypeError("adapters must be AcceptanceAdapters")
    missing = []
    if not _has_all_callables(adapters.input_source, "start", "stop", "health"):
        missing.append("input_source_lifecycle")
    if not _has_callable(adapters.vad, "detect_speech"):
        missing.append("vad_detect")
    if not _has_callable(adapters.asr, "transcribe"):
        missing.append("asr_transcribe")
    if not _has_callable(adapters.asr, "interrupt", "stop", "cancel"):
        missing.append("asr_cancel")
    if not _has_callable(adapters.asr, "wait_stopped"):
        missing.append("asr_stop_observer")
    if not _has_callable(adapters.reasoner, "generate"):
        missing.append("reasoner_generate")
    if is_tts_provider_port(adapters.speech):
        # The provider port exposes cancel/wait_stopped on its opened session,
        # so requiring legacy synthesize()/interrupt() methods here would
        # reject the new boundary before a real acceptance provider can test
        # those session-level guarantees.
        pass
    else:
        if not _has_callable(adapters.speech, "synthesize"):
            missing.append("speech_synthesize")
        if not _has_callable(adapters.speech, "interrupt", "stop", "cancel"):
            missing.append("speech_cancel")
        if not _has_callable(adapters.speech, "wait_stopped"):
            missing.append("speech_stop_observer")
    if not _has_callable(adapters.playback, "play"):
        missing.append("playback_play")
    if not _has_callable(adapters.playback, "interrupt", "stop", "cancel"):
        missing.append("playback_cancel")
    if not _has_callable(adapters.playback, "wait_stopped"):
        missing.append("playback_stop_observer")
    if route == AudioRoute.SPEAKER_MIC.value:
        if not _has_callable(adapters.aec, "process"):
            missing.append("aec_process")
    return tuple(missing)


def _validate_metrics(metrics: Tuple[Tuple[str, MetricValue], ...]) -> None:
    for key, value in metrics:
        if not isinstance(key, str) or _METRIC_RE.fullmatch(key) is None:
            raise ValueError("metric names must be lowercase identifiers")
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            continue
        if isinstance(value, float) and math.isfinite(value):
            continue
        raise ValueError("metrics must contain finite numeric or boolean values")


@dataclass(frozen=True, slots=True)
class AcceptanceCheckEvidence:
    """One sanitized result returned by an acceptance provider."""

    check: str
    status: AcceptanceCheckStatus
    duration_ms: int = 0
    code: str = ""
    metrics: Tuple[Tuple[str, MetricValue], ...] = ()

    def __post_init__(self) -> None:
        if self.check not in C_ACCEPTANCE_CHECKS:
            raise ValueError("unknown acceptance check")
        object.__setattr__(self, "status", AcceptanceCheckStatus(self.status))
        if int(self.duration_ms) < 0:
            raise ValueError("duration_ms must not be negative")
        object.__setattr__(self, "duration_ms", int(self.duration_ms))
        if self.code and _CODE_RE.fullmatch(self.code) is None:
            raise ValueError("code must be a bounded uppercase identifier")
        _validate_metrics(tuple(self.metrics))
        object.__setattr__(self, "metrics", tuple(self.metrics))

    @property
    def metric_map(self) -> Mapping[str, MetricValue]:
        return dict(self.metrics)

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "code": self.code,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class FullDuplexAcceptanceReport:
    """Structured, bounded output of one executor run."""

    status: AcceptanceRunStatus
    run_id: str
    media_generation: int
    device_id: str
    thresholds: AcceptanceThresholds
    evidence: Tuple[AcceptanceCheckEvidence, ...] = ()
    reason: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    pending_sync_work: bool = False
    missing_ports: Tuple[str, ...] = ()
    # An in-process identity used by TargetVoiceRuntime to reject reports
    # assembled outside the executor.  It is intentionally omitted from
    # serialized health output.
    _provenance: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", AcceptanceRunStatus(self.status))
        if self.media_generation < 0:
            raise ValueError("media_generation must not be negative")
        if not str(self.device_id).strip():
            raise ValueError("device_id must not be empty")
        if not str(self.run_id).strip():
            raise ValueError("run_id must not be empty")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(
            self,
            "missing_ports",
            tuple(str(item)[:120] for item in self.missing_ports),
        )

    @property
    def checks(self) -> dict:
        evidence = {item.check: item for item in self.evidence}
        return {
            name: evidence.get(name) is not None
            and evidence[name].status is AcceptanceCheckStatus.PASSED
            for name in C_ACCEPTANCE_CHECKS
        }

    @property
    def missing(self) -> Tuple[str, ...]:
        return tuple(name for name, passed in self.checks.items() if not passed)

    @property
    def all_checks_passed(self) -> bool:
        return bool(self.evidence) and not self.missing

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "run_id": self.run_id,
            "media_generation": self.media_generation,
            "device_id": self.device_id,
            "thresholds": self.thresholds.to_dict(),
            "checks": self.checks,
            "missing": list(self.missing),
            "evidence": [item.to_dict() for item in self.evidence],
            "reason": self.reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pending_sync_work": self.pending_sync_work,
            "missing_ports": list(self.missing_ports),
        }


_REQUIRED_METRICS = {
    "continuous_capture": ("capture_frames",),
    "route_and_echo_control": ("route_verified", "echo_control_verified"),
    "vad_and_wake_word": ("vad_segments", "wake_word_detected"),
    "asr_tts_concurrent": ("concurrent_observed",),
    "cancel_asr": ("cancelled", "stop_latency_ms"),
    "asr_stop_confirmed": ("stop_latency_ms",),
    "cancel_generation": ("cancelled",),
    "cancel_tts": ("cancelled",),
    "cancel_playback": ("cancelled", "stop_latency_ms"),
    "playback_stop_confirmed": ("stop_latency_ms",),
    "resource_budget": ("queue_depth", "queue_duration_ms"),
}


class FullDuplexAcceptanceExecutor:
    """Run explicit checks with bounded time and no implicit side effects."""

    def __init__(
        self,
        *,
        provider: Optional[AcceptanceCheckProvider],
        device: DeviceDescriptor,
        adapters: AcceptanceAdapters,
        thresholds: AcceptanceThresholds,
        run_id: Optional[str] = None,
    ) -> None:
        if not isinstance(device, DeviceDescriptor):
            raise TypeError("device must be a DeviceDescriptor")
        if not isinstance(adapters, AcceptanceAdapters):
            raise TypeError("adapters must be AcceptanceAdapters")
        if not isinstance(thresholds, AcceptanceThresholds):
            raise TypeError("thresholds must be AcceptanceThresholds")
        self.provider = provider
        self.device = device
        self.adapters = adapters
        self.thresholds = thresholds
        self.run_id = str(run_id or ("acceptance_" + uuid.uuid4().hex))[:96]
        self._provenance = object()
        self._pending_sync_tasks: set[asyncio.Task] = set()
        self._run_state_lock = threading.RLock()
        self._running = False
        self._cancel_event = threading.Event()

    @property
    def sync_cleanup_pending(self) -> bool:
        """Whether a timed-out synchronous check still owns a worker thread."""
        return any(not task.done() for task in self._pending_sync_tasks)

    @property
    def running(self) -> bool:
        with self._run_state_lock:
            return self._running

    @property
    def cancellation_requested(self) -> bool:
        """Whether the owning runtime has asked this run to wind down."""
        return self._cancel_event.is_set()

    def request_cancel(self) -> None:
        """Signal cooperative providers before their task is cancelled.

        A synchronous provider cannot be force-killed by ``asyncio``.  The
        context event gives it one explicit, thread-safe way to leave its
        current check.  Runtime code still waits for the worker task before
        treating cleanup as complete.
        """
        self._cancel_event.set()

    async def wait_for_cleanup(self, timeout_s: float) -> bool:
        """Wait only for known synchronous workers that outlived their task."""
        timeout = max(0.0, float(timeout_s))
        pending = tuple(task for task in self._pending_sync_tasks if not task.done())
        if not pending:
            return True
        _, still_pending = await asyncio.wait(pending, timeout=timeout)
        return not still_pending and not self.sync_cleanup_pending

    async def run(
        self,
        *,
        media_generation: int,
        capabilities: ProviderCapabilities,
    ) -> FullDuplexAcceptanceReport:
        started = time.time()
        with self._run_state_lock:
            if self._running:
                # A second run could overlap real device actions.  Return a
                # bounded, explicit non-execution report instead.
                return self._report(
                    AcceptanceRunStatus.NOT_EXECUTED,
                    tuple(
                        AcceptanceCheckEvidence(
                            check=name,
                            status=AcceptanceCheckStatus.NOT_EXECUTED,
                            code="ACCEPTANCE-RUN-IN-PROGRESS",
                        )
                        for name in C_ACCEPTANCE_CHECKS
                    ),
                    "run_in_progress",
                    started,
                    int(media_generation),
                )
            if self.cancellation_requested:
                return self._cancelled_report(started, int(media_generation))
            self._running = True
        try:
            return await self._run_once(started, media_generation=media_generation, capabilities=capabilities)
        finally:
            with self._run_state_lock:
                self._running = False

    async def _run_once(
        self,
        started: float,
        *,
        media_generation: int,
        capabilities: ProviderCapabilities,
    ) -> FullDuplexAcceptanceReport:
        if not isinstance(capabilities, ProviderCapabilities):
            raise TypeError("capabilities must be ProviderCapabilities")
        context = AcceptanceExecutionContext(
            device=self.device,
            media_generation=int(media_generation),
            capabilities=capabilities,
            adapters=self.adapters,
            thresholds=self.thresholds,
            run_id=self.run_id,
            _cancel_event=self._cancel_event,
        )
        if context.cancellation_requested:
            return self._cancelled_report(started, context.media_generation)
        if self.sync_cleanup_pending:
            evidence = tuple(
                AcceptanceCheckEvidence(
                    check=name,
                    status=AcceptanceCheckStatus.NOT_EXECUTED,
                    code="ACCEPTANCE-PREVIOUS-SYNC-ACTIVE",
                )
                for name in C_ACCEPTANCE_CHECKS
            )
            return self._report(
                AcceptanceRunStatus.NOT_EXECUTED,
                evidence,
                "pending_sync_cleanup",
                started,
                context.media_generation,
            )
        if self.provider is None:
            evidence = tuple(
                AcceptanceCheckEvidence(
                    check=name,
                    status=AcceptanceCheckStatus.NOT_EXECUTED,
                    code="ACCEPTANCE-NO-PROVIDER",
                )
                for name in C_ACCEPTANCE_CHECKS
            )
            return self._report(
                AcceptanceRunStatus.NOT_EXECUTED,
                evidence,
                "provider_required",
                started,
                context.media_generation,
            )

        method = getattr(self.provider, "run_check", None)
        if not callable(method):
            evidence = tuple(
                AcceptanceCheckEvidence(
                    check=name,
                    status=AcceptanceCheckStatus.NOT_EXECUTED,
                    code="ACCEPTANCE-PORT-MISSING",
                )
                for name in C_ACCEPTANCE_CHECKS
            )
            return self._report(
                AcceptanceRunStatus.NOT_EXECUTED,
                evidence,
                "provider_port_required",
                started,
                context.media_generation,
            )

        missing_ports = inspect_acceptance_adapters(
            self.adapters,
            route=self.device.route,
        )
        if missing_ports:
            evidence = tuple(
                AcceptanceCheckEvidence(
                    check=name,
                    status=AcceptanceCheckStatus.NOT_EXECUTED,
                    code="ACCEPTANCE-PORT-MISSING",
                )
                for name in C_ACCEPTANCE_CHECKS
            )
            return self._report(
                AcceptanceRunStatus.NOT_EXECUTED,
                evidence,
                "adapter_ports_missing",
                started,
                context.media_generation,
                missing_ports=missing_ports,
            )

        evidence_list = []
        deadline = asyncio.get_running_loop().time() + self.thresholds.total_timeout_s
        for check in C_ACCEPTANCE_CHECKS:
            if context.cancellation_requested:
                evidence_list.append(
                    AcceptanceCheckEvidence(
                        check=check,
                        status=AcceptanceCheckStatus.NOT_EXECUTED,
                        code="ACCEPTANCE-CANCELLED",
                    )
                )
                continue
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                evidence_list.append(
                    AcceptanceCheckEvidence(
                        check=check,
                        status=AcceptanceCheckStatus.NOT_EXECUTED,
                        code="ACCEPTANCE-TOTAL-TIMEOUT",
                    )
                )
                continue
            timeout = min(self.thresholds.per_check_timeout_s, remaining)
            evidence_list.append(
                await self._run_one(method, check, context, timeout)
            )

        evidence = tuple(evidence_list)
        if all(item.status is AcceptanceCheckStatus.NOT_EXECUTED for item in evidence):
            status = AcceptanceRunStatus.NOT_EXECUTED
            reason = "no_checks_executed"
        elif all(item.status is AcceptanceCheckStatus.PASSED for item in evidence):
            status = AcceptanceRunStatus.PASSED
            reason = "all_checks_passed"
        elif any(item.status is AcceptanceCheckStatus.ERROR for item in evidence):
            status = AcceptanceRunStatus.ERROR
            reason = "provider_error"
        else:
            status = AcceptanceRunStatus.FAILED
            reason = "requirements_failed"
        return self._report(status, evidence, reason, started, context.media_generation)

    async def _run_one(
        self,
        method: Any,
        check: str,
        context: AcceptanceExecutionContext,
        timeout: float,
    ) -> AcceptanceCheckEvidence:
        try:
            result = await self._call_provider(method, check, context, timeout)
        except asyncio.TimeoutError:
            return AcceptanceCheckEvidence(
                check=check,
                status=AcceptanceCheckStatus.TIMED_OUT,
                code="ACCEPTANCE-CHECK-TIMEOUT",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not expose provider exception text, which can contain input
            # transcripts or device details.
            return AcceptanceCheckEvidence(
                check=check,
                status=AcceptanceCheckStatus.ERROR,
                code="ACCEPTANCE-PROVIDER-ERROR",
            )

        if not isinstance(result, AcceptanceCheckEvidence):
            return AcceptanceCheckEvidence(
                check=check,
                status=AcceptanceCheckStatus.ERROR,
                code="ACCEPTANCE-EVIDENCE-INVALID",
            )
        if result.check != check:
            return AcceptanceCheckEvidence(
                check=check,
                status=AcceptanceCheckStatus.ERROR,
                code="ACCEPTANCE-CHECK-MISMATCH",
            )
        return self._apply_thresholds(result, context.thresholds)

    async def _call_provider(
        self,
        method: Any,
        check: str,
        context: AcceptanceExecutionContext,
        timeout: float,
    ) -> Any:
        """Support sync adapters without allowing them to block the loop."""
        if inspect.iscoroutinefunction(method):
            return await asyncio.wait_for(method(check, context), timeout=timeout)
        started = asyncio.get_running_loop().time()
        task = asyncio.create_task(asyncio.to_thread(method, check, context))
        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            # ``wait_for`` cannot terminate a running Python worker thread.
            # Keep the task visible and reject subsequent runs until it has
            # actually returned, rather than letting a stale hardware action
            # overlap with a new acceptance attempt.
            self._retain_pending_sync_task(task)
            raise
        except asyncio.CancelledError:
            # Cancelling the coroutine that waits on ``to_thread`` does not
            # cancel the worker.  Keep that worker visible so the runtime
            # cannot restart onto a still-running acceptance operation.
            self._retain_pending_sync_task(task)
            raise
        if inspect.isawaitable(result):
            remaining = max(0.0, timeout - (asyncio.get_running_loop().time() - started))
            if remaining <= 0:
                raise asyncio.TimeoutError
            return await asyncio.wait_for(result, timeout=remaining)
        return result

    def _retain_pending_sync_task(self, task: asyncio.Task) -> None:
        if task.done():
            return
        self._pending_sync_tasks.add(task)
        task.add_done_callback(self._discard_pending_sync_task)

    def _cancelled_report(
        self,
        started: float,
        media_generation: int,
    ) -> FullDuplexAcceptanceReport:
        evidence = tuple(
            AcceptanceCheckEvidence(
                check=name,
                status=AcceptanceCheckStatus.NOT_EXECUTED,
                code="ACCEPTANCE-CANCELLED",
            )
            for name in C_ACCEPTANCE_CHECKS
        )
        return self._report(
            AcceptanceRunStatus.NOT_EXECUTED,
            evidence,
            "cancellation_requested",
            started,
            media_generation,
        )

    def _discard_pending_sync_task(self, task: asyncio.Task) -> None:
        self._pending_sync_tasks.discard(task)
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception:
            # The original timeout is already represented in the report; a
            # later worker failure cannot become an unobserved task warning.
            return
        if inspect.isawaitable(result):
            # The synchronous call outlived its acceptance budget and later
            # produced an awaitable.  It must not start after the fact; close
            # a coroutine object so Python does not retain an unawaited
            # provider operation or emit a warning during shutdown.
            close = getattr(result, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _apply_thresholds(
        evidence: AcceptanceCheckEvidence,
        thresholds: AcceptanceThresholds,
    ) -> AcceptanceCheckEvidence:
        if evidence.status is not AcceptanceCheckStatus.PASSED:
            return evidence
        metrics = evidence.metric_map
        required = _REQUIRED_METRICS.get(evidence.check, ())
        if any(name not in metrics for name in required):
            return AcceptanceCheckEvidence(
                check=evidence.check,
                status=AcceptanceCheckStatus.FAILED,
                duration_ms=evidence.duration_ms,
                code="ACCEPTANCE-METRIC-MISSING",
                metrics=evidence.metrics,
            )
        if evidence.duration_ms > int(thresholds.per_check_timeout_s * 1000):
            return AcceptanceCheckEvidence(
                check=evidence.check,
                status=AcceptanceCheckStatus.FAILED,
                duration_ms=evidence.duration_ms,
                code="ACCEPTANCE-THRESHOLD-EXCEEDED",
                metrics=evidence.metrics,
            )

        violations = []
        if evidence.check == "continuous_capture":
            if metrics.get("capture_frames", 0) < thresholds.min_capture_frames:
                violations.append("capture_frames")
        elif evidence.check in {"cancel_asr", "asr_stop_confirmed", "cancel_playback", "playback_stop_confirmed"}:
            if metrics.get("stop_latency_ms", 0) > thresholds.max_stop_latency_ms:
                violations.append("stop_latency_ms")
        elif evidence.check == "resource_budget":
            if metrics.get("queue_depth", 0) > thresholds.max_queue_depth:
                violations.append("queue_depth")
            if metrics.get("queue_duration_ms", 0) > thresholds.max_queue_duration_ms:
                violations.append("queue_duration_ms")

        boolean_requirements = {
            "route_and_echo_control": ("route_verified", "echo_control_verified"),
            "vad_and_wake_word": ("wake_word_detected",),
            "asr_tts_concurrent": ("concurrent_observed",),
            "cancel_asr": ("cancelled",),
            "cancel_generation": ("cancelled",),
            "cancel_tts": ("cancelled",),
            "cancel_playback": ("cancelled",),
        }
        for name in boolean_requirements.get(evidence.check, ()):
            if metrics.get(name) is not True:
                violations.append(name)
        if evidence.check == "vad_and_wake_word" and metrics.get("vad_segments", 0) < 1:
            violations.append("vad_segments")
        if violations:
            return AcceptanceCheckEvidence(
                check=evidence.check,
                status=AcceptanceCheckStatus.FAILED,
                duration_ms=evidence.duration_ms,
                code="ACCEPTANCE-THRESHOLD-EXCEEDED",
                metrics=evidence.metrics,
            )
        return evidence

    def _report(
        self,
        status: AcceptanceRunStatus,
        evidence: Tuple[AcceptanceCheckEvidence, ...],
        reason: str,
        started: float,
        media_generation: int,
        missing_ports: Tuple[str, ...] = (),
    ) -> FullDuplexAcceptanceReport:
        return FullDuplexAcceptanceReport(
            status=status,
            run_id=self.run_id,
            media_generation=media_generation,
            device_id=self.device.device_id,
            thresholds=self.thresholds,
            evidence=evidence,
            reason=reason,
            started_at=started,
            finished_at=time.time(),
            pending_sync_work=self.sync_cleanup_pending,
            missing_ports=missing_ports,
            _provenance=self._provenance,
        )


__all__ = [
    "AcceptanceAdapters",
    "AcceptanceCheckEvidence",
    "AcceptanceCheckProvider",
    "AcceptanceCheckStatus",
    "AcceptanceExecutionContext",
    "AcceptanceRunStatus",
    "AcceptanceThresholds",
    "C_ACCEPTANCE_CHECKS",
    "DEFAULT_ACCEPTANCE_THRESHOLDS",
    "FullDuplexAcceptanceExecutor",
    "FullDuplexAcceptanceReport",
    "inspect_acceptance_adapters",
]
