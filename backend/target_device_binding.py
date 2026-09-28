"""Fail-closed explicit endpoint selection for Target voice.

P0-1 (2026-09-28): devices are identified by name + host API name.
Same-name devices across MME / DirectSound / WASAPI are common on Windows;
matching by name alone raises TARGET-DEVICE-AMBIGUOUS.  Adding host API
disambiguates; if still ambiguous, the error is kept (never silently pick).
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.media_adapter import DeviceDescriptor


class DeviceBindingError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TargetDeviceBinding:
    input_name: str
    output_name: str
    route: str = "speaker_mic"
    input_hostapi_name: Optional[str] = None
    output_hostapi_name: Optional[str] = None

    def __post_init__(self):
        if not self.input_name.strip() or not self.output_name.strip():
            raise DeviceBindingError("TARGET-DEVICE-NAME-REQUIRED")
        if self.route not in ("speaker_mic", "headset"):
            raise DeviceBindingError("TARGET-DEVICE-ROUTE-INVALID")


@dataclass(frozen=True)
class ResolvedTargetDevices:
    binding: TargetDeviceBinding
    input_index: int
    output_index: int
    input_hostapi: int
    output_hostapi: int

    def descriptor(self) -> DeviceDescriptor:
        return DeviceDescriptor(
            device_id=str(self.input_index), name=self.binding.input_name,
            input_channels=1, output_channels=0, sample_rate=16_000,
            route=self.binding.route, reference_available=False,
        )

    def verify(self, sd: Any) -> None:
        if resolve_devices(sd, self.binding) != self:
            raise DeviceBindingError("TARGET-DEVICE-CHANGED")


def _hostapi_name(apis: list, index: int) -> str:
    if 0 <= index < len(apis):
        return str(apis[index].get("name", ""))
    return ""


def resolve_devices(sd: Any, binding: TargetDeviceBinding) -> ResolvedTargetDevices:
    rows = sd.query_devices()
    apis = sd.query_hostapis()

    def select(name: str, key: str, hostapi_name: Optional[str]):
        candidates = [
            (i, row) for i, row in enumerate(rows)
            if row.get("name") == name and int(row.get(key, 0)) > 0
        ]
        if hostapi_name:
            ha = hostapi_name.strip().lower()
            candidates = [
                (i, row) for i, row in candidates
                if _hostapi_name(apis, int(row.get("hostapi", -1))).lower() == ha
            ]
        if len(candidates) != 1:
            raise DeviceBindingError(
                "TARGET-DEVICE-MISSING" if not candidates
                else "TARGET-DEVICE-AMBIGUOUS")
        return candidates[0]

    input_index, input_row = select(
        binding.input_name, "max_input_channels", binding.input_hostapi_name)
    output_index, output_row = select(
        binding.output_name, "max_output_channels", binding.output_hostapi_name)
    try:
        sd.check_input_settings(device=input_index, samplerate=16_000,
                                channels=1, dtype="float32")
        sd.check_output_settings(device=output_index, samplerate=24_000,
                                 channels=2, dtype="float32")
    except Exception as exc:
        raise DeviceBindingError("TARGET-DEVICE-FORMAT-UNSUPPORTED") from exc
    return ResolvedTargetDevices(binding, input_index, output_index,
                                 int(input_row.get("hostapi", -1)),
                                 int(output_row.get("hostapi", -1)))
