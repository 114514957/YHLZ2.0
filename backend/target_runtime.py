"""Thin lifecycle coordinator for the isolated target voice chain."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, replace
from enum import Enum
import threading
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from backend.asr_bridge import ASRBridge
from backend.media_adapter import DeviceDescriptor, MediaAdapter, MediaError, MediaState
from backend.runtime_events import RuntimeEventRelay
from backend.session_kernel import (
    AudioRoute,
    CapabilityAssessment,
    EventKind,
    ProviderCapabilities,
)
from backend.target_chain import TargetVoiceChain
from backend.target_acceptance import (
    AcceptanceAdapters,
    AcceptanceRunStatus,
    AcceptanceThresholds,
    C_ACCEPTANCE_CHECKS,
    DEFAULT_ACCEPTANCE_THRESHOLDS,
    FullDuplexAcceptanceExecutor,
    FullDuplexAcceptanceReport,
)
from backend.target_probe import (
    EnvironmentProbeReport,
    InputDeviceSelection,
    ProbeStatus,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeConfigSnapshot:
    """Immutable effective budgets exposed to health and acceptance tools."""

    version: str
    stop_timeout_s: float
    media_queue_capacity: int
    media_queue_duration_ms: int
    segment_preroll_frames: int
    segment_end_silence_frames: int
    segment_max_frames: int
    segment_min_frames: int
    segment_max_duration_ms: int
    segment_min_duration_ms: int
    asr_timeout_s: float
    asr_cancel_timeout_s: float
    acceptance_thresholds: AcceptanceThresholds

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "stop_timeout_s": self.stop_timeout_s,
            "media_queue_capacity": self.media_queue_capacity,
            "media_queue_duration_ms": self.media_queue_duration_ms,
            "segment_preroll_frames": self.segment_preroll_frames,
            "segment_end_silence_frames": self.segment_end_silence_frames,
            "segment_max_frames": self.segment_max_frames,
            "segment_min_frames": self.segment_min_frames,
            "segment_max_duration_ms": self.segment_max_duration_ms,
            "segment_min_duration_ms": self.segment_min_duration_ms,
            "asr_timeout_s": self.asr_timeout_s,
            "asr_cancel_timeout_s": self.asr_cancel_timeout_s,
            "acceptance_thresholds": self.acceptance_thresholds.to_dict(),
        }


class FaultImportance(str, Enum):
    CORE = "core"
    IMPORTANT = "important"
    PERIPHERAL = "peripheral"


class FaultAction(str, Enum):
    DEGRADE_B = "degrade_b"
    RESTART_WHEN_IDLE = "restart_when_idle"
    RECORD_ONLY = "record_only"


@dataclass(frozen=True, slots=True)
class RuntimeFaultDecision:
    code: str
    importance: FaultImportance
    action: FaultAction
    retryable: bool = True

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "importance": self.importance.value,
            "action": self.action.value,
            "retryable": self.retryable,
        }


class RuntimeFaultPolicy:
    """Classify target-chain faults without performing recovery implicitly."""

    _CORE_PREFIXES = (
        "MEDIA-SOURCE-",
        "MEDIA-VAD-",
        "MEDIA-FORMAT-",
        "MEDIA-FRAME-HANDLER-",
        "ASR-CANCEL-",
        "VOICE-PLAYBACK-",
    )
    _DEGRADE_PREFIXES = (
        "MEDIA-AEC-",
        "MEDIA-BACKPRESSURE",
    )

    def decide(self, code: str) -> RuntimeFaultDecision:
        normalized = str(code or "RUNTIME-UNKNOWN")[:160]
        if normalized.startswith(self._CORE_PREFIXES):
            return RuntimeFaultDecision(
                normalized,
                FaultImportance.CORE,
                FaultAction.RESTART_WHEN_IDLE,
            )
        if normalized.startswith(self._DEGRADE_PREFIXES):
            return RuntimeFaultDecision(
                normalized,
                FaultImportance.IMPORTANT,
                FaultAction.DEGRADE_B,
            )
        return RuntimeFaultDecision(
            normalized,
            FaultImportance.IMPORTANT,
            FaultAction.DEGRADE_B,
        )


class RuntimeState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"


class AcceptanceStatus(str, Enum):
    """Independent evidence state for a runtime's full-duplex claim."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class FullDuplexAcceptance:
    """In-memory result of a single device/provider acceptance run."""

    status: AcceptanceStatus
    media_generation: int = 0
    device_id: str = ""
    checks: Tuple[Tuple[str, bool], ...] = ()
    missing: Tuple[str, ...] = ()
    reason: str = ""
    recorded_at: float = 0.0

    @classmethod
    def not_run(
        cls,
        media_generation: int = 0,
        device_id: str = "",
        reason: str = "not_run",
    ) -> "FullDuplexAcceptance":
        return cls(
            status=AcceptanceStatus.NOT_RUN,
            media_generation=media_generation,
            device_id=device_id,
            reason=reason,
            recorded_at=time.time(),
        )

    @property
    def c_verified(self) -> bool:
        return self.status is AcceptanceStatus.PASSED

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "c_verified": self.c_verified,
            "media_generation": self.media_generation,
            "device_id": self.device_id,
            "checks": {name: passed for name, passed in self.checks},
            "missing": list(self.missing),
            "reason": self.reason,
            "recorded_at": self.recorded_at,
        }


class TargetVoiceRuntime:
    """Own the start/stop order of Media, ASR, and TargetVoiceChain only."""

    def __init__(
        self,
        *,
        media: MediaAdapter,
        asr: ASRBridge,
        chain: TargetVoiceChain,
        stop_timeout_s: float = 3.0,
        fault_policy: Optional[RuntimeFaultPolicy] = None,
        environment_report: Optional[EnvironmentProbeReport] = None,
        acceptance_thresholds: Optional[AcceptanceThresholds] = None,
    ) -> None:
        if asr.chain is not chain:
            raise ValueError("ASR bridge and runtime must share the same TargetVoiceChain")
        if stop_timeout_s <= 0:
            raise ValueError("stop_timeout_s must be positive")
        self.media = media
        self.asr = asr
        self.chain = chain
        self.stop_timeout_s = float(stop_timeout_s)
        if acceptance_thresholds is not None and not isinstance(
            acceptance_thresholds, AcceptanceThresholds
        ):
            raise TypeError("acceptance_thresholds must be AcceptanceThresholds or None")
        self.acceptance_thresholds = self._effective_acceptance_thresholds(
            acceptance_thresholds or DEFAULT_ACCEPTANCE_THRESHOLDS
        )
        self._state = RuntimeState.STOPPED
        self._started = False
        self._run_task: Optional[asyncio.Task] = None
        self.fault_policy = fault_policy or RuntimeFaultPolicy()
        self._environment_report = environment_report
        self._input_selection: Optional[InputDeviceSelection] = None
        self._fault_lock = threading.RLock()
        self._faults: Dict[str, dict] = {}
        self._acceptance_lock = threading.RLock()
        self._acceptance = FullDuplexAcceptance.not_run()
        self._acceptance_report: Optional[FullDuplexAcceptanceReport] = None
        self._acceptance_execution_lock = threading.RLock()
        self._acceptance_execution_in_progress = False
        self._acceptance_execution_executor: Optional[FullDuplexAcceptanceExecutor] = None
        self._acceptance_execution_task: Optional[asyncio.Task] = None
        self._acceptance_execution_generation = 0
        self.events = RuntimeEventRelay(chain.kernel)

        previous_handler = media.on_frame

        async def dispatch(frame: Any) -> None:
            if previous_handler is not None:
                result = previous_handler(frame)
                if inspect.isawaitable(result):
                    await result
            await self.asr.accept_frame(frame)

        # The runtime is the single owner of the media-to-ASR hand-off.  A
        # pre-existing handler is retained only as an observer.
        media.on_frame = dispatch
        self._compose_media_event_sink(media)
        self._compose_asr_event_sink(self.asr)
        self._compose_event_sink(self.asr.assembler, self.events.segment)
        self._compose_playback_event_sink(self.chain.playback)

    @property
    def state(self) -> RuntimeState:
        return self._state

    def start(
        self,
        device: DeviceDescriptor,
        capabilities: ProviderCapabilities,
    ) -> CapabilityAssessment:
        if self._started:
            raise MediaError("target voice runtime is already running")
        if self._acceptance_in_progress():
            raise MediaError("target voice runtime has pending acceptance cleanup")
        selection = self._input_selection
        if selection is not None and not self._selection_matches_device(selection, device):
            raise MediaError("runtime device does not match the bound input selection")
        self._state = RuntimeState.STARTING
        try:
            self.chain.start_playback()
            asr_start = getattr(self.asr, "start", None)
            if callable(asr_start):
                start_value = asr_start()
                if inspect.isawaitable(start_value):
                    raise MediaError("target ASR startup must be synchronous")
            assessment = self.media.start(device, capabilities)
            effective = self.media.capabilities
            if effective is None:
                raise MediaError("media adapter did not expose effective capabilities")
            self.chain.start(effective)
            self._started = True
            with self._acceptance_lock:
                self._acceptance = FullDuplexAcceptance.not_run(
                    self.media.generation,
                    device.device_id,
                    "runtime_started",
                )
                self._acceptance_report = None
            self._state = (
                RuntimeState.RUNNING
                if assessment.c_verified
                else RuntimeState.DEGRADED
            )
            return assessment
        except Exception:
            self._state = RuntimeState.FAILED
            self._invalidate_acceptance("startup_failed")
            try:
                self.chain.close_playback_sync()
            except Exception:
                logger.exception("failed to roll back playback startup")
            # If Media opened successfully but Kernel startup failed, release
            # only the resources this runtime owns.
            try:
                self.media.stop()
            except Exception:
                logger.exception("failed to roll back media startup")
            raise

    async def run(self) -> None:
        if not self._started:
            raise MediaError("target voice runtime is not started")
        current = asyncio.current_task()
        if self._run_task is not None and not self._run_task.done() and self._run_task is not current:
            raise MediaError("target voice runtime already has a media consumer")
        self._run_task = current
        try:
            await self.media.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._state = RuntimeState.FAILED
            self._invalidate_acceptance("media_run_failed")
            raise
        finally:
            if self._run_task is current:
                self._run_task = None

    def ingest(self, samples: Any, **kwargs: Any) -> bool:
        if not self._started or self._state not in {RuntimeState.RUNNING, RuntimeState.DEGRADED}:
            return False
        return self.media.ingest(samples, **kwargs)

    async def wait_idle(self) -> None:
        await self.media.wait_idle()
        await self.asr.wait_idle()
        await self.chain.wait_idle()

    async def stop(self, reason: str = "shutdown") -> None:
        if not self._started and self._state is RuntimeState.STOPPED:
            return
        self._state = RuntimeState.STOPPING
        self._invalidate_acceptance("runtime_stopping")
        run_task = self._run_task
        try:
            await self._cancel_acceptance_execution(reason)
            await self.asr.close(reason)
        finally:
            try:
                self.media.stop()
            finally:
                await self._await_run_task(run_task)
                try:
                    await self.chain.shutdown()
                finally:
                    self._started = False
                    self._state = RuntimeState.STOPPED
                    self._invalidate_acceptance("runtime_stopped")

    async def restart(
        self,
        device: DeviceDescriptor,
        capabilities: ProviderCapabilities,
        reason: str = "restart",
    ) -> CapabilityAssessment:
        """Perform an explicit stop/reopen/start cycle for runtime state only."""
        if self._started or self._state is not RuntimeState.STOPPED:
            await self.stop(reason)
        if self._acceptance_in_progress():
            raise MediaError("restart blocked by pending acceptance cleanup")
        if self.chain.kernel.snapshot().get("state") != "stopped":
            raise MediaError("restart requires a fully stopped target runtime")
        self.asr.reopen()
        self.chain.reopen()
        return self.start(device, capabilities)

    def health(self) -> dict:
        media_health = self.media.health()
        session_health = self.chain.snapshot()
        capability_mode = self._capability_mode(media_health, session_health)
        acceptance = self.acceptance_snapshot()
        c_verified = (
            self._started
            and self._state in {RuntimeState.RUNNING, RuntimeState.DEGRADED}
            and capability_mode == "C"
            and acceptance["c_verified"]
            and acceptance["media_generation"] == media_health.get("generation")
            and not self._acceptance_in_progress()
        )
        return {
            "state": self._state.value,
            "started": self._started,
            "run_task": bool(self._run_task is not None and not self._run_task.done()),
            "config": self.config_snapshot().to_dict(),
            "faults": self.faults_snapshot(),
            "environment": (
                self._environment_report.to_dict()
                if self._environment_report is not None
                else None
            ),
            "input_selection": (
                self._input_selection.to_dict()
                if self._input_selection is not None
                else None
            ),
            # A C-capable adapter set is not a C-certified runtime until an
            # explicit acceptance record proves the selected device/path.
            "mode": "C" if c_verified else "B",
            "capability_mode": capability_mode,
            "c_verified": c_verified,
            "acceptance": acceptance,
            "acceptance_execution": self.acceptance_execution_snapshot(),
            "media": media_health,
            "asr": self.asr.snapshot(),
            "session": session_health,
            "playback": session_health.get("ports", {}).get("playback_health"),
        }

    def set_environment_report(self, report: Optional[EnvironmentProbeReport]) -> None:
        """Inject a previously collected report; never probes hardware here."""
        if report is not None and not isinstance(report, EnvironmentProbeReport):
            raise TypeError("report must be an EnvironmentProbeReport or None")
        if report is not self._environment_report:
            self._invalidate_acceptance("environment_report_replaced")
            self._input_selection = None
        self._environment_report = report

    def set_input_selection(self, selection: Optional[InputDeviceSelection]) -> None:
        """Bind an explicit probe-derived microphone selection to this runtime."""
        if selection is not None and not isinstance(selection, InputDeviceSelection):
            raise TypeError("selection must be an InputDeviceSelection or None")
        if selection is not None:
            report = self._environment_report
            if report is None or not self._selection_matches_report(selection, report):
                raise MediaError("input selection does not match the current environment report")
        if selection is not self._input_selection:
            self._invalidate_acceptance("input_selection_replaced")
        self._input_selection = selection
        self.chain.kernel.record_system_event(
            EventKind.TASK,
            {
                "action": "input_selection_bound" if selection is not None else "input_selection_cleared",
                "device_id": selection.device.device_id if selection is not None else None,
                "route": selection.device.route if selection is not None else None,
            },
        )

    async def execute_full_duplex_acceptance(
        self,
        executor: FullDuplexAcceptanceExecutor,
    ) -> FullDuplexAcceptance:
        """Run and record an explicit, bounded acceptance executor report."""
        if not self._started:
            raise MediaError("full-duplex acceptance requires a running target runtime")
        if self._state not in {RuntimeState.RUNNING, RuntimeState.DEGRADED}:
            raise MediaError("full-duplex acceptance requires an active target runtime")
        if not isinstance(executor, FullDuplexAcceptanceExecutor):
            raise TypeError("executor must be a FullDuplexAcceptanceExecutor")
        media_health = self.media.health()
        device = media_health.get("device")
        capabilities = self.media.capabilities
        if not isinstance(device, Mapping) or capabilities is None:
            raise MediaError("runtime has no effective device or capabilities")
        current_device = self.media_device_descriptor(device)
        if executor.device != current_device:
            raise MediaError("acceptance executor device does not match running device")
        if executor.adapters.matches_identity(self._acceptance_adapters()) is False:
            raise MediaError("acceptance executor adapters do not match running runtime")
        if executor.thresholds != self.acceptance_thresholds:
            raise MediaError("acceptance executor thresholds do not match runtime policy")
        current_task = asyncio.current_task()
        if current_task is None:
            raise RuntimeError("full-duplex acceptance requires an asyncio task")
        media_generation = int(media_health.get("generation", 0) or 0)
        if not self._begin_acceptance_execution(executor, current_task, media_generation):
            self.chain.kernel.record_system_event(
                EventKind.ERROR,
                {
                    "code": "VOICE-C-ACCEPTANCE-IN-PROGRESS",
                    "component": "target_runtime",
                    "retryable": True,
                },
            )
            raise MediaError("full-duplex acceptance is already running")
        self._invalidate_acceptance("acceptance_execution_started")
        self.chain.kernel.record_system_event(
            EventKind.TASK,
            {
                "action": "full_duplex_acceptance_started",
                "media_generation": media_generation,
            },
        )
        try:
            report = await executor.run(
                media_generation=media_generation,
                capabilities=capabilities,
            )
            if not self._acceptance_execution_matches(executor, current_task):
                raise MediaError("full-duplex acceptance execution was superseded")
            if (
                not self._started
                or self._state not in {RuntimeState.RUNNING, RuntimeState.DEGRADED}
                or self.media.generation != media_generation
            ):
                self.chain.kernel.record_system_event(
                    EventKind.ERROR,
                    {
                        "code": "VOICE-C-ACCEPTANCE-STALE",
                        "component": "target_runtime",
                        "retryable": True,
                    },
                )
                raise MediaError("full-duplex acceptance completed against a stale runtime")
            return self._record_full_duplex_acceptance_report(
                report,
                expected_provenance=executor._provenance,
            )
        except Exception as exc:
            self.chain.kernel.record_system_event(
                EventKind.ERROR,
                {
                    "code": "VOICE-C-ACCEPTANCE-EXECUTION-FAILED",
                    "component": "target_runtime",
                    "detail": type(exc).__name__,
                    "retryable": True,
                },
            )
            raise
        finally:
            self._finish_acceptance_execution(executor, current_task)

    def record_full_duplex_acceptance_report(
        self,
        report: FullDuplexAcceptanceReport,
    ) -> FullDuplexAcceptance:
        """Retain an external report for diagnosis without allowing C proof.

        Real C eligibility is deliberately only available through
        ``execute_full_duplex_acceptance``.  A caller may retain a structured
        report from another process for diagnosis, but it cannot prove that
        this running provider/device path executed it.
        """
        return self._record_full_duplex_acceptance_report(report)

    def _record_full_duplex_acceptance_report(
        self,
        report: FullDuplexAcceptanceReport,
        *,
        expected_provenance: object = None,
    ) -> FullDuplexAcceptance:
        """Record report evidence with an executor-local provenance check."""
        if not self._started:
            raise MediaError("full-duplex acceptance requires a running target runtime")
        if not isinstance(report, FullDuplexAcceptanceReport):
            raise TypeError("report must be a FullDuplexAcceptanceReport")
        with self._acceptance_lock:
            self._acceptance_report = report
        return self._record_acceptance_checks(
            report.checks,
            report=report,
            expected_provenance=expected_provenance,
        )

    def record_full_duplex_acceptance(
        self,
        checks: Mapping[str, bool],
    ) -> FullDuplexAcceptance:
        """Compatibility shim that deliberately cannot certify C.

        Boolean maps from the former external harness have no timing,
        provider, or device evidence.  They remain visible as a rejected
        attempt, but a structured ``FullDuplexAcceptanceReport`` is required
        for a C result.
        """
        if not self._started:
            raise MediaError("full-duplex acceptance requires a running target runtime")
        if not isinstance(checks, Mapping):
            raise TypeError("checks must be a mapping of acceptance check names to booleans")

        return self._record_acceptance_checks({}, report=None)

    def _record_acceptance_checks(
        self,
        checks: Mapping[str, bool],
        *,
        report: Optional[FullDuplexAcceptanceReport],
        expected_provenance: object = None,
    ) -> FullDuplexAcceptance:
        """Apply report evidence and current-runtime prerequisites."""

        media_health = self.media.health()
        session_health = self.chain.snapshot()
        device = media_health.get("device")
        device_id = str(device.get("device_id", "")) if isinstance(device, Mapping) else ""
        check_map = {
            str(name)[:160]: bool(value)
            for name, value in checks.items()
            if str(name).strip()
        }
        missing = [
            "acceptance_check:" + name
            for name in C_ACCEPTANCE_CHECKS
            if not check_map.get(name, False)
        ]
        if report is None:
            missing.append("structured_acceptance_report_required")
        else:
            if expected_provenance is None or report._provenance is not expected_provenance:
                missing.append("acceptance_report_provenance")
            if report.status is not AcceptanceRunStatus.PASSED:
                missing.append("acceptance_execution:" + report.status.value)
            if report.pending_sync_work:
                missing.append("acceptance_pending_sync_work")
            if not report.all_checks_passed:
                missing.append("acceptance_report_checks")
            if report.media_generation != int(media_health.get("generation", 0) or 0):
                missing.append("acceptance_report_generation_mismatch")
            if report.device_id != device_id:
                missing.append("acceptance_report_device_mismatch")
            if report.thresholds != self.acceptance_thresholds:
                missing.append("acceptance_report_thresholds_mismatch")
        if self._capability_mode(media_health, session_health) != "C":
            missing.append("capability_candidate_c")
        if not isinstance(device, Mapping) or device.get("route") == AudioRoute.UNKNOWN.value:
            missing.append("explicit_audio_route")

        selection = self._input_selection
        if selection is None:
            missing.append("explicit_input_selection")
        elif not isinstance(device, Mapping) or not self._selection_matches_device(
            selection,
            self.media_device_descriptor(device),
        ):
            missing.append("input_selection_device_mismatch")
        elif selection.probe_status is not ProbeStatus.READY:
            missing.append("input_selection_probe_ready")

        ports = session_health.get("ports", {})
        if not isinstance(ports, Mapping) or not ports.get("speech_cancel_supported"):
            missing.append("speech_cancel_supported")
        if not isinstance(ports, Mapping) or not ports.get("speech_stop_observable"):
            missing.append("speech_stop_observable")
        if not isinstance(ports, Mapping) or not ports.get("playback_stop_observable"):
            missing.append("playback_stop_observable")

        asr_health = self.asr.snapshot()
        asr_ports = asr_health.get("ports", {})
        if not isinstance(asr_ports, Mapping) or not asr_ports.get("asr_stop_observable"):
            missing.append("asr_stop_observable")
        asr_provider = asr_health.get("provider", {})
        if isinstance(asr_provider, Mapping) and asr_provider.get("available") is False:
            missing.append("asr_provider_available")

        environment_report = self._environment_report
        if environment_report is None:
            missing.append("environment_probe")
        elif environment_report.status is not ProbeStatus.READY:
            missing.append("environment_probe_ready")
        elif not environment_report.device_query_attempted:
            missing.append("environment_device_query")
        elif not any(
            item.device_id == device_id and item.input_channels > 0
            for item in environment_report.devices
        ):
            missing.append("environment_selected_input")

        unique_missing = tuple(dict.fromkeys(missing))
        if report is not None and report.status is AcceptanceRunStatus.NOT_EXECUTED:
            status = AcceptanceStatus.NOT_RUN
        else:
            status = AcceptanceStatus.PASSED if not unique_missing else AcceptanceStatus.FAILED
        acceptance = FullDuplexAcceptance(
            status=status,
            media_generation=int(media_health.get("generation", 0) or 0),
            device_id=device_id,
            checks=tuple(sorted(check_map.items())),
            missing=unique_missing,
            reason=(
                "acceptance_recorded"
                if status is AcceptanceStatus.PASSED
                else (
                    "acceptance_not_executed"
                    if status is AcceptanceStatus.NOT_RUN
                    else "requirements_missing"
                )
            ),
            recorded_at=time.time(),
        )
        with self._acceptance_lock:
            self._acceptance = acceptance

        payload = {
            "capability": "full_duplex_acceptance",
            "status": acceptance.status.value,
            "c_verified": acceptance.c_verified,
            "media_generation": acceptance.media_generation,
            "missing": list(acceptance.missing),
            "execution_status": report.status.value if report is not None else "rejected_boolean_map",
            "run_id": report.run_id if report is not None else None,
        }
        self.chain.kernel.record_system_event(EventKind.CAPABILITY, payload)
        if not acceptance.c_verified:
            error_code = (
                "VOICE-C-ACCEPTANCE-NOT-EXECUTED"
                if acceptance.status is AcceptanceStatus.NOT_RUN
                else "VOICE-C-ACCEPTANCE-FAILED"
            )
            self.chain.kernel.record_system_event(
                EventKind.ERROR,
                {
                    "code": error_code,
                    "component": "target_runtime",
                    "missing": list(acceptance.missing),
                    "retryable": True,
                },
            )
        return acceptance

    def acceptance_snapshot(self) -> dict:
        with self._acceptance_lock:
            acceptance = self._acceptance
        return acceptance.to_dict()

    def acceptance_execution_snapshot(self) -> Optional[dict]:
        """Expose the last structured report without claiming it is current."""
        with self._acceptance_lock:
            report = self._acceptance_report
            acceptance = self._acceptance
        with self._acceptance_execution_lock:
            self._refresh_acceptance_execution_locked()
            executor = self._acceptance_execution_executor
            in_progress = self._acceptance_execution_in_progress
            cleanup_pending = bool(executor is not None and executor.sync_cleanup_pending)
            cancellation_requested = bool(
                executor is not None and executor.cancellation_requested
            )
            active_run_id = executor.run_id if executor is not None else None
        if report is None:
            if not in_progress:
                return None
            return {
                "status": "cancelling" if cancellation_requested else "in_progress",
                "in_progress": True,
                "cleanup_pending": cleanup_pending,
                "cancellation_requested": cancellation_requested,
                "run_id": active_run_id,
            }
        payload = report.to_dict()
        media_health = self.media.health()
        device = media_health.get("device")
        current_device_id = (
            str(device.get("device_id", "")) if isinstance(device, Mapping) else ""
        )
        payload["valid_for_current_runtime"] = bool(
            self._started
            and self._state in {RuntimeState.RUNNING, RuntimeState.DEGRADED}
            and acceptance.status is AcceptanceStatus.PASSED
            and report.media_generation == int(media_health.get("generation", 0) or 0)
            and report.device_id == current_device_id
        )
        payload["in_progress"] = in_progress
        payload["cleanup_pending"] = cleanup_pending
        payload["cancellation_requested"] = cancellation_requested
        payload["active_run_id"] = active_run_id
        return payload

    def _capability_mode(self, media_health: Mapping[str, Any], session_health: Mapping[str, Any]) -> str:
        if not self._started:
            return "B"
        if media_health.get("mode") == "B" or session_health.get("duplex_mode") == "B":
            return "B"
        asr_provider = self.asr.snapshot().get("provider", {})
        if isinstance(asr_provider, Mapping) and asr_provider.get("available") is False:
            return "B"
        return "C"

    def _invalidate_acceptance(self, reason: str) -> None:
        """Invalidate evidence when its runtime/device basis changes."""
        with self._acceptance_lock:
            previous = self._acceptance
            self._acceptance = FullDuplexAcceptance(
                status=AcceptanceStatus.INVALIDATED,
                media_generation=self.media.generation,
                device_id=previous.device_id,
                checks=previous.checks,
                missing=tuple(dict.fromkeys((*previous.missing, "runtime:" + str(reason)[:120]))),
                reason=str(reason)[:160],
                recorded_at=time.time(),
            )

    @staticmethod
    def media_device_descriptor(device: Mapping[str, Any]) -> DeviceDescriptor:
        """Normalize a health snapshot only after caller has checked its shape."""
        return DeviceDescriptor(
            device_id=str(device.get("device_id", "")),
            name=str(device.get("name", "")),
            input_channels=int(device.get("input_channels", 0) or 0),
            output_channels=int(device.get("output_channels", 0) or 0),
            sample_rate=int(device.get("sample_rate", 0) or 0),
            route=str(device.get("route", AudioRoute.UNKNOWN.value)),
            reference_available=bool(device.get("reference_available", False)),
        )

    @staticmethod
    def _selection_matches_device(
        selection: InputDeviceSelection,
        device: DeviceDescriptor,
    ) -> bool:
        selected = selection.device
        return (
            selected.device_id == device.device_id
            and selected.input_channels == device.input_channels
            and selected.output_channels == device.output_channels
            and selected.sample_rate == device.sample_rate
            and selected.route == device.route
            and selected.reference_available == device.reference_available
        )

    @staticmethod
    def _selection_matches_report(
        selection: InputDeviceSelection,
        report: EnvironmentProbeReport,
    ) -> bool:
        if selection.probe_status is not report.status:
            return False
        if selection.probe_captured_at != report.captured_at:
            return False
        return any(
            item.device_id == selection.device.device_id
            # The probe reports a maximum channel count while the selection
            # records the explicitly requested capture count.
            and item.input_channels >= selection.device.input_channels
            and item.output_channels == selection.device.output_channels
            and item.sample_rate == selection.device.sample_rate
            for item in report.devices
        )

    def config_snapshot(self) -> RuntimeConfigSnapshot:
        """Return the effective, read-only budgets for this runtime instance."""
        assembler = self.asr.assembler
        return RuntimeConfigSnapshot(
            version="target-chain-v1",
            stop_timeout_s=self.stop_timeout_s,
            media_queue_capacity=self.media.queue_capacity,
            media_queue_duration_ms=self.media.max_queue_duration_ms,
            segment_preroll_frames=assembler.preroll_frames,
            segment_end_silence_frames=assembler.end_silence_frames,
            segment_max_frames=assembler.max_frames,
            segment_min_frames=assembler.min_frames,
            segment_max_duration_ms=assembler.max_duration_ms,
            segment_min_duration_ms=assembler.min_duration_ms,
            asr_timeout_s=self.asr.timeout_s,
            asr_cancel_timeout_s=self.asr.cancel_timeout_s,
            acceptance_thresholds=self.acceptance_thresholds,
        )

    def _acceptance_adapters(self) -> AcceptanceAdapters:
        """Return the exact provider objects owned by this runtime."""
        return AcceptanceAdapters(
            input_source=self.media.source,
            vad=self.media.vad,
            asr=self.asr.asr,
            reasoner=self.chain.reasoner,
            # The provider-neutral port is the speech owner once selected;
            # retain the historical speech adapter for the compatibility path.
            speech=self.chain.tts_provider or self.chain.speech,
            playback=self.chain.playback,
            aec=self.media.aec,
        )

    def _begin_acceptance_execution(
        self,
        executor: FullDuplexAcceptanceExecutor,
        task: asyncio.Task,
        media_generation: int,
    ) -> bool:
        with self._acceptance_execution_lock:
            self._refresh_acceptance_execution_locked()
            if self._acceptance_execution_in_progress:
                return False
            self._acceptance_execution_in_progress = True
            self._acceptance_execution_executor = executor
            self._acceptance_execution_task = task
            self._acceptance_execution_generation = int(media_generation)
            return True

    def _finish_acceptance_execution(
        self,
        executor: FullDuplexAcceptanceExecutor,
        task: asyncio.Task,
    ) -> None:
        with self._acceptance_execution_lock:
            if (
                self._acceptance_execution_executor is not executor
                or self._acceptance_execution_task is not task
            ):
                return
            self._acceptance_execution_task = None
            self._refresh_acceptance_execution_locked()

    def _acceptance_in_progress(self) -> bool:
        with self._acceptance_execution_lock:
            self._refresh_acceptance_execution_locked()
            return self._acceptance_execution_in_progress

    def _acceptance_execution_matches(
        self,
        executor: FullDuplexAcceptanceExecutor,
        task: asyncio.Task,
    ) -> bool:
        with self._acceptance_execution_lock:
            self._refresh_acceptance_execution_locked()
            return (
                self._acceptance_execution_in_progress
                and self._acceptance_execution_executor is executor
                and self._acceptance_execution_task is task
            )

    def _refresh_acceptance_execution_locked(self) -> None:
        """Retain ownership until a cancelled synchronous worker has exited."""
        executor = self._acceptance_execution_executor
        task = self._acceptance_execution_task
        if executor is None:
            self._acceptance_execution_in_progress = False
            self._acceptance_execution_task = None
            self._acceptance_execution_generation = 0
            return
        if task is not None and not task.done():
            self._acceptance_execution_in_progress = True
            return
        if executor.sync_cleanup_pending:
            self._acceptance_execution_in_progress = True
            self._acceptance_execution_task = None
            return
        self._acceptance_execution_in_progress = False
        self._acceptance_execution_executor = None
        self._acceptance_execution_task = None
        self._acceptance_execution_generation = 0

    async def _cancel_acceptance_execution(self, reason: str) -> bool:
        """Cancel the active C check before releasing shared voice resources."""
        with self._acceptance_execution_lock:
            self._refresh_acceptance_execution_locked()
            executor = self._acceptance_execution_executor
            task = self._acceptance_execution_task
        if executor is None:
            return True

        executor.request_cancel()
        self.chain.kernel.record_system_event(
            EventKind.TASK,
            {
                "action": "full_duplex_acceptance_cancel_requested",
                "media_generation": self._acceptance_execution_generation,
            },
        )
        current_task = asyncio.current_task()
        deadline = asyncio.get_running_loop().time() + self.stop_timeout_s
        task_terminal = task is None or task.done()
        if task is current_task:
            self.chain.kernel.record_system_event(
                EventKind.ERROR,
                {
                    "code": "VOICE-C-ACCEPTANCE-CANCEL-FAILED",
                    "component": "target_runtime",
                    "detail": "self_cancel",
                    "retryable": True,
                },
            )
        elif not task_terminal and task is not None:
            task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
                )
            except asyncio.CancelledError:
                # The acceptance task was cancelled as requested.  Preserve
                # cancellation of this stop coroutine itself instead.
                if not task.done():
                    raise
            except asyncio.TimeoutError:
                self.chain.kernel.record_system_event(
                    EventKind.ERROR,
                    {
                        "code": "VOICE-C-ACCEPTANCE-CANCEL-TIMEOUT",
                        "component": "target_runtime",
                        "retryable": True,
                    },
                )
            except Exception as exc:
                self.chain.kernel.record_system_event(
                    EventKind.ERROR,
                    {
                        "code": "VOICE-C-ACCEPTANCE-CANCEL-FAILED",
                        "component": "target_runtime",
                        "detail": type(exc).__name__,
                        "retryable": True,
                    },
                )
            task_terminal = task.done()

        cleanup_complete = await executor.wait_for_cleanup(
            max(0.0, deadline - asyncio.get_running_loop().time())
        )
        still_active = self._acceptance_in_progress()
        if not task_terminal or not cleanup_complete or still_active:
            self.chain.kernel.record_system_event(
                EventKind.ERROR,
                {
                    "code": "VOICE-C-ACCEPTANCE-CLEANUP-PENDING",
                    "component": "target_runtime",
                    "retryable": True,
                },
            )
            return False
        return True

    def _effective_acceptance_thresholds(
        self,
        configured: AcceptanceThresholds,
    ) -> AcceptanceThresholds:
        """Intersect initial policy limits with live chain safety budgets."""
        max_stop_latency_ms = max(
            1,
            int(min(self.stop_timeout_s, self.asr.cancel_timeout_s) * 1000),
        )
        return replace(
            configured,
            max_stop_latency_ms=min(
                configured.max_stop_latency_ms,
                max_stop_latency_ms,
            ),
            min_capture_frames=max(
                configured.min_capture_frames,
                self.asr.assembler.min_frames,
            ),
            max_queue_depth=min(
                configured.max_queue_depth,
                self.media.queue_capacity,
            ),
            max_queue_duration_ms=min(
                configured.max_queue_duration_ms,
                self.media.max_queue_duration_ms,
            ),
        )

    def faults_snapshot(self) -> list[dict]:
        """Return bounded, non-sensitive fault classification evidence."""
        with self._fault_lock:
            rows = [dict(item) for item in self._faults.values()]
        return sorted(rows, key=lambda item: (item["last_seen"], item["code"]))

    async def _await_run_task(self, task: Optional[asyncio.Task]) -> bool:
        """Wait for the owned media consumer and report a bounded leak."""
        if task is None or task is asyncio.current_task() or task.done():
            return True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.stop_timeout_s)
            return True
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=min(self.stop_timeout_s, 0.5),
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self.chain.kernel.record_system_event(
                EventKind.ERROR,
                {
                    "code": "RUNTIME-RUN-STOP-TIMEOUT",
                    "component": "target_runtime",
                    "retryable": True,
                },
            )
            return False
        except asyncio.CancelledError:
            return task.done()
        except Exception as exc:
            self.chain.kernel.record_system_event(
                EventKind.ERROR,
                {
                    "code": "RUNTIME-RUN-FAILED",
                    "component": "target_runtime",
                    "detail": type(exc).__name__,
                    "retryable": True,
                },
            )
            return task.done()

    def _handle_media_event(self, event: Any) -> None:
        """Make runtime media failures visible to the Kernel capability view."""
        if str(getattr(event, "kind", "")) != "MEDIA_ERROR":
            return
        code = getattr(event, "code", None)
        if not code:
            return
        self._record_runtime_fault(str(code), "media")

    def _handle_asr_event(self, event: Any) -> None:
        """Downgrade evidence when a serial ASR cancellation cannot be proven."""
        if str(getattr(event, "kind", "")) != "ASR_ERROR":
            return
        payload = getattr(event, "payload", {}) or {}
        code = payload.get("code") if isinstance(payload, Mapping) else None
        if not code:
            return
        self._record_runtime_fault(str(code), "asr")

    def _handle_playback_event(self, event: Any) -> None:
        """Treat output-port faults as core target-chain health evidence."""
        kind = str(getattr(event, "kind", ""))
        code = getattr(event, "code", None)
        if not code:
            payload = getattr(event, "payload", {}) or {}
            code = payload.get("code") if isinstance(payload, Mapping) else None
        if not code:
            return
        if "ERROR" not in kind and "UNDERRUN" not in kind:
            return
        self._record_runtime_fault(str(code), "playback")

    def _record_runtime_fault(self, code: str, component: str) -> None:
        """Record and monotonically downgrade one target runtime fault."""
        self._invalidate_acceptance(str(component) + ":" + str(code))
        decision = self.fault_policy.decide(str(code))
        now = time.time()
        with self._fault_lock:
            previous = self._faults.get(decision.code)
            self._faults[decision.code] = {
                **decision.to_dict(),
                "count": int(previous["count"] + 1) if previous else 1,
                "first_seen": previous["first_seen"] if previous else now,
                "last_seen": now,
            }
        degrade = getattr(self.chain.kernel, "degrade_capability", None)
        if not callable(degrade):
            return
        try:
            # Capability downgrades are monotonic for the current runtime.
            # Recovery, if later justified by a probe, must restart/reassess
            # the runtime instead of silently claiming C again.
            degrade(
                decision.code,
                reason=decision.action.value,
                component=str(component)[:160],
            )
        except Exception:
            # Event observability must never turn an adapter callback into a
            # second failure; the original event has already been relayed.
            logger.exception("failed to propagate media capability downgrade")

    def _compose_media_event_sink(self, owner: Any) -> None:
        previous = getattr(owner, "on_event", None)
        relay = self.events.media

        def sink(event: Any) -> None:
            try:
                if previous is not None:
                    previous(event)
            finally:
                relay(event)
                self._handle_media_event(event)

        owner.on_event = sink

    def _compose_asr_event_sink(self, owner: Any) -> None:
        previous = getattr(owner, "on_event", None)
        relay = self.events.asr

        def sink(event: Any) -> None:
            try:
                if previous is not None:
                    previous(event)
            finally:
                relay(event)
                self._handle_asr_event(event)

        owner.on_event = sink

    def _compose_playback_event_sink(self, owner: Any) -> None:
        if owner is None:
            return
        previous = getattr(owner, "on_event", None)
        relay = self.events.playback

        def sink(event: Any) -> None:
            try:
                if previous is not None:
                    previous(event)
            finally:
                relay(event)
                self._handle_playback_event(event)

        owner.on_event = sink

    @staticmethod
    def _compose_event_sink(owner: Any, relay: Any) -> None:
        previous = getattr(owner, "on_event", None)
        if previous is relay:
            return

        def sink(event: Any) -> None:
            try:
                if previous is not None:
                    previous(event)
            finally:
                relay(event)

        owner.on_event = sink


__all__ = [
    "AcceptanceStatus",
    "C_ACCEPTANCE_CHECKS",
    "FaultAction",
    "FaultImportance",
    "FullDuplexAcceptance",
    "RuntimeConfigSnapshot",
    "RuntimeFaultDecision",
    "RuntimeFaultPolicy",
    "RuntimeState",
    "TargetVoiceRuntime",
]
