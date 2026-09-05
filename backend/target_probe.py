"""Side-effect-free environment probe for the target voice chain.

The probe reports whether optional audio/model dependencies and device
enumeration are available.  It never opens a stream, starts a model, installs
packages, or writes a report; callers decide where (or whether) to retain the
returned value.
"""

from __future__ import annotations

import importlib
import importlib.util
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Tuple

from backend.media_adapter import DeviceDescriptor
from backend.session_kernel import AudioRoute


class ProbeStatus(str, Enum):
    READY = "ready"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class DeviceSelectionError(ValueError):
    """Raised when a probe result cannot safely select microphone ingress."""


@dataclass(frozen=True, slots=True)
class DeviceProbe:
    device_id: str
    name: str
    input_channels: int
    output_channels: int
    sample_rate: int

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "input_channels": self.input_channels,
            "output_channels": self.output_channels,
            "sample_rate": self.sample_rate,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentProbeReport:
    status: ProbeStatus
    dependencies: Tuple[Tuple[str, bool], ...] = ()
    devices: Tuple[DeviceProbe, ...] = ()
    reasons: Tuple[str, ...] = ()
    device_query_attempted: bool = False
    c_verified: bool = False
    verification: str = "not_run"
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "dependencies": {name: available for name, available in self.dependencies},
            "devices": [device.to_dict() for device in self.devices],
            "reasons": list(self.reasons),
            "device_query_attempted": self.device_query_attempted,
            # Device discovery is only a prerequisite; it is never C proof.
            "c_verified": False,
            "verification": self.verification,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True, slots=True)
class InputDeviceSelection:
    """An explicit microphone selection derived from a read-only probe.

    Enumeration does not establish whether a device is a headset or a
    speaker-and-microphone route. The caller must declare that route from
    evidence outside the probe; this value never certifies C by itself.
    """

    device: DeviceDescriptor
    probe_status: ProbeStatus
    probe_captured_at: float

    @property
    def c_verified(self) -> bool:
        return False

    def to_dict(self) -> dict:
        return {
            "device": self.device.to_dict(),
            "probe_status": self.probe_status.value,
            "probe_captured_at": self.probe_captured_at,
            "c_verified": False,
        }


def select_input_device(
    report: EnvironmentProbeReport,
    device_id: str,
    *,
    route: str = AudioRoute.UNKNOWN.value,
    reference_available: bool = False,
    input_channels: int = 1,
) -> InputDeviceSelection:
    """Choose one enumerated microphone without guessing its physical route.

    ``sounddevice`` reports endpoint channel counts, not whether a device is
    a headset, an acoustic reference route, or a paired playback device.
    Therefore a route defaults to ``unknown`` and callers may only declare an
    AEC reference for an explicitly selected ``speaker_mic`` route.
    """
    if not isinstance(report, EnvironmentProbeReport):
        raise TypeError("report must be an EnvironmentProbeReport")
    if report.status not in {ProbeStatus.READY, ProbeStatus.PARTIAL}:
        raise DeviceSelectionError("device selection requires a successful device probe")
    selected = next(
        (device for device in report.devices if device.device_id == str(device_id)),
        None,
    )
    if selected is None:
        raise DeviceSelectionError("selected device was not present in the probe report")
    if selected.input_channels <= 0:
        raise DeviceSelectionError("selected device has no input channels")
    try:
        selected_channels = int(input_channels)
    except (TypeError, ValueError) as exc:
        raise DeviceSelectionError("input_channels must be an integer") from exc
    if selected_channels <= 0 or selected_channels > selected.input_channels:
        raise DeviceSelectionError("input_channels is outside the device capability")
    try:
        normalized_route = AudioRoute(route)
    except ValueError as exc:
        raise DeviceSelectionError("route must be a known AudioRoute value") from exc
    if reference_available and normalized_route is not AudioRoute.SPEAKER_MIC:
        raise DeviceSelectionError(
            "reference_available requires an explicit speaker_mic route"
        )
    return InputDeviceSelection(
        device=DeviceDescriptor(
            device_id=selected.device_id,
            name=selected.name,
            # DeviceProbe carries the maximum channel count advertised by the
            # driver. The target input contract must choose its actual stream
            # channel count explicitly instead of treating that maximum as a
            # capture setting.
            input_channels=selected_channels,
            output_channels=selected.output_channels,
            sample_rate=selected.sample_rate,
            route=normalized_route.value,
            reference_available=bool(reference_available),
        ),
        probe_status=report.status,
        probe_captured_at=report.captured_at,
    )


class TargetEnvironmentProbe:
    """Inspect optional runtime prerequisites without touching live audio."""

    DEFAULT_DEPENDENCIES = (
        "sounddevice",
        "numpy",
        "scipy",
        "onnxruntime",
        "faster_whisper",
    )

    def __init__(
        self,
        *,
        dependency_names: Optional[Tuple[str, ...]] = None,
        dependency_finder: Optional[Callable[[str], Any]] = None,
        module_loader: Optional[Callable[[str], Any]] = None,
        sounddevice_module: Any = None,
    ) -> None:
        names = dependency_names or self.DEFAULT_DEPENDENCIES
        if not names or any(not str(name).strip() for name in names):
            raise ValueError("dependency_names must contain non-empty names")
        normalized_names = tuple(dict.fromkeys(str(name) for name in names))
        # Device discovery always needs sounddevice, even when a caller only
        # wants to report a narrower model dependency set.
        if "sounddevice" not in normalized_names:
            normalized_names = ("sounddevice", *normalized_names)
        self.dependency_names = normalized_names
        self._find_spec = dependency_finder or importlib.util.find_spec
        self._load_module = module_loader or importlib.import_module
        self._sounddevice = sounddevice_module

    def inspect(self) -> EnvironmentProbeReport:
        dependencies = []
        reasons = []
        for name in self.dependency_names:
            try:
                available = self._find_spec(name) is not None
            except Exception as exc:
                available = False
                reasons.append("dependency:{0}:{1}".format(name, type(exc).__name__))
            if name == "sounddevice" and self._sounddevice is not None:
                available = True
            dependencies.append((name, bool(available)))

        dependency_map = dict(dependencies)
        missing = [name for name, available in dependencies if not available]
        if missing:
            reasons.append("missing_dependencies:" + ",".join(missing))

        devices = []
        query_attempted = False
        query_error = False
        sounddevice_available = dependency_map.get("sounddevice", False)
        # Model inference packages are not a prerequisite for a read-only
        # device list. This permits a partial report that accurately says
        # "devices visible, speech stack incomplete".
        if sounddevice_available:
            try:
                sounddevice = self._sounddevice or self._load_module("sounddevice")
                query_attempted = True
                rows = sounddevice.query_devices()
                if isinstance(rows, Mapping):
                    rows = [rows]
                for index, row in enumerate(rows or ()):
                    if not isinstance(row, Mapping):
                        continue
                    try:
                        input_channels = int(row.get("max_input_channels", 0) or 0)
                        output_channels = int(row.get("max_output_channels", 0) or 0)
                        sample_rate = int(float(row.get("default_samplerate", 16_000) or 16_000))
                    except (TypeError, ValueError):
                        reasons.append("device:{0}:invalid_metadata".format(index))
                        continue
                    if input_channels <= 0 and output_channels <= 0:
                        continue
                    devices.append(
                        DeviceProbe(
                            device_id=str(index),
                            name=str(row.get("name", "unknown"))[:160],
                            input_channels=max(input_channels, 0),
                            output_channels=max(output_channels, 0),
                            sample_rate=max(sample_rate, 1),
                        )
                    )
            except Exception as exc:
                query_error = True
                reasons.append("device_query:{0}".format(type(exc).__name__))

        model_dependencies_missing = [name for name in missing if name != "sounddevice"]
        if not sounddevice_available:
            status = ProbeStatus.UNAVAILABLE
        elif query_error:
            status = ProbeStatus.ERROR
        elif model_dependencies_missing:
            status = ProbeStatus.PARTIAL
        else:
            status = ProbeStatus.READY
        if not sounddevice_available:
            reasons.append("device_enumeration_unavailable")
        elif not query_attempted:
            reasons.append("device_query_not_attempted")
        reasons.append("c_authentication_not_run")
        return EnvironmentProbeReport(
            status=status,
            dependencies=tuple(dependencies),
            devices=tuple(devices),
            reasons=tuple(dict.fromkeys(reasons)),
            device_query_attempted=query_attempted,
            c_verified=False,
            verification="not_run",
        )


__all__ = [
    "DeviceProbe",
    "DeviceSelectionError",
    "EnvironmentProbeReport",
    "InputDeviceSelection",
    "ProbeStatus",
    "TargetEnvironmentProbe",
    "select_input_device",
]
