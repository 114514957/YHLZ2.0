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
    input_sample_rate: int = 16_000
    output_sample_rate: int = 24_000
    input_channels: int = 1
    output_channels: int = 2

    def descriptor(self) -> DeviceDescriptor:
        return DeviceDescriptor(
            device_id=str(self.input_index), name=self.binding.input_name,
            input_channels=self.input_channels, output_channels=self.output_channels,
            sample_rate=self.input_sample_rate,
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
    def negotiate(check, index, row, key, rates, channels):
        # Probe formats ONLY on the explicitly selected endpoint. Never switch
        # devices or mark reference/acoustic verification from a format probe.
        default = int(row.get("default_samplerate", 0) or 0)
        candidates = list(dict.fromkeys((*rates, default)))
        for channel_count in channels:
            if channel_count > int(row.get(key, 0)): continue
            for rate in candidates:
                if rate not in (8000,16000,24000,32000,44100,48000,96000): continue
                try:
                    check(device=index, samplerate=rate, channels=channel_count, dtype="float32")
                    return rate, channel_count
                except Exception:
                    continue
        raise DeviceBindingError("TARGET-DEVICE-FORMAT-UNSUPPORTED")

    input_rate, input_channels = negotiate(
        sd.check_input_settings,input_index,input_row,"max_input_channels",
        (16000,48000,44100,32000,24000,8000),(1,2))
    output_rate, output_channels = negotiate(
        sd.check_output_settings,output_index,output_row,"max_output_channels",
        (24000,48000,44100,32000,16000,8000),(2,1))
    return ResolvedTargetDevices(binding, input_index, output_index,
                                 int(input_row.get("hostapi", -1)),
                                 int(output_row.get("hostapi", -1)),
                                 input_rate,output_rate,input_channels,output_channels)
